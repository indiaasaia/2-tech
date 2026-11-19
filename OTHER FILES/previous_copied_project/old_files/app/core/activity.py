"""Persistent activity tracking for every pipeline step.

Every meaningful step of the pipeline appends a structured JSON event to
``data/output/activity.log`` and prints a short status line, so a run can be
reviewed live on the console or afterwards via ``python run.py status``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.core import config


def log_event(phase: str, step: str, message: str, status: str = "ok", **extra: Any) -> None:
    """Record one pipeline event, persist it, and print a short status line."""
    event: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phase": phase,
        "step": step,
        "message": message,
        "status": status,
    }
    event.update(extra)
    try:
        config.ACTIVITY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with config.ACTIVITY_LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass
    marker = {"ok": "+", "warn": "!", "error": "x", "info": "."}.get(status, ".")
    print(f"[{event['ts'][11:19]}] {marker} {phase}/{step}: {message}")


def load_events(limit: int | None = None) -> list[dict[str, Any]]:
    """Read recorded events, newest last; ``limit`` keeps only the tail."""
    if not config.ACTIVITY_LOG.exists():
        return []
    events: list[dict[str, Any]] = []
    with config.ACTIVITY_LOG.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events[-limit:] if limit else events
