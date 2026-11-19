"""Step 1: fetch jobs from both sources and save them to program_files/output/todays_overall_jobs.csv.

Each source is fetched independently: if one source fails, its error is printed
with a full traceback and the other source is still fetched.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import pandas as pd

# Make the archived `app` package and the program_files package importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "old_files"))
sys.path.insert(0, str(PROJECT_ROOT))

from sub_program_files.stepstone_scraper import get_stepstone_jobs
from sub_program_files.workingstudent_scraper import get_workingstudent_jobs

OUTPUT_CSV = Path(__file__).resolve().parent / "output" / "todays_overall_jobs.csv"


def _fetch_source(name: str, fetch_fn) -> list[dict]:
    """Fetch one source; on failure print a traceback and return [] instead of crashing.

    This keeps a broken source from killing the rest of the pipeline, and the
    traceback makes the root cause visible.
    """
    try:
        jobs = fetch_fn() or []
        print(f"[STEP1] {name}: {len(jobs)} jobs fetched")
        return jobs
    except Exception as exc:  # noqa: BLE001 - source failure must not stop the other source
        print(f"[STEP1] ERROR {name} failed: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return []


def fetch_jobs() -> int:
    """Fetch jobs from both sources and save the combined list to output/todays_overall_jobs.csv.

    Returns the number of jobs saved. Raises RuntimeError if nothing could be fetched,
    so callers (and main.py) can tell that the step failed.
    """
    jobs = _fetch_source("stepstone", get_stepstone_jobs) + _fetch_source(
        "workingstudentjobs.de", get_workingstudent_jobs
    )
    if not jobs:
        raise RuntimeError("both job sources returned no jobs — check the tracebacks above")

    try:
        OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(jobs).to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not write {OUTPUT_CSV}: {exc}") from exc

    print(f"[STEP1] saved {len(jobs)} jobs -> {OUTPUT_CSV}")
    return len(jobs)


if __name__ == "__main__":
    try:
        fetch_jobs()
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[STEP1] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc