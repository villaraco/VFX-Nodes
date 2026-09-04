/**
 * VFX Nodes — colours, info panels & FluxBatch auto-queue.
 * ==========================================================
 * - Orange theme for the ``VFX`` category.
 * - ``vfx_info`` panel for Prepare / Restore / FluxBatch nodes.
 * - Auto-queue: intercepts Impact Pack's ``impact-add-queue`` WebSocket event,
 *   auto-increments prompt_index/variation BEFORE Impact Pack re-queues.
 */

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const ORANGE = "#FF8C00";
const DARK_BG = "#3D2000";
const INFO_FONT = "11px 'Segoe UI', sans-serif";
const LINE_H = 15;
const INFO_PAD = 6;

const INFO_NODES = new Set([
    "VFXPrepareResolution",
    "VFXRestoreResolution",
    "VFXFluxBatchPrompts",
]);

app.registerExtension({
    name: "VFX_Nodes.colors",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!INFO_NODES.has(nodeData.name)) return;

        const origExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (output) {
            origExecuted?.apply(this, arguments);
            const vfx = output?.vfx_info;
            this._vfxLines = vfx?.length ? vfx : null;
            this._vfxBatchTotal = output?.batch_total?.[0] ?? 0;
            this._vfxBatchVars = output?.batch_variations?.[0] ?? 5;
            this.setDirtyCanvas(true, true);
        };

        const origDraw = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            origDraw?.apply(this, arguments);
            if (!this._vfxLines || this.flags?.collapsed) return;

            const lines = this._vfxLines;
            const count = lines.length;
            const w = 170;
            const h = count * LINE_H;
            const x = (this.size[0] - w) / 2;
            const y = this.size[1] - h - INFO_PAD;

            ctx.save();
            ctx.globalAlpha = 0.55;
            ctx.fillStyle = DARK_BG;
            ctx.beginPath();
            ctx.roundRect(x - 3, y - 1, w, h + 3, 3);
            ctx.fill();
            ctx.globalAlpha = 1;

            ctx.font = INFO_FONT;
            ctx.fillStyle = ORANGE;
            ctx.textAlign = "left";
            ctx.textBaseline = "top";
            for (let i = 0; i < count; i++) {
                ctx.fillText(lines[i], x, y + i * LINE_H);
            }
            ctx.restore();
        };

        const origRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            origRemoved?.apply(this, arguments);
            this._vfxLines = null;
            this._vfxBatchTotal = 0;
            this._vfxBatchVars = 5;
        };
    },

    nodeCreated(node) {
        if (node.constructor?.category === "VFX") {
            node.color = ORANGE;
            node.bgcolor = DARK_BG;
        }
    },

    setup() {
        if (!api) return;

        api.addEventListener("impact-add-queue", () => {
            const nodes = (app.graph._nodes || []).filter(
                (n) => n.type === "VFXFluxBatchPrompts"
            );
            if (!nodes.length) return;

            for (const node of nodes) {
                const autoQueueW = node.widgets?.find(
                    (w) => w.name === "auto_queue"
                );
                if (!autoQueueW?.value) continue;

                const idxW = node.widgets?.find(
                    (w) => w.name === "prompt_index"
                );
                const varW = node.widgets?.find(
                    (w) => w.name === "variation"
                );
                if (!idxW || !varW) continue;

                const totalPrompts = node._vfxBatchTotal || 0;
                const totalVars = node._vfxBatchVars || 5;

                const curIdx = idxW.value;
                const curVar = varW.value;

                let nextVar = curVar + 1;
                let nextIdx = curIdx;
                if (nextVar >= totalVars) {
                    nextVar = 0;
                    nextIdx = curIdx + 1;
                }

                if (totalPrompts > 0 && nextIdx >= totalPrompts) {
                    autoQueueW.value = false;
                    node.setDirtyCanvas(true, true);
                    continue;
                }

                idxW.value = nextIdx;
                varW.value = nextVar;
                node.setDirtyCanvas(true, true);
            }
        });
    },
});
