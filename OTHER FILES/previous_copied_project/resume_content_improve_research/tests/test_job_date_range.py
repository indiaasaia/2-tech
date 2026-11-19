from __future__ import annotations

import importlib.util
import sys
from datetime import date
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


def test_filter_jobs_keeps_both_inclusive_workweek_boundaries(tmp_path, monkeypatch):
    input_csv = tmp_path / "jobs.csv"
    output_csv = tmp_path / "filtered.csv"
    pd.DataFrame(
        [
            {"title": "Earlier job", "posted_time": "2026-09-20"},
            {"title": "Monday job", "posted_time": "2026-09-21"},
            {"title": "Friday job", "posted_time": "2026-09-25"},
            {"title": "Weekend job", "posted_time": "2026-09-26"},
            {"title": "Unknown date", "posted_time": "unknown"},
        ]
    ).to_csv(input_csv, index=False)
    monkeypatch.setattr(job_filter, "_load_domain_buckets", lambda: {})

    kept = job_filter.filter_jobs(
        input_csv,
        output_csv,
        start_date="2026-09-21",
        end_date="2026-09-25",
    )

    result = pd.read_csv(output_csv)
    assert kept == 2
    assert result["title"].tolist() == ["Monday job", "Friday job"]
