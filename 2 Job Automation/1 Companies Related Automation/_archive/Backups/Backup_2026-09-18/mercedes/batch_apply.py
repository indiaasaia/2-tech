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
OUTPUT_DIR = PROJECT_DIR / "program_files" / "output_mercedes"
RESULTS_DIR = PROJECT_DIR / "results"
ADAPTED_CSV = OUTPUT_DIR / "2_filted_jobs.csv"
MAP_CSV = OUTPUT_DIR / "job_resume_map.csv"


def _load_module(file_name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PROJECT_DIR / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_targets(limit: int | None) -> list[dict]:
    """First N unique-role jobs with a resume map entry; per-job apply URL."""
    import pandas as pd

    jobs = pd.read_csv(ADAPTED_CSV, keep_default_na=False)
    resume_map = pd.read_csv(MAP_CSV, keep_default_na=False)
    resume_by_url = {str(r["job_url"]): r for _, r in resume_map.iterrows()}

    targets: list[dict] = []
    seen_titles: set[str] = set()
    for _, job in jobs.iterrows():
        title_key = str(job["title"]).strip().lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        map_row = resume_by_url.get(str(job["job_url"]))
        if map_row is None or str(map_row["status"]) != "OK":
            continue
        targets.append({
            "title": str(job["title"]),
            "job_url": str(job["job_url"]),
            "apply_url": str(job.get("apply_url") or ""),
            "resume_pdf": str(map_row["resume_pdf"]),
        })
        if limit is not None and len(targets) >= limit:
            break
    return targets


def classify(apply_url: str) -> str:
    if "taleo.net" in apply_url:
        return "taleo"
    if "myworkdayjobs.com" in apply_url:
        return "workday"
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
        print(f"\n=== [{index}/{len(targets)}] {target['title'][:60]} ({portal}) ===")
        entry = {**target, "portal": portal, "dry_run_status": "", "submit_status": "", "notes": []}

        if portal == "unknown":
            entry["dry_run_status"] = "SKIPPED_NO_AUTOMATION"
            entry["notes"].append(f"manual apply: {target['apply_url']}")
            report.append(entry)
            continue

        try:
            if portal == "taleo":
                result = taleo.apply_to_taleo_job(
                    apply_url=target["apply_url"],
                    resume_path=Path(target["resume_pdf"]),
                    dry_run=True,
                    headless=args.headless,
                    job_title=target["title"],
                )
            else:
                result = workday.apply_to_mercedes_job(
                    job_url=target["apply_url"],
                    resume_path=Path(target["resume_pdf"]),
                    dry_run=True,
                    headless=args.headless,
                )
            entry["dry_run_status"] = str(result.get("status"))
            entry["notes"].extend(str(note) for note in result.get("notes", []))

            safe = entry["dry_run_status"] in ("DRY_RUN_COMPLETE", "DRY_RUN")
            if args.submit and safe:
                print(f"[BATCH] dry-run clean -> submitting {target['title'][:50]}")
                if portal == "taleo":
                    result = taleo.apply_to_taleo_job(
                        apply_url=target["apply_url"],
                        resume_path=Path(target["resume_pdf"]),
                        dry_run=False,
                        headless=args.headless,
                        job_title=target["title"],
                    )
                else:
                    result = workday.apply_to_mercedes_job(
                        job_url=target["apply_url"],
                        resume_path=Path(target["resume_pdf"]),
                        dry_run=False,
                        headless=args.headless,
                    )
                entry["submit_status"] = str(result.get("status"))
                entry["notes"].extend(str(note) for note in result.get("notes", []))
            elif args.submit and not safe:
                entry["submit_status"] = "SKIPPED_UNSAFE_DRY_RUN"
        except Exception as exc:  # noqa: BLE001 - one job must never stop the batch
            entry["dry_run_status"] = entry["dry_run_status"] or "EXCEPTION"
            entry["notes"].append(f"{type(exc).__name__}: {exc}")

        report.append(entry)

    RESULTS_DIR.mkdir(exist_ok=True)
    report_path = RESULTS_DIR / "batch_apply_report.json"
    report_path.write_text(json.dumps(
        {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "mode": "submit" if args.submit else "dry-run",
         "results": report},
        indent=2, ensure_ascii=False), encoding="utf-8")

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
    print(f"[BATCH] {ready}/{len(report)} dry-runs clean")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
