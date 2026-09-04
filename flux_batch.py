"""
VFX Flux Batch Prompts — automated prompt generation for Flux2 campaigns.
==========================================================================
Lee un archivo markdown con prompts de Flux2, parsea las tablas,
y genera salidas de prompt + seed para cada combinacion prompt x variacion.

Compatible con auto-queue daisy-chain via JS companion (vfx_flux_batch.js).
"""

from __future__ import annotations

import os
import re

DEFAULT_NEGATIVE = (
    "blurry, low quality, distorted, deformed, bad anatomy, watermark, "
    "text, logo, signature, extra limbs, fused fingers, ugly, mutation, "
    "worst quality, jpeg artifacts, "
    "visible legs, long legs, stretched limbs, human legs, animal legs, "
    "paws separated from body, realistic anatomy, visible knees, "
    "visible ankles, elongated body, disproportionate limbs"
)

DEFAULT_SUFFIX = (
    "tack sharp focus, high contrast, vibrant saturated colors, rich tones, "
    "professional color grading, bright commercial studio lighting, "
    "strong key light with soft fill, crisp details, deep blacks, "
    "clean white seamless background, 8K ultra high detail, "
    "professional product photography, professionally retouched"
)

_PROMPT_CACHE: dict[str, list[dict]] = {}
_PROMPT_CACHE_MTIME: dict[str, float] = {}


# ============================================================================
# Markdown parser
# ============================================================================

def _parse_flux2_md(filepath: str) -> list[dict]:
    """Parse Flux2 prompt markdown file.

    Returns list of dicts::

        {number: int, name: str, prompt: str, section: str}

    Skips ``[VIDEO ...]`` entries and non-prompt rows.
    Results are cached by filepath + mtime.
    """
    if not os.path.isfile(filepath):
        return []

    mtime = os.path.getmtime(filepath)
    if filepath in _PROMPT_CACHE and _PROMPT_CACHE_MTIME.get(filepath) == mtime:
        return _PROMPT_CACHE[filepath]

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    prompts: list[dict] = []
    current_section = ""

    for line in lines:
        stripped = line.strip()

        # Track markdown headers for section context
        if stripped.startswith("## ") or stripped.startswith("### "):
            current_section = re.sub(r"^#+\s*", "", stripped)
            current_section = re.sub(r"^\d+\.?\s*", "", current_section)
            continue

        # Only process table rows
        if not stripped.startswith("|"):
            continue

        # Skip separator rows like |---|-------|
        if re.match(r"^\|[\s\-:]+\|", stripped):
            continue

        # Split columns (skip empty first/last from leading/trailing |)
        cols = [c.strip() for c in stripped.split("|")]
        if cols and cols[0] == "":
            cols = cols[1:]
        if cols and cols[-1] == "":
            cols = cols[:-1]

        if len(cols) < 3:
            continue

        # Detect header row (first column is "#" or non-numeric)
        try:
            number = int(cols[0])
        except ValueError:
            continue

        # Extract based on column count (3-col vs 4-col tables with Nivel)
        name = cols[1]
        prompt_text = cols[-1]  # last column is always the prompt

        # Skip VIDEO entries
        if "[VIDEO" in prompt_text:
            continue

        # Clean prompt — strip backtick code formatting
        prompt_clean = prompt_text.strip("`").strip()
        prompt_clean = re.sub(r"^`+|`+$", "", prompt_clean).strip()

        if prompt_clean:
            prompts.append(
                {
                    "number": number,
                    "name": name,
                    "prompt": prompt_clean,
                    "section": current_section,
                }
            )

    _PROMPT_CACHE[filepath] = prompts
    _PROMPT_CACHE_MTIME[filepath] = mtime
    return prompts


# ============================================================================
# Node
# ============================================================================

class VFXFluxBatchPrompts:
    """Generador batch de prompts para campanas Flux2.

    Lee un archivo markdown con prompts de Flux2 (formato tabla),
    parsea las piezas y genera salidas de prompt + seed para cada
    combinacion prompt x variacion.

    **Uso manual:**
        Ajusta prompt_index y variation para seleccionar la combinacion.
        Conecta la salida ``prompt`` al CLIP Text Encode
        (clic derecho -> Convert Widget to Input).

    **Auto-queue:**
        Activa auto_queue y ejecuta una vez. El JS companion encola
        automaticamente todas las combinaciones restantes con un
        daisy-chain (una a una, cancelable en cualquier momento).

    **Seed:** ``base_seed + prompt_index * variations + variation``.
    """

    DESCRIPTION = (
        "Generador batch de prompts para campanas Flux2. "
        "Lee un archivo markdown con tablas de prompts y genera salidas "
        "de prompt + seed + filename_prefix para cada combinacion. "
        "Conecta filename_prefix a SaveImage para guardar con nombre descriptivo. "
        "Usa auto_queue=true + ImpactQueueTrigger para lanzar el batch completo."
    )

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "file_path": (
                    "STRING",
                    {
                        "default": "E:\\OpenCode\\Proyecto-LAB\\MIOPIA-HELP\\prompts-flux2-totie.md",
                        "multiline": False,
                        "tooltip": "Ruta al archivo markdown con los prompts de Flux2 (formato tabla).",
                    },
                ),
                "prompt_index": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 9999,
                        "step": 1,
                        "tooltip": "Indice del prompt (0-based). Selecciona la pieza de la campana.",
                    },
                ),
                "variation": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 999,
                        "step": 1,
                        "tooltip": "Variacion de seed. 0 = primera version, 1 = segunda, etc.",
                    },
                ),
                "variations": (
                    "INT",
                    {
                        "default": 5,
                        "min": 1,
                        "max": 100,
                        "step": 1,
                        "tooltip": "Cuantas versiones (semillas) generar por cada prompt.",
                    },
                ),
                "base_seed": (
                    "INT",
                    {
                        "default": 42,
                        "min": 0,
                        "max": 0xFFFFFFFF,
                        "step": 1,
                        "tooltip": "Seed base. Seed final = base_seed + prompt_index * variations + variation.",
                    },
                ),
                "auto_queue": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "ON: auto-incrementa prompt_index/variation en cada ejecucion. Usalo con ImpactQueueTrigger (mode=true) para lanzar el batch completo con un solo Ctrl+Enter.",
                    },
                ),
                "prompt_suffix": (
                    "STRING",
                    {
                        "default": DEFAULT_SUFFIX,
                        "multiline": True,
                        "tooltip": "Anadido al FINAL de cada prompt. Para mejorar nitidez, contraste, iluminacion, colores, etc. Vacio = no se anade nada.",
                    },
                ),
            },
        }

    RETURN_TYPES = (
        "STRING",
        "STRING",
        "INT",
        "STRING",
        "INT",
        "INT",
        "STRING",
        "STRING",
    )
    RETURN_NAMES = (
        "prompt",
        "negative_prompt",
        "seed",
        "piece_name",
        "piece_number",
        "total_prompts",
        "section",
        "filename_prefix",
    )
    FUNCTION = "get_prompt"
    CATEGORY = "VFX"

    def get_prompt(
        self,
        file_path: str,
        prompt_index: int,
        variation: int,
        variations: int,
        base_seed: int,
        auto_queue: bool,
        prompt_suffix: str = "",
    ):
        prompts = _parse_flux2_md(file_path)
        total = len(prompts)

        if total == 0:
            result = ("", DEFAULT_NEGATIVE, base_seed, "", 0, 0, "", "")
            return {
                "ui": {"vfx_info": ["No prompts found", "Check file path"], "batch_total": [0], "batch_variations": [0]},
                "result": result,
            }

        # Clamp to valid range (wrap-around for resilience)
        idx = prompt_index % total if prompt_index >= total else prompt_index
        var = variation % variations if variation >= variations else variation

        entry = prompts[idx]
        seed = base_seed + prompt_index * variations + variation

        # Concatenate suffix if provided
        suffix = prompt_suffix.strip() if prompt_suffix else ""
        full_prompt = f"{entry['prompt']}, {suffix}" if suffix else entry["prompt"]

        # Build sanitized filename prefix: "001_Totie_gesto_OK_seed42"
        name_slug = re.sub(r"[\\/:*?\"<>|]", "", entry["name"])
        name_slug = re.sub(r"\s+", "_", name_slug)
        name_slug = name_slug[:50].strip("_")
        filename_prefix = f"{entry['number']:03d}_{name_slug}_seed{seed}"

        result = (
            full_prompt,
            DEFAULT_NEGATIVE,
            seed,
            entry["name"],
            entry["number"],
            total,
            entry["section"],
            filename_prefix,
        )

        # Build info panel lines
        name_trunc = entry["name"][:28]
        vfx_info = [
            f"#{entry['number']} {name_trunc}",
            f"prompt {idx + 1}/{total}  var {var + 1}/{variations}",
            f"seed: {seed}",
        ]
        if suffix:
            vfx_info.append(f"[suffix: {len(suffix)} chars]")
        if auto_queue:
            vfx_info.append("AUTO-QUEUE ON")

        return {"ui": {"vfx_info": vfx_info, "batch_total": [total], "batch_variations": [variations]}, "result": result}
