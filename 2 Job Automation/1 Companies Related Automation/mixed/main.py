"""Central Orchestrator for the Mixed Job Automation Ecosystem.

Runs the complete lifecycle for any registered company:
  1. Fetch & Language Filter (job_fetcher/<company>.py)
  2. Tailored ATS Resumes + DIN 5008 Cover Letters + Bundles (resume_and_cover_letter/run_hub.py)
  3. Automated Application (auto_apply/<company>_apply.py) - if supported

Usage:
  python main.py --list
  python main.py <company> [--limit N] [--dry-run | --submit] [--skip-fetch] [--skip-resume] [--skip-apply]

Examples:
  python main.py bosch --limit 2 --dry-run
  python main.py bmw --limit 2             (runs fetch + resume/cover letter; reports no auto-applier)
  python main.py mercedes --submit
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from job_fetcher.registry import get_fetcher, has_fetcher, list_fetchers
from auto_apply.registry import get_applier, has_applier, list_appliers
from resume_and_cover_letter.run_hub import run_hub


def print_status_table():
    fetchers = list_fetchers()
    appliers = list_appliers()

    all_companies = sorted(set(list(fetchers.keys()) + list(appliers.keys())))
    print("\n" + "=" * 80)
    print("MIXED JOB AUTOMATION ECOSYSTEM - REGISTERED COMPANIES")
    print("=" * 80)
    print(f"{'Company ID':<18} | {'Display Name':<22} | {'Portal':<20} | {'Auto-Apply'}")
    print("-" * 80)
    for cid in all_companies:
        f_info = fetchers.get(cid, {})
        dname = f_info.get("display_name", cid.capitalize())
        portal = f_info.get("portal_type", "Unknown")
        can_apply = "✅ YES" if has_applier(cid) else "❌ NO (Fetch & Resumes only)"
        print(f"{cid:<18} | {dname:<22} | {portal:<20} | {can_apply}")
    print("=" * 80 + "\n")


def run_pipeline(
    company: str,
    limit: int | None = None,
    jobs_filter: str | None = None,
    dry_run: bool = True,
    submit: bool = False,
    skip_fetch: bool = False,
    skip_resume: bool = False,
    skip_apply: bool = False,
    force: bool = False,
    force_letters: bool = False,
    build_only: bool = False,
    headless: bool = False,
) -> int:
    started_all = time.time()
    company_id = company.lower().replace("-", "_").replace(" ", "_")

    if not has_fetcher(company_id):
        available = ", ".join(sorted(list_fetchers().keys()))
        print(f"Error: Unknown company '{company}'. Available companies: {available}")
        return 1

    display_name = getattr(type(get_fetcher(company_id)), "display_name", company_id)
    print("\n" + "#" * 80)
    print(f"# RUNNING PIPELINE FOR: {display_name} ({company_id})")
    print(f"# Auto-Apply capability: {'YES' if has_applier(company_id) else 'NO (Fetch & Documents only)'}")
    print("#" * 80 + "\n")

    # -------------------------------------------------------------
    # STAGE 1: Job Fetching & Language Filter
    # -------------------------------------------------------------
    if not skip_fetch:
        print(f"== STAGE 1 | Fetching jobs & filtering language for {company_id} ==")
        fetcher = get_fetcher(company_id)
        fetched_jobs = fetcher.fetch_jobs(force=force, limit=limit)
        en_ok = sum(1 for j in fetched_jobs if j.language_filter == "ENGLISH_OK")
        print(f"[Stage 1 Done] Total: {len(fetched_jobs)} | English OK: {en_ok}")
        if not fetched_jobs:
            print("[Stage 1] No jobs found to process. Exiting.")
            return 0
    else:
        print(f"[Stage 1] Skipped (--skip-fetch)")

    # -------------------------------------------------------------
    # STAGE 2: Resume & Cover Letter Hub (Steps 4 + 5 + 6)
    # -------------------------------------------------------------
    if not skip_resume:
        print(f"\n== STAGE 2 | Generating tailored Resumes & Cover Letters for {company_id} ==")
        hub_rc = run_hub(
            company=company_id,
            limit=limit,
            jobs=jobs_filter,
            force=force,
            force_letters=force_letters,
            build_only=build_only,
        )
        if hub_rc != 0:
            print(f"[Stage 2 Warning] Hub finished with non-zero exit code: {hub_rc}")
    else:
        print(f"[Stage 2] Skipped (--skip-resume)")

    # -------------------------------------------------------------
    # STAGE 3: Auto-Application
    # -------------------------------------------------------------
    if not skip_apply:
        print(f"\n== STAGE 3 | Auto-Apply for {company_id} ==")
        if not has_applier(company_id):
            print(f"ℹ️  Company '{company_id}' does not have an auto-apply bot registered yet.")
            print(f"   Fetch, tailored ATS resumes, and DIN 5008 cover letters completed successfully!")
            print(f"   Verified documents ready for manual upload at:")
            print(f"     - Resumes:      mixed/resume_and_cover_letter/program_files/output_v2/resume_{company_id}/")
            print(f"     - Cover Letters: mixed/resume_and_cover_letter/program_files/output_v2/letters_{company_id}/")
            print(f"     - Map Manifest: mixed/resume_and_cover_letter/program_files/output_v2/state/job_bundle_map_{company_id}.csv")
            return 0

        applier = get_applier(company_id)
        mode_dry_run = not submit
        print(f"[Stage 3] Driving auto-apply bot ({'DRY-RUN' if mode_dry_run else 'REAL SUBMIT'})")

        results = applier.apply_batch(
            limit=limit,
            dry_run=mode_dry_run,
            headless=headless,
            jobs_filter=jobs_filter,
        )

        print("\n" + "-" * 50)
        print(f"STAGE 3 APPLICATION SUMMARY ({company_id}):")
        for res in results:
            print(f"  [{res.status:<14}] {res.job_url}")
            if res.errors:
                print(f"      Errors: {res.errors}")
        print("-" * 50)
    else:
        print(f"[Stage 3] Skipped (--skip-apply)")

    total_time = time.time() - started_all
    print(f"\n[DONE] Pipeline finished for {company_id} in {total_time:.1f}s\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Unified Job Automation Ecosystem (Fetch -> Resumes + Cover Letters -> Auto-Apply)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("company", nargs="?", default=None, help="Company ID (e.g. bosch, mercedes, infineon, sap, bmw, siemens...)")
    parser.add_argument("--list", action="store_true", help="List all supported companies and capabilities")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N jobs")
    parser.add_argument("--jobs", type=str, default=None, help="Job URL substring filter")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run application in dry-run mode (default)")
    parser.add_argument("--submit", action="store_true", help="Truly submit applications")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip job fetching stage")
    parser.add_argument("--skip-resume", action="store_true", help="Skip resume and cover letter creation")
    parser.add_argument("--skip-apply", action="store_true", help="Skip application stage")
    parser.add_argument("--force", action="store_true", help="Force re-fetch / re-generation of components")
    parser.add_argument("--force-letters", action="store_true", help="Force re-generation of cover letters")
    parser.add_argument("--build-only", action="store_true", help="Rebuild PDFs/DOCX from saved components without LLM calls")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")

    args = parser.parse_args(argv)

    if args.list or not args.company:
        print_status_table()
        if not args.company:
            print("Specify a company ID to run the full pipeline. Example: python main.py bosch --limit 2")
            return 0

    return run_pipeline(
        company=args.company,
        limit=args.limit,
        jobs_filter=args.jobs,
        dry_run=not args.submit,
        submit=args.submit,
        skip_fetch=args.skip_fetch,
        skip_resume=args.skip_resume,
        skip_apply=args.skip_apply,
        force=args.force,
        force_letters=args.force_letters,
        build_only=args.build_only,
        headless=args.headless,
    )


if __name__ == "__main__":
    sys.exit(main())
