"""Posting-date parsing and strict last-N-days filtering."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

_UNIT_SECONDS = {
    "minute": 60, "minutes": 60,
    "hour": 3600, "hours": 3600,
    "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
    "minuten": 60, "stunde": 3600, "stunden": 3600,
    "tag": 86400, "tage": 86400, "tagen": 86400,
    "woche": 604800, "wochen": 604800,
}


def parse_posted_at(value: Any, now: datetime | None = None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    lowered = text.lower()
    if lowered in {"just now", "now", "today", "heute"}:
        return current
    if lowered in {"yesterday", "gestern"}:
        return current - timedelta(days=1)
    match = re.search(
        r"(\d+)\s*(minute|minutes|hour|hours|day|days|week|weeks|minuten|stunde|stunden|tag|tage|tagen|woche|wochen)",
        lowered,
    )
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        seconds = amount * _UNIT_SECONDS[unit]
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
