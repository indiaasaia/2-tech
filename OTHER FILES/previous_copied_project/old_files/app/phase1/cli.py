"""Run Phase 1: fetch Stepstone + workingstudentjobs.de and save CSV files."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from app.core import config
from app.core import activity
from app.phase1 import combine, stepstone_fetcher, workingstudent_fetcher
from app.phase2 import resume_generator as phase2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JOB_AUTOMATION Phase 1 job fetcher")
    parser.add_argument("--source", choices=("both", "stepstone", "workingstudent"), default="both")
    parser.add_argument("--stepstone-pages", type=int, default=config.STEPSTONE_MAX_PAGES)
    parser.add_argument("--workingstudent-pages", type=int, default=config.WSJ_MAX_PAGES)
    parser.add_argument("--no-details", action="store_true", help="Only fetch listing pages")
    parser.add_argument("--headed", action="store_true", help="Show the Stepstone browser")
    parser.add_argument("--phase2", action="store_true", help="Generate Phase 2 resumes after fetching")
    parser.add_argument("--phase2-limit", type=int, default=None, help="Process only the first N jobs in Phase 2")
    parser.add_argument("--no-pdf", action="store_true", help="Do not compile Phase 2 LaTeX files to PDF")
    args = parser.parse_args(argv)
    if args.stepstone_pages < 1 or args.workingstudent_pages < 1:
        parser.error("page limits must be at least 1")
    if args.phase2_limit is not None and args.phase2_limit < 1:
        parser.error("--phase2-limit must be at least 1")

    stepstone = None
    workingstudent = None
    errors: list[str] = []
    if args.source in ("both", "stepstone"):
        activity.log_event("phase1", "fetch_start", "fetching stepstone listings", source="stepstone", pages=args.stepstone_pages, details=not args.no_details)
        try:
            stepstone = stepstone_fetcher.fetch(
                max_pages=args.stepstone_pages,
                fetch_details=not args.no_details,
                headless=not args.headed,
            )
            activity.log_event("phase1", "fetch_done", f"stepstone returned {len(stepstone)} jobs", source="stepstone", rows=len(stepstone))
        except Exception as exc:
            errors.append(f"stepstone: {type(exc).__name__}: {exc}")
            activity.log_event("phase1", "fetch_done", errors[-1], status="error", source="stepstone")
            print(f"[ERROR] {errors[-1]}")
    if args.source in ("both", "workingstudent"):
        activity.log_event("phase1", "fetch_start", "fetching workingstudentjobs.de listings", source="workingstudentjobs.de", pages=args.workingstudent_pages, details=not args.no_details)
        try:
            workingstudent = workingstudent_fetcher.fetch(
                max_pages=args.workingstudent_pages,
                fetch_details=not args.no_details,
            )
            activity.log_event("phase1", "fetch_done", f"workingstudentjobs.de returned {len(workingstudent)} jobs", source="workingstudentjobs.de", rows=len(workingstudent))
        except Exception as exc:
            errors.append(f"workingstudentjobs.de: {type(exc).__name__}: {exc}")
            activity.log_event("phase1", "fetch_done", errors[-1], status="error", source="workingstudentjobs.de")
            print(f"[ERROR] {errors[-1]}")

    if stepstone is None and workingstudent is None:
        activity.log_event("phase1", "combine", "no source produced a dataset", status="error")
        print("[ERROR] no source produced a dataset")
        return 1

    combined = combine.combine(*(frame for frame in (stepstone, workingstudent) if frame is not None))
    combine.save(combined)
    activity.log_event("phase1", "combine", f"combined {len(combined)} unique jobs after dedup", rows=len(combined))
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": 1,
        "sources_requested": args.source,
        "details_requested": not args.no_details,
        "max_posting_age_days": config.MAX_POSTING_AGE_DAYS,
        "stepstone_rows": int(len(stepstone)) if stepstone is not None else 0,
        "workingstudent_rows": int(len(workingstudent)) if workingstudent is not None else 0,
        "combined_rows": int(len(combined)),
        "errors": errors,
        "stepstone_csv": str(config.STEPSTONE_CSV),
        "workingstudent_csv": str(config.WORKINGSTUDENT_CSV),
        "combined_csv": str(config.COMBINED_CSV),
    }
    config.REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.phase2:
        phase2_results = phase2.run_phase2(limit=args.phase2_limit, compile_pdf=not args.no_pdf)
        report["phase2_jobs_processed"] = len(phase2_results)
        config.REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
