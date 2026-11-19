"""Fetch detail pages only for selected Stepstone workweek postings."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.phase1 import stepstone_fetcher

OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output"
FILTERED_CSV = OUTPUT_DIR / "2_filted_jobs.csv"
STEPSTONE_CSV = OUTPUT_DIR / "stepstone_jobs.csv"
OVERALL_CSV = OUTPUT_DIR / "todays_overall_jobs.csv"




def _sync_by_url(frame: pd.DataFrame, job_url: str, detail: dict[str, str]) -> pd.DataFrame:
    if frame.empty or "job_url" not in frame.columns:
        return frame
    matches = frame["job_url"].astype(str).eq(job_url)
    for column, value in detail.items():
        if column not in frame.columns:
            frame[column] = ""
        if value:
            frame.loc[matches, column] = value
    return frame


def main() -> int:
    filtered = pd.read_csv(FILTERED_CSV, keep_default_na=False)
    selected = filtered[
        filtered["source"].astype(str).str.lower().eq("stepstone")
    ]
    if selected.empty:
        print("[DETAILS] no selected Stepstone jobs")
        return 0

    raw_overall = pd.read_csv(OVERALL_CSV, keep_default_na=False)
    stepstone = pd.read_csv(STEPSTONE_CSV, keep_default_na=False)

    driver = stepstone_fetcher._driver(headless=False)
    failures: list[str] = []
    successes = 0
    try:
        for index, row in enumerate(selected.to_dict("records"), 1):
            url = str(row.get("job_url") or "").strip()
            if not url:
                failures.append(f"{row.get('title', '?')}: missing job_url")
                continue
            try:
                detail = stepstone_fetcher._details(driver, url)
            except Exception as exc:  # noqa: BLE001 - continue to other selected postings
                failures.append(f"{row.get('title', '?')}: {type(exc).__name__}: {exc}")
                print(f"[DETAILS] [{index}/{len(selected)}] FAILED: {failures[-1]}")
                continue

            filtered = _sync_by_url(filtered, url, detail)
            raw_overall = _sync_by_url(raw_overall, url, detail)
            stepstone = _sync_by_url(stepstone, url, detail)
            successes += bool(detail.get("job_description") or detail.get("applicant_profile"))
            # Checkpoint after every posting so a later browser/network error does not
            # lose already retrieved details.
            filtered.to_csv(FILTERED_CSV, index=False, encoding="utf-8")
            raw_overall.to_csv(OVERALL_CSV, index=False, encoding="utf-8")
            stepstone.to_csv(STEPSTONE_CSV, index=False, encoding="utf-8")
            has_description = bool(detail.get("job_description"))
            print(f"[DETAILS] [{index}/{len(selected)}] {row.get('title', '?')}: {'description' if has_description else 'no description text'}")
    finally:
        driver.quit()

    print(f"[DETAILS] descriptions retrieved: {successes}/{len(selected)}")
    if failures:
        print(f"[DETAILS] failed postings: {len(failures)}")
        for failure in failures:
            print(f"  - {failure}")
    return 0 if successes == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
