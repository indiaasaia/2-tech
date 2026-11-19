"""Helpers for reading pipeline CSVs (the source of truth)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def load_csv(path: str | Path) -> pd.DataFrame | None:
    """Return a DataFrame, or None when the file does not exist yet."""
    csv_path = Path(path)
    if not csv_path.exists():
        return None
    try:
        return pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception:
        return None


def row_count(path: str | Path) -> int:
    frame = load_csv(path)
    return 0 if frame is None else int(len(frame))


def summarize(settings: dict[str, Any]) -> dict[str, Any]:
    """Counts across every phase, used by the Overview page."""
    from . import paths

    phase1 = settings.get("phase1", {})
    phase2 = settings.get("phase2", {})
    companies = load_csv(phase1.get("csv_path") or paths.PHASE2_COMPANIES)
    contacts = load_csv(phase2.get("csv_path") or paths.PHASE2_RESULTS)
    outcomes = load_csv(phase2.get("outcomes_path") or paths.PHASE2_OUTCOMES)
    history = load_csv(paths.PHASE3_HISTORY)

    status_counts: dict[str, int] = {}
    if outcomes is not None and not outcomes.empty and "status" in outcomes.columns:
        status_counts = {str(k): int(v) for k, v in outcomes["status"].value_counts().items()}

    return {
        "companies": 0 if companies is None else int(len(companies)),
        "contacts": 0 if contacts is None else int(len(contacts)),
        "companies_done": int(sum(status_counts.values())),
        "outcomes": status_counts,
        "sent": 0 if history is None else int(len(history)),
    }
