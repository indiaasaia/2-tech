"""Fetcher registry for mixed job automation ecosystem."""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Type

from .base import BaseJobFetcher

_REGISTRY: dict[str, Type[BaseJobFetcher]] = {}
# Aliases resolve to a real fetcher but are hidden from `list_fetchers()` so the
# CLI never advertises two rows for the same company (e.g. siemens/simense).
_ALIASES: set[str] = set()


def register_fetcher(company_id: str, *, alias: bool = False):
    def decorator(cls: Type[BaseJobFetcher]):
        norm = company_id.lower()
        _REGISTRY[norm] = cls
        if alias:
            _ALIASES.add(norm)
        return cls
    return decorator


def has_fetcher(company_id: str) -> bool:
    """True when a fetcher (canonical id or alias) is registered for company_id."""
    norm = company_id.lower().replace("-", "_").replace(" ", "_")
    if norm not in _REGISTRY:
        _auto_discover()
    return norm in _REGISTRY


def get_fetcher(company_id: str) -> BaseJobFetcher:
    norm = company_id.lower().replace("-", "_").replace(" ", "_")
    # Lazy auto-import known builtins
    if norm not in _REGISTRY:
        _auto_discover()
    if norm not in _REGISTRY:
        raise ValueError(
            f"No job fetcher registered for company '{company_id}'. "
            f"Registered: {', '.join(sorted(_REGISTRY.keys()))}"
        )
    return _REGISTRY[norm]()


def list_fetchers(include_aliases: bool = False) -> dict[str, dict]:
    """Registered companies for display. Aliases are hidden unless requested."""
    _auto_discover()
    result = {}
    for cid, cls in sorted(_REGISTRY.items()):
        if not include_aliases and cid in _ALIASES:
            continue
        result[cid] = {
            "company_id": cid,
            "display_name": getattr(cls, "display_name", cid.capitalize()),
            "portal_type": getattr(cls, "portal_type", "Unknown"),
            "class": cls.__name__,
        }
    return result


def _auto_discover():
    pkg_dir = Path(__file__).resolve().parent
    for py_file in pkg_dir.glob("*.py"):
        stem = py_file.stem
        if stem in ("__init__", "base", "registry", "language_filter"):
            continue
        try:
            importlib.import_module(f"job_fetcher.{stem}")
        except Exception:
            # Fallback when running from mixed/ directory directly
            try:
                importlib.import_module(stem)
            except Exception:
                pass
