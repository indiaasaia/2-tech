"""Step 2: keep only jobs posted yesterday or today (calendar window).

Reads program_files/output/todays_overall_jobs.csv (written by step 1), keeps the
jobs whose posting date falls on today's or yesterday's calendar date (local time),
and saves the result to program_files/output/2_filted_jobs.csv.

Any job whose posting date cannot be parsed is DROPPED (it cannot be proven fresh)
and reported so unusual date formats are easy to spot.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
INPUT_CSV = OUTPUT_DIR / "todays_overall_jobs.csv"
OUTPUT_CSV = OUTPUT_DIR / "2_filted_jobs.csv"

# Date candidates checked in order: posted_time first, then detail_online_date.
DATE_COLUMNS = ("posted_time", "detail_online_date")

# English + German relative time units, in seconds.
_UNIT_SECONDS = {
    "minute": 60, "minutes": 60,
    "hour": 3600, "hours": 3600,
    "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
    "minuten": 60, "stunde": 3600, "stunden": 3600,
    "tag": 86400, "tage": 86400, "tagen": 86400,
    "woche": 604800, "wochen": 604800,
}


def parse_posted_at(value: object, now: datetime | None = None) -> datetime | None:
    """Parse a posted-date string into an aware UTC datetime, or None if unparseable."""
    text = str(value or "").strip()
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    lowered = text.lower()

    if lowered in {"just now", "now", "today", "heute"}:
        return now
    if lowered in {"yesterday", "gestern"}:
        return now - timedelta(days=1)

    # Relative phrases like "11 hours ago", "Published: 4 hours ago", "vor 2 Tagen".
    match = re.search(
        r"(\d+)\s*(minute|minutes|hour|hours|day|days|week|weeks|minuten|stunde|stunden|tag|tage|tagen|woche|wochen)",
        lowered,
    )
    if match:
        seconds = int(match.group(1)) * _UNIT_SECONDS[match.group(2)]
        return now - timedelta(seconds=seconds)

    # ISO date strings, e.g. 2026-08-30, 2026-08-30T10:00:00Z, ...+00:00.
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def recent_dates() -> set:
    """Calendar dates (local time) the job must fall on: today and yesterday."""
    now_local = datetime.now(timezone.utc).astimezone()
    return {now_local.date(), (now_local - timedelta(days=1)).date()}


def posted_yesterday_or_today(value: object) -> bool:
    """True if the posting date resolves to today's or yesterday's calendar date."""
    posted = parse_posted_at(value)
    if posted is None:
        return False
    return posted.astimezone().date() in recent_dates()


def pick_date_column(frame: pd.DataFrame) -> str:
    """Return the first available date column name, raising a clear error if none exists."""
    for column in DATE_COLUMNS:
        if column in frame.columns:
            return column
    raise RuntimeError(
        f"no posting-date column found in {INPUT_CSV} (looked for {list(DATE_COLUMNS)}; "
        f"actual columns: {list(frame.columns)})"
    )


def filter_jobs(input_csv: Path = INPUT_CSV, output_csv: Path = OUTPUT_CSV) -> int:
    """Keep jobs posted yesterday or today, save them, and return the count kept.

    Raises RuntimeError with a clear message if the input is missing, unreadable,
    or has no usable date column.
    """
    if not input_csv.exists():
        raise RuntimeError(f"input not found: {input_csv} — run step 1 (1_fetch_jobs.py) first")

    try:
        frame = pd.read_csv(input_csv)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise RuntimeError(f"could not read {input_csv}: {exc}") from exc

    if frame.empty:
        print(f"[FILTER] input is empty: {input_csv}")
        return 0

    date_column = pick_date_column(frame)
    kept_mask = frame[date_column].map(posted_yesterday_or_today).fillna(False)
    kept = frame[kept_mask].reset_index(drop=True)

    dropped = len(frame) - len(kept)
    if dropped:
        unparseable = frame.loc[~kept_mask, date_column].astype(str).str.strip().unique()[:5]
        print(f"[FILTER] dropped {dropped} job(s) not posted yesterday or today (or unparseable)")
        print(f"[FILTER] sample of dropped dates: {list(unparseable)}")

    try:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        kept.to_csv(output_csv, index=False, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not write {output_csv}: {exc}") from exc

    print(f"[FILTER] kept {len(kept)}/{len(frame)} job(s) posted yesterday or today -> {output_csv}")
    return len(kept)


if __name__ == "__main__":
    import traceback

    try:
        filter_jobs()
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[FILTER] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc