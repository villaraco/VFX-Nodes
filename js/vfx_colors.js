import { app } from "../../../scripts/app.js";

const ORANGE = "#FF8C00";
const DARK_BG = "#3D2000";

app.registerExtension({
    name: "VFX_Nodes.colors",
    nodeCreated(node) {
        if (node.constructor?.category === "VFX") {
            node.color = ORANGE;
            node.bgcolor = DARK_BG;
        }
    },
});
