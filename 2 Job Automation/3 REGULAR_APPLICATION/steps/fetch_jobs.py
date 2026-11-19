"""Step 1: fetch jobs from Stepstone and workingstudentjobs.de for the last N days.

Writes output/jobs/fetched_jobs.csv. Each source is fetched independently: if
one fails, its traceback is printed and the other source is still fetched.

Run alone:  python steps/fetch_jobs.py --days 3
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fetching import config  # noqa: E402
from fetching import stepstone_fetcher, workingstudent_fetcher  # noqa: E402
try:
    from engine import config as engine_config
    engine_config.ensure_utf8_stdout()
except Exception:
    pass

OUTPUT_CSV = PROJECT_ROOT / "output" / "jobs" / "fetched_jobs.csv"


def _fetch_source(name: str, fetch_fn) -> list[dict]:
    """Fetch one source; on failure print a traceback and return [] instead of crashing."""
    try:
        frame = fetch_fn()
        jobs = frame.to_dict("records") if frame is not None else []
        print(f"[STEP1] {name}: {len(jobs)} jobs fetched")
        return jobs
    except Exception as exc:  # noqa: BLE001 - one source failing must not stop the other
        print(f"[STEP1] ERROR {name} failed: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return []


def fetch_jobs(days: float = 1.0, pages: int | None = None, headless: bool = False) -> int:
    """Fetch both sources for the last `days` days and save the combined list.

    `pages` caps the listing pages per source/keyword (None = the source default,
    scaled with `days` for workingstudentjobs.de). Stepstone runs in a visible
    Chrome window by default (headless runs were blocked by the site before).
    Returns the number of jobs saved; raises RuntimeError when nothing was fetched.
    """
    wsj_pages = pages if pages is not None else config.wsj_pages_for(days)
    print(f"[STEP1] window: last {days:g} day(s) | stepstone pages/keyword: "
          f"{pages or config.STEPSTONE_MAX_PAGES} | workingstudentjobs.de pages: {wsj_pages}")
    jobs = _fetch_source("stepstone", lambda: stepstone_fetcher.fetch(
        max_pages=pages, headless=headless, max_posting_age_days=days))
    jobs += _fetch_source("workingstudentjobs.de", lambda: workingstudent_fetcher.fetch(
        max_pages=wsj_pages, max_posting_age_days=days))
    if not jobs:
        raise RuntimeError("both job sources returned no jobs - check the tracebacks above")

    try:
        OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(jobs).to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not write {OUTPUT_CSV}: {exc}") from exc

    print(f"[STEP1] saved {len(jobs)} jobs -> {OUTPUT_CSV}")
    return len(jobs)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="fetch jobs (step 1)")
    parser.add_argument("--days", type=float, default=1.0, help="posting window in days (default 1)")
    parser.add_argument("--pages", type=int, default=None, help="max listing pages per source/keyword")
    parser.add_argument("--headless", action="store_true", help="run Chrome without a window")
    args = parser.parse_args()
    try:
        fetch_jobs(days=args.days, pages=args.pages, headless=args.headless)
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[STEP1] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
