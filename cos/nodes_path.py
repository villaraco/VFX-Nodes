"""COS Path — the workhorse: short prefix + version + sidecar.

Thin ComfyUI node layer. It resolves the COS root from ComfyUI's output
directory and delegates every operation to :mod:`cos.core`.

The node returns the same short prefix for EXR / video / PNG; each save
node appends its own counter and extension (``_00001_.exr`` ...).
"""

from __future__ import annotations

from pathlib import Path

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


def _resolve_project(project, project_path: str = "") -> dict:
    """Project dict from the wired object, or from a ``project.json`` path."""
    if project_path and project_path.strip():
        return core.load_project(project_path.strip())
    if isinstance(project, dict) and project:
        return project
    raise ValueError(
        "COS: conecta 'project' (nodo COS Project) o rellena 'project_path'."
    )


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
                "shot": ("COS_SHOT", {"tooltip": "Objeto del nodo COS Shot: fija seq, variante, plano y nombre."}),
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
        shot=None,
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
        data = _resolve_project(project, project_path)

        shot_name = ""
        if isinstance(shot, dict) and shot.get("path"):
            seq = shot.get("seq") or seq
            shot_id = shot.get("shot_id") or shot_id
            variant = shot.get("variant") or variant
            shot_name = shot.get("shot_name") or ""

        task = core.normalize_task(task_custom) if (task_custom or "").strip() else core.normalize_task(task)
        variant = (variant or "").strip() or None
        shot_id = (shot_id or "").strip()
        shot_name = (shot_name or "").strip() or core.shot_name_for(data, seq, shot_id)

        shot_dir = core.shot_dir_for(root, data, seq, shot_id, variant, shot_name)
        if ensure_dirs:
            core.ensure_shot_dirs(shot_dir)

        version = core.resolve_version(shot_dir, version_mode)
        core.register_task(shot_dir, version, task)

        out = core.build_output(
            root, data, seq, shot_id, task, version, variant, shot_name=shot_name
        )
        if ensure_dirs:
            out["out_dir"].mkdir(parents=True, exist_ok=True)

        meta_name = ""
        if write_meta:
            workflow = extra_pnginfo.get("workflow") if isinstance(extra_pnginfo, dict) else None
            meta = core.build_meta(
                data,
                seq,
                shot_id,
                shot_name,
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


class COSShot:
    """Ensure a shot exists: folder tree + registration in ``project.json``.

    Use it to add a new shot without recreating the whole project. The
    output ``shot`` (``COS_SHOT``) feeds ``COS Approve``.
    """

    DESCRIPTION = (
        "Asegura un plano: crea su arbol (01_INPUT/02_WORK/03_PUBLISH + "
        "_NOTES.md) y, opcionalmente, lo registra en project.json y regenera "
        "_PROJECT.md. Salida shot (COS_SHOT) para COS Approve."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project": ("COS_PROJECT", {"tooltip": "Objeto del nodo COS Project."}),
                "seq": ("STRING", {"default": "cine", "tooltip": "Secuencia (se crea si no existia)."}),
                "shot_id": ("STRING", {"default": "0010", "tooltip": "ID del plano (ej. 0010)."}),
            },
            "optional": {
                "project_path": ("STRING", {"default": "", "tooltip": "Alternativa a 'project': ruta a un project.json existente."}),
                "variant": ("STRING", {"default": "", "tooltip": "Variante de la secuencia (vacio si no tiene)."}),
                "shot_name": ("STRING", {"default": "", "tooltip": "Nombre legible del plano (ej. boca). Vacio = el que ya tenga."}),
                "register": ("BOOLEAN", {"default": True, "tooltip": "Registra el plano en project.json si no estaba."}),
            },
        }

    RETURN_TYPES = ("COS_SHOT", "STRING", "STRING")
    RETURN_NAMES = ("shot", "shot_path", "info")
    FUNCTION = "run"
    CATEGORY = "COS"
    OUTPUT_NODE = False

    def run(
        self,
        project,
        seq: str,
        shot_id: str,
        project_path: str = "",
        variant: str = "",
        shot_name: str = "",
        register: bool = True,
    ):
        root = _output_root()
        data = _resolve_project(project, project_path)

        seq = (seq or "").strip()
        shot_id = (shot_id or "").strip()
        shot_name = (shot_name or "").strip()
        variant = (variant or "").strip() or None

        registered = False
        if register:
            name = shot_name or core.shot_name_for(data, seq, shot_id)
            if name:
                data = core.add_shot(data, seq, shot_id, name)
                core.write_project(root, data)
                core.write_project_md(root, data)
                registered = True
            else:
                print("[COS] Shot: sin nombre de plano; no se registra en project.json.")

        shot = core.build_shot(root, data, seq, shot_id, variant, shot_name or None)
        core.ensure_shot_dirs(shot["path"])

        info = f"{shot['shot_id']}_{shot['shot_name']} @ {shot['path']}"
        if registered:
            info += " | registrado en project.json"
        return (shot, shot["path"], info)


class COSApprove:
    """Publish a task/version: copy from ``02_WORK/v###`` to ``03_PUBLISH``.

    Copies, never moves, never re-encodes, never renames. The published
    folder *is* the approved state.
    """

    DESCRIPTION = (
        "Publica una version: copia los archivos de la task (render + sidecar) "
        "de 02_WORK/v### a 03_PUBLISH sin renombrar. Copia, nunca mueve ni "
        "re-encodea. 'version' acepta 'current' o v###."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "task": (
                    list(core.VALID_TASKS),
                    {"default": "i2v", "tooltip": "Task a publicar. Para una task propia usa 'task_custom'."},
                ),
            },
            "optional": {
                "shot": ("COS_SHOT", {"tooltip": "Objeto del nodo COS Shot."}),
                "shot_path": ("STRING", {"default": "", "tooltip": "Alternativa a 'shot': ruta de la carpeta del plano."}),
                "task_custom": ("STRING", {"default": "", "tooltip": "Task libre; si no esta vacia, sustituye a 'task'."}),
                "version": ("STRING", {"default": "current", "tooltip": "'current' (la version en curso) o v###."}),
            },
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("published", "count", "info")
    FUNCTION = "run"
    CATEGORY = "COS"
    OUTPUT_NODE = False

    def run(
        self,
        task: str,
        shot=None,
        shot_path: str = "",
        task_custom: str = "",
        version: str = "current",
    ):
        if shot_path and shot_path.strip():
            shot_dir = Path(shot_path.strip())
        elif isinstance(shot, dict) and shot.get("path"):
            shot_dir = Path(shot["path"])
        else:
            raise ValueError(
                "COS Approve: conecta 'shot' (nodo COS Shot) o rellena 'shot_path'."
            )

        task = core.normalize_task(task_custom) if (task_custom or "").strip() else core.normalize_task(task)
        version = (version or "current").strip()

        if version == "current":
            version = core.current_version(shot_dir)
            if not version:
                raise ValueError(
                    f"COS Approve: no hay ninguna version en {shot_dir / '02_WORK'}."
                )
        else:
            core.parse_version(version)

        copied = core.approve_copy(shot_dir, task, version)
        names = [p.name for p in copied]
        if not copied:
            print(f"[COS] Approve: no habia archivos de {task}/{version} en {shot_dir}")

        published = "\n".join(names)
        info = f"{len(copied)} archivo(s) de {task}/{version} -> 03_PUBLISH"
        return (published, len(copied), info)
