"""INFINEON pipeline — shared sequence across all company folders.

  1_INFINEON_Jobs_fetching.py   fetch jobs (writes INFINEON_results.csv / _detailed.csv / _full.json)
  2_INFINEON_language_filter.py language filter (rule-based, in-place on the detailed CSV)
  resume_creation (hub)         resume generation via ../resume_creation/run_resume_creation.py infineon
  infineon_job_apply.py         apply automation for ONE job (Playwright)

Steps 1-3 are identical in every folder; only the apply stage differs
(bmw/simense/bwi/airbus/simense_energy have no apply automation yet).

Run:
    python main.py --limit 2     # fetch -> filter -> hub resumes (first 2 jobs)
    python main.py --apply --url <job-url> [--resume path.pdf] [--dry-run|--submit]
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
HUB_RUNNER = PROJECT_ROOT.parent / "resume_creation" / "run_resume_creation.py"


def _import_step(module: str, func: str = "main"):
    spec = importlib.util.spec_from_file_location(module, PROJECT_ROOT / f"{module}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, func)


def main() -> int:
    parser = argparse.ArgumentParser(description="INFINEON pipeline: fetch -> filter -> hub resumes -> apply")
    parser.add_argument("--limit", type=int, default=None, help="first N jobs for the hub resume stage")
    parser.add_argument("--force", action="store_true", help="re-run gated_ok jobs in the hub")
    parser.add_argument("--apply", action="store_true", help="run single-job apply after the hub stage")
    parser.add_argument("--url", default=None, help="job posting URL for --apply")
    parser.add_argument("--resume", default=None, help="resume PDF override for --apply")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    print("== STEP 1 | fetch jobs ==")
    if subprocess.run([sys.executable, str(PROJECT_ROOT / "1_INFINEON_Jobs_fetching.py")]).returncode != 0:
        return 1
    print("\n== STEP 2 | language filter ==")
    if subprocess.run([sys.executable, str(PROJECT_ROOT / "2_INFINEON_language_filter.py")]).returncode != 0:
        return 1
    print("\n== STEP 3 | resume creation (hub: resume_creation/) ==")
    cmd = [sys.executable, str(HUB_RUNNER), "infineon"]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.force:
        cmd.append("--force")
    if subprocess.run(cmd).returncode != 0:
        return 1

    if args.apply:
        print("\n== STEP 4 | job application ==")
        argv = []
        if args.url:
            argv += ["--url", args.url]
        if args.resume:
            argv += ["--resume", args.resume]
        if args.submit:
            argv.append("--submit")
        elif args.dry_run:
            argv.append("--dry-run")
        if args.headless:
            argv.append("--headless")
        sys.argv = ["apply"] + argv
        return _import_step("infineon_job_apply")()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
