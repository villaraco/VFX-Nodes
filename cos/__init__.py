"""COS (Comfy Output Standard) subpackage for VFX-Nodes.

* :mod:`cos.core` holds the pure logic (stdlib only).
* The ComfyUI node classes live in ``cos/nodes_*.py`` and are registered
  here via ``COS_NODE_CLASS_MAPPINGS``.

Node registration is guarded so the package stays importable without
ComfyUI (``validate_cos.py`` runs standalone).
"""

from __future__ import annotations

from . import core

NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

try:
    import folder_paths  # noqa: F401  (present only inside ComfyUI)

    _IN_COMFYUI = True
except ImportError:
    _IN_COMFYUI = False

if _IN_COMFYUI:
    from .nodes_path import COSApprove, COSPath, COSShot
    from .nodes_project import COSProject

    NODE_CLASS_MAPPINGS["COSProject"] = COSProject
    NODE_DISPLAY_NAME_MAPPINGS["COSProject"] = "COS Project"

    NODE_CLASS_MAPPINGS["COSPath"] = COSPath
    NODE_DISPLAY_NAME_MAPPINGS["COSPath"] = "COS Path"

    NODE_CLASS_MAPPINGS["COSShot"] = COSShot
    NODE_DISPLAY_NAME_MAPPINGS["COSShot"] = "COS Shot"

    NODE_CLASS_MAPPINGS["COSApprove"] = COSApprove
    NODE_DISPLAY_NAME_MAPPINGS["COSApprove"] = "COS Approve"

__all__ = [
    "core",
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
