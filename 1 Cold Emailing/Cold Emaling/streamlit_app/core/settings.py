"""Settings persistence.

A single JSON file (``streamlit_app/settings.json``, git-ignored because it
holds API keys) is the source of truth for everything the user edits in the
UI:

- API keys (label + value + enabled; tried in order, rotated on failure)
- target cities (filled into the Phase 1 prompt's {{CITIES}} placeholder)
- pipeline knobs (models, batch size, caps, temperatures, file paths)

On first run the file is seeded with the default values (the target cities
and the additional API keys supplied for this project). ``GEMINI_API_KEY``
from the environment is imported as the primary key when present.
"""
from __future__ import annotations

import json
import os
from typing import Any

from . import paths

# Supplied "additional" keys for this project. They are Yandex Cloud keys
# (the "AQ." prefix), so they get provider "yandex" and are usable once a
# folder id is added in Settings.
_DEFAULT_API_KEYS: list[dict[str, Any]] = [
    {
        "label": "Additional key 1",
        "value": "AQ.Ab8RN6KkiY1bfiYE-IgaUOzQKYuo9FHp4T3ZWIC4JjdKeUC9qw",
        "provider": "yandex",
        "folder_id": "",
        "enabled": True,
    },
    {
        "label": "Additional key 2",
        "value": "AQ.Ab8RN6KIo3eC7ZbV7oKQ8uP-DRjau3dgJIetSSvSEcEziYJ8cw",
        "provider": "yandex",
        "folder_id": "",
        "enabled": True,
    },
]

PROVIDERS = ("gemini", "yandex")


def _normalize_key(item: dict[str, Any]) -> dict[str, Any]:
    """Backfill provider/folder_id on older key records.

    Keys beginning with "AQ." are Yandex-format; everything else defaults to
    Gemini unless the record already says otherwise.
    """
    value = str(item.get("value") or "").strip()
    provider = str(item.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        provider = "yandex" if value.startswith("AQ.") else "gemini"
    return {
        "label": str(item.get("label") or ""),
        "value": value,
        "provider": provider,
        "folder_id": str(item.get("folder_id") or "").strip(),
        "enabled": bool(item.get("enabled", True)),
    }


def _defaults() -> dict[str, Any]:
    keys = [_normalize_key(k) for k in _DEFAULT_API_KEYS]
    env_key = os.environ.get("GEMINI_API_KEY", "")
    if env_key:
        keys.insert(
            0,
            _normalize_key({"label": "Primary Gemini (from env)", "value": env_key, "enabled": True}),
        )
    return {
        "api_keys": keys,
        "cities": ["Berlin", "Munich", "Frankfurt", "Hamburg"],
        "phase1": {
            "model": "gemini-3.6-flash",
            "batch_size": 5,
            "total_cap": 50,
            "min_hiring_score": 55,
            "max_runs": 20,
            "temperature": 0.2,
            # Phase 1 writes directly to the file Phase 2 reads, so the
            # pipeline is linked out of the box.
            "csv_path": str(paths.PHASE2_COMPANIES),
            "prompt_path": str(paths.PHASE1_PROMPT),
        },
        "phase2": {
            "model": "gemini-3.7-flash",
            "fallback_models": ["gemini-3.6-flash", "gemini-3.5-flash"],
            "max_iterations": 3,
            "temperature": 0.2,
            "limit": None,
            "companies_path": str(paths.PHASE2_COMPANIES),
            "csv_path": str(paths.PHASE2_RESULTS),
            "outcomes_path": str(paths.PHASE2_OUTCOMES),
            "prompt_path": str(paths.PHASE2_PROMPT),
            "repeat_prompt_path": str(paths.PHASE2_REPEAT_PROMPT),
        },
    }


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge ``override`` into ``base``; nested dicts merge recursively."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load() -> dict[str, Any]:
    """Load settings, deep-merged over defaults (new fields appear even if a
    saved file predates them). Seeds the file on first run."""
    if not paths.SETTINGS_PATH.exists():
        save(_defaults())
        return _defaults()
    try:
        saved = json.loads(paths.SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        saved = {}
    merged = _deep_merge(_defaults(), saved)
    merged["api_keys"] = [_normalize_key(k) for k in merged.get("api_keys", [])]
    # Keep the file in sync so the user can inspect it at any time.
    save(merged)
    return merged


def save(settings: dict[str, Any]) -> None:
    """Persist settings; skips the write when the content is unchanged.

    ``load()`` is called on every page render and by the live-run monitor
    (every 2 s), so without this guard the file would be rewritten
    constantly and could race a concurrent save.
    """
    content = json.dumps(settings, indent=2, ensure_ascii=False)
    if paths.SETTINGS_PATH.exists():
        try:
            if paths.SETTINGS_PATH.read_text(encoding="utf-8") == content:
                return
        except OSError:
            pass
    paths.SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    paths.SETTINGS_PATH.write_text(content, encoding="utf-8")


def enabled_keys(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Enabled key records (with a non-empty value), in order."""
    return [
        _normalize_key(item)
        for item in settings.get("api_keys", [])
        if item.get("enabled") and str(item.get("value") or "").strip()
    ]


def provider_ready(key: dict[str, Any]) -> bool:
    """True when the key record has everything its provider needs."""
    if key.get("provider") == "yandex":
        return bool(key.get("folder_id"))
    return True


def cities(settings: dict[str, Any]) -> list[str]:
    return [str(c).strip() for c in settings.get("cities", []) if str(c).strip()]
