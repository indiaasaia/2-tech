from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FILTER_PATH = PROJECT_ROOT / "program_files" / "2_filter_jobs.py"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

spec = importlib.util.spec_from_file_location("job_filter", FILTER_PATH)
assert spec and spec.loader
job_filter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job_filter)


def test_resolve_date_range_accepts_iso_dates_and_rejects_invalid_ranges():
    assert job_filter.resolve_date_range("2026-09-21", "2026-09-25") == (
        date(2026, 9, 21),
        date(2026, 9, 25),
    )

    with pytest.raises(ValueError, match="on or before"):
        job_filter.resolve_date_range("2026-09-26", "2026-09-25")
    with pytest.raises(ValueError, match="ISO dates"):
        job_filter.resolve_date_range("not-a-date", "2026-09-25")


def test_filter_jobs_keeps_only_the_rolling_last_24_hours(tmp_path):
    input_csv = tmp_path / "jobs.csv"
    output_csv = tmp_path / "filtered.csv"
    now = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
    pd.DataFrame(
        [
            {"title": "Just inside", "posted_time": (now - timedelta(hours=23, minutes=59)).isoformat()},
            {"title": "Exactly 24 hours", "posted_time": (now - timedelta(hours=24)).isoformat()},
            {"title": "Just outside", "posted_time": (now - timedelta(hours=24, seconds=1)).isoformat()},
            {"title": "Future posting", "posted_time": (now + timedelta(seconds=1)).isoformat()},
            {"title": "Relative fresh", "posted_time": "12 hours ago"},
            {"title": "Unknown date", "posted_time": "unknown"},
        ]
    ).to_csv(input_csv, index=False)

    kept = job_filter.filter_jobs(input_csv, output_csv, now=now)

    result = pd.read_csv(output_csv)
    assert kept == 3
    assert result["title"].tolist() == ["Just inside", "Exactly 24 hours", "Relative fresh"]


def test_posted_within_last_24_hours_handles_naive_now_and_future_dates():
    now = datetime(2026, 9, 25, 12, 0)
    assert job_filter.posted_within_last_24_hours("2026-09-24T12:00:00", now=now)
    assert not job_filter.posted_within_last_24_hours("2026-09-24T11:59:59", now=now)
    assert not job_filter.posted_within_last_24_hours("2026-09-25T12:00:01", now=now)
