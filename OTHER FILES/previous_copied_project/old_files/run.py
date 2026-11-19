"""Unified CLI for JOB_AUTOMATION: fetch, generate, track, and run end to end.

Usage:
    python run.py fetch [options]      Phase 1: scrape job listings (Stepstone + workingstudentjobs.de)
    python run.py resumes [options]    Phase 2: tailored resumes for jobs.csv
    python run.py letters [options]    Phase 3: cover letters + application manifest
    python run.py all [options]        End-to-end: fetch, then run every job through resumes + letters
    python run.py demo                 Create a sample jobs.csv so the pipeline runs fully offline
    python run.py status [options]     Show tracked activity and the latest run reports

Every step is written to ``data/output/activity.log``; ``status`` summarizes it.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.core import config
from app.core import activity
from app.phase1 import cli as phase1_cli
from app.phase2 import cli as phase2_cli
from app.phase3 import cli as phase3_cli
from app.workflow import run_sequential


# ---------------------------------------------------------------------------
# Sample data (offline end-to-end demo)
# ---------------------------------------------------------------------------

def _sample_jobs(now: datetime | None = None) -> pd.DataFrame:
    current = now or datetime.now(timezone.utc)
    stamp = current.isoformat(timespec="seconds")
    rows = [
        {
            "source": "stepstone", "source_job_id": "demo-001",
            "title": "Working Student - Python Backend Development",
            "company": "TechNova GmbH", "location": "Berlin, Germany",
            "posted_time": stamp, "job_url": "https://example.com/jobs/demo-001",
            "company_url": "https://technova.example", "snippet": "Backend working student role with Python, FastAPI and SQL.",
            "detail_contract_type": "Part-time", "detail_work_type": "Hybrid",
            "job_description": ("TechNova builds cloud APIs for logistics. As a working student you support the backend team "
                                "building and improving REST APIs with Python and FastAPI, work with PostgreSQL, and help "
                                "maintain Docker-based CI pipelines."),
            "applicant_profile": ("Enrolled in a Bachelor's or Master's program in Computer Science or a related field. "
                                  "Good knowledge of Python, some experience with SQL and REST APIs, curiosity for clean code."),
            "your_tasks": "Develop and improve REST APIs with Python and FastAPI; write SQL queries; support CI/CD with Docker.",
            "requirements": "Python, FastAPI, SQL, Docker",
            "what_they_offer": "Flexible working hours, 20h/week, remote-friendly, mentorship.",
            "we_offer": "Flexible working hours, 20h/week, remote-friendly, mentorship.",
        },
        {
            "source": "stepstone", "source_job_id": "demo-002",
            "title": "Werkstudent AI / Machine Learning",
            "company": "DataWorks GmbH", "location": "Munich, Germany",
            "posted_time": stamp, "job_url": "https://example.com/jobs/demo-002",
            "company_url": "https://dataworks.example", "snippet": "AI working student supporting ML model development and NLP pipelines.",
            "detail_contract_type": "Part-time", "detail_work_type": "On-site",
            "job_description": ("DataWorks applies machine learning to industrial sensor data. You will help build and evaluate "
                                "ML models, prepare datasets, and experiment with LLM-based applications using Python."),
            "applicant_profile": ("Currently studying Computer Science, AI or Data Science. Solid Python skills, first experience "
                                  "with scikit-learn or PyTorch, interest in NLP and large language models."),
            "your_tasks": "Prepare datasets; train and evaluate ML models; prototype LLM applications; document experiments.",
            "requirements": "Python, Machine Learning, PyTorch, NLP",
            "what_they_offer": "Paid working student position, mentoring by senior ML engineers, modern tech stack.",
            "we_offer": "Paid working student position, mentoring by senior ML engineers, modern tech stack.",
        },
        {
            "source": "workingstudentjobs.de", "source_job_id": "demo-003",
            "title": "Internship - Data Engineering",
            "company": "CloudSystems AG", "location": "Cologne, Germany",
            "posted_time": stamp, "job_url": "https://example.com/jobs/demo-003",
            "company_url": "https://cloudsystems.example", "snippet": "Data engineering intern working with SQL, Python and ETL pipelines.",
            "detail_contract_type": "Internship", "detail_work_type": "Hybrid",
            "job_description": ("CloudSystems AG operates a large analytics platform. As a data engineering intern you build and "
                                "improve ETL pipelines, write SQL for data warehouse queries, and automate data quality checks with Python."),
            "applicant_profile": "Enrolled in a technical program with strong SQL and Python skills and an interest in data engineering.",
            "your_tasks": "Build ETL pipelines; write and optimize SQL; automate data quality checks with pandas and Python.",
            "requirements": "SQL, Python, ETL, pandas",
            "what_they_offer": "Structured internship program, real project ownership, competitive allowance.",
            "we_offer": "Structured internship program, real project ownership, competitive allowance.",
        },
        {
            "source": "workingstudentjobs.de", "source_job_id": "demo-004",
            "title": "Working Student - Full Stack Development",
            "company": "WebForge", "location": "Hamburg, Germany",
            "posted_time": stamp, "job_url": "https://example.com/jobs/demo-004",
            "company_url": "https://webforge.example", "snippet": "Full stack working student building web apps with React, Node.js and MongoDB.",
            "detail_contract_type": "Part-time", "detail_work_type": "Remote",
            "job_description": ("WebForge builds web applications for startups. You will work across the stack with React, Node.js "
                                "and MongoDB, ship small features end to end, and take part in code reviews."),
            "applicant_profile": ("Studying Computer Science or similar; comfortable with JavaScript/TypeScript, basic React or Node.js, "
                                  "and a desire to learn full stack development."),
            "your_tasks": "Implement UI components in React; build REST endpoints with Node.js; work with MongoDB data models.",
            "requirements": "JavaScript, React, Node.js, MongoDB",
            "what_they_offer": "Remote-first, flexible hours, learning budget, startup atmosphere.",
            "we_offer": "Remote-first, flexible hours, learning budget, startup atmosphere.",
        },
    ]
    frame = pd.DataFrame(rows)
    for column in config.COMMON_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[config.COMMON_COLUMNS]


def _write_sample(path: Path) -> int:
    frame = _sample_jobs()
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")
    activity.log_event("demo", "sample_jobs", f"wrote {len(frame)} sample jobs -> {path}", rows=len(frame))
    return len(frame)


def _csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return int(len(pd.read_csv(path, keep_default_na=False)))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_fetch(argv: list[str]) -> int:
    return phase1_cli.main(argv)


def cmd_resumes(argv: list[str]) -> int:
    return phase2_cli.main(argv)


def cmd_letters(argv: list[str]) -> int:
    return phase3_cli.main(argv)


def cmd_all(args: argparse.Namespace) -> int:
    source_csv = args.input_csv or config.COMBINED_CSV
    if args.sample:
        activity.log_event("workflow", "start", "end-to-end run using sample jobs (no live scraping)")
        _write_sample(source_csv)
    elif args.input_csv is None:
        fetch_args = ["--source", args.source, "--stepstone-pages", str(args.stepstone_pages),
                      "--workingstudent-pages", str(args.workingstudent_pages)]
        if args.no_details:
            fetch_args.append("--no-details")
        if args.headed:
            fetch_args.append("--headed")
        code = cmd_fetch(fetch_args)
        if code != 0 and _csv_row_count(source_csv) == 0:
            activity.log_event("workflow", "start", "fetch failed and no jobs.csv exists; use --sample for an offline run", status="error")
            print("[WORKFLOW] fetch produced no jobs; re-run with --sample for an offline demo")
            return 1

    count = _csv_row_count(source_csv)
    if count == 0:
        activity.log_event("workflow", "start", "jobs CSV is empty; nothing to process", status="error")
        print(f"[WORKFLOW] no jobs found in {source_csv}; run 'python run.py fetch' or 'python run.py all --sample'")
        return 1

    activity.log_event("workflow", "start", f"processing {count} finalized jobs sequentially", jobs=count)
    results = run_sequential(source_csv, args.limit, use_llm=not args.no_llm, compile_pdfs=not args.no_pdf)
    ready = sum(item["application_status"] == "ready_for_review" for item in results)
    print(f"[WORKFLOW] completed {ready}/{len(results)} applications ready_for_review")
    print(f"[WORKFLOW] manifest: {config.APPLICATIONS_CSV}")
    return 0 if ready == len(results) else 1


def cmd_demo(args: argparse.Namespace) -> int:
    count = _write_sample(args.output)
    print(f"[DEMO] wrote {count} sample jobs to {args.output}")
    print(f"[DEMO] next: python run.py all --sample --no-llm   (or: python run.py resumes && python run.py letters)")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    events = activity.load_events(args.tail)
    print("=" * 72)
    print("JOB_AUTOMATION - activity & status")
    print("=" * 72)

    if events:
        counts: dict[str, dict[str, int]] = {}
        for event in events:
            bucket = counts.setdefault(event.get("phase", "?"), {})
            bucket[event.get("status", "?")] = bucket.get(event.get("status", "?"), 0) + 1
        print("\n[events by phase/status]")
        for phase, statuses in counts.items():
            parts = "  ".join(f"{k}={v}" for k, v in sorted(statuses.items()))
            print(f"  {phase:<10} {parts}")
        print(f"\n[last {len(events)} events]")
        for event in events:
            marker = {"ok": "+", "warn": "!", "error": "x", "info": "."}.get(event.get("status", "ok"), ".")
            print(f"  {event.get('ts', '')} {marker} {event.get('phase', '')}/{event.get('step', '')}: {event.get('message', '')}")
    else:
        print("\n[no activity recorded yet] run 'python run.py all --sample' to generate the first run.")

    for label, path in (("phase1 report", config.REPORT_JSON), ("phase2 report", config.PHASE2_REPORT), ("phase3 report", config.PHASE3_REPORT)):
        if path.exists():
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            print(f"\n[{label}] {path}")
            for key, value in report.items():
                if key == "results":
                    continue
                print(f"  {key}: {value}")

    if config.APPLICATIONS_CSV.exists():
        try:
            manifest = pd.read_csv(config.APPLICATIONS_CSV, keep_default_na=False)
        except Exception:
            manifest = pd.DataFrame()
        if not manifest.empty:
            print(f"\n[applications manifest] {config.APPLICATIONS_CSV} ({len(manifest)} rows)")
            columns = [c for c in ("index", "company", "title", "resume_method", "cover_method", "application_status") if c in manifest.columns]
            if columns:
                print(manifest[columns].to_string(index=False))

    print("\n[files]")
    for label, path in (("jobs.csv", config.COMBINED_CSV), ("stepstone", config.STEPSTONE_CSV),
                        ("workingstudentjobs.de", config.WORKINGSTUDENT_CSV), ("activity.log", config.ACTIVITY_LOG)):
        exists = path.exists()
        print(f"  {label:<22} {'present' if exists else 'missing'}" + (f" ({_csv_row_count(path)} rows)" if exists and path.suffix == ".csv" else ""))
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run.py", description="JOB_AUTOMATION unified CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fetch", help="Phase 1: scrape Stepstone + workingstudentjobs.de")

    resumes = sub.add_parser("resumes", help="Phase 2: tailored resumes")
    resumes.add_argument("--input-csv", type=Path, default=config.COMBINED_CSV)
    resumes.add_argument("--limit", type=int, default=None)
    resumes.add_argument("--no-llm", action="store_true", help="Skip Ollama; use the truthful local template")
    resumes.add_argument("--no-pdf", action="store_true", help="Write LaTeX only; skip PDF compilation")

    letters = sub.add_parser("letters", help="Phase 3: cover letters + application manifest")
    letters.add_argument("--input-csv", type=Path, default=config.COMBINED_CSV)
    letters.add_argument("--limit", type=int, default=None)
    letters.add_argument("--no-llm", action="store_true")
    letters.add_argument("--no-pdf", action="store_true")

    all_ = sub.add_parser("all", help="End-to-end: fetch, then resume + cover letter per job")
    all_.add_argument("--source", choices=("both", "stepstone", "workingstudent"), default="both")
    all_.add_argument("--stepstone-pages", type=int, default=config.STEPSTONE_MAX_PAGES)
    all_.add_argument("--workingstudent-pages", type=int, default=config.WSJ_MAX_PAGES)
    all_.add_argument("--no-details", action="store_true", help="Only fetch listing pages in Phase 1")
    all_.add_argument("--headed", action="store_true", help="Show the Stepstone browser")
    all_.add_argument("--sample", action="store_true", help="Use generated sample jobs instead of live scraping")
    all_.add_argument("--input-csv", type=Path, default=None, help="Use an existing jobs CSV instead of fetching")
    all_.add_argument("--limit", type=int, default=None, help="Process only the first N jobs")
    all_.add_argument("--no-llm", action="store_true")
    all_.add_argument("--no-pdf", action="store_true")

    demo = sub.add_parser("demo", help="Create a sample jobs.csv for a fully offline run")
    demo.add_argument("--output", type=Path, default=config.COMBINED_CSV)

    status = sub.add_parser("status", help="Show tracked activity and latest run reports")
    status.add_argument("--tail", type=int, default=25, help="Show only the last N activity events")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, rest = parser.parse_known_args(argv)
    if args.command == "fetch":
        return cmd_fetch(rest)
    if args.command == "resumes":
        return cmd_resumes(rest)
    if args.command == "letters":
        return cmd_letters(rest)
    if args.command == "all":
        return cmd_all(args)
    if args.command == "demo":
        return cmd_demo(args)
    if args.command == "status":
        return cmd_status(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
