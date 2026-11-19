"""Pipeline Runner for auto-application-workingstudent.

Orchestrates the complete working student job application pipeline:
  Stage 1: Fetch jobs ONLY from workingstudentjobs.de
  Stage 2: Filter for last 24 hours (or configurable rolling days)
  Stage 3: Deduplication check: drop already-applied jobs before screening!
  Stage 4: Test Ollama keys & run LLM screening (role type, German level <= A2, location, tech domain)
  Stage 5: JD analysis & resume tailoring (grounded in candidate KB, zero hallucination)
  Stage 6: LaTeX resume build & G1-G4 verification gates (1-page PDF + DOCX)
  Stage 7: Cover letter generation (Anschreiben DE/EN) & L1-L4 verification gates
  Stage 8: Interactive application dashboard generation
  Stage 9: Auto application dispatch (modular: dry-run validation by default, live submission when enabled)
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from . import applied_tracker, auto_applier, config, dashboard_generator, fetcher, recency_filter, screener
except ImportError:
    import applied_tracker, auto_applier, config, dashboard_generator, fetcher, recency_filter, screener

config.ensure_utf8_stdout()

# Engine modules
from engine import config as engine_config
from engine import run_step4, run_step5, run_step6
from steps import test_keys


def _stage(name: str, fn):
    """Run one stage, catching exceptions cleanly."""
    print(f"\n{'='*15} {name} {'='*15}")
    try:
        result = fn()
        return True, result
    except Exception as exc:
        print(f"[PIPELINE ERROR] {name} FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False, None


def run_workingstudent_pipeline(
    days: float = config.DEFAULT_POSTING_AGE_DAYS,
    pages: int = config.DEFAULT_MAX_PAGES,
    max_jobs: int | None = None,
    skip_fetch: bool = False,
    force: bool = False,
    force_letters: bool = False,
    auto_apply: bool = False,
) -> int:
    """Execute the complete workingstudent pipeline end-to-end."""
    config.ensure_dirs()
    print("=" * 60)
    print("WORKINGSTUDENT.DE AUTO APPLICATION PIPELINE")
    print(f"Target Window  : Last {days:g} day(s) ({int(days*24)} hours)")
    print(f"Source         : workingstudentjobs.de (Exclusive)")
    if max_jobs:
        print(f"Job Limit      : Processing at most {max_jobs} jobs")
    print(f"Auto-Apply Mode: {'LIVE SUBMISSION' if auto_apply else 'SAFE DRY-RUN / READY STAGING'}")
    print("=" * 60)

    # Stage 1: Fetch from workingstudentjobs.de ONLY
    if not skip_fetch:
        ok, _ = _stage(
            f"STAGE 1 | Fetch from workingstudentjobs.de (max {pages} pages)",
            lambda: fetcher.fetch_jobs(max_pages=pages, fetch_details=True),
        )
        if not ok:
            print("[PIPELINE] Fetch stage failed.")
            return 1
    else:
        print("\n=== STAGE 1 | Fetching skipped (--skip-fetch reused existing data) ===")

    # Stage 2: Filter for last 24 hours
    ok, filtered_df = _stage(
        f"STAGE 2 | Filter for last {days:g} day(s)",
        lambda: recency_filter.filter_jobs(days=days),
    )
    if not ok or filtered_df is None or filtered_df.empty:
        print(f"[PIPELINE] No fresh jobs found within the last {days:g} day(s).")
        return 0

    # Stage 3: Check whether we already applied or not
    def _check_applied():
        unapplied, already_applied = applied_tracker.filter_unapplied(filtered_df)
        unapplied_df = pd.DataFrame(unapplied)
        unapplied_df.to_csv(config.UNAPPLIED_CSV, index=False, encoding="utf-8-sig")
        return unapplied_df, already_applied

    ok, check_result = _stage("STAGE 3 | Check Already Applied Status (Deduplication)", _check_applied)
    if not ok:
        return 1
    unapplied_df, already_applied = check_result
    if unapplied_df.empty:
        print("[PIPELINE] All jobs in the current window have already been applied to! Nothing new to process.")
        return 0

    print(f"[PIPELINE] Continuing with {len(unapplied_df)} new unapplied jobs.")

    # Stage 4: Test Keys & LLM Screening
    ok, active_keys = _stage("STAGE 4a | Verify Ollama API Keys", test_keys.test_ollama_keys)
    if not ok or not active_keys:
        print(f"[PIPELINE] Warning: No active Ollama keys found in {config.KEYS_FILE}.")
        print("[PIPELINE] LLM screening will use deterministic keyword fallback.")

    ok, screened_df = _stage(
        "STAGE 4b | LLM Screening (Role Type, German <= A2, Location, Tech)",
        lambda: screener.screen_jobs(input_csv=config.UNAPPLIED_CSV, include_thesis=True),
    )

    # Register dropped jobs as fetched_only in tracker
    if config.SCREENING_REPORT_CSV.exists():
        try:
            rep_df = pd.read_csv(config.SCREENING_REPORT_CSV, keep_default_na=False)
            for _, r in rep_df.iterrows():
                if str(r.get("decision", "")).lower() == "drop":
                    applied_tracker.mark_fetched_only(
                        job_url=str(r.get("job_url", "")),
                        company=str(r.get("company", "")),
                        title=str(r.get("title", "")),
                        location=str(r.get("location", "")),
                        notes=f"Screening dropped: {r.get('reason', '')}",
                    )
        except Exception:
            pass

    if not ok or screened_df is None or screened_df.empty:
        print("[PIPELINE] No jobs passed screening criteria.")
        return 0

    target_urls = set(str(u) for u in screened_df["job_url"].dropna().tolist())
    print(f"[PIPELINE] {len(target_urls)} jobs passed screening and domain gating.")

    # Stage 5: JD Analysis & Resume Tailoring
    # Redirect engine input to our workingstudent screened CSV
    engine_config.FILTERED_JOBS_CSV = config.SCREENED_CSV
    ok, _ = _stage(
        "STAGE 5 | JD Analysis & Resume Tailoring (Knowledge Base Grounded)",
        lambda: run_step4.run_pipeline(limit=max_jobs, force=force, no_domain_filter=False),
    )
    if not ok:
        return 1

    # Stage 6: LaTeX Resume Build & Quality Gates (1-page PDF + DOCX)
    ok, _ = _stage(
        "STAGE 6 | Compile Resumes & Run Verification Gates (Tectonic)",
        lambda: run_step5.main(only_urls=target_urls),
    )
    if not ok:
        return 1

    # Stage 7: Cover Letter Generation & Gates
    ok, _ = _stage(
        "STAGE 7 | Generate & Verify Cover Letters (Anschreiben DE/EN)",
        lambda: run_step6.run_pipeline(force=force_letters, only_urls=target_urls),
    )
    if not ok:
        return 1

    # Stage 8: Interactive Dashboard
    ok, dash_path = _stage("STAGE 8 | Build Working Student Dashboard", dashboard_generator.build_dashboard)
    if ok:
        print(f"[PIPELINE] Dashboard ready: {dash_path}")

    # Stage 9: Auto Application Dispatch (Modular)
    def _run_applier():
        applier = auto_applier.AutoApplier(dry_run=not auto_apply)
        # Load resume and letter artifacts to assemble application packages
        packages = []
        for _, row in screened_df.iterrows():
            url = str(row.get("job_url") or "")
            # Find generated files
            res_pdf = ""
            let_pdf = ""
            let_txt = ""

            # Check engine resume report
            if engine_config.REPORT_PATH.exists():
                try:
                    import json
                    rep = json.loads(engine_config.REPORT_PATH.read_text(encoding="utf-8"))
                    for r in rep.get("results", []):
                        if r.get("job_url") == url:
                            res_pdf = r.get("pdf", "")
                            break
                except Exception:
                    pass

            # Check engine letters report
            if engine_config.LETTERS_REPORT_PATH.exists():
                try:
                    import json
                    lrep = json.loads(engine_config.LETTERS_REPORT_PATH.read_text(encoding="utf-8"))
                    for r in lrep.get("results", []):
                        if r.get("job_url") == url:
                            arts = r.get("artifacts") or {}
                            let_pdf = arts.get("letter_pdf", "")
                            txt_path = arts.get("textfield_txt", "")
                            if txt_path and Path(txt_path).exists():
                                let_txt = Path(txt_path).read_text(encoding="utf-8")
                            break
                except Exception:
                    pass

            pkg = applier.assemble_package(
                job_row=row.to_dict(),
                resume_pdf=res_pdf,
                letter_pdf=let_pdf,
                letter_text=let_txt,
            )
            res = applier.dispatch(pkg)
            packages.append((pkg, res))
        return packages

    ok, dispatch_res = _stage("STAGE 9 | Auto Application Process", _run_applier)

    # Print summary
    print("\n" + "=" * 60)
    print("PIPELINE EXECUTION SUMMARY")
    print("=" * 60)
    print(f"Working Student Jobs Screened: {len(screened_df)}")
    print(f"Target Application Packages   : {len(target_urls)}")
    print(f"Dashboard File               : {config.DASHBOARD_HTML}")
    print(f"Tracker Database             : {config.APPLIED_CSV}")
    print("=" * 60)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Working Student Auto Application Pipeline")
    parser.add_argument("--days", type=float, default=config.DEFAULT_POSTING_AGE_DAYS, help="Recency window in days (default: 1.0 = 24h)")
    parser.add_argument("--pages", type=int, default=config.DEFAULT_MAX_PAGES, help="Max listing pages to scrape (default: 6)")
    parser.add_argument("--max-jobs", type=int, default=None, help="Process at most N jobs (useful for testing)")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip web scraping and reuse existing fetched jobs")
    parser.add_argument("--force", action="store_true", help="Force regenerate resumes even if previously built")
    parser.add_argument("--force-letters", action="store_true", help="Force regenerate cover letters even if previously built")
    parser.add_argument("--auto-apply", action="store_true", help="Enable live auto-application (default is safe dry-run staging)")
    args = parser.parse_args(argv)

    return run_workingstudent_pipeline(
        days=args.days,
        pages=args.pages,
        max_jobs=args.max_jobs,
        skip_fetch=args.skip_fetch,
        force=args.force,
        force_letters=args.force_letters,
        auto_apply=args.auto_apply,
    )


if __name__ == "__main__":
    raise SystemExit(main())
