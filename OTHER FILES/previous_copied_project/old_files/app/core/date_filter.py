"""Posting-date parsing and strict last-48-hour filtering."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any


def parse_posted_at(value: Any, now: datetime | None = None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    lowered = text.lower()
    if lowered in {"just now", "now", "today"}:
        return current
    if lowered == "yesterday":
        return current - timedelta(days=1)
    match = re.search(r"(\d+)\s*(minute|minutes|hour|hours|day|days|week|weeks)", lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        seconds = amount * {"minute": 60, "minutes": 60, "hour": 3600, "hours": 3600, "day": 86400, "days": 86400, "week": 604800, "weeks": 604800}[unit]
        return current - timedelta(seconds=seconds)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_within_last_days(value: Any, days: float = 2.0, now: datetime | None = None) -> bool:
    posted = parse_posted_at(value, now=now)
    if posted is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = current.astimezone(timezone.utc) - posted
    return timedelta(0) <= age <= timedelta(days=days)
