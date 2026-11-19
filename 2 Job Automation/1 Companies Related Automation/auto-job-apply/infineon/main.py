"""INFINEON pipeline — shared sequence across all company folders.

  1_INFINEON_Jobs_fetching.py   fetch jobs (writes INFINEON_results.csv / _detailed.csv / _full.json)
  2_INFINEON_language_filter.py language filter (rule-based, in-place on detailed CSV)
  resume creation               hub via ../resume_creation/run_resume_creation.py infineon
                                OR local via sub_program_files/run_local_resume.py
  infineon_job_apply.py         apply automation for ONE job (Playwright)

Run:
    python main.py                           # fetch -> filter -> hub resumes
    python main.py --local-resume            # fetch -> filter -> local resume generation
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
    for f in RESULTS_DIR.glob("*-result.json"):
        try:
            import json, re
            jid = f.name.split("-result")[0]
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("status") == "SUCCESS":
                submitted.add(str(data.get("job_id") or jid))
        except Exception:
            continue
    return submitted


def _resolve_eligible_job() -> tuple[str, Path] | tuple[None, None]:
    """Find the first ENGLISH_OK, unapplied job from INFINEON_jobs_detailed.csv and resolve its resume."""
    csv_path = PROJECT_ROOT / "INFINEON_jobs_detailed.csv"
    if not csv_path.exists():
        return None, None

    submitted = _submitted_job_ids()
    target_url = None
    target_job_id = None

    with csv_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("Language_Filter") == "ENGLISH_OK":
                jid = str(row.get("job_id") or "")
                if jid not in submitted:
                    target_url = row.get("apply_url") or f"https://jobs.infineon.com/careers/apply?pid={jid}"
                    target_job_id = jid
                    break

    if not target_url:
        return None, None

    # Resolve resume
    resume_candidates = [
        PROJECT_ROOT / "sub_program_files" / "output" / "job_resume_map_local.csv",
        PROJECT_ROOT.parent.parent / "resume_creation" / "program_files" / "output_v2" / "state" / "job_resume_map_infineon.csv",
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
    parser = argparse.ArgumentParser(description="INFINEON pipeline: fetch -> filter -> resumes -> apply")
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
    parser.add_argument("--submit", action="store_true", help="live submission to Infineon Eightfold portal")
    parser.add_argument("--headless", action="store_true", help="run Playwright in headless mode")
    args = parser.parse_args()

    # Step 1: Fetch
    if not args.skip_fetch:
        print("== STEP 1 | fetch jobs ==")
        fetch_cmd = [sys.executable, str(PROJECT_ROOT / "1_INFINEON_Jobs_fetching.py")]
        if args.limit:
            fetch_cmd += ["--limit", str(args.limit)]
        if subprocess.run(fetch_cmd).returncode != 0:
            return 1
    else:
        print("== STEP 1 | skipped fetch ==")

    # Step 2: Language Filter
    if not args.skip_filter:
        print("\n== STEP 2 | language filter ==")
        if subprocess.run([sys.executable, str(PROJECT_ROOT / "2_INFINEON_language_filter.py")]).returncode != 0:
            return 1
    else:
        print("\n== STEP 2 | skipped filter ==")

    # Step 3: Resumes
    if not args.skip_resume:
        if args.local_resume or not HUB_RUNNER.exists():
            print("\n== STEP 3 | local resume generation (sub_program_files/) ==")
            if args.build_only:
                builder = PROJECT_ROOT / "sub_program_files" / "resume_content" / "5_create_resume.py"
                if subprocess.run([sys.executable, str(builder)]).returncode != 0:
                    return 1
            else:
                if subprocess.run([sys.executable, str(LOCAL_RUNNER)]).returncode != 0:
                    return 1
        else:
            print("\n== STEP 3 | resume creation (hub: resume_creation/) ==")
            cmd = [sys.executable, str(HUB_RUNNER), "infineon"]
            if args.limit:
                cmd += ["--limit", str(args.limit)]
            if args.force:
                cmd.append("--force")
            if subprocess.run(cmd).returncode != 0:
                print("\n[main] Hub failed or unavailable. Falling back to local resume generator...")
                if subprocess.run([sys.executable, str(LOCAL_RUNNER)]).returncode != 0:
                    return 1
    else:
        print("\n== STEP 3 | skipped resume creation ==")

    # Step 4: Apply
    if args.apply:
        print("\n== STEP 4 | job application ==")
        target_url = args.url
        target_resume = Path(args.resume) if args.resume else None

        if not target_url:
            resolved_url, resolved_pdf = _resolve_eligible_job()
            if not resolved_url:
                print("ERROR: Could not auto-resolve an eligible unapplied ENGLISH_OK job.")
                return 1
            target_url = resolved_url
            if not target_resume:
                target_resume = resolved_pdf
            print(f"[main] Auto-resolved eligible job: {target_url}")
            print(f"[main] Resume: {target_resume}")

        apply_mod = _import_step("infineon_job_apply", "apply_to_infineon_job")
        dry_run = not args.submit
        res = apply_mod(
            job_url=target_url,
            resume_path=target_resume,
            dry_run=dry_run,
            headless=args.headless,
        )
        print(f"\n[main] Apply result status: {res.get('status')}")
        return 0 if res.get("status") in {"SUCCESS", "DRY_RUN"} else 1

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
