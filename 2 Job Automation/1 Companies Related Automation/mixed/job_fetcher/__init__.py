"""Job fetcher package for mixed job automation ecosystem.

Provides modular, plug-and-play job fetchers for each supported company.
To add a new company, simply add a new module in this folder and register it in registry.py.
"""
from __future__ import annotations

from .registry import get_fetcher, has_fetcher, list_fetchers, register_fetcher

__all__ = ["get_fetcher", "has_fetcher", "list_fetchers", "register_fetcher"]
