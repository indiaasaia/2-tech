"""AIRBUS pipeline — shared sequence across all company folders.

  1_AIRBUS_jobs_fetching.py   fetch jobs (writes AIRBUS_results.csv / AIRBUS_jobs_full.json)
  2_language_filter.py        language filter (rule-based, in-place on AIRBUS_results.csv)
  resume_creation (hub)       resume generation via ../resume_creation/run_resume_creation.py airbus

Steps 1-3 are identical in every folder; this folder has NO apply automation yet
(bosch/mercedes/infineon/sap do).

Run:
    python main.py --limit 2     # fetch -> filter -> hub resumes (first 2 jobs)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
HUB_RUNNER = PROJECT_ROOT.parent / "resume_creation" / "run_resume_creation.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="AIRBUS pipeline: fetch -> filter -> hub resumes (no apply yet)")
    parser.add_argument("--limit", type=int, default=None, help="first N jobs for the hub resume stage")
    parser.add_argument("--force", action="store_true", help="re-run gated_ok jobs in the hub")
    args = parser.parse_args()

    print("== STEP 1 | fetch jobs ==")
    if subprocess.run([sys.executable, str(PROJECT_ROOT / "1_AIRBUS_jobs_fetching.py")]).returncode != 0:
        return 1
    print("\n== STEP 2 | language filter ==")
    if subprocess.run([sys.executable, str(PROJECT_ROOT / "2_language_filter.py")]).returncode != 0:
        return 1
    print("\n== STEP 3 | resume creation (hub: resume_creation/) ==")
    cmd = [sys.executable, str(HUB_RUNNER), "airbus"]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.force:
        cmd.append("--force")
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
