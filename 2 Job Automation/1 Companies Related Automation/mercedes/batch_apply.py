"""batch_apply.py -- apply to the targeted Mercedes jobs with their own resumes.

Reads the pipeline outputs (2_filted_jobs.csv + job_resume_map.csv), takes the
first N unique-role jobs, and routes each posting to the right portal
automation:

    tas-DAIMLER.taleo.net  -> 5_apply_taleo.apply_to_taleo_job
    *.myworkdayjobs.com    -> 4_MERCEDES_job_apply.apply_to_mercedes_job

Per job it runs the DRY-RUN first; only jobs whose dry-run ended in
DRY_RUN_COMPLETE / DRY_RUN are considered safe to really submit (and only
when --submit was passed; every real submission additionally asks for a
typed YES inside the automation scripts).

Results: results/batch_apply_report.json + console table.

Usage:
    python batch_apply.py --dry-run                # walk every job, submit nothing
    python batch_apply.py --submit                 # dry-run, then submit the safe ones
    python batch_apply.py --limit 5 --submit
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
HUB_STATE = PROJECT_DIR.parent / "resume_creation" / "program_files" / "output_v2" / "state"
ADAPTED_CSV = PROJECT_DIR / "MERCEDES_jobs_detailed.csv"
MAP_CSV = HUB_STATE / "job_resume_map_mercedes.csv"


def _load_module(file_name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PROJECT_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESULTS_DIR = PROJECT_DIR / "results"
TIER_ORDER = {"strong": 0, "good": 1, "weak": 2, "poor": 3}
MAX_ATTEMPTS = 23          # per-job retry budget requested by the user
ATTEMPT_BACKOFF_S = 10     # pause between attempts
# Deterministic blockers: retrying cannot change the outcome, so stop after the
# first attempt and record the reason (retries are only for transient failures
# like timeouts, page-load glitches, or portal hiccups).
NON_RETRYABLE = {"NEEDS_CREDENTIALS", "NEEDS_ATTENTION", "LOGIN_REQUIRED",
                 "SKIPPED_NO_AUTOMATION", "NOT_FOUND"}


def load_targets(limit: int | None) -> list[dict]:
    """Unique-role jobs with a resume map entry, ordered strong -> good -> weak ->
    poor (tier from the hub shortlist.json, best score first within a tier)."""
    import pandas as pd

    jobs = pd.read_csv(ADAPTED_CSV, keep_default_na=False)
    resume_map = pd.read_csv(MAP_CSV, keep_default_na=False)
    resume_by_url = {str(r["job_url"]): r for _, r in resume_map.iterrows()}

    shortlist_path = HUB_STATE.parent / "shortlist.json"
    tiers: dict[str, tuple[str, float]] = {}
    if shortlist_path.exists():
        try:
            shortlist = json.loads(shortlist_path.read_text(encoding="utf-8"))
            for entry in shortlist.get("jobs", []):
                url = str(entry.get("job_url") or "")
                if url:
                    tiers[url] = (str(entry.get("tier") or "poor"), float(entry.get("score") or 0))
        except (json.JSONDecodeError, OSError):
            pass

    targets: list[dict] = []
    seen_titles: set[str] = set()
    for _, job in jobs.iterrows():
        title_key = str(job["title"]).strip().lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        url = str(job.get("job_url") or job.get("link") or "")
        map_row = resume_by_url.get(url)
        if map_row is None or str(map_row["status"]) != "OK":
            continue
        # Resolve the REAL apply URL: most jobs.mercedes-benz.com postings route
        # to Taleo, whose URL lives in custom_fields.apply_url. Without this the
        # Workday bot gets a careers-site link it cannot resolve (no R-id).
        apply_url = str(job.get("apply_url") or url)
        raw = str(job.get("custom_fields") or "")
        if raw:
            try:
                cf = json.loads(raw)
                cf_apply = str(cf.get("apply_url") or "")
                if cf_apply:
                    apply_url = cf_apply
            except json.JSONDecodeError:
                pass
        targets.append({
            "title": str(job["title"]),
            "job_url": url,
            "apply_url": apply_url,
            "resume_pdf": str(map_row["resume_pdf"]),
            "tier": tiers.get(url, ("poor", 0.0))[0],
            "score": tiers.get(url, ("poor", 0.0))[1],
        })
        if limit is not None and len(targets) >= limit:
            break
    targets.sort(key=lambda t: (TIER_ORDER.get(t["tier"], 9), -t["score"]))
    return targets


def classify(apply_url: str) -> str:
    if "taleo.net" in apply_url:
        return "taleo"
    if "myworkdayjobs.com" in apply_url or "jobs.mercedes-benz.com" in apply_url:
        return "workday"  # careers-site links resolve via the portal's search list
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-apply Mercedes jobs with per-job resumes.")
    parser.add_argument("--limit", type=int, default=None, help="first N unique-role jobs")
    parser.add_argument("--dry-run", action="store_true", help="dry-run every job, submit nothing")
    parser.add_argument("--submit", action="store_true",
                        help="dry-run first, then really submit the safe ones (each asks YES)")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.submit:
        parser.error("choose --dry-run or --submit")

    targets = load_targets(args.limit)
    print(f"[BATCH] {len(targets)} unique-role job(s) targeted")
    taleo = _load_module("5_apply_taleo.py", "apply_taleo")
    workday = _load_module("4_MERCEDES_job_apply.py", "apply_mercedes")

    report: list[dict] = []
    for index, target in enumerate(targets, 1):
        portal = classify(target["apply_url"])
        print(f"\n=== [{index}/{len(targets)}] [{target.get('tier', '?').upper()} "
              f"score={target.get('score', 0):.0f}] {target['title'][:60]} ({portal}) ===")
        entry = {**target, "portal": portal, "dry_run_status": "", "submit_status": "",
                 "attempts": 0, "notes": []}

        if portal == "unknown":
            entry["dry_run_status"] = "SKIPPED_NO_AUTOMATION"
            entry["notes"].append(f"manual apply: {target['apply_url']}")
            report.append(entry)
            continue

        try:
            # Up to MAX_ATTEMPTS attempts per job; a clean dry-run breaks out to the
            # submit path. One job's failure never stops the batch — failures are
            # recorded and the flow continues with the next job in sequence.
            dry_result = None
            for attempt in range(1, MAX_ATTEMPTS + 1):
                entry["attempts"] = attempt
                if portal == "taleo":
                    dry_result = taleo.apply_to_taleo_job(
                        apply_url=target["apply_url"],
                        resume_path=Path(target["resume_pdf"]),
                        dry_run=True,
                        headless=args.headless,
                        job_title=target["title"],
                    )
                else:
                    dry_result = workday.apply_to_mercedes_job(
                        job_url=target["apply_url"],
                        resume_path=Path(target["resume_pdf"]),
                        dry_run=True,
                        headless=args.headless,
                    )
                entry["dry_run_status"] = str(dry_result.get("status"))
                entry["notes"].extend(str(note) for note in dry_result.get("notes", []))
                if entry["dry_run_status"] in ("DRY_RUN_COMPLETE", "DRY_RUN"):
                    break
                if entry["dry_run_status"] in NON_RETRYABLE:
                    print(f"[BATCH] {entry['dry_run_status']} is not retryable - "
                          f"recording and moving on")
                    break
                print(f"[BATCH] attempt {attempt}/{MAX_ATTEMPTS} dry-run not clean "
                      f"({entry['dry_run_status']}), retrying...")
                time.sleep(ATTEMPT_BACKOFF_S)

            safe = entry["dry_run_status"] in ("DRY_RUN_COMPLETE", "DRY_RUN")
            if args.submit and safe:
                print(f"[BATCH] dry-run clean -> submitting {target['title'][:50]}")
                submit_result = None
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    if portal == "taleo":
                        submit_result = taleo.apply_to_taleo_job(
                            apply_url=target["apply_url"],
                            resume_path=Path(target["resume_pdf"]),
                            dry_run=False,
                            headless=args.headless,
                            job_title=target["title"],
                        )
                    else:
                        submit_result = workday.apply_to_mercedes_job(
                            job_url=target["apply_url"],
                            resume_path=Path(target["resume_pdf"]),
                            dry_run=False,
                            headless=args.headless,
                        )
                    entry["submit_status"] = str(submit_result.get("status"))
                    entry["notes"].extend(str(note) for note in submit_result.get("notes", []))
                    if entry["submit_status"] in ("SUCCESS", "SUBMITTED"):
                        break
                    if entry["submit_status"] in NON_RETRYABLE:
                        print(f"[BATCH] {entry['submit_status']} is not retryable - "
                              f"recording and moving on")
                        break
                    print(f"[BATCH] attempt {attempt}/{MAX_ATTEMPTS} submit not confirmed "
                          f"({entry['submit_status']}), retrying...")
                    time.sleep(ATTEMPT_BACKOFF_S)
            elif args.submit and not safe:
                entry["submit_status"] = "SKIPPED_UNSAFE_DRY_RUN"
        except Exception as exc:  # noqa: BLE001 - one job must never stop the batch
            entry["dry_run_status"] = entry["dry_run_status"] or "EXCEPTION"
            entry["notes"].append(f"{type(exc).__name__}: {exc}")

        report.append(entry)
        # Persist the report after EVERY job so an interrupted batch keeps its record.
        RESULTS_DIR.mkdir(exist_ok=True)
        (RESULTS_DIR / "batch_apply_report.json").write_text(json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "mode": "submit" if args.submit else "dry-run",
             "results": report},
            indent=2, ensure_ascii=False), encoding="utf-8")

    RESULTS_DIR.mkdir(exist_ok=True)
    report_path = RESULTS_DIR / "batch_apply_report.json"

    print("\n=== BATCH APPLY REPORT ===")
    for entry in report:
        line = f"  {entry['title'][:48]:48} | {entry['portal']:8} | dry: {entry['dry_run_status']:22}"
        if args.submit:
            line += f" | submit: {entry['submit_status']}"
        print(line)
        for note in entry["notes"][:2]:
            print(f"      - {note[:100]}")
    print(f"[BATCH] report -> {report_path}")

    ready = sum(1 for e in report if e["dry_run_status"] in ("DRY_RUN_COMPLETE", "DRY_RUN"))
    submitted = sum(1 for e in report if e.get("submit_status") in ("SUCCESS", "SUBMITTED"))
    print(f"[BATCH] {ready}/{len(report)} dry-runs clean | {submitted} submitted")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
