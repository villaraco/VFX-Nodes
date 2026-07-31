import { app } from "../../../scripts/app.js";

const ORANGE = "#FF8C00";
const DARK_BG = "#3D2000";
const INFO_FONT = "11px 'Segoe UI', sans-serif";
const LINE_H = 15;
const INFO_PAD = 6;

const RES_NODES = new Set([
    "VFXPrepareResolution",
    "VFXRestoreResolution",
]);

app.registerExtension({
    name: "VFX_Nodes.colors",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!RES_NODES.has(nodeData.name)) return;

        const origExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (output) {
            origExecuted?.apply(this, arguments);
            const vfx = output?.vfx_info;
            this._vfxLines = vfx?.length ? vfx : null;
            this.setDirtyCanvas(true, true);
        };

        const origDraw = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            origDraw?.apply(this, arguments);
            if (!this._vfxLines || this.flags?.collapsed) return;

            const lines = this._vfxLines;
            const count = lines.length;
            const w = 155;
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
        };
    },

    nodeCreated(node) {
        if (node.constructor?.category === "VFX") {
            node.color = ORANGE;
            node.bgcolor = DARK_BG;
        }
    },
});
