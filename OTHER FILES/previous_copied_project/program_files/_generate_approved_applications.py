#!/usr/bin/env python3
"""Generate application documents only for the user-approved final jobs CSV.

The CSV is the allowlist: no scraper, secondary filter, or prior output can add
jobs. Outputs are checkpointed after each resume-generation/build result.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resume_content_improve_research import config
from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.llm import load_first_key
from resume_content_improve_research.run_step4 import process_job
from resume_content_improve_research.run_step5 import build_record
from resume_content_improve_research.templates.build import find_latex_engine, safe_name
from resume_content_improve_research.verification.triage import write_shortlist

config.ensure_utf8_stdout()
APPROVED_CSV = ROOT / "program_files" / "output" / "fresh_run_2026-10-05" / "FINAL_eligible_jobs.csv"
OUT = config.OUTPUT_DIR
COMPONENTS_PATH = OUT / "components_v2.json"
RESUME_REPORT = config.REPORT_PATH
MANIFEST_PATH = OUT / "generation_manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_approved() -> tuple[list[dict], str]:
    if not APPROVED_CSV.is_file():
        raise RuntimeError(f"approved input CSV is missing: {APPROVED_CSV}")
    with APPROVED_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        jobs = list(csv.DictReader(handle))
    if not jobs:
        raise RuntimeError("approved input CSV has no job rows")
    required = ("job_url", "title", "company", "job_description")
    missing_columns = [name for name in required if name not in jobs[0]]
    if missing_columns:
        raise RuntimeError(f"approved CSV missing required columns: {missing_columns}")
    for index, job in enumerate(jobs, 2):
        absent = [name for name in required if not str(job.get(name) or "").strip()]
        if absent:
            raise RuntimeError(f"CSV row {index} lacks required fields: {absent}")
        for key, expected in (("date_decision", "KEEP"),
                              ("lang_decision", "Eligible"),
                              ("domain_decision", "keep")):
            if key in job and job.get(key) != expected:
                raise RuntimeError(f"CSV row {index} is not approved: {key}={job.get(key)!r}")
    urls = [str(job["job_url"]).strip() for job in jobs]
    if any(not url.startswith(("https://", "http://")) for url in urls):
        raise RuntimeError("approved CSV contains a non-HTTP job URL")
    if len(urls) != len(set(urls)):
        raise RuntimeError("approved CSV contains duplicate job URLs")
    return jobs, digest(APPROVED_CSV)


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError(f"expected a JSON list in {path}")
    return data


def write_resume_checkpoint(results: list[dict], total: int) -> None:
    dump_json(RESUME_REPORT, {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "v2",
        "total_jobs": total,
        "results": results,
    })


def main() -> int:
    jobs, csv_sha256 = read_approved()
    key = load_first_key()
    if not key:
        raise RuntimeError("no Ollama key is configured; cannot generate resumes")
    kb = kb_loader.load_kb()
    engine = find_latex_engine()
    if not engine:
        raise RuntimeError("no LaTeX engine is installed; PDF deliverables cannot be built")

    OUT.mkdir(parents=True, exist_ok=True)
    prior_manifest = {}
    if MANIFEST_PATH.exists():
        try:
            prior_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    if prior_manifest.get("approved_csv_sha256") not in (None, csv_sha256):
        raise RuntimeError("output checkpoints were made from a different CSV; refusing to reuse them")

    print(f"APPROVED INPUT: {APPROVED_CSV}")
    print(f"ALLOWLIST: {len(jobs)} jobs | SHA-256 {csv_sha256}")
    print(f"OUTPUT: {OUT}")
    print("Scope: use these rows as-is; do not fetch or re-filter jobs.")

    previous = {str(record.get("job_url") or ""): record
                for record in load_records(COMPONENTS_PATH)}
    records: list[dict] = []
    for index, job in enumerate(jobs, 1):
        url = str(job["job_url"]).strip()
        prior = previous.get(url)
        if prior and prior.get("status") == "gated_ok" and prior.get("components"):
            record = prior
            print(f"[STEP 4] [{index}/{len(jobs)}] {job['title'][:58]} -> checkpoint kept")
        else:
            print(f"[STEP 4] [{index}/{len(jobs)}] {job['title'][:58]}")
            record = process_job(job, key, kb, tailor=True)
            print(f"          -> {record['status']}" + (f" | {record['error'][:120]}" if record.get("error") else ""))
        records.append(record)
        dump_json(COMPONENTS_PATH, records)
        dump_json(MANIFEST_PATH, {
            "approved_csv": str(APPROVED_CSV.relative_to(ROOT)),
            "approved_csv_sha256": csv_sha256,
            "approved_rows": len(jobs),
            "generation_started_at_utc": prior_manifest.get("generation_started_at_utc") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "phase": "resume_components",
            "components_written": len(records),
            "components_status_counts": dict(Counter(r.get("status", "unknown") for r in records)),
        })

    if len(records) != len(jobs) or {r.get("job_url") for r in records} != {j["job_url"] for j in jobs}:
        raise RuntimeError("resume-component checkpoint does not exactly match the approved URL set")

    print(f"\nSTEP 5: building PDFs/DOCX with {Path(engine).name}")
    existing_report = {}
    if RESUME_REPORT.exists():
        try:
            existing_report = json.loads(RESUME_REPORT.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    prior_results = {r.get("job_url"): r for r in existing_report.get("results", [])}
    name_counts: dict[str, int] = {}
    resume_results: list[dict] = []
    for index, record in enumerate(records, 1):
        title = record.get("title") or "resume"
        stem = safe_name(title)
        name_counts[stem] = name_counts.get(stem, 0) + 1
        if name_counts[stem] > 1:
            stem = f"{stem}-{name_counts[stem]}"
        prior_result = prior_results.get(record.get("job_url"))
        if (prior_result and prior_result.get("status") == "verified"
                and prior_result.get("artifacts", {}).get("resume_pdf")
                and Path(prior_result["artifacts"]["resume_pdf"]).is_file()
                and prior_result.get("artifacts", {}).get("resume_docx")
                and Path(prior_result["artifacts"]["resume_docx"]).is_file()):
            result = prior_result
            print(f"[STEP 5] [{index}/{len(records)}] {title[:58]} -> checkpoint kept")
        else:
            print(f"[STEP 5] [{index}/{len(records)}] {title[:58]}")
            result = build_record(record, engine, name=stem)
            result["file_stem"] = stem
            print(f"          -> {result['status']}" + (f" score={result['score']}" if result.get("score") is not None else "") + (f" | {result['build_error'][:100]}" if result.get("build_error") else ""))
        resume_results.append(result)
        write_resume_checkpoint(resume_results, len(records))
        dump_json(MANIFEST_PATH, {
            "approved_csv": str(APPROVED_CSV.relative_to(ROOT)),
            "approved_csv_sha256": csv_sha256,
            "approved_rows": len(jobs),
            "generation_started_at_utc": prior_manifest.get("generation_started_at_utc") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "phase": "resume_builds",
            "components_written": len(records),
            "resume_results_written": len(resume_results),
            "resume_status_counts": dict(Counter(r.get("status", "unknown") for r in resume_results)),
        })

    write_shortlist(resume_results)

    print("\nSTEP 6: creating cover letters from the same approved job records")
    from resume_content_improve_research import run_step6
    letter_exit = run_step6.main([])

    letter_report_path = config.LETTERS_REPORT_PATH
    letter_report = json.loads(letter_report_path.read_text(encoding="utf-8")) if letter_report_path.exists() else {"results": []}
    letter_results = letter_report.get("results", [])
    job_urls = {job["job_url"] for job in jobs}
    urls_ok = (
        {r.get("job_url") for r in records} == job_urls
        and {r.get("job_url") for r in resume_results} == job_urls
        and {r.get("job_url") for r in letter_results} == job_urls
    )
    resume_pdf = sum(bool(r.get("pdf") and Path(r["pdf"]).is_file()) for r in resume_results)
    resume_docx = sum(bool(r.get("docx") and Path(r["docx"]).is_file()) for r in resume_results)
    resume_verified = sum(r.get("status") == "verified" for r in resume_results)
    letters_gated = sum(bool(r.get("letter_gates_passed")) for r in letter_results)
    letter_pdf = sum(bool((r.get("artifacts") or {}).get("letter_pdf") and Path(r["artifacts"]["letter_pdf"]).is_file()) for r in letter_results)
    letter_docx = sum(bool((r.get("artifacts") or {}).get("letter_docx") and Path(r["artifacts"]["letter_docx"]).is_file()) for r in letter_results)
    letter_txt = sum(bool((r.get("artifacts") or {}).get("letter_txt") and Path(r["artifacts"]["letter_txt"]).is_file()) for r in letter_results)
    complete = urls_ok and resume_verified == len(jobs) and resume_pdf == len(jobs) and resume_docx == len(jobs) and letters_gated == len(jobs) and letter_pdf == len(jobs) and letter_docx == len(jobs) and letter_txt == len(jobs) and letter_exit == 0
    final = {
        "approved_csv": str(APPROVED_CSV.relative_to(ROOT)),
        "approved_csv_sha256": csv_sha256,
        "approved_jobs": len(jobs),
        "job_url_sets_match_exactly": urls_ok,
        "resume_verified": resume_verified,
        "resume_pdf_present": resume_pdf,
        "resume_docx_present": resume_docx,
        "letters_gates_passed": letters_gated,
        "letter_pdf_present": letter_pdf,
        "letter_docx_present": letter_docx,
        "letter_text_present": letter_txt,
        "step6_exit_code": letter_exit,
        "complete": complete,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    dump_json(MANIFEST_PATH, final)
    print("\nFINAL CHECK:")
    print(json.dumps(final, indent=2, ensure_ascii=False))
    inventory_rows = []
    resume_by_url = {result.get("job_url"): result for result in resume_results}
    letters_by_url = {result.get("job_url"): result for result in letter_results}
    for job in jobs:
        resume_result = resume_by_url[job["job_url"]]
        letter_result = letters_by_url[job["job_url"]]
        letter_artifacts = letter_result.get("artifacts") or {}
        inventory_rows.append({
            "job_url": job["job_url"], "company": job.get("company", ""),
            "title": job.get("title", ""), "resume_status": resume_result.get("status", ""),
            "resume_score": resume_result.get("score"), "resume_pdf": resume_result.get("pdf", ""),
            "resume_pdf_exists": bool(resume_result.get("pdf") and Path(resume_result["pdf"]).is_file()),
            "resume_docx": resume_result.get("docx", ""),
            "resume_docx_exists": bool(resume_result.get("docx") and Path(resume_result["docx"]).is_file()),
            "letter_gates_passed": bool(letter_result.get("letter_gates_passed")),
            "letter_error": letter_result.get("letter_error", ""),
            "letter_pdf": letter_artifacts.get("letter_pdf", ""),
            "letter_pdf_exists": bool(letter_artifacts.get("letter_pdf") and Path(letter_artifacts["letter_pdf"]).is_file()),
            "letter_docx": letter_artifacts.get("letter_docx", ""),
            "letter_docx_exists": bool(letter_artifacts.get("letter_docx") and Path(letter_artifacts["letter_docx"]).is_file()),
            "letter_txt": letter_artifacts.get("letter_txt", ""),
            "letter_txt_exists": bool(letter_artifacts.get("letter_txt") and Path(letter_artifacts["letter_txt"]).is_file()),
        })
    inventory_path = OUT / "approved_applications.csv"
    with inventory_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(inventory_rows[0]))
        writer.writeheader()
        writer.writerows(inventory_rows)
    final["inventory_csv"] = "program_files/output_v2/approved_applications.csv"
    final["complete_applications"] = sum(
        all(row[key] for key in ("resume_pdf_exists", "resume_docx_exists", "letter_pdf_exists", "letter_docx_exists", "letter_txt_exists"))
        for row in inventory_rows
    )
    final["incomplete_applications"] = [
        {"company": row["company"], "title": row["title"], "resume_status": row["resume_status"], "letter_error": row["letter_error"]}
        for row in inventory_rows
        if not all(row[key] for key in ("resume_pdf_exists", "resume_docx_exists", "letter_pdf_exists", "letter_docx_exists", "letter_txt_exists"))
    ]
    final["complete"] = final["complete_applications"] == len(jobs)
    dump_json(MANIFEST_PATH, final)
    for report_path in (RESUME_REPORT, config.LETTERS_REPORT_PATH):
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        payload["approved_csv_sha256"] = csv_sha256
        payload["approved_job_count"] = len(jobs)
        payload["job_url_sets_match_approved_csv"] = urls_ok
        report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    bundle_payload = json.loads(config.BUNDLES_PATH.read_text(encoding="utf-8"))
    bundle_payload["approved_csv_sha256"] = csv_sha256
    bundle_payload["approved_job_count"] = len(jobs)
    bundle_payload["job_url_sets_match_approved_csv"] = urls_ok
    config.BUNDLES_PATH.write_text(json.dumps(bundle_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nFINAL OUTPUT STATUS:")
    print(json.dumps(final, indent=2, ensure_ascii=False))
    resume_by_url = {result.get("job_url"): result for result in resume_results}
    letters_by_url = {result.get("job_url"): result for result in letter_results}
    for job in jobs:
        resume_result = resume_by_url[job["job_url"]]
        letter_result = letters_by_url[job["job_url"]]
        letter_artifacts = letter_result.get("artifacts") or {}
        inventory_rows.append({
            "job_url": job["job_url"],
            "company": job.get("company", ""),
            "title": job.get("title", ""),
            "resume_status": resume_result.get("status", ""),
            "resume_score": resume_result.get("score"),
            "resume_pdf": resume_result.get("pdf", ""),
            "resume_pdf_exists": bool(resume_result.get("pdf") and Path(resume_result["pdf"]).is_file()),
            "resume_docx": resume_result.get("docx", ""),
            "resume_docx_exists": bool(resume_result.get("docx") and Path(resume_result["docx"]).is_file()),
            "letter_gates_passed": bool(letter_result.get("letter_gates_passed")),
            "letter_error": letter_result.get("letter_error", ""),
            "letter_pdf": letter_artifacts.get("letter_pdf", ""),
            "letter_pdf_exists": bool(letter_artifacts.get("letter_pdf") and Path(letter_artifacts["letter_pdf"]).is_file()),
            "letter_docx": letter_artifacts.get("letter_docx", ""),
            "letter_docx_exists": bool(letter_artifacts.get("letter_docx") and Path(letter_artifacts["letter_docx"]).is_file()),
            "letter_txt": letter_artifacts.get("letter_txt", ""),
            "letter_txt_exists": bool(letter_artifacts.get("letter_txt") and Path(letter_artifacts["letter_txt"]).is_file()),
        })
    inventory_path = OUT / "approved_applications.csv"
    with inventory_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(inventory_rows[0]))
        writer.writeheader()
        writer.writerows(inventory_rows)
    print(f"Per-job artifact inventory -> {inventory_path}")
    final["inventory_csv"] = str(inventory_path.relative_to(ROOT))
    final["complete_applications"] = sum(
        all(row[key] for key in ("resume_pdf_exists", "resume_docx_exists", "letter_pdf_exists", "letter_docx_exists", "letter_txt_exists"))
        for row in inventory_rows
    )
    final["incomplete_applications"] = [
        {"company": row["company"], "title": row["title"],
         "resume_status": row["resume_status"], "letter_error": row["letter_error"]}
        for row in inventory_rows
        if not all(row[key] for key in ("resume_pdf_exists", "resume_docx_exists", "letter_pdf_exists", "letter_docx_exists", "letter_txt_exists"))
    ]
    final["complete"] = final["complete_applications"] == len(jobs)
    dump_json(MANIFEST_PATH, final)
    if not complete:
        print("\nINCOMPLETE ITEMS:")
        for result in resume_results:
            if result.get("status") != "verified" or not result.get("pdf") or not result.get("docx"):
                print(f"  RESUME | {result.get('company')} | {result.get('title')} | {result.get('build_error') or result.get('status')}")
        for result in letter_results:
            artifacts = result.get("artifacts") or {}
            if not result.get("letter_gates_passed") or not all(artifacts.get(k) and Path(artifacts[k]).is_file() for k in ("letter_pdf", "letter_docx", "letter_txt")):
                print(f"  LETTER | {result.get('company')} | {result.get('title')} | {result.get('letter_error') or 'missing artifact'}")
        return 1
    print(f"\nSUCCESS: one verified resume (PDF+DOCX) and one gated cover letter (PDF+DOCX+TXT) for each of the {len(jobs)} approved jobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
