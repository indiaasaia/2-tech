"""Auto-apply registry for mixed job automation ecosystem."""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Type

from .base import BaseApplier

_REGISTRY: dict[str, Type[BaseApplier]] = {}


def register_applier(company_id: str):
    def decorator(cls: Type[BaseApplier]):
        _REGISTRY[company_id.lower()] = cls
        return cls
    return decorator


def has_applier(company_id: str) -> bool:
    norm = company_id.lower().replace("-", "_").replace(" ", "_")
    if norm not in _REGISTRY:
        _auto_discover()
    return norm in _REGISTRY


def get_applier(company_id: str) -> BaseApplier | None:
    norm = company_id.lower().replace("-", "_").replace(" ", "_")
    if norm not in _REGISTRY:
        _auto_discover()
    cls = _REGISTRY.get(norm)
    return cls() if cls else None


def list_appliers() -> dict[str, dict]:
    _auto_discover()
    result = {}
    for cid, cls in sorted(_REGISTRY.items()):
        result[cid] = {
            "company_id": cid,
            "display_name": getattr(cls, "display_name", cid.capitalize()),
            "portal_name": getattr(cls, "portal_name", "Unknown"),
            "class": cls.__name__,
        }
    return result


def _auto_discover():
    pkg_dir = Path(__file__).resolve().parent
    for py_file in pkg_dir.glob("*.py"):
        stem = py_file.stem
        if stem in ("__init__", "base", "registry"):
            continue
        try:
            importlib.import_module(f"auto_apply.{stem}")
        except Exception:
            try:
                importlib.import_module(stem)
            except Exception:
                pass
