"""COS Path — the workhorse: short prefix + version + sidecar.

Thin ComfyUI node layer. It resolves the COS root from ComfyUI's output
directory and delegates every operation to :mod:`cos.core`.

The node returns the same short prefix for EXR / video / PNG; each save
node appends its own counter and extension (``_00001_.exr`` ...).
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


class COSPath:
    """Resolve the output prefix, the version and the ``_meta.json`` sidecar.

    * ``current`` -- reuse the working version of the shot.
    * ``new``     -- open the next version (a new generative pass).

    Wire ``exr_prefix`` / ``video_prefix`` / ``png_prefix`` into the save
    nodes (right click on ``filename_prefix`` -> *Convert widget to input*).
    """

    DESCRIPTION = (
        "Genera el prefijo corto de guardado y resuelve la version del plano. "
        "Nombre: <show>_<seq>[_<variant>]_<shot>_<task>_v### (sin modelo, seed, "
        "artista ni resolucion). Crea las carpetas necesarias y escribe el "
        "sidecar <base>_meta.json con seed, modelo, resolucion, workflow y "
        "prompt. El root es el output directory de ComfyUI."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project": ("COS_PROJECT", {"tooltip": "Objeto del nodo COS Project."}),
                "seq": ("STRING", {"default": "cine", "tooltip": "Secuencia (debe existir en project.json)."}),
                "shot_id": ("STRING", {"default": "0010", "tooltip": "ID del plano (ej. 0010)."}),
                "task": (
                    list(core.VALID_TASKS),
                    {"default": "i2v", "tooltip": "Operacion de ComfyUI. Para una task propia usa 'task_custom'."},
                ),
                "version_mode": (
                    ["current", "new"],
                    {"default": "current", "tooltip": "current: reusa la version en curso. new: abre la siguiente pasada generativa."},
                ),
            },
            "optional": {
                "project_path": ("STRING", {"default": "", "tooltip": "Alternativa a 'project': ruta a un project.json existente."}),
                "variant": ("STRING", {"default": "", "tooltip": "Variante de la secuencia (vacio si la secuencia no tiene variantes)."}),
                "task_custom": ("STRING", {"default": "", "tooltip": "Task libre; si no esta vacia, sustituye a 'task'."}),
                "model": ("STRING", {"default": "", "tooltip": "Nombre del modelo (solo para el sidecar)."}),
                "seed": ("INT", {"default": 0, "forceInput": True, "tooltip": "Seed de cualquier nodo INT (solo para el sidecar)."}),
                "write_meta": ("BOOLEAN", {"default": True, "tooltip": "Escribe el sidecar _meta.json."}),
                "ensure_dirs": ("BOOLEAN", {"default": True, "tooltip": "Crea las carpetas del plano y de la version."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("exr_prefix", "video_prefix", "png_prefix", "version", "out_dir", "info")
    FUNCTION = "run"
    CATEGORY = "COS"
    OUTPUT_NODE = False

    def run(
        self,
        project,
        seq: str,
        shot_id: str,
        task: str,
        version_mode: str,
        project_path: str = "",
        variant: str = "",
        task_custom: str = "",
        model: str = "",
        seed: int = 0,
        write_meta: bool = True,
        ensure_dirs: bool = True,
        prompt=None,
        extra_pnginfo=None,
    ):
        root = _output_root()

        if project_path and project_path.strip():
            data = core.load_project(project_path.strip())
        elif isinstance(project, dict) and project:
            data = project
        else:
            raise ValueError(
                "COS Path: conecta 'project' (nodo COS Project) o rellena 'project_path'."
            )

        task = core.normalize_task(task_custom) if (task_custom or "").strip() else core.normalize_task(task)
        variant = (variant or "").strip() or None
        shot_id = (shot_id or "").strip()

        shot_dir = core.resolve_shot_dir(root, data, seq, shot_id, variant)
        if ensure_dirs:
            core.ensure_shot_dirs(shot_dir)

        version = core.resolve_version(shot_dir, version_mode)
        core.register_task(shot_dir, version, task)

        out = core.build_output(root, data, seq, shot_id, task, version, variant)
        if ensure_dirs:
            out["out_dir"].mkdir(parents=True, exist_ok=True)

        meta_name = ""
        if write_meta:
            workflow = extra_pnginfo.get("workflow") if isinstance(extra_pnginfo, dict) else None
            meta = core.build_meta(
                data,
                seq,
                shot_id,
                core.shot_name_for(data, seq, shot_id),
                task,
                version,
                model=model,
                seed=int(seed),
                resolution=core.resolve_resolution(data, seq, variant),
                fps=data.get("fps", 24),
                variant=variant,
                workflow=workflow,
                prompt=prompt,
            )
            meta_name = core.write_meta(out["out_dir"], out["base"], meta).name

        info = f"{out['base']} @ {out['out_dir']}"
        if meta_name:
            info += f" | {meta_name}"
        return (out["prefix"], out["prefix"], out["prefix"], version, str(out["out_dir"]), info)
