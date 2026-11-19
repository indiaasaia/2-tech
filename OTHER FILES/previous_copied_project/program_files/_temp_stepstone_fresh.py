"""TEMP helper: run the Stepstone fetch with a pre-cached chromedriver.

Windows Application Control currently blocks selenium-manager.exe, so
webdriver.Chrome() can't auto-resolve a driver. This wrapper points the
Service directly at the newest cached chromedriver and writes the result to
program_files/output/stepstone_fresh.csv (merged into todays_overall_jobs.csv
later, after the parallel workingstudent fetch finishes).
"""
from __future__ import annotations

import glob
import os
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "old_files"))
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

import sub_program_files.stepstone_scraper as ss

OUTPUT_CSV = PROJECT_ROOT / "program_files" / "output" / "stepstone_fresh.csv"


def _newest_cached_driver() -> str:
    pattern = os.path.expanduser(r"~\.cache\selenium\chromedriver\win64\*\chromedriver.exe")
    candidates = sorted(glob.glob(pattern), key=os.path.getmtime)
    if not candidates:
        raise RuntimeError("no cached chromedriver found")
    return candidates[-1]


def main() -> None:
    driver_path = _newest_cached_driver()
    print(f"[STEPSTONE-FRESH] using cached driver: {driver_path}")

    original_init = webdriver.Chrome.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.pop("service", None)
        kwargs.pop("options", None)
        original_init(self, service=Service(executable_path=driver_path), **kwargs)

    webdriver.Chrome.__init__ = patched_init  # type: ignore[method-assign]

    try:
        jobs = ss.get_stepstone_jobs() or []
    except Exception as exc:  # noqa: BLE001 - report and stop this process
        print(f"[STEPSTONE-FRESH] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(jobs).to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"[STEPSTONE-FRESH] saved {len(jobs)} stepstone jobs -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
