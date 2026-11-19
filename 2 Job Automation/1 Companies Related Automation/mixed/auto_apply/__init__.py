"""Auto-apply package for mixed job automation ecosystem."""
from __future__ import annotations

from .registry import get_applier, has_applier, list_appliers, register_applier

__all__ = ["get_applier", "has_applier", "list_appliers", "register_applier"]
