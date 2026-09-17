"""COS core — pure logic for the Comfy Output Standard.

No torch, no ComfyUI, no network. Only the standard library, so it is
fully testable from ``validate_cos.py`` and importable from the node
layer without side effects.

Responsibilities:
  * naming   -- build the short ``<show>_<seq>[_<variant>]_<shot>_<task>_v###`` base
  * skeleton -- create the COS directory tree
  * state    -- resolve versions (``current`` / ``new``) in ``_state.json``
  * sidecar  -- build and write ``<base>_meta.json``
  * publish  -- copy (never move) approved files to ``03_PUBLISH``
  * safety   -- reject path traversal / illegal Windows characters

See ``docs/Plan - COS Nodes.md`` for the full specification.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

# ============================================================================
# Constants
# ============================================================================

SCHEMA = 1

VALID_TASKS = (
    "t2i", "i2i", "t2v", "i2v", "v2v",
    "edit", "inpaint", "faceswap", "upscale", "mask",
)

ROOT_DIRS = ("PROJECTS", "RND", "ASSETS", "_INBOX", "_TRASH")
SHOT_SUBDIRS = ("01_INPUT", "02_WORK", "03_PUBLISH")

SHOW_RE = re.compile(r"^[a-z]{3}$")
VERSION_RE = re.compile(r"^v(\d{3,})$")
COMPONENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ILLEGAL_CHARS = set('<>:"|?*\\/')


# ============================================================================
# Validation helpers
# ============================================================================

def validate_show(show: str) -> str:
    """Validate a 3-letter lowercase show code (e.g. ``tot``)."""
    if not isinstance(show, str) or not SHOW_RE.match(show):
        raise ValueError(f"Invalid show code {show!r}: expected 3 lowercase letters")
    return show


def validate_component(value: str, field: str = "component") -> str:
    """Validate a path/name component: no traversal, no illegal chars."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"Invalid {field}: empty")
    if ".." in value:
        raise ValueError(f"Invalid {field} {value!r}: '..' not allowed")
    if any(ch in _ILLEGAL_CHARS for ch in value):
        raise ValueError(f"Invalid {field} {value!r}: illegal character")
    if not COMPONENT_RE.match(value):
        raise ValueError(
            f"Invalid {field} {value!r}: only letters, digits, '_' and '-' allowed"
        )
    return value


def normalize_task(task: str) -> str:
    """Lowercase/sanitize a task name. Tasks are extensible (free entry)."""
    if not isinstance(task, str) or not task.strip():
        raise ValueError("Invalid task: empty")
    normalized = re.sub(r"[^\w]+", "_", task.strip().lower(), flags=re.UNICODE).strip("_")
    if not normalized:
        raise ValueError(f"Invalid task {task!r}")
    return validate_component(normalized, "task")


def is_within(root: Path | str, path: Path | str) -> bool:
    """True if ``path`` resolves inside ``root`` (both resolved first)."""
    root_r = Path(root).resolve()
    try:
        Path(path).resolve().relative_to(root_r)
        return True
    except ValueError:
        return False


# ============================================================================
# Naming
# ============================================================================

def make_slug(show: str, project: str) -> str:
    """Return the project folder slug, e.g. ``TOT_Totie``."""
    show = validate_show(show)
    if not isinstance(project, str) or not project.strip():
        raise ValueError("Invalid project name: empty")
    cleaned = re.sub(r"[^\w]+", "_", project.strip(), flags=re.UNICODE).strip("_")
    if not cleaned:
        raise ValueError(f"Invalid project name {project!r}")
    return f"{show.upper()}_{cleaned}"


def format_version(n: int) -> str:
    """``1`` -> ``v001``."""
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"Invalid version number: {n!r}")
    return f"v{n:03d}"


def parse_version(version: str) -> int:
    """``v001`` -> ``1``."""
    if not isinstance(version, str):
        raise ValueError(f"Invalid version {version!r}")
    m = VERSION_RE.match(version)
    if not m:
        raise ValueError(f"Invalid version {version!r}: expected v###")
    return int(m.group(1))


def build_base(
    show: str,
    seq: str,
    shot: str,
    task: str,
    version: str,
    variant: str | None = None,
) -> str:
    """Build the short filename base (without the ``_#####_`` counter).

    ``<show>_<seq>[_<variant>]_<shot>_<task>_v###``
    """
    validate_show(show)
    parts = [show, validate_component(seq, "seq")]
    if variant:
        parts.append(validate_component(variant, "variant"))
    parts.append(validate_component(shot, "shot"))
    parts.append(normalize_task(task))
    parts.append(validate_component(version, "version"))
    if not VERSION_RE.match(version):
        raise ValueError(f"Invalid version {version!r}: expected v###")
    return "_".join(parts)


def shot_dir_name(shot_id: str, shot_name: str) -> str:
    """Folder name for a shot, e.g. ``0010_boca``."""
    return f"{validate_component(shot_id, 'shot_id')}_{validate_component(shot_name, 'shot_name')}"


# ============================================================================
# Project paths + project.json
# ============================================================================

def project_dir(root: Path | str, slug: str) -> Path:
    return Path(root) / "PROJECTS" / slug


def project_json_path(root: Path | str, slug: str) -> Path:
    return project_dir(root, slug) / "project.json"


def write_project(root: Path | str, project: dict) -> Path:
    """Write ``project.json`` for the given project dict."""
    slug = project["slug"]
    path = project_json_path(root, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(project)
    payload["updated"] = _today()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_project(path: Path | str) -> dict:
    """Load a ``project.json`` (accepts the file path or a project dir)."""
    p = Path(path)
    if p.is_dir():
        p = p / "project.json"
    return json.loads(p.read_text(encoding="utf-8"))


def list_projects(root: Path | str) -> list[dict]:
    """Return every readable ``project.json`` under ``PROJECTS/``."""
    projects_dir = Path(root) / "PROJECTS"
    out: list[dict] = []
    if not projects_dir.exists():
        return out
    for child in sorted(projects_dir.iterdir()):
        pj = child / "project.json"
        if child.is_dir() and pj.exists():
            try:
                out.append(load_project(pj))
            except (OSError, json.JSONDecodeError):
                continue
    return out


# ============================================================================
# Skeleton
# ============================================================================

def ensure_root(root: Path | str) -> Path:
    """Create the COS root skeleton (idempotent)."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for d in ROOT_DIRS:
        (root / d).mkdir(exist_ok=True)
    return root


def _ensure_notes(shot_path: Path) -> None:
    notes = shot_path / "_NOTES.md"
    if not notes.exists():
        notes.write_text(
            f"# {shot_path.name}\n\nContexto, seeds y decisiones del plano.\n",
            encoding="utf-8",
        )


def build_skeleton(root: Path | str, project: dict) -> list[Path]:
    """Create the full COS tree for ``project`` and return the dirs created.

    Structure: ``PROJECTS/<slug>/<seq>[/<variant>]/<shot>/{01_INPUT,02_WORK,03_PUBLISH}``
    """
    ensure_root(root)
    created: list[Path] = []

    pdir = project_dir(root, project["slug"])
    pdir.mkdir(parents=True, exist_ok=True)
    created.append(pdir)

    for special in ("_WORKFLOWS",):
        d = pdir / special
        d.mkdir(exist_ok=True)
        created.append(d)

    for seq, sdef in project.get("sequences", {}).items():
        validate_component(seq, "seq")
        seq_dir = pdir / seq
        seq_dir.mkdir(parents=True, exist_ok=True)
        created.append(seq_dir)

        variants = sdef.get("variants") or {}
        shots = sdef.get("shots") or {}

        if variants:
            for variant in variants:
                validate_component(variant, "variant")
                var_dir = seq_dir / variant
                var_dir.mkdir(parents=True, exist_ok=True)
                created.append(var_dir)
                for shot_id, shot_name in shots.items():
                    created.extend(_make_shot(var_dir, shot_id, shot_name))
        else:
            for shot_id, shot_name in shots.items():
                created.extend(_make_shot(seq_dir, shot_id, shot_name))

    return created


def _make_shot(parent: Path, shot_id: str, shot_name: str) -> list[Path]:
    shot_path = parent / shot_dir_name(shot_id, shot_name)
    shot_path.mkdir(parents=True, exist_ok=True)
    out = [shot_path]
    for sub in SHOT_SUBDIRS:
        d = shot_path / sub
        d.mkdir(exist_ok=True)
        out.append(d)
    _ensure_notes(shot_path)
    return out


# ============================================================================
# Versioning (02_WORK/_state.json)
# ============================================================================

def work_dir(shot_dir: Path | str) -> Path:
    return Path(shot_dir) / "02_WORK"


def state_path(shot_dir: Path | str) -> Path:
    return work_dir(shot_dir) / "_state.json"


def load_state(shot_dir: Path | str) -> dict:
    sp = state_path(shot_dir)
    if sp.exists():
        return json.loads(sp.read_text(encoding="utf-8"))
    return {"current_version": None, "history": []}


def save_state(shot_dir: Path | str, state: dict) -> Path:
    work = work_dir(shot_dir)
    work.mkdir(parents=True, exist_ok=True)
    sp = state_path(shot_dir)
    sp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return sp


def existing_versions(shot_dir: Path | str) -> list[int]:
    work = work_dir(shot_dir)
    if not work.exists():
        return []
    out = [
        parse_version(p.name)
        for p in work.iterdir()
        if p.is_dir() and VERSION_RE.match(p.name)
    ]
    return sorted(out)


def resolve_version(
    shot_dir: Path | str,
    mode: str = "current",
    date: str | None = None,
) -> str:
    """Resolve the working version and ensure its folder exists.

    ``current`` -- reuse ``_state.current_version``; else max existing; else ``v001``.
    ``new``     -- one past the highest known version; updates the state.
    """
    if mode not in ("current", "new"):
        raise ValueError(f"Invalid version_mode {mode!r}: use 'current' or 'new'")

    state = load_state(shot_dir)
    existing = existing_versions(shot_dir)
    current = parse_version(state["current_version"]) if state.get("current_version") else 0
    highest = max([current, *existing]) if (current or existing) else 0

    if mode == "current":
        n = current or highest or 1
    else:
        n = highest + 1

    version = format_version(n)
    (work_dir(shot_dir) / version).mkdir(parents=True, exist_ok=True)

    state["current_version"] = version
    history = state.setdefault("history", [])
    if not any(h.get("version") == version for h in history):
        history.append({"version": version, "date": date or _today(), "tasks": []})
    save_state(shot_dir, state)
    return version


def register_task(shot_dir: Path | str, version: str, task: str) -> None:
    """Record that ``task`` was produced in ``version`` (for the state history)."""
    validate_component(version, "version")
    task = normalize_task(task)
    state = load_state(shot_dir)
    for entry in state.get("history", []):
        if entry.get("version") == version:
            tasks = entry.setdefault("tasks", [])
            if task not in tasks:
                tasks.append(task)
            save_state(shot_dir, state)
            return
    state.setdefault("history", []).append(
        {"version": version, "date": _today(), "tasks": [task]}
    )
    save_state(shot_dir, state)


# ============================================================================
# Sidecar
# ============================================================================

def build_meta(
    project: dict,
    seq: str,
    shot_id: str,
    shot_name: str,
    task: str,
    version: str,
    *,
    model: str = "",
    seed: int = 0,
    resolution: list[int] | None = None,
    fps: int = 24,
    variant: str | None = None,
    workflow: dict | None = None,
    prompt: dict | None = None,
    created: str | None = None,
) -> dict:
    """Build the sidecar dict. Identity first, workflow/prompt last."""
    return {
        "schema": SCHEMA,
        "show": project.get("show"),
        "seq": seq,
        "variant": variant,
        "shot": shot_id,
        "shot_name": shot_name,
        "task": normalize_task(task),
        "model": model,
        "version": version,
        "seed": seed,
        "resolution": resolution,
        "fps": fps,
        "created": created or datetime.now().isoformat(timespec="seconds"),
        "workflow": workflow,
        "prompt": prompt,
    }


def meta_path(out_dir: Path | str, base: str) -> Path:
    return Path(out_dir) / f"{base}_meta.json"


def write_meta(out_dir: Path | str, base: str, meta: dict) -> Path:
    """Write ``<out_dir>/<base>_meta.json`` and return its path."""
    path = meta_path(out_dir, base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ============================================================================
# Publish (03_PUBLISH)
# ============================================================================

def approve_copy(
    shot_dir: Path | str,
    task: str,
    version: str,
) -> list[Path]:
    """Copy the files of ``task``/``version`` to ``03_PUBLISH/`` without renaming.

    Copies, never moves, never re-encodes. Returns the destination paths.
    """
    task = normalize_task(task)
    validate_component(version, "version")
    src = work_dir(shot_dir) / version
    if not src.exists():
        raise FileNotFoundError(f"Version folder not found: {src}")

    publish = Path(shot_dir) / "03_PUBLISH"
    publish.mkdir(parents=True, exist_ok=True)

    token = f"_{task}_{version}"
    copied: list[Path] = []
    for f in sorted(src.iterdir()):
        if f.is_file() and token in f.name:
            dest = publish / f.name
            shutil.copy2(f, dest)
            copied.append(dest)
    return copied


# ============================================================================
# Human-readable project sheet (_PROJECT.md)
# ============================================================================

def render_project_md(project: dict) -> str:
    """Render ``_PROJECT.md`` from a project dict (regenerated, not manual)."""
    lines: list[str] = []
    lines.append("---")
    lines.append(f"slug: {project.get('slug', '')}")
    lines.append(f"show: {project.get('show', '')}")
    lines.append(f"artist: {project.get('artist', '')}")
    lines.append(f"fps: {project.get('fps', '')}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {project.get('project', project.get('slug', 'Proyecto'))}")
    lines.append("")
    lines.append("> Generado por COS desde `project.json`. Las notas manuales van en `_NOTES.md`.")
    lines.append("")
    lines.append("## Planos")
    lines.append("")
    lines.append("| Seq | Variante | Shot | Nombre | Resolucion |")
    lines.append("|---|---|---|---|---|")
    for seq, sdef in project.get("sequences", {}).items():
        variants = sdef.get("variants") or {}
        shots = sdef.get("shots") or {}
        seq_res = sdef.get("resolution")
        if variants:
            for variant, vdef in variants.items():
                res = vdef.get("resolution") or seq_res
                for shot_id, shot_name in shots.items():
                    lines.append(
                        f"| {seq} | {variant} | {shot_id} | {shot_name} | {_fmt_res(res)} |"
                    )
        else:
            for shot_id, shot_name in shots.items():
                lines.append(
                    f"| {seq} | - | {shot_id} | {shot_name} | {_fmt_res(seq_res)} |"
                )
    lines.append("")
    return "\n".join(lines)


def _fmt_res(res) -> str:
    if not res:
        return "-"
    return "x".join(str(v) for v in res)


# ============================================================================
# Internal helpers
# ============================================================================

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")
