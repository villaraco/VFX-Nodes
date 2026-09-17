"""COS (Comfy Output Standard) subpackage for VFX-Nodes.

Phase 0 ships the pure logic in :mod:`cos.core`. The ComfyUI node
classes (``COS Project``, ``COS Shot``, ``COS Path``, ``COS Approve``)
are added in later phases and registered here via
``COS_NODE_CLASS_MAPPINGS``.

Keep this module importable without ComfyUI (the node layer imports it
lazily) so ``validate_cos.py`` runs standalone.
"""

from __future__ import annotations

from . import core

__all__ = ["core"]
