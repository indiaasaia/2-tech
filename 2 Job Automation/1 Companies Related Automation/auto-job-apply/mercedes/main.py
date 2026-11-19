"""MERCEDES pipeline — unified runner for Mercedes-Benz Tech Innovation & Group.

Stages:
  1. 1_MERCEDES_Jobs_fetching.py   Fetch jobs from Workday + Taleo
  2. 2_MERCEDES_language_filter.py Language filter (rule-based)
  3. sub_program_files/            Local resume generation (Tectonic PDFs)
  4. mercedes_job_apply.py         Workday autonomous application engine

Usage:
  python main.py                                      # Steps 1 to 3 (fetch, filter, resumes)
  python main.py --apply --dry-run                    # Full pipeline with dry-run apply
  python main.py --skip-fetch --apply --dry-run       # Use existing jobs + apply
  python main.py --apply --url <job_url> --dry-run    # Apply to specific job
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _pick_first_workday_job() -> tuple[str, str] | None:
    """Find the first unapplied Workday job and its tailored resume."""
    local_map = ROOT / "sub_program_files" / "output" / "job_resume_map_local.csv"
    if local_map.exists():
        with open(local_map, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                url = row.get("job_url", "")
                pdf = row.get("resume_pdf", "")
                if "myworkdayjobs.com" in url and Path(pdf).exists():
                    return url, pdf
    detailed_csv = ROOT / "MERCEDES_jobs_detailed.csv"
    if detailed_csv.exists():
        with open(detailed_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("portal") == "workday" or "myworkdayjobs.com" in row.get("link", ""):
                    return row.get("link", ""), ""
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="MERCEDES pipeline: fetch -> filter -> resumes -> apply")
    parser.add_argument("--skip-fetch", action="store_true", help="skip Step 1 fetch")
    parser.add_argument("--skip-filter", action="store_true", help="skip Step 2 language filter")
    parser.add_argument("--skip-resume", action="store_true", help="skip Step 3 resume creation")
    parser.add_argument("--apply", action="store_true", help="run apply stage after resume stage")
    parser.add_argument("--url", default=None, help="job posting URL for --apply")
    parser.add_argument("--resume", default=None, help="resume PDF override for --apply")
    parser.add_argument("--dry-run", action="store_true", default=True, help="dry-run application without submitting")
    parser.add_argument("--submit", action="store_true", help="live submission to Workday portal")
    parser.add_argument("--headless", action="store_true", help="run Playwright in headless mode")
    args = parser.parse_args()

    # Step 1: Fetch
    if not args.skip_fetch:
        print("\n== STEP 1 | fetch Mercedes jobs ==")
        res = subprocess.run([sys.executable, str(ROOT / "1_MERCEDES_Jobs_fetching.py")], check=False)
        if res.returncode != 0:
            print("ERROR: Step 1 failed.")
            return res.returncode

    # Step 2: Language Filter
    if not args.skip_filter:
        print("\n== STEP 2 | language filter ==")
        res = subprocess.run([sys.executable, str(ROOT / "2_MERCEDES_language_filter.py")], check=False)
        if res.returncode != 0:
            print("ERROR: Step 2 failed.")
            return res.returncode

    # Step 3: Local Resume Engine
    if not args.skip_resume:
        print("\n== STEP 3 | local resume generation ==")
        runner = ROOT / "sub_program_files" / "run_local_resume.py"
        res = subprocess.run([sys.executable, str(runner)], check=False)
        if res.returncode != 0:
            print("ERROR: Step 3 failed.")
            return res.returncode

    # Step 4: Apply
    if args.apply:
        print("\n== STEP 4 | Workday job application ==")
        target_url = args.url
        target_resume = args.resume

        if not target_url:
            picked = _pick_first_workday_job()
            if picked:
                target_url, default_resume = picked
                if not target_resume:
                    target_resume = default_resume
                print(f"Auto-selected Workday job: {target_url}")
            else:
                print("ERROR: No eligible Workday job found in dataset.")
                return 1

        apply_cmd = [sys.executable, str(ROOT / "mercedes_job_apply.py"), "--url", target_url]
        if target_resume:
            apply_cmd += ["--resume", target_resume]
        if args.submit:
            apply_cmd.append("--submit")
        else:
            apply_cmd.append("--dry-run")
        if args.headless:
            apply_cmd.append("--headless")

        res = subprocess.run(apply_cmd, check=False)
        return res.returncode

    print("\nPipeline finished successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
