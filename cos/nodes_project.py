"""COS Project — create / load / refresh the project config.

Thin ComfyUI node layer. It resolves the COS root from ComfyUI's output
directory and delegates every operation to :mod:`cos.core`.

The config uses the studio's project schema (``<PROJECT>.json``), so COS is
grammar-compatible with the pipeline even though it is an independent system.
"""

from __future__ import annotations

import os

from . import core

try:
    import folder_paths
except ImportError:  # standalone / tests
    folder_paths = None


def output_root() -> str:
    """COS root = ComfyUI output directory (never write outside it)."""
    if folder_paths is None:
        raise RuntimeError("folder_paths no disponible: ejecuta dentro de ComfyUI")
    return folder_paths.get_output_directory()


def default_artist() -> str:
    """Artist folder name (``COS_ARTIST`` > Windows user > ``comfy``)."""
    return os.environ.get("COS_ARTIST") or os.environ.get("USERNAME") or "comfy"


class COSProject:
    """Create or load a COS project: ``<PROJECT>.json`` + ``_PROJECT.md`` + tree.

    * ``create``  -- build from the inputs (idempotent).
    * ``load``    -- read the existing ``<PROJECT>.json`` (falls back to create).
    * ``refresh`` -- rewrite the config and the tree from the inputs.

    The root is ComfyUI's output directory (``--output-directory``), so the
    nodes can write straight into the COS tree with a ``filename_prefix``.
    """

    DESCRIPTION = (
        "Crea o carga un proyecto COS. Escribe <PROJECT>.json (esquema del "
        "pipeline: fps, formatos, masking, entidades) y _PROJECT.md, y prepara "
        "el arbol <PROJECT>/<shot|asset>/<ENTIDAD>/{work,version,publish}. "
        "El root es el output directory de ComfyUI."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (
                    ["create", "load", "refresh"],
                    {"default": "create", "tooltip": "create: desde los inputs. load: lee el config existente. refresh: reescribe config y arbol."},
                ),
                "project": ("STRING", {"default": "TOTIE", "tooltip": "Codigo de proyecto (ej. TOTIE)."}),
                "fps": ("INT", {"default": 24, "min": 1, "max": 240, "tooltip": "FPS del proyecto."}),
                "width": ("INT", {"default": 3840, "min": 1, "max": 16384, "tooltip": "Ancho master."}),
                "height": ("INT", {"default": 2160, "min": 1, "max": 16384, "tooltip": "Alto master."}),
                "entities": ("STRING", {"default": "TOTIE_003_0030,TOTIE_003_0010", "multiline": True, "tooltip": "Entidades separadas por comas. Formato <PROJECT>_<SEQ>_<SHOT> (ej. TOTIE_003_0030). Para assets: TOTIE_CHR_Totie:asset"}),
            },
            "optional": {
                "format_name": ("STRING", {"default": "", "tooltip": "Nombre del formato (vacio = el del proyecto)."}),
                "par": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 10.0, "step": 0.01, "tooltip": "Pixel aspect ratio."}),
                "ocio": ("STRING", {"default": "", "tooltip": "Ruta al config.ocio (informativo)."}),
                "handles_in": ("INT", {"default": 8, "min": 0, "max": 1000, "tooltip": "Handles de entrada."}),
                "handles_out": ("INT", {"default": 8, "min": 0, "max": 1000, "tooltip": "Handles de salida."}),
                "artist": ("STRING", {"default": "", "tooltip": "Artista por defecto (vacio = usuario de Windows)."}),
            },
        }

    RETURN_TYPES = ("COS_PROJECT", "STRING", "STRING")
    RETURN_NAMES = ("project", "project_path", "info")
    FUNCTION = "run"
    CATEGORY = "COS"
    OUTPUT_NODE = False

    def run(
        self,
        action: str,
        project: str,
        fps: int,
        width: int,
        height: int,
        entities: str,
        format_name: str = "",
        par: float = 1.0,
        ocio: str = "",
        handles_in: int = 8,
        handles_out: int = 8,
        artist: str = "",
    ):
        root = output_root()
        project = core.validate_project(project)
        cfg_path = core.project_config_path(root, project)

        if action == "load" and cfg_path.exists():
            config = core.load_project_config(cfg_path)
            action_done = "loaded"
        else:
            if action == "load":
                print(f"[COS] config no encontrado en {cfg_path}; creando desde los inputs.")
            config = core.build_project_config(
                project,
                fps=fps,
                width=width,
                height=height,
                par=par,
                format_name=format_name,
                entities=core.parse_entities(entities),
                root=root,
                ocio=ocio,
                handles=(handles_in, handles_out),
            )
            if artist:
                config["artist"] = artist
            core.write_project_config(root, config)
            action_done = "created" if action != "refresh" else "refreshed"

        core.ensure_project(root, config)
        core.write_project_md(root, config)

        n_entities = len(config.get("entities") or {})
        fmt = core.config_format(config)
        info = (
            f"{action_done}: {project} @ {root} | {n_entities} entidades | "
            f"{fmt.get('width')}x{fmt.get('height')} @ {config.get('fps')}fps"
        )
        return (config, str(cfg_path), info)
