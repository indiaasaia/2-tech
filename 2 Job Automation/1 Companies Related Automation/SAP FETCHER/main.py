"""SAP pipeline — shared sequence across all company folders.

  1_sap_job_fetcher.py      fetch jobs (writes sap_results.csv)
  2_language_filter.py      language filter (rule-based, in-place on sap_results.csv)
  resume creation           hub via ../resume_creation/run_resume_creation.py sap
                            OR local via sub_program_files/run_local_resume.py
  sap_job_apply.py          apply automation for ONE job or batch (SuccessFactors)

Run:
    python main.py                           # fetch -> filter -> hub resumes
    python main.py --local-resume            # fetch -> filter -> local resume generation
    python main.py --build-only              # rebuild resumes from saved state (no LLM calls)
    python main.py --apply --dry-run         # full pipeline + dry-run apply to first eligible job
    python main.py --apply --url <job-url>   # apply to a specific job posting
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
HUB_CANDIDATES = [
    PROJECT_ROOT.parent / "resume_creation" / "run_resume_creation.py",
    PROJECT_ROOT.parent.parent / "resume_creation" / "run_resume_creation.py",
    Path(r"E:\WorkSpace\2 Tech\2 Job Automation\Companies Related Automation\resume_creation\run_resume_creation.py"),
]
HUB_RUNNER = next((p for p in HUB_CANDIDATES if p.exists() and p.is_file()), HUB_CANDIDATES[0])
LOCAL_RUNNER = PROJECT_ROOT / "sub_program_files" / "run_local_resume.py"
RESULTS_DIR = PROJECT_ROOT / "results"
BASE_CV = Path(r"E:\WorkSpace\2 Tech\1 Cold Emailing\Cold Emaling\RAVAL_MEETKUMAR_RESUME.pdf")


def _import_step(module: str, func: str = "main"):
    spec = importlib.util.spec_from_file_location(module, PROJECT_ROOT / f"{module}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, func)


def _submitted_job_ids() -> set[str]:
    submitted = set()
    for f in RESULTS_DIR.glob("sap-*-result.json"):
        try:
            import json, re
            match = re.search(r"sap-(\d+)", f.name)
            if match and json.loads(f.read_text(encoding="utf-8")).get("status") == "SUCCESS":
                submitted.add(match.group(1))
        except Exception:
            continue
    return submitted


def _resolve_eligible_job() -> tuple[str, Path] | tuple[None, None]:
    """Find the first ENGLISH_OK, unapplied job from sap_results.csv and resolve its resume."""
    csv_path = PROJECT_ROOT / "sap_results.csv"
    if not csv_path.exists():
        return None, None

    submitted = _submitted_job_ids()
    target_url = None
    target_job_id = None

    with csv_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("Language_Filter") == "ENGLISH_OK":
                jid = str(row.get("Job ID") or "")
                if jid not in submitted:
                    target_url = row.get("Link")
                    target_job_id = jid
                    break

    if not target_url:
        return None, None

    # Resolve resume
    resume_candidates = [
        PROJECT_ROOT.parent / "resume_creation" / "program_files" / "output_v2" / "state" / "job_resume_map_sap.csv",
        PROJECT_ROOT / "sub_program_files" / "output" / "job_resume_map_local.csv",
    ]
    for map_file in resume_candidates:
        if map_file.exists():
            with map_file.open(encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if (target_job_id in r.get("job_url", "") or target_url == r.get("job_url", "")) and r.get("resume_pdf"):
                        p = Path(r["resume_pdf"])
                        if p.is_file():
                            return target_url, p

    return target_url, BASE_CV if BASE_CV.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser(description="SAP pipeline: fetch -> filter -> resumes -> apply")
    parser.add_argument("--limit", type=int, default=None, help="first N jobs for resume generation")
    parser.add_argument("--force", action="store_true", help="force rebuild/regenerate resumes")
    parser.add_argument("--build-only", action="store_true", help="rebuild pdfs from saved state without LLM calls")
    parser.add_argument("--local-resume", action="store_true", help="use self-contained sub_program_files resume generator")
    parser.add_argument("--skip-fetch", action="store_true", help="skip Step 1 fetch")
    parser.add_argument("--skip-filter", action="store_true", help="skip Step 2 language filter")
    parser.add_argument("--skip-resume", action="store_true", help="skip Step 3 resume creation")
    parser.add_argument("--apply", action="store_true", help="run apply stage after resume stage")
    parser.add_argument("--url", default=None, help="job posting URL for --apply")
    parser.add_argument("--resume", default=None, help="resume PDF override for --apply")
    parser.add_argument("--dry-run", action="store_true", help="dry-run application without submitting")
    parser.add_argument("--submit", action="store_true", help="live submission to SAP SuccessFactors")
    parser.add_argument("--headless", action="store_true", help="run Playwright in headless mode")
    args = parser.parse_args()

    # Step 1: Job Fetcher
    if not args.skip_fetch:
        print("== STEP 1 | fetch jobs ==")
        if subprocess.run([sys.executable, str(PROJECT_ROOT / "1_sap_job_fetcher.py")]).returncode != 0:
            return 1
    else:
        print("== STEP 1 | skipped fetch ==")

    # Step 2: Language Filter
    if not args.skip_filter:
        print("\n== STEP 2 | language filter ==")
        if subprocess.run([sys.executable, str(PROJECT_ROOT / "2_language_filter.py")]).returncode != 0:
            return 1
    else:
        print("\n== STEP 2 | skipped filter ==")

    # Step 3: Resume Creation
    if not args.skip_resume:
        print("\n== STEP 3 | resume creation ==")
        if args.local_resume or not HUB_RUNNER.exists():
            print("Running local resume pipeline (sub_program_files)...")
            if subprocess.run([sys.executable, str(LOCAL_RUNNER)]).returncode != 0:
                return 1
        else:
            print("Running shared hub resume creation (resume_creation/)...")
            cmd = [sys.executable, str(HUB_RUNNER), "sap"]
            if args.limit:
                cmd += ["--limit", str(args.limit)]
            if args.force:
                cmd.append("--force")
            if args.build_only:
                cmd.append("--build-only")
            res = subprocess.run(cmd)
            if res.returncode != 0:
                print("Hub runner returned non-zero. Falling back to local resume pipeline...")
                if subprocess.run([sys.executable, str(LOCAL_RUNNER)]).returncode != 0:
                    return 1

    # Step 4: Job Apply Automation
    if args.apply:
        print("\n== STEP 4 | job application ==")
        url = args.url
        resume = args.resume

        if not url:
            resolved_url, resolved_resume = _resolve_eligible_job()
            if resolved_url:
                url = resolved_url
                if not resume and resolved_resume:
                    resume = str(resolved_resume)
                print(f"[main] Auto-resolved eligible job: {url}\n[main] Resume: {resume}")
            else:
                print("[main] No unapplied ENGLISH_OK jobs found in sap_results.csv")

        argv = []
        if url:
            argv += ["--url", url]
        if resume:
            argv += ["--resume", resume]
        if args.submit:
            argv.append("--submit")
        elif args.dry_run:
            argv.append("--dry-run")
        if args.headless:
            argv.append("--headless")

        sys.argv = ["apply"] + argv
        return _import_step("sap_job_apply")()

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
