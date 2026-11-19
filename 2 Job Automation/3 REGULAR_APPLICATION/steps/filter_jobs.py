"""Step 2: keep only jobs posted within the last N days (default 1 = 24 hours).

Reads output/jobs/fetched_jobs.csv (written by step 1), keeps jobs posted in the
rolling N-day window ending now, drops duplicate job URLs, and writes
output/jobs/filtered_jobs.csv (the input of the resume engine).

Run alone:  python steps/filter_jobs.py --days 3

Any job whose posting date cannot be parsed is DROPPED (it cannot be proven fresh)
and reported so unusual date formats are easy to spot.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
try:
    from engine import config
    config.ensure_utf8_stdout()
except Exception:
    pass

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "jobs"
INPUT_CSV = OUTPUT_DIR / "fetched_jobs.csv"
OUTPUT_CSV = OUTPUT_DIR / "filtered_jobs.csv"

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


def posted_within_last_24_hours(value: object, now: datetime | None = None, days: float = 1.0) -> bool:
    """True only when a posting timestamp is between now and `days` days ago (default 24 hours)."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    posted = parse_posted_at(value, now=current)
    if posted is None:
        return False
    age = current - posted
    return timedelta(0) <= age <= timedelta(days=days)


def pick_date_column(frame: pd.DataFrame) -> str:
    """Return the first available date column name, raising a clear error if none exists."""
    for column in DATE_COLUMNS:
        if column in frame.columns:
            return column
    raise RuntimeError(
        f"no posting-date column found in {INPUT_CSV} (looked for {list(DATE_COLUMNS)}; "
        f"actual columns: {list(frame.columns)})"
    )


def resolve_date_range(start_date: str, end_date: str) -> tuple[date, date]:
    """Parse an inclusive YYYY-MM-DD range and reject malformed or reversed dates."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("dates must use ISO dates (YYYY-MM-DD)") from exc
    if start > end:
        raise ValueError("start date must be on or before end date")
    return start, end


def _load_domain_buckets() -> dict:
    """Compatibility hook for callers that provide additional filter buckets."""
    return {}


def filter_jobs(input_csv: Path = INPUT_CSV, output_csv: Path = OUTPUT_CSV,
                start_date: str | None = None, end_date: str | None = None,
                now: datetime | None = None, days: float = 1.0) -> int:
    """Keep jobs posted in the last 24 hours (or explicit date range), then save."

    Raises RuntimeError with a clear message if the input is missing, unreadable,
    or has no usable date column.
    """
    if not input_csv.exists():
        raise RuntimeError(f"input not found: {input_csv} - run step 1 (steps/fetch_jobs.py) first")

    try:
        frame = pd.read_csv(input_csv)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise RuntimeError(f"could not read {input_csv}: {exc}") from exc

    if frame.empty:
        print(f"[FILTER] input is empty: {input_csv}")
        return 0

    date_column = pick_date_column(frame)
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None:
            raise ValueError("both start_date and end_date are required")
        first, last = resolve_date_range(start_date, end_date)
        range_matches = [
            bool(parsed is not None and first <= parsed.astimezone().date() <= last)
            for parsed in (parse_posted_at(value) for value in frame[date_column].tolist())
        ]
        kept_mask = pd.Series(range_matches, index=frame.index)
    else:
        kept_mask = frame[date_column].map(
            lambda value: posted_within_last_24_hours(value, now=now, days=days)
        ).fillna(False)
    kept = frame[kept_mask].reset_index(drop=True)
    if "job_url" in kept.columns:              # the same ad can come from two keyword searches
        before = len(kept)
        kept = kept.drop_duplicates(subset="job_url").reset_index(drop=True)
        if before != len(kept):
            print(f"[FILTER] removed {before - len(kept)} duplicate job URL(s)")

    dropped = len(frame) - len(kept)
    if dropped:
        unparseable = frame.loc[~kept_mask, date_column].astype(str).str.strip().unique()[:5]
        if start_date is None and end_date is None:
            print(f"[FILTER] dropped {dropped} job(s) outside the last {days:g} day(s) (or unparseable)")
        else:
            print(f"[FILTER] dropped {dropped} job(s) outside {start_date}..{end_date} (or unparseable)")
        print(f"[FILTER] sample of dropped dates: {list(unparseable)}")

    try:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        kept.to_csv(output_csv, index=False, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not write {output_csv}: {exc}") from exc

    window = f"{start_date}..{end_date}" if start_date and end_date else f"last {days:g} day(s)"
    print(f"[FILTER] kept {len(kept)}/{len(frame)} job(s) in {window} -> {output_csv}")
    return len(kept)


if __name__ == "__main__":
    import traceback

    import argparse

    parser = argparse.ArgumentParser(description="keep jobs from the last N days (step 2)")
    parser.add_argument("--days", type=float, default=1.0, help="posting window in days (default 1)")
    args = parser.parse_args()
    try:
        filter_jobs(days=args.days)
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[FILTER] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc