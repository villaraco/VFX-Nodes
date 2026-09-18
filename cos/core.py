"""COS core — pure logic for the Comfy Output Standard (v2).

COS is an **independent** system with its own work root, but its naming
grammar and sidecar schema are **compatible** with the studio pipeline
(KrakenPipeline), so a later publish step can deliver to compo the same way
the 3D department does. This is a clean-room implementation: no KrakenPipeline
code is copied or imported.

Grammar (token-compatible):

    entity         {project}_{sequence}_{shot}            TOTIE_003_0030
    group          {entity}_{task}[_{description}]        TOTIE_003_0030_i2v_callao
    version name   {group}_v{####}                        TOTIE_003_0030_i2v_callao_v0001
    file           {version_name}_{frame}_.{ext}          ..._v0001_00001_.exr

``version`` is zero-padded to 4 digits (``_v0001``), like Kraken. The frame
token is written by the ComfyUI save node itself (``_00001_``).

Tree (mirrors the studio layout):

    <ROOT>/<PROJECT>/<shot|asset>/<ENTITY>/
        work/<task>/<artist>/<version_name>.json          working files (workflow)
        version/<task>/<version_name>/
            <version_name>.json                            version sidecar
            _source/<version_name>.json                    workfile copy
            _png/  _exr/  _mov/                            output packs + _<pack>.json
        publish/<task>/                                    published versions

Only the standard library — fully testable from ``validate_cos.py``.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from math import gcd
from pathlib import Path

# ============================================================================
# Constants
# ============================================================================

SCHEMA = 2
VERSION_ZFILL = 4
VERSION_SEP = "_"      # version strings already carry the "v" (v0001)
TOKEN_SEP = "_"

ENTITY_TYPES = ("shot", "asset")
VALID_TASKS = (
    "t2i", "i2i", "t2v", "i2v", "v2v",
    "edit", "inpaint", "faceswap", "upscale", "mask",
)

#: Output packs: role -> extension + technical defaults for the sidecar.
PACKS = {
    "png": {"ext": "png", "colorspace": "sRGB", "bit_depth": 8,
            "channels": ["rgb.r", "rgb.g", "rgb.b"]},
    "exr": {"ext": "exr", "colorspace": "ACES - ACEScg", "bit_depth": 32,
            "channels": ["rgba.red", "rgba.green", "rgba.blue", "rgba.alpha"]},
    "mov": {"ext": "mp4", "colorspace": "Output - sRGB", "codec": "hevc",
            "pix_fmt": "yuv420p", "channels": ["rgb.r", "rgb.g", "rgb.b"]},
}

VERSION_RE = re.compile(r"^v(\d{3,})$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9]+$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ILLEGAL_CHARS = set('<>:"|?*\\/')
_PROJECT_MD = "_PROJECT.md"


# ============================================================================
# Validation
# ============================================================================

def validate_token(value: str, field: str = "token") -> str:
    """Validate a path/name token: no traversal, no illegal characters."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"Invalid {field}: empty")
    if ".." in value:
        raise ValueError(f"Invalid {field} {value!r}: '..' not allowed")
    if any(ch in _ILLEGAL_CHARS for ch in value):
        raise ValueError(f"Invalid {field} {value!r}: illegal character")
    if not TOKEN_RE.match(value):
        raise ValueError(f"Invalid {field} {value!r}: only letters, digits, '_', '-' and '.'")
    return value


def validate_project(project: str) -> str:
    """Project code, e.g. ``TOTIE``."""
    if not isinstance(project, str) or not PROJECT_RE.match(project):
        raise ValueError(f"Invalid project {project!r}: letters and digits only")
    return project


def validate_artist(value: str) -> str:
    """Artist name — spaces allowed (studio style: ``Ivan Cadenas``)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Invalid artist: empty")
    value = value.strip()
    if ".." in value or any(ch in _ILLEGAL_CHARS for ch in value):
        raise ValueError(f"Invalid artist {value!r}")
    if value.endswith("."):
        raise ValueError(f"Invalid artist {value!r}")
    return value


def normalize_task(task: str) -> str:
    """Lowercase/sanitize a task name. Tasks are extensible (free entry)."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Invalid task: empty")
    normalized = re.sub(r"[^\w]+", "_", task.strip().lower()).strip("_")
    if not normalized:
        raise ValueError(f"Invalid task {task!r}")
    return validate_token(normalized, "task")


def normalize_description(description: str | None) -> str | None:
    """Optional description token (our 'variant': callao, granvia, gen...)."""
    if description is None:
        return None
    description = str(description).strip()
    if not description:
        return None
    return validate_token(re.sub(r"[^\w]+", "_", description).strip("_"), "description")


def is_within(root: Path | str, path: Path | str) -> bool:
    """True if ``path`` resolves inside ``root`` (both resolved first)."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


# ============================================================================
# Grammar
# ============================================================================

def format_version(n: int) -> str:
    """``1`` -> ``v0001``."""
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"Invalid version number: {n!r}")
    return f"v{str(n).zfill(VERSION_ZFILL)}"


def parse_version(version: str) -> int:
    """``v0001`` -> ``1``."""
    if not isinstance(version, str):
        raise ValueError(f"Invalid version {version!r}")
    m = VERSION_RE.match(version)
    if not m:
        raise ValueError(f"Invalid version {version!r}: expected v####")
    return int(m.group(1))


def build_entity(project: str, sequence: str, shot: str) -> str:
    """``TOTIE`` + ``003`` + ``0030`` -> ``TOTIE_003_0030``."""
    parts = [
        validate_project(project),
        validate_token(sequence, "sequence"),
        validate_token(shot, "shot"),
    ]
    return TOKEN_SEP.join(parts)


def split_entity(entity: str) -> dict:
    """``TOTIE_003_0030`` -> ``{project, sequence, shot}`` (extra parts join the shot)."""
    entity = validate_token(entity, "entity")
    parts = entity.split(TOKEN_SEP)
    if len(parts) < 3:
        raise ValueError(f"Invalid entity {entity!r}: expected <project>_<sequence>_<shot>")
    return {
        "project": parts[0],
        "sequence": parts[1],
        "shot": TOKEN_SEP.join(parts[2:]),
    }


def build_group(entity: str, task: str, description: str | None = None) -> str:
    """``{entity}_{task}[_{description}]``."""
    parts = [validate_token(entity, "entity"), normalize_task(task)]
    description = normalize_description(description)
    if description:
        parts.append(description)
    return TOKEN_SEP.join(parts)


def build_version_name(
    entity: str,
    task: str,
    version: str,
    description: str | None = None,
) -> str:
    """``{entity}_{task}[_{description}]_v####``."""
    validate_token(version, "version")
    if not VERSION_RE.match(version):
        raise ValueError(f"Invalid version {version!r}: expected v####")
    return f"{build_group(entity, task, description)}{VERSION_SEP}{version}"


# ============================================================================
# Paths (mirror the studio layout)
# ============================================================================

def project_dir(root: Path | str, project: str) -> Path:
    return Path(root) / validate_project(project)


def project_config_path(root: Path | str, project: str) -> Path:
    return project_dir(root, project) / f"{validate_project(project)}.json"


def project_md_path(root: Path | str, project: str) -> Path:
    return project_dir(root, project) / _PROJECT_MD


def entity_dir(
    root: Path | str,
    project: str,
    entity_type: str,
    entity: str,
) -> Path:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"Invalid entity_type {entity_type!r}: use {ENTITY_TYPES}")
    return project_dir(root, project) / entity_type / validate_token(entity, "entity")


def work_dir(
    root: Path | str,
    project: str,
    entity_type: str,
    entity: str,
    task: str,
    artist: str | None = None,
) -> Path:
    """``<entity>/work/<task>[/<artist>]/`` — working files (workflow JSON)."""
    path = entity_dir(root, project, entity_type, entity) / "work" / normalize_task(task)
    if artist:
        path = path / validate_artist(artist)
    return path


def version_task_dir(
    root: Path | str,
    project: str,
    entity_type: str,
    entity: str,
    task: str,
) -> Path:
    """``<entity>/version/<task>/`` — holds one folder per version."""
    return entity_dir(root, project, entity_type, entity) / "version" / normalize_task(task)


def version_dir(
    root: Path | str,
    project: str,
    entity_type: str,
    entity: str,
    task: str,
    version_name: str,
) -> Path:
    return version_task_dir(root, project, entity_type, entity, task) / validate_token(
        version_name, "version_name"
    )


def publish_task_dir(
    root: Path | str,
    project: str,
    entity_type: str,
    entity: str,
    task: str,
) -> Path:
    return entity_dir(root, project, entity_type, entity) / "publish" / normalize_task(task)


def pack_dir(version_path: Path | str, pack: str) -> Path:
    """``<version>/_png`` etc."""
    if pack not in PACKS:
        raise ValueError(f"Unknown pack {pack!r}: use {tuple(PACKS)}")
    return Path(version_path) / f"_{pack}"


def source_dir(version_path: Path | str) -> Path:
    return Path(version_path) / "_source"


# ============================================================================
# Project config (Kraken-compatible schema)
# ============================================================================

def build_project_config(
    project: str,
    fps: int = 24,
    width: int = 1920,
    height: int = 1080,
    par: float = 1.0,
    format_name: str = "",
    entities: dict | None = None,
    root: Path | str = "",
    ocio: str = "",
    handles: tuple[int, int] = (8, 8),
) -> dict:
    """Assemble ``<PROJECT>.json`` with the studio's project schema.

    ``entities`` maps entity names to ``{"entity_type": "shot"|"asset"}``.
    """
    project = validate_project(project)
    format_name = format_name or project
    ratio = _ratio(width, height)
    directory = ""
    if root:
        directory = (Path(root) / project).as_posix()
    return {
        "name": project,
        "fps": int(fps),
        "OCIO": {"windows": ocio, "darwin": ocio, "linux": ocio},
        "formats": [{"name": format_name, "width": int(width), "height": int(height), "par": float(par)}],
        "masking_ratio": {"name": format_name, "width": ratio[0], "height": ratio[1]},
        "default_handles_in": int(handles[0]),
        "default_handles_out": int(handles[1]),
        "directory": {"windows": directory, "darwin": directory, "linux": directory},
        "entities": entities or {},
    }


def write_project_config(root: Path | str, config: dict) -> Path:
    path = project_config_path(root, config["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    config["updated"] = _today()
    path.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding="utf-8")
    return path


def load_project_config(path: Path | str) -> dict:
    """Load ``<PROJECT>.json`` (accepts the file or the project dir)."""
    p = Path(path)
    if p.is_dir():
        candidates = sorted(p.glob("*.json"))
        if not candidates:
            raise FileNotFoundError(f"No project config in {p}")
        p = candidates[0]
    return json.loads(p.read_text(encoding="utf-8"))


def list_projects(root: Path | str) -> list[dict]:
    """Every readable ``<PROJECT>/<PROJECT>.json`` under ``root``."""
    out: list[dict] = []
    root_path = Path(root)
    if not root_path.exists():
        return out
    for child in sorted(root_path.iterdir()):
        if not child.is_dir():
            continue
        for cfg in sorted(child.glob("*.json")):
            try:
                out.append(json.loads(cfg.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
            break
    return out


def list_entities(root: Path | str) -> dict:
    """Every entity across all project configs.

    ``{entity: {"project": <name>, "entity_type": "shot"|"asset"}}`` — feeds the
    dynamic dropdowns of the nodes.
    """
    out: dict = {}
    for config in list_projects(root):
        project = config.get("name") or ""
        for entity, edef in (config.get("entities") or {}).items():
            try:
                split_entity(entity)
            except ValueError:
                continue
            out[entity] = {
                "project": project,
                "entity_type": (edef or {}).get("entity_type", "shot"),
            }
    return out


def config_format(config: dict) -> dict:
    """First format entry of a project config (width/height/par)."""
    formats = config.get("formats") or []
    if not formats:
        return {"width": 1920, "height": 1080, "par": 1.0}
    return formats[0]


def parse_entities(spec: str) -> dict:
    """``"TOTIE_003_0030,TOTIE_DZN_0010"`` -> ``{entity: {"entity_type": "shot"}}``.

    An entry may carry a type with ``:`` (``TOTIE_CHR_Totie:asset``).
    """
    out: dict = {}
    for item in (spec or "").replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        name, _, kind = item.partition(":")
        name = name.strip()
        kind = (kind.strip() or "shot").lower()
        if kind not in ENTITY_TYPES:
            raise ValueError(f"Invalid entity_type {kind!r} for {name!r}")
        split_entity(name)  # validates the grammar
        out[name] = {"entity_type": kind}
    return out


def render_project_md(config: dict) -> str:
    """Human sheet, regenerated from ``<PROJECT>.json``."""
    fmt = config_format(config)
    ratio = config.get("masking_ratio") or {}
    lines = [
        "---",
        f"project: {config.get('name', '')}",
        f"fps: {config.get('fps', '')}",
        "---",
        "",
        f"# {config.get('name', '')}",
        "",
        "> Generado por COS desde el config del proyecto. Las notas manuales van aparte.",
        "",
        "## Formato",
        "",
        f"- Master: {fmt.get('width')}x{fmt.get('height')} par {fmt.get('par', 1)}",
        f"- Masking: {ratio.get('width')}:{ratio.get('height')}",
        f"- Handles: {config.get('default_handles_in')}/{config.get('default_handles_out')}",
        "",
        "## Entidades",
        "",
        "| Entidad | Tipo | Secuencia | Plano |",
        "|---|---|---|---|",
    ]
    for entity, edef in (config.get("entities") or {}).items():
        tokens = split_entity(entity)
        lines.append(
            f"| {entity} | {edef.get('entity_type', 'shot')} | {tokens['sequence']} | {tokens['shot']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_project_md(root: Path | str, config: dict) -> Path:
    path = project_md_path(root, config["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_project_md(config), encoding="utf-8")
    return path


# ============================================================================
# Skeleton
# ============================================================================

def ensure_project(root: Path | str, config: dict) -> list[Path]:
    """Create ``<ROOT>/<PROJECT>/`` + the tree of every entity (idempotent)."""
    project = config["name"]
    pdir = project_dir(root, project)
    pdir.mkdir(parents=True, exist_ok=True)
    created = [pdir]

    for entity, edef in (config.get("entities") or {}).items():
        entity_type = edef.get("entity_type", "shot")
        edir = entity_dir(root, project, entity_type, entity)
        (edir / "work").mkdir(parents=True, exist_ok=True)
        (edir / "version").mkdir(parents=True, exist_ok=True)
        (edir / "publish").mkdir(parents=True, exist_ok=True)
        created.append(edir)
    return created


def ensure_entity(
    root: Path | str,
    project: str,
    entity_type: str,
    entity: str,
) -> Path:
    """Create the entity folders (work/version/publish) and return its dir."""
    edir = entity_dir(root, project, entity_type, entity)
    for sub in ("work", "version", "publish"):
        (edir / sub).mkdir(parents=True, exist_ok=True)
    return edir


# ============================================================================
# Versions
# ============================================================================

def existing_versions(version_task_path: Path | str) -> list[int]:
    """Version numbers found in ``version/<task>/`` (parsed from folder names)."""
    path = Path(version_task_path)
    if not path.exists():
        return []
    out: list[int] = []
    for child in path.iterdir():
        if not child.is_dir():
            continue
        match = re.search(r"_v(\d{3,})$", child.name)
        if match:
            out.append(int(match.group(1)))
    return sorted(out)


def current_version(version_task_path: Path | str) -> str | None:
    """Highest existing version, or ``None`` (never creates anything)."""
    existing = existing_versions(version_task_path)
    return format_version(max(existing)) if existing else None


def resolve_version(version_task_path: Path | str, mode: str = "current") -> str:
    """``current`` -> highest existing (or ``v0001``); ``new`` -> one past it."""
    if mode not in ("current", "new"):
        raise ValueError(f"Invalid version_mode {mode!r}: use 'current' or 'new'")
    existing = existing_versions(version_task_path)
    highest = max(existing) if existing else 0
    n = highest + 1 if mode == "new" else (highest or 1)
    return format_version(n)


# ============================================================================
# Sidecars
# ============================================================================

def build_version_meta(
    config: dict,
    entity: str,
    task: str,
    version: str,
    *,
    entity_type: str = "shot",
    description: str | None = None,
    user: str = "",
    dependencies: list[str] | None = None,
    comfy: dict | None = None,
    date: str | None = None,
) -> dict:
    """Version sidecar: the studio's keys, plus an additive ``comfy`` block."""
    tokens = split_entity(entity)
    task = normalize_task(task)
    description = normalize_description(description)
    version_num = parse_version(version)
    return {
        "date": date or datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "dependencies": list(dependencies or []),
        "description": description or "",
        "entity": entity,
        "entity_type": entity_type,
        "episode": "",
        "group": build_group(entity, task, description),
        "name": build_version_name(entity, task, version, description),
        "project": config.get("name") or tokens["project"],
        "scene": "",
        "sequence": tokens["sequence"],
        "task": task,
        "user": user,
        "version": version_num,
        "comfy": comfy or {},
    }


def build_output_meta(
    pack: str,
    version_name: str,
    config: dict,
    *,
    single: bool = False,
    source: str = "",
) -> dict:
    """Output sidecar (``_<pack>/_<pack>.json``) with real attributes."""
    if pack not in PACKS:
        raise ValueError(f"Unknown pack {pack!r}: use {tuple(PACKS)}")
    spec = PACKS[pack]
    fmt = config_format(config)
    attributes = {
        "ext": spec["ext"],
        "width": int(fmt.get("width", 1920)),
        "height": int(fmt.get("height", 1080)),
        "pixel_aspect_ratio": float(fmt.get("par", 1.0)),
        "colorspace": spec["colorspace"],
        "software": "comfyui",
    }
    for key in ("bit_depth", "codec", "pix_fmt", "channels"):
        if key in spec:
            attributes[key] = spec[key]
    return {
        "attributes": attributes,
        "name": pack,
        "single": single,
        "source": source or f"{version_name}.json",
    }


def write_sidecar(path: Path | str, data: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    return path


def version_meta_path(version_path: Path | str, version_name: str) -> Path:
    return Path(version_path) / f"{version_name}.json"


def output_meta_path(version_path: Path | str, pack: str) -> Path:
    return pack_dir(version_path, pack) / f"_{pack}.json"


def write_version_meta(version_path: Path | str, version_name: str, meta: dict) -> Path:
    return write_sidecar(version_meta_path(version_path, version_name), meta)


def write_output_meta(version_path: Path | str, pack: str, meta: dict) -> Path:
    return write_sidecar(output_meta_path(version_path, pack), meta)


def write_source_copy(version_path: Path | str, version_name: str, workflow: dict | None) -> Path | None:
    """Copy the workfile (ComfyUI workflow JSON) into ``_source/``."""
    if not workflow:
        return None
    path = source_dir(version_path) / f"{version_name}.json"
    return write_sidecar(path, workflow)


# ============================================================================
# Publish
# ============================================================================

def publish_version(version_path: Path | str, dest: Path | str) -> list[Path]:
    """Copy a whole version folder to ``dest`` (copy, never move, never rename)."""
    src = Path(version_path)
    if not src.exists():
        raise FileNotFoundError(f"Version folder not found: {src}")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for item in sorted(src.iterdir()):
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
            copied.append(target)
        else:
            shutil.copy2(item, target)
            copied.append(target)
    return copied


def write_output_sidecars(
    version_path: Path | str,
    version_name: str,
    config: dict,
    source: str = "",
) -> list[Path]:
    """Write ``_<pack>/_<pack>.json`` for every pack folder present."""
    written: list[Path] = []
    version_path = Path(version_path)
    for pack in PACKS:
        directory = pack_dir(version_path, pack)
        if not directory.is_dir():
            continue
        meta = build_output_meta(pack, version_name, config, source=source)
        written.append(write_output_meta(version_path, pack, meta))
    return written


# ============================================================================
# Output resolution (COS Path)
# ============================================================================

def build_output(
    root: Path | str,
    config: dict,
    entity: str,
    task: str,
    version: str,
    description: str | None = None,
    entity_type: str = "shot",
) -> dict:
    """Resolve the version folder + the three pack prefixes for ComfyUI.

    ``prefix`` values are relative (forward slashes) and ready for a ComfyUI
    ``filename_prefix``; the save node appends ``_00001_.<ext>``.
    """
    project = config.get("name") or split_entity(entity)["project"]
    version_name = build_version_name(entity, task, version, description)
    vpath = version_dir(root, project, entity_type, entity, task, version_name)
    root_path = Path(root).resolve()
    if not is_within(root_path, vpath):
        raise ValueError(f"Version folder escapes the COS root: {vpath}")
    rel = vpath.relative_to(root_path).as_posix()
    prefixes = {
        pack: f"{rel}/_{pack}/{version_name}"
        for pack in PACKS
    }
    return {
        "version_name": version_name,
        "group": build_group(entity, task, description),
        "version_path": vpath,
        "prefixes": prefixes,
    }


def parse_dependencies(spec: str) -> list[str]:
    """``"A_v0001, B_v0002"`` -> ``["A_v0001", "B_v0002"]`` (also newlines/;)."""
    out: list[str] = []
    for item in re.split(r"[,\n;]+", spec or ""):
        item = item.strip()
        if item:
            out.append(item)
    return out


# ============================================================================
# Internal helpers
# ============================================================================

def _ratio(width: int, height: int) -> tuple[int, int]:
    if not width or not height:
        return (16, 9)
    divisor = gcd(int(width), int(height))
    return (int(width) // divisor, int(height) // divisor)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")
