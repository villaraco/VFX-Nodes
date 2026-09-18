/**
 * COS Nodes — colours & Refresh button.
 * =====================================
 * - Brown/orange theme for the ``COS`` category (sibling of the VFX orange).
 * - "Refresh COS" button: re-fetches ``/object_info`` so the dynamic entity
 *   dropdowns pick up projects/entities created since the page loaded.
 *   (Same as pressing R — ComfyUI's "Refresh Node Definitions".)
 */

import { app } from "../../../scripts/app.js";

const COS_BROWN = "#B35C00";
const COS_BG = "#2E1A00";

const COS_NODES = new Set(["COSProject", "COSShot", "COSPath", "COSApprove"]);

async function refreshCos() {
    try {
        if (typeof app.refreshComboInNodes === "function") {
            await app.refreshComboInNodes();
            return;
        }
        // Fallback for older frontends: refetch the defs by hand.
        const { api } = await import("../../../scripts/api.js");
        const defs = await api.getNodeDefs();
        for (const node of app.graph?._nodes || []) {
            if (COS_NODES.has(node.type) && node.refreshComboInNode) {
                node.refreshComboInNode(defs);
            }
        }
    } catch (err) {
        console.warn("[COS] no se pudo refrescar la lista de entidades:", err);
    }
}

app.registerExtension({
    name: "COS_Nodes.ui",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (!COS_NODES.has(nodeData.name)) return;

        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origOnNodeCreated?.apply(this, arguments);

            this.color = COS_BROWN;
            this.bgcolor = COS_BG;

            this.addWidget("button", "Refresh COS", null, () => refreshCos(), {
                tooltip: "Vuelve a leer los proyectos y entidades (igual que pulsar R).",
            });
        };
    },
});
