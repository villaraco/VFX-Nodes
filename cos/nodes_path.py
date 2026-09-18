"""COS Shot / Path / Approve — the working nodes.

Thin ComfyUI node layer over :mod:`cos.core`. The root is ComfyUI's output
directory, so the ``filename_prefix`` values returned here write straight
into the COS tree (no staging copy needed).
"""

from __future__ import annotations

from pathlib import Path

from . import core
from .nodes_project import default_artist, output_root

try:
    import folder_paths  # noqa: F401  (present only inside ComfyUI)
except ImportError:  # standalone / tests
    pass


def _resolve_project(project, project_path: str = "") -> dict:
    """Project config from the wired object, or from a config path."""
    if project_path and project_path.strip():
        return core.load_project_config(project_path.strip())
    if isinstance(project, dict) and project:
        return project
    raise ValueError("COS: conecta 'project' (nodo COS Project) o rellena 'project_path'.")


def _load_config(root: str, project: str) -> dict:
    """Config of ``project`` (minimal fallback if it is missing)."""
    path = core.project_config_path(root, project)
    if path.exists():
        return core.load_project_config(path)
    return core.build_project_config(project, root=root)


def _shot_context(shot, shot_path: str, root: str) -> dict:
    """Resolve (project, entity, entity_type) from a COS_SHOT or a folder path."""
    if isinstance(shot, dict) and shot.get("entity"):
        return {
            "project": shot.get("project"),
            "entity": shot.get("entity"),
            "entity_type": shot.get("entity_type", "shot"),
        }
    if shot_path and shot_path.strip():
        path = Path(shot_path.strip())
        tokens = core.split_entity(path.name)
        return {
            "project": path.parent.parent.name or tokens["project"],
            "entity": path.name,
            "entity_type": path.parent.name,
        }
    raise ValueError("COS Approve: conecta 'shot' (nodo COS Shot) o rellena 'shot_path'.")


class COSShot:
    """Ensure an entity exists: ``work/``, ``version/`` and ``publish/``.

    Registers the entity in ``<PROJECT>.json`` when it was not there yet, so a
    new shot can be added without recreating the project.
    """

    DESCRIPTION = (
        "Asegura una entidad (<PROJECT>_<SEQ>_<SHOT>): crea work/version/publish "
        "y la registra en el config del proyecto si no estaba. Salida shot "
        "(COS_SHOT) para COS Path y COS Approve."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project": ("COS_PROJECT", {"tooltip": "Objeto del nodo COS Project."}),
                "entity": ("STRING", {"default": "TOTIE_003_0030", "tooltip": "Entidad <PROJECT>_<SEQ>_<SHOT>."}),
            },
            "optional": {
                "project_path": ("STRING", {"default": "", "tooltip": "Alternativa a 'project': ruta al <PROJECT>.json."}),
                "entity_type": (list(core.ENTITY_TYPES), {"default": "shot", "tooltip": "shot o asset."}),
                "register": ("BOOLEAN", {"default": True, "tooltip": "Registra la entidad en el config si no estaba."}),
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
        entity: str,
        project_path: str = "",
        entity_type: str = "shot",
        register: bool = True,
    ):
        root = output_root()
        config = _resolve_project(project, project_path)
        entity = (entity or "").strip()
        tokens = core.split_entity(entity)

        if entity_type not in core.ENTITY_TYPES:
            raise ValueError(f"entity_type invalido: {entity_type!r}")

        registered = False
        if register and entity not in (config.get("entities") or {}):
            config.setdefault("entities", {})[entity] = {"entity_type": entity_type}
            core.write_project_config(root, config)
            core.write_project_md(root, config)
            registered = True

        path = core.ensure_entity(root, config["name"], entity_type, entity)
        shot = {
            "schema": core.SCHEMA,
            "project": config.get("name") or tokens["project"],
            "entity": entity,
            "entity_type": entity_type,
            "sequence": tokens["sequence"],
            "shot": tokens["shot"],
            "path": str(path),
        }
        info = f"{entity} ({entity_type}) @ {path}"
        if registered:
            info += " | registrado en el config"
        return (shot, str(path), info)


class COSPath:
    """Resolve the version folder, the pack prefixes and the sidecars.

    Writes the workfile (workflow JSON) into ``work/<task>/<artist>/`` and the
    version sidecar + ``_source`` copy into ``version/<task>/<version>/``.
    """

    DESCRIPTION = (
        "Resuelve la version y devuelve los prefijos de guardado para los packs "
        "(_png/_exr/_mov). Escribe el sidecar de version (esquema del pipeline + "
        "bloque comfy con seed, modelo, workflow y prompt) y guarda el workflow "
        "en work/<task>/<artist>/. Nombres: <ENTIDAD>_<task>[_<desc>]_v####."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project": ("COS_PROJECT", {"tooltip": "Objeto del nodo COS Project."}),
                "entity": ("STRING", {"default": "TOTIE_003_0030", "tooltip": "Entidad <PROJECT>_<SEQ>_<SHOT>."}),
                "task": (
                    list(core.VALID_TASKS),
                    {"default": "i2v", "tooltip": "Task propia de COS. Para una libre usa 'task_custom'."},
                ),
                "version_mode": (
                    ["current", "new"],
                    {"default": "current", "tooltip": "current: reusa la ultima version. new: abre la siguiente."},
                ),
            },
            "optional": {
                "shot": ("COS_SHOT", {"tooltip": "Objeto del nodo COS Shot: fija entidad y tipo."}),
                "project_path": ("STRING", {"default": "", "tooltip": "Alternativa a 'project'."}),
                "description": ("STRING", {"default": "", "tooltip": "Descriptivo opcional (ej. callao, granvia). Va al nombre y al sidecar."}),
                "task_custom": ("STRING", {"default": "", "tooltip": "Task libre; si no esta vacia, sustituye a 'task'."}),
                "dependencies": ("STRING", {"default": "", "multiline": True, "tooltip": "Versiones de las que come esta (una por linea). Va al sidecar."}),
                "model": ("STRING", {"default": "", "tooltip": "Modelo usado (bloque comfy del sidecar)."}),
                "seed": ("INT", {"default": 0, "forceInput": True, "tooltip": "Seed de cualquier nodo INT (bloque comfy)."}),
                "artist": ("STRING", {"default": "", "tooltip": "Artista (vacio = usuario de Windows)."}),
                "save_workfile": ("BOOLEAN", {"default": True, "tooltip": "Guarda el workflow en work/<task>/<artist>/."}),
                "write_meta": ("BOOLEAN", {"default": True, "tooltip": "Escribe el sidecar de version y la copia en _source/."}),
                "ensure_dirs": ("BOOLEAN", {"default": True, "tooltip": "Crea las carpetas necesarias."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("png_prefix", "exr_prefix", "video_prefix", "version", "out_dir", "info")
    FUNCTION = "run"
    CATEGORY = "COS"
    OUTPUT_NODE = False

    def run(
        self,
        project,
        entity: str,
        task: str,
        version_mode: str,
        shot=None,
        project_path: str = "",
        description: str = "",
        task_custom: str = "",
        dependencies: str = "",
        model: str = "",
        seed: int = 0,
        artist: str = "",
        save_workfile: bool = True,
        write_meta: bool = True,
        ensure_dirs: bool = True,
        prompt=None,
        extra_pnginfo=None,
    ):
        root = output_root()
        config = _resolve_project(project, project_path)

        entity_type = "shot"
        if isinstance(shot, dict) and shot.get("entity"):
            entity = shot["entity"]
            entity_type = shot.get("entity_type", "shot")
        entity = (entity or "").strip()

        task = core.normalize_task(task_custom) if (task_custom or "").strip() else core.normalize_task(task)
        description = core.normalize_description(description)
        artist = (artist or "").strip() or default_artist()

        project_name = config.get("name") or core.split_entity(entity)["project"]
        vtask = core.version_task_dir(root, project_name, entity_type, entity, task)
        version = core.resolve_version(vtask, version_mode)

        out = core.build_output(root, config, entity, task, version, description, entity_type)
        version_name = out["version_name"]
        vpath = out["version_path"]

        if ensure_dirs:
            core.ensure_entity(root, project_name, entity_type, entity)
            vpath.mkdir(parents=True, exist_ok=True)

        workflow = extra_pnginfo.get("workflow") if isinstance(extra_pnginfo, dict) else None

        workfile = None
        if save_workfile and workflow:
            wdir = core.work_dir(root, project_name, entity_type, entity, task, artist)
            wdir.mkdir(parents=True, exist_ok=True)
            workfile = core.write_sidecar(wdir / f"{version_name}.json", workflow)

        meta_name = ""
        if write_meta:
            fmt = core.config_format(config)
            comfy = {
                "model": model,
                "seed": int(seed),
                "resolution": [fmt.get("width"), fmt.get("height")],
                "workflow": workflow,
                "prompt": prompt,
            }
            meta = core.build_version_meta(
                config,
                entity,
                task,
                version,
                entity_type=entity_type,
                description=description,
                user=artist,
                dependencies=core.parse_dependencies(dependencies),
                comfy=comfy,
            )
            meta_name = core.write_version_meta(vpath, version_name, meta).name
            core.write_source_copy(vpath, version_name, workflow)

        info = f"{version_name} @ {vpath}"
        if workfile:
            info += f" | workfile {workfile.name}"
        if meta_name:
            info += f" | {meta_name}"
        return (
            out["prefixes"]["png"],
            out["prefixes"]["exr"],
            out["prefixes"]["mov"],
            version,
            str(vpath),
            info,
        )


class COSApprove:
    """Publish a version: output sidecars + copy to ``publish/<task>/``.

    Writes ``_<pack>/_<pack>.json`` for the packs that exist and copies the
    whole version folder (copy, never move, never rename). The delivery to the
    studio publish path / ShotGrid is a later phase.
    """

    DESCRIPTION = (
        "Publica una version: escribe los sidecars de salida de los packs que "
        "existan (_png/_exr/_mov) y copia la version a publish/<task>/ sin "
        "renombrar. Copia, nunca mueve ni re-encodea. 'version' acepta 'current'."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "task": (
                    list(core.VALID_TASKS),
                    {"default": "i2v", "tooltip": "Task a publicar. Para una libre usa 'task_custom'."},
                ),
            },
            "optional": {
                "shot": ("COS_SHOT", {"tooltip": "Objeto del nodo COS Shot."}),
                "shot_path": ("STRING", {"default": "", "tooltip": "Alternativa a 'shot': carpeta de la entidad."}),
                "task_custom": ("STRING", {"default": "", "tooltip": "Task libre; si no esta vacia, sustituye a 'task'."}),
                "version": ("STRING", {"default": "current", "tooltip": "'current' (la ultima) o v####."}),
                "description": ("STRING", {"default": "", "tooltip": "Descriptivo usado al crear la version (ej. callao)."}),
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
        description: str = "",
    ):
        root = output_root()
        context = _shot_context(shot, shot_path, root)
        project_name = context["project"]
        entity = context["entity"]
        entity_type = context["entity_type"]

        task = core.normalize_task(task_custom) if (task_custom or "").strip() else core.normalize_task(task)
        description = core.normalize_description(description)

        vtask = core.version_task_dir(root, project_name, entity_type, entity, task)
        version = (version or "current").strip()
        if version == "current":
            version = core.current_version(vtask)
            if not version:
                raise ValueError(f"COS Approve: no hay ninguna version en {vtask}.")
        else:
            core.parse_version(version)

        version_name = core.build_version_name(entity, task, version, description)
        vpath = core.version_dir(root, project_name, entity_type, entity, task, version_name)
        if not vpath.is_dir():
            raise FileNotFoundError(f"COS Approve: no existe {vpath}")

        config = _load_config(root, project_name)
        sidecars = core.write_output_sidecars(vpath, version_name, config, source=f"{version_name}.json")

        dest = core.publish_task_dir(root, project_name, entity_type, entity, task) / version_name
        copied = core.publish_version(vpath, dest)

        published = "\n".join(p.name for p in copied)
        info = (
            f"{version_name}: {len(copied)} item(s) -> {dest} | "
            f"{len(sidecars)} sidecar(s) de salida"
        )
        return (published, len(copied), info)
