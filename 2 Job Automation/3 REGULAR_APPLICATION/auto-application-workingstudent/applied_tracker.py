"""Applied Jobs Tracker & Deduplication Registry.

Tracks job applications to prevent duplicate submissions and redundant LLM processing.
Maintains both JSON (primary store with full details) and CSV (spreadsheet-friendly view).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from . import config
except ImportError:
    import config

config.ensure_utf8_stdout()

# Valid Application Statuses
STATUS_APPLIED = "applied"
STATUS_READY_TO_APPLY = "ready_to_apply"
STATUS_FETCHED_ONLY = "fetched_only"
STATUS_SKIPPED = "skipped"
STATUS_INTERVIEW = "interview"
STATUS_OFFER = "offer"
STATUS_REJECTED = "rejected"

VALID_STATUSES = {
    STATUS_APPLIED,
    STATUS_READY_TO_APPLY,
    STATUS_FETCHED_ONLY,
    STATUS_SKIPPED,
    STATUS_INTERVIEW,
    STATUS_OFFER,
    STATUS_REJECTED,
}


def _normalize_text(val: str) -> str:
    """Normalize text for fuzzy duplicate matching (lower, alphanumeric only)."""
    if not val:
        return ""
    val = re.sub(r"\(.*?\)", " ", val)  # drop (m/f/d), (f/m/x)
    val = re.sub(r"[^a-zA-Z0-9\s]", " ", val).lower()
    return " ".join(val.split())


def _normalize_key(company: str, title: str) -> str:
    """Construct a normalized signature key from company and job title."""
    co_norm = _normalize_text(company)
    ti_norm = _normalize_text(title)
    return f"{co_norm}::{ti_norm}"


def load_tracker() -> dict[str, Any]:
    """Load the applied jobs database from JSON."""
    config.ensure_dirs()
    if not config.APPLIED_JSON.exists():
        return {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "jobs": {},
        }
    try:
        data = json.loads(config.APPLIED_JSON.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid format")
        if "jobs" not in data or not isinstance(data["jobs"], dict):
            data["jobs"] = {}
        return data
    except Exception as exc:
        print(f"[TRACKER] Warning: Failed to read {config.APPLIED_JSON} ({exc}), creating fresh registry")
        return {
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "jobs": {},
        }


def save_tracker(data: dict[str, Any]) -> None:
    """Save the tracker dictionary to JSON and export CSV mirror."""
    config.ensure_dirs()
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    config.APPLIED_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    export_csv(data)


def export_csv(data: dict[str, Any] | None = None) -> Path:
    """Export the applied jobs registry to CSV."""
    config.ensure_dirs()
    if data is None:
        data = load_tracker()
    
    rows = []
    for url, item in data.get("jobs", {}).items():
        rows.append({
            "job_url": url,
            "company": item.get("company", ""),
            "title": item.get("title", ""),
            "status": item.get("status", ""),
            "applied_at": item.get("applied_at", ""),
            "method": item.get("method", ""),
            "location": item.get("location", ""),
            "notes": item.get("notes", ""),
            "resume_path": item.get("resume_path", ""),
            "cover_letter_path": item.get("cover_letter_path", ""),
            "last_updated": item.get("last_updated", ""),
        })

    frame = pd.DataFrame(rows)
    if not frame.empty:
        # Sort by applied_at desc
        frame = frame.sort_values(by="applied_at", ascending=False)
    frame.to_csv(config.APPLIED_CSV, index=False, encoding="utf-8-sig")
    return config.APPLIED_CSV


def is_applied(job_url: str, company: str = "", title: str = "") -> bool:
    """Check if a job is already applied (by URL or company+title match)."""
    if not job_url:
        return False
    tracker = load_tracker()
    jobs = tracker.get("jobs", {})

    # Check exact URL
    if job_url in jobs and jobs[job_url].get("status") == STATUS_APPLIED:
        return True

    # Check normalized signature if company and title are provided
    if company and title:
        target_sig = _normalize_key(company, title)
        for _, rec in jobs.items():
            if rec.get("status") == STATUS_APPLIED:
                rec_sig = _normalize_key(rec.get("company", ""), rec.get("title", ""))
                if target_sig and rec_sig and target_sig == rec_sig:
                    return True

    return False


def get_job_record(job_url: str) -> dict[str, Any] | None:
    """Retrieve full tracking details for a job URL."""
    tracker = load_tracker()
    return tracker.get("jobs", {}).get(job_url)


def mark_applied(
    job_url: str,
    company: str,
    title: str,
    location: str = "",
    method: str = "manual",
    notes: str = "",
    resume_path: str = "",
    cover_letter_path: str = "",
) -> dict[str, Any]:
    """Register a job as APPLIED."""
    tracker = load_tracker()
    now_str = datetime.now(timezone.utc).isoformat()
    record = tracker.get("jobs", {}).get(job_url, {})
    record.update({
        "job_url": job_url,
        "company": company or record.get("company", ""),
        "title": title or record.get("title", ""),
        "location": location or record.get("location", ""),
        "status": STATUS_APPLIED,
        "applied_at": record.get("applied_at") or now_str,
        "method": method or record.get("method", "manual"),
        "notes": notes or record.get("notes", ""),
        "resume_path": resume_path or record.get("resume_path", ""),
        "cover_letter_path": cover_letter_path or record.get("cover_letter_path", ""),
        "last_updated": now_str,
    })
    tracker["jobs"][job_url] = record
    save_tracker(tracker)
    print(f"[TRACKER] Marked APPLIED: {company} - {title}")
    return record


def mark_ready(
    job_url: str,
    company: str,
    title: str,
    location: str = "",
    notes: str = "",
    resume_path: str = "",
    cover_letter_path: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Register a job as READY_TO_APPLY (tailored documents generated)."""
    tracker = load_tracker()
    now_str = datetime.now(timezone.utc).isoformat()
    record = tracker.get("jobs", {}).get(job_url, {})
    # Don't downgrade an already applied job unless forced by explicit user action
    if not force and record.get("status") == STATUS_APPLIED:
        return record
    record.update({
        "job_url": job_url,
        "company": company or record.get("company", ""),
        "title": title or record.get("title", ""),
        "location": location or record.get("location", ""),
        "status": STATUS_READY_TO_APPLY,
        "notes": notes or record.get("notes", ""),
        "resume_path": resume_path or record.get("resume_path", ""),
        "cover_letter_path": cover_letter_path or record.get("cover_letter_path", ""),
        "last_updated": now_str,
    })
    tracker["jobs"][job_url] = record
    save_tracker(tracker)
    return record


def mark_fetched_only(
    job_url: str,
    company: str,
    title: str,
    location: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Register a job as FETCHED_ONLY (scraped but not yet tailored/applied)."""
    tracker = load_tracker()
    now_str = datetime.now(timezone.utc).isoformat()
    record = tracker.get("jobs", {}).get(job_url, {})
    # Don't overwrite higher status
    if record.get("status") in (STATUS_APPLIED, STATUS_READY_TO_APPLY):
        return record
    record.update({
        "job_url": job_url,
        "company": company or record.get("company", ""),
        "title": title or record.get("title", ""),
        "location": location or record.get("location", ""),
        "status": STATUS_FETCHED_ONLY,
        "notes": notes or record.get("notes", ""),
        "last_updated": now_str,
    })
    tracker["jobs"][job_url] = record
    save_tracker(tracker)
    return record


def mark_status(job_url: str, status: str, notes: str = "") -> bool:
    """Update status of a job (e.g. interview, rejected, skipped)."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Allowed: {VALID_STATUSES}")
    tracker = load_tracker()
    if job_url not in tracker.get("jobs", {}):
        return False
    tracker["jobs"][job_url]["status"] = status
    if notes:
        tracker["jobs"][job_url]["notes"] = notes
    tracker["jobs"][job_url]["last_updated"] = datetime.now(timezone.utc).isoformat()
    save_tracker(tracker)
    print(f"[TRACKER] Updated status to {status} for: {job_url}")
    return True


def filter_unapplied(
    items: pd.DataFrame | list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter out jobs that have already been marked as APPLIED.

    Returns:
        (unapplied_list, already_applied_list)
    """
    if isinstance(items, pd.DataFrame):
        records = items.to_dict("records")
    else:
        records = list(items)

    unapplied: list[dict[str, Any]] = []
    already_applied: list[dict[str, Any]] = []

    for item in records:
        url = str(item.get("job_url") or "").strip()
        company = str(item.get("company") or "").strip()
        title = str(item.get("title") or "").strip()

        if is_applied(url, company=company, title=title):
            already_applied.append(item)
        else:
            unapplied.append(item)

    print(
        f"[TRACKER] Deduplication check: {len(unapplied)} new unapplied jobs, "
        f"{len(already_applied)} skipped (already applied)."
    )
    return unapplied, already_applied


def get_summary() -> dict[str, int]:
    """Get count of jobs per status."""
    tracker = load_tracker()
    summary: dict[str, int] = {s: 0 for s in VALID_STATUSES}
    for item in tracker.get("jobs", {}).values():
        status = item.get("status")
        if status in summary:
            summary[status] += 1
        else:
            summary[status] = summary.get(status, 0) + 1
    return summary


def get_categorized_jobs() -> dict[str, Any]:
    """Retrieve all tracked jobs categorized into Ready, Applied, and Fetched Only."""
    tracker = load_tracker()
    jobs_dict = tracker.get("jobs", {})

    # Also load screened jobs and screening report for metadata enrichment
    metadata: dict[str, dict[str, Any]] = {}
    for p in (config.SCREENED_CSV, config.SCREENING_REPORT_CSV, config.FETCHED_CSV):
        if p.exists():
            try:
                df = pd.read_csv(p, keep_default_na=False)
                for _, r in df.iterrows():
                    u = str(r.get("job_url", "")).strip()
                    if u and u not in metadata:
                        metadata[u] = r.to_dict()
            except Exception:
                pass

    # Engine resume & cover letter artifacts
    resumes_report: dict[str, Any] = {}
    letters_report: dict[str, Any] = {}
    eng_res = config.PROJECT_ROOT / "output" / "applications" / "resume_report.json"
    eng_let = config.PROJECT_ROOT / "output" / "applications" / "letters_report.json"

    if eng_res.exists():
        try:
            rdata = json.loads(eng_res.read_text(encoding="utf-8"))
            for r in rdata.get("results", []):
                if r.get("job_url"):
                    resumes_report[r["job_url"]] = r
        except Exception:
            pass

    if eng_let.exists():
        try:
            ldata = json.loads(eng_let.read_text(encoding="utf-8"))
            for r in ldata.get("results", []):
                if r.get("job_url"):
                    letters_report[r["job_url"]] = r
        except Exception:
            pass

    ready_list: list[dict[str, Any]] = []
    applied_list: list[dict[str, Any]] = []
    fetched_list: list[dict[str, Any]] = []

    # Process all jobs in tracker
    seen_urls: set[str] = set()
    for url, rec in jobs_dict.items():
        seen_urls.add(url)
        meta = metadata.get(url, {})
        res_info = resumes_report.get(url, {})
        let_info = letters_report.get(url, {})
        let_arts = let_info.get("artifacts") or {}

        # Resolve paths
        resume_pdf = rec.get("resume_path") or res_info.get("pdf") or ""
        letter_pdf = rec.get("cover_letter_path") or let_arts.get("letter_pdf") or ""
        let_txt_path = let_arts.get("textfield_txt") or ""
        let_text = ""
        if let_txt_path and Path(let_txt_path).exists():
            try:
                let_text = Path(let_txt_path).read_text(encoding="utf-8").strip()
            except Exception:
                pass

        card = {
            "job_url": url,
            "company": rec.get("company") or meta.get("company") or "Company",
            "title": rec.get("title") or meta.get("title") or "Role",
            "location": rec.get("location") or meta.get("location") or "Germany",
            "posted_time": meta.get("posted_time", ""),
            "role_type": meta.get("role_type") or "working_student",
            "tech_domain": meta.get("tech_domain") or "tech",
            "german_req": meta.get("german_requirement") or "none",
            "german_level": meta.get("german_level") or "none",
            "status": rec.get("status", STATUS_FETCHED_ONLY),
            "applied_at": rec.get("applied_at", ""),
            "method": rec.get("method", "manual"),
            "notes": rec.get("notes", ""),
            "resume_path": resume_pdf,
            "cover_letter_path": letter_pdf,
            "cover_letter_text": let_text,
            "last_updated": rec.get("last_updated", ""),
        }

        status = rec.get("status")
        if status == STATUS_APPLIED:
            applied_list.append(card)
        elif status == STATUS_READY_TO_APPLY:
            ready_list.append(card)
        else:
            fetched_list.append(card)

    # Ingest any untracked jobs from screened_jobs.csv or fetched_jobs.csv
    for url, meta in metadata.items():
        if url in seen_urls:
            continue
        seen_urls.add(url)
        res_info = resumes_report.get(url, {})
        let_info = letters_report.get(url, {})
        let_arts = let_info.get("artifacts") or {}

        resume_pdf = res_info.get("pdf") or ""
        letter_pdf = let_arts.get("letter_pdf") or ""
        let_txt_path = let_arts.get("textfield_txt") or ""
        let_text = ""
        if let_txt_path and Path(let_txt_path).exists():
            try:
                let_text = Path(let_txt_path).read_text(encoding="utf-8").strip()
            except Exception:
                pass

        # Determine default status
        if res_info.get("status") == "verified" or letter_pdf:
            default_status = STATUS_READY_TO_APPLY
        elif meta.get("screening_decision") == "keep":
            default_status = STATUS_READY_TO_APPLY
        else:
            default_status = STATUS_FETCHED_ONLY

        card = {
            "job_url": url,
            "company": meta.get("company") or "Company",
            "title": meta.get("title") or "Role",
            "location": meta.get("location") or "Germany",
            "posted_time": meta.get("posted_time", ""),
            "role_type": meta.get("role_type") or "working_student",
            "tech_domain": meta.get("tech_domain") or "tech",
            "german_req": meta.get("german_requirement") or "none",
            "german_level": meta.get("german_level") or "none",
            "status": default_status,
            "applied_at": "",
            "method": "manual",
            "notes": meta.get("reason") or "",
            "resume_path": resume_pdf,
            "cover_letter_path": letter_pdf,
            "cover_letter_text": let_text,
            "last_updated": meta.get("scraped_at_utc") or "",
        }

        if default_status == STATUS_READY_TO_APPLY:
            ready_list.append(card)
        else:
            fetched_list.append(card)

    # Sort each list by last_updated desc
    ready_list.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
    applied_list.sort(key=lambda x: x.get("applied_at", "") or x.get("last_updated", ""), reverse=True)
    fetched_list.sort(key=lambda x: x.get("last_updated", ""), reverse=True)

    return {
        "counts": {
            "ready_for_application": len(ready_list),
            "applied": len(applied_list),
            "fetched_only": len(fetched_list),
            "total": len(ready_list) + len(applied_list) + len(fetched_list),
        },
        "ready_for_application": ready_list,
        "applied": applied_list,
        "fetched_only": fetched_list,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Applied Jobs Tracker CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # list
    list_p = subparsers.add_parser("list", help="List tracked jobs")
    list_p.add_argument("--status", choices=list(VALID_STATUSES), help="Filter by status")

    # check
    check_p = subparsers.add_parser("check", help="Check if URL is applied")
    check_p.add_argument("url", help="Job URL to check")

    # add
    add_p = subparsers.add_parser("add", help="Mark job as applied")
    add_p.add_argument("url", help="Job URL")
    add_p.add_argument("--company", default="", help="Company name")
    add_p.add_argument("--title", default="", help="Job title")
    add_p.add_argument("--status", default=STATUS_APPLIED, choices=list(VALID_STATUSES), help="Status")
    add_p.add_argument("--notes", default="", help="Notes")

    # stats
    subparsers.add_parser("stats", help="Show summary counts")

    # sync
    subparsers.add_parser("sync", help="Synchronize JSON to CSV")

    args = parser.parse_args(argv)

    if args.command == "list":
        tracker = load_tracker()
        jobs = tracker.get("jobs", {})
        count = 0
        for url, item in jobs.items():
            if args.status and item.get("status") != args.status:
                continue
            count += 1
            print(f"[{item.get('status', 'unknown').upper()}] {item.get('company')} - {item.get('title')}")
            print(f"  URL: {url}")
            if item.get("applied_at"):
                print(f"  Applied: {item.get('applied_at')}")
        print(f"\nTotal: {count} job(s)")
        return 0

    if args.command == "check":
        applied = is_applied(args.url)
        print(f"URL: {args.url}")
        print(f"Applied: {'YES' if applied else 'NO'}")
        rec = get_job_record(args.url)
        if rec:
            print(f"Record details: {json.dumps(rec, indent=2)}")
        return 0

    if args.command == "add":
        if args.status == STATUS_APPLIED:
            mark_applied(args.url, company=args.company, title=args.title, notes=args.notes)
        else:
            mark_status(args.url, args.status, notes=args.notes)
        return 0

    if args.command == "stats":
        stats = get_summary()
        print("=== Applied Tracker Stats ===")
        for s, count in stats.items():
            print(f"  {s:<15}: {count}")
        return 0

    if args.command == "sync":
        p = export_csv()
        print(f"[TRACKER] Synced to {p}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
