# AGENTS.md -- VFX-Nodes Project Context for OpenCode

## User

**Name:** Mike
**ComfyUI install:** `E:\Comfyui\ComfyUI-Easy-Install\ComfyUI\custom_nodes\VFX_Nodes\`
**Obsidian Vault (Diario):** `E:\Obsidian\Vault-DIARIO-OpenCode\`
**Obsidian Vault (ComfyUI):** `E:\Obsidian\Vault-Comfyui\`

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

The project uses TWO Obsidian vaults. Both must be updated when documenting work.

### Vault 1: DIARIO-OpenCode (`E:\Obsidian\Vault-DIARIO-OpenCode\`)

Project-specific docs and daily session logs.

```
Vault-DIARIO-OpenCode/
├── Diario/                  Daily notes (YYYY-MM-DD.md)
│   └── 2026-07-31.md        Example: pixel shift debugging session
├── Proyectos/
│   └── VFX-Nodes/           Project documentation
│       ├── VFX-Nodes.md         Main project hub (version, changelog, links)
│       ├── VFXFramePad.md       New node documentation
│       ├── Instalación VFX_NODES.md  Installation guide
│       └── VFX Nodes - Correcciones de Bugs.md
└── Templates/               Note templates
```

### Vault 2: ComfyUI (`E:\Obsidian\Vault-Comfyui\`)

User-facing documentation and workflow guides for ComfyUI usage.

```
Vault-Comfyui/
└── DOCUMENTS/
    ├── Pipeline VFX - Control de Resolucion en ComfyUI.md  Main pipeline guide
    ├── VFX Frame Pad - Guía de Uso.md                      FramePad usage guide
    └── Instalacion VFX_NODES.md                            Installation guide
```

### Post-session documentation checklist

After every working session, run through this checklist:

1. **Commit & Push** — `git add`, `git commit`, `git push` all code changes to GitHub
2. **Vault DIARIO** — Create/update daily note in `Diario/YYYY-MM-DD.md` with:
   - Objectives completed
   - Technical findings (bugs, solutions, lessons)
   - Files changed
   - References to related notes
3. **Vault DIARIO — Project hub** — Update `Proyectos/VFX-Nodes/VFX-Nodes.md`:
   - Bump version if applicable
   - Add changelog entry
   - Add session entry
   - Add link to daily note
4. **Vault DIARIO — Bug corrections** — If debugging was done, update `VFX Nodes - Correcciones de Bugs.md`
5. **Vault ComfyUI** — Update relevant guides if:
   - New feature added (pipeline workflow, new parameter)
   - New best practice discovered
   - Workflow tip or warning to document
6. **Deploy** — Copy updated files to ComfyUI install:
   ```powershell
   Copy-Item "E:\OpenCode\Proyecto-LAB\VFX-Nodes\__init__.py" -Destination "E:\Comfyui\ComfyUI-Easy-Install\ComfyUI\custom_nodes\VFX_Nodes\__init__.py"
   Copy-Item "E:\OpenCode\Proyecto-LAB\VFX-Nodes\js\*" -Destination "E:\Comfyui\ComfyUI-Easy-Install\ComfyUI\custom_nodes\VFX_Nodes\js\" -Recurse
   ```

### Documentation workflow (detailed)

1. Update `Proyectos/VFX-Nodes/VFX-Nodes.md` — bump version, update changelog
2. Create/update node-specific doc in `Proyectos/VFX-Nodes/` (e.g., `VFXFramePad.md`)
3. Create daily note in `Diario/YYYY-MM-DD.md` with session summary
4. If new node or node count changed, update `Instalación VFX_NODES.md`
5. Update `Vault-Comfyui/DOCUMENTS/` guides for user-facing changes
6. Run `validate_roundtrip.py` and confirm 0 failures before deploying
