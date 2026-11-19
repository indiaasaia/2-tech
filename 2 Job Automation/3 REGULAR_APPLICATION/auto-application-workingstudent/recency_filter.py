"""Recency filter for workingstudent jobs.

Enforces rolling time window (default: last 24 hours / 1.0 day).
Parses ISO timestamps, UTC dates, and relative date formats.
Drops unparseable dates or dates older than the window.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from . import config
except ImportError:
    import config

config.ensure_utf8_stdout()


def parse_datetime(val: Any) -> datetime | None:
    """Parse various datetime representations into a timezone-aware UTC datetime."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None

    # Try ISO formats
    for iso_fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s, iso_fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
        except ValueError:
            pass

    # Try dateutil / pandas
    try:
        dt = pd.to_datetime(s, utc=True)
        if not pd.isna(dt):
            return dt.to_pydatetime()
    except Exception:
        pass

    # Relative expressions (e.g. "today", "yesterday", "2 hours ago", "1 day ago")
    now_utc = datetime.now(timezone.utc)
    s_low = s.lower()
    if "today" in s_low or "heute" in s_low:
        return now_utc
    if "yesterday" in s_low or "gestern" in s_low:
        return now_utc - timedelta(days=1)
    
    m_hours = re.search(r"(\d+)\s*(?:hour|std|stunde)", s_low)
    if m_hours:
        return now_utc - timedelta(hours=int(m_hours.group(1)))
        
    m_days = re.search(r"(\d+)\s*(?:day|tag)", s_low)
    if m_days:
        return now_utc - timedelta(days=int(m_days.group(1)))

    return None


def is_within_window(posted_val: Any, days: float = 1.0) -> bool:
    """Return True if posted_val is strictly within the rolling window ending now."""
    dt = parse_datetime(posted_val)
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    return dt >= cutoff


def filter_jobs(
    days: float = config.DEFAULT_POSTING_AGE_DAYS,
    input_csv: Path | None = None,
    output_csv: Path | None = None,
) -> pd.DataFrame:
    """Filter jobs from input_csv to strictly those posted in the last N days."""
    config.ensure_dirs()
    in_path = input_csv or config.FETCHED_CSV
    out_path = output_csv or config.FILTERED_CSV

    if not in_path.exists():
        print(f"[RECENCY-FILTER] Error: Input file not found: {in_path}")
        return pd.DataFrame()

    frame = pd.read_csv(in_path, keep_default_na=False)
    if frame.empty:
        print("[RECENCY-FILTER] Input file is empty.")
        return frame

    initial_count = len(frame)
    # Deduplicate on job_url
    if "job_url" in frame.columns:
        frame = frame.drop_duplicates(subset=["job_url"]).reset_index(drop=True)

    kept_rows = []
    dropped_unparsed = 0
    dropped_aged = 0

    for _, row in frame.iterrows():
        posted_val = row.get("posted_time") or row.get("detail_online_date")
        dt = parse_datetime(posted_val)
        if dt is None:
            dropped_unparsed += 1
            continue
        if is_within_window(posted_val, days=days):
            kept_rows.append(row)
        else:
            dropped_aged += 1

    filtered_df = pd.DataFrame(kept_rows)
    filtered_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[RECENCY-FILTER] Window: Last {days:g} day(s) (past {int(days*24)} hours)")
    print(f"[RECENCY-FILTER] Initial jobs: {initial_count}")
    print(f"[RECENCY-FILTER] Dropped (older than {days:g} days): {dropped_aged}")
    print(f"[RECENCY-FILTER] Dropped (unparseable date): {dropped_unparsed}")
    print(f"[RECENCY-FILTER] Kept: {len(filtered_df)} jobs -> saved to {out_path}")
    return filtered_df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Filter jobs by recency window")
    parser.add_argument("--days", type=float, default=config.DEFAULT_POSTING_AGE_DAYS, help="Window in days (default: 1.0 = 24h)")
    args = parser.parse_args(argv)

    df = filter_jobs(days=args.days)
    return 0 if not df.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
