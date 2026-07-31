# AGENTS.md -- VFX-Nodes Project Context for OpenCode

## User

**Name:** Mike
**ComfyUI install:** `E:\Comfyui\ComfyUI-Easy-Install\ComfyUI\custom_nodes\VFX_Nodes\`
**Obsidian Vault:** `E:\Obsidian\Vault-DIARIO-OpenCode\`

## Project

VFX-Nodes: Custom nodes for ComfyUI that ensure pixel-perfect resolution roundtrip
in VFX pipelines. Input images go through AI models at any resolution and come back
at the exact original resolution and format.

## How It Works

```
Original Image  →  [VFXPrepareResolution]  →  AI Model  →  [VFXRestoreResolution]  →  Original Resolution
                     (pad or downscale+pad)                   (crop or crop+upscale)
```

## Project Structure

```
VFX-Nodes/
├── __init__.py              Main nodes: VFXPrepareResolution, VFXRestoreResolution, VFXFitDimension, VFXFramePad
├── corrections.py           Optional: VFXCorrections (SIFT align + color match + blend)
├── validate_roundtrip.py    Standalone test suite (no ComfyUI needed)
├── requirements.txt         opencv-contrib-python (optional, for corrections node)
├── js/
│   └── vfx_colors.js        ComfyUI UI colors (orange theme for VFX category)
├── docs/                    Project specifications (linked from Obsidian vault)
├── README.md                User-facing documentation
└── AGENTS.md                This file
```

## Tech Stack

- Python 3.10+ (ComfyUI requirement)
- PyTorch (comes with ComfyUI)
- opencv-contrib-python (optional, for VFXCorrections node)

## Conventions

- **Language:** Documentation and comments in Spanish. Code in English.
- **Node naming:** VFX{Name} prefix, CATEGORY = "VFX"
- **Node design:** Each node is a class with INPUT_TYPES, RETURN_TYPES, FUNCTION.
- **Input validation:** Minimal -- ComfyUI handles type checking. Nodes assume valid inputs.
- **Error handling:** Graceful degradation. If optional deps missing, nodes skip features instead of crashing.
- **Testing:** validate_roundtrip.py is standalone. Import nodes directly, no ComfyUI server needed.

## Key Design Decisions

1. **Asymmetric padding (right + bottom):** Anchor top-left. No centering. This makes crop trivial -- just remove known padding dimensions.
2. **Uniform scale on restore:** Single scale factor for both axes. Zero aspect distortion.
3. **Adaptive restore:** If model changes output dimensions (e.g., Flux2Klein rebuckets), node handles it gracefully instead of crashing.
4. **Multiple alignment:** All pad/scale operations align to VAE multiple (varies per model).

## How to Test

```bash
python validate_roundtrip.py        # All tests
python validate_roundtrip.py --all  # Same
```

CI/CD: exit code 0 = all pass, exit code 1 = failures.

## Integration with ComfyUI

Copy the VFX-Nodes folder to `ComfyUI/custom_nodes/VFX_Nodes/`. The `__init__.py` registers nodes via NODE_CLASS_MAPPINGS. The `js/` folder provides UI theme colors.

## Obsidian Vault Documentation

When asked to document the project, write notes in the Obsidian vault at
`E:\Obsidian\Vault-DIARIO-OpenCode\`. The project-specific docs live in
`Proyectos/VFX-Nodes/`. Daily session summaries go in `Diario/YYYY-MM-DD.md`.

### Vault structure (relevant paths)

```
Vault-DIARIO-OpenCode/
├── Diario/                  Daily notes (YYYY-MM-DD.md)
│   └── 2026-07-30.md        Example: VFXFramePad implementation session
├── Proyectos/
│   └── VFX-Nodes/           Project documentation
│       ├── VFX-Nodes.md         Main project hub (version, changelog, links)
│       ├── VFXFramePad.md       New node documentation
│       ├── Instalación VFX_NODES.md  Installation guide
│       └── VFX Nodes - Correcciones de Bugs.md
└── Templates/               Note templates
```

### Documentation workflow

1. Update `Proyectos/VFX-Nodes/VFX-Nodes.md` — bump version, update changelog
2. Create/update node-specific doc in `Proyectos/VFX-Nodes/` (e.g., `VFXFramePad.md`)
3. Create daily note in `Diario/YYYY-MM-DD.md` with session summary
4. If new node or node count changed, update `Instalación VFX_NODES.md`
