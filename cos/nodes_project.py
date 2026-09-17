"""COS Project — create / load / refresh a COS project.

Thin ComfyUI node layer. It resolves the COS root from ComfyUI's output
directory and delegates every operation to :mod:`cos.core`.
"""

from __future__ import annotations

from . import core

try:
    import folder_paths
except ImportError:  # standalone / tests
    folder_paths = None


def _output_root() -> str:
    """COS root = ComfyUI output directory (never write outside it)."""
    if folder_paths is None:
        raise RuntimeError("folder_paths no disponible: ejecuta dentro de ComfyUI")
    return folder_paths.get_output_directory()


class COSProject:
    """Create or load a COS project: root skeleton + ``project.json`` + ``_PROJECT.md``.

    * ``create``  -- build from the inputs (idempotent; preserves ``created``).
    * ``load``    -- read the existing ``project.json`` (falls back to create).
    * ``refresh`` -- rebuild skeleton + ``_PROJECT.md`` from the inputs.
    """

    DESCRIPTION = (
        "Crea o carga un proyecto COS. Genera el esqueleto de carpetas "
        "(PROJECTS/RND/ASSETS/_INBOX/_TRASH y el arbol por secuencia/plano), "
        "escribe project.json (ficha de maquina) y _PROJECT.md (ficha humana). "
        "El root es el output directory de ComfyUI. Salida project para los "
        "demas nodos COS."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (
                    ["create", "load", "refresh"],
                    {"default": "create", "tooltip": "create: crea desde los inputs. load: lee el project.json existente. refresh: regenera esqueleto y _PROJECT.md."},
                ),
                "show": ("STRING", {"default": "tot", "tooltip": "Codigo de show: 3 letras minusculas (ej. tot)."}),
                "project": ("STRING", {"default": "Totie", "tooltip": "Nombre legible del proyecto (ej. Totie)."}),
                "artist": ("STRING", {"default": "mio", "tooltip": "Iniciales del artista (solo para el sidecar)."}),
                "fps": ("INT", {"default": 24, "min": 1, "max": 240, "tooltip": "FPS del proyecto."}),
                "sequences": ("STRING", {"default": "cine,pant", "tooltip": "Secuencias separadas por comas (ej. cine,pant)."}),
                "variants": ("STRING", {"default": ";gen,callao,granvia", "tooltip": "Variantes por secuencia, separadas por ';' (posicional). Vacio = sin variantes. Ej. ';gen,callao,granvia'."}),
                "shots": ("STRING", {"default": "cine:0010_cine;pant:0010_boca,0020_oreja,0030_despedida", "tooltip": "Planos por secuencia: seq:id_nombre separados por ','; secuencias por ';'."}),
            },
            "optional": {
                "config_extra": ("STRING", {"default": "", "multiline": True, "tooltip": "JSON opcional con resoluciones/extras. Se fusiona en project.json. Ej. {\"sequences\": {\"pant\": {\"variants\": {\"gen\": {\"resolution\": [1920, 1080]}}}}}"}),
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
        show: str,
        project: str,
        artist: str,
        fps: int,
        sequences: str,
        variants: str,
        shots: str,
        config_extra: str = "",
    ):
        root = _output_root()
        slug = core.make_slug(show, project)
        pjson = core.project_json_path(root, slug)

        if action == "load" and pjson.exists():
            data = core.load_project(pjson)
            core.build_skeleton(root, data)
            core.write_project_md(root, data)
            action_done = "loaded"
        else:
            if action == "load":
                print(f"[COS] project.json no encontrado en {pjson}; creando desde los inputs.")
            created = None
            if pjson.exists():
                try:
                    created = core.load_project(pjson).get("created")
                except (OSError, ValueError):
                    created = None
            data = core.build_project_dict(
                show, project, artist, fps,
                sequences, variants, shots,
                config_extra, root=root, created=created,
            )
            core.build_skeleton(root, data)
            core.write_project(root, data)
            core.write_project_md(root, data)
            action_done = "created" if action != "refresh" else "refreshed"

        n_seq = len(data.get("sequences", {}))
        n_shots = sum(len(s.get("shots", {})) for s in data.get("sequences", {}).values())
        info = f"{action_done}: {slug} @ {root} | {n_seq} seq, {n_shots} planos"
        return (data, str(pjson), info)
