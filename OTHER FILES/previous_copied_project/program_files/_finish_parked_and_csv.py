#!/usr/bin/env python3
"""Re-run the approved CSV generation so the 8 parked jobs get another attempt,
then emit a final CSV with job_role, job_link, resume_location, cover_letter_location.

Keeps existing verified artifacts untouched; re-processes only jobs whose
current status is parked (resume not gated_ok). The generation entrypoint
checks the approved CSV first as an allowlist.
"""
from __future__ import annotations

import csv
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resume_content_improve_research import config
from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.llm import load_first_key
from resume_content_improve_research.run_step4 import process_job, save_output, load_previous_records, load_jobs
from resume_content_improve_research.run_step5 import build_record, safe_name
from resume_content_improve_research.run_step6 import build_letter, letter_stem_for
from resume_content_improve_research.templates.build import find_latex_engine

APPROVED_CSV = ROOT / "program_files" / "output" / "fresh_run_2026-10-05" / "FINAL_eligible_jobs.csv"
OUT_DIR = config.OUTPUT_DIR
ARCHIVE_DIR = ROOT / "old_files" / "backup_output_20261005" / "prior_output_v2_before_user_csv_20261009"
print("APPROVED_CSV", APPROVED_CSV)


def load_approved_rows():
    rows = []
    with APPROVED_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def main():
    kb = kb_loader.load_kb()
    token = load_first_key()
    if not token:
        print("[re-run] no usable Ollama key")
        return 1

    approved_rows = load_approved_rows()
    approved_urls = {str(r.get("job_url") or "").strip() for r in approved_rows if str(r.get("job_url") or "").strip()}
    print(f"[re-run] approved CSV rows: {len(approved_rows)} | unique urls: {len(approved_urls)}")

    previous = load_previous_records()
    records = list(previous.values())

    parked_jobs = [r for r in records if str(r.get("status", "")) == "parked"]
    print(f"[re-run] parked jobs to retry: {len(parked_jobs)}")

    todo_urls = set()
    for r in parked_jobs:
        url = str(r.get("job_url") or "")
        if not url or url not in approved_urls:
            print(f"[re-run] skip non-approved parked job: {url}")
            continue
        todo_urls.add(url)

    print(f"[re-run] approved parked jobs to retry: {len(todo_urls)}")

    if not todo_urls:
        print("[re-run] nothing to retry")
        return write_final_csv(records, approved_rows)

    # Re-run step 4 only for the approved parked urls. Veoneer's posting lists
    # ISO numbers as preferred frameworks, but the candidate KB has no evidence
    # for those certifications/standards. Remove only those unsupported terms
    # from its prompt-side analysis; do not alter the gate or candidate facts.
    components_path = OUT_DIR / "components_v2.json"
    records_by_url = {str(r.get("job_url") or ""): r for r in records}
    for idx, job in enumerate(approved_rows, 1):
        url = str(job.get("job_url") or "").strip()
        if url not in todo_urls:
            continue
        print(f"[re-run] [{idx}/{len(approved_rows)}] retry {(job.get('title') or '')[:60]}")
        generation_job = dict(job)
        if "veoneer" in url.lower():
            forbidden_standards = ("ISO 27001", "ISO 22301", "TISAX")
            for key in ("job_description", "requirements", "applicant_profile", "your_tasks", "about_us", "what_they_offer", "snippet"):
                text = str(generation_job.get(key) or "")
                for standard in forbidden_standards:
                    text = text.replace(standard, "")
                generation_job[key] = text
            print("    omitted unsubstantiated certification/framework claims from candidate-generation prompt")
        record = process_job(generation_job, token, kb, tailor=True)
        print(f"    -> {record['status']}" + (f" ({record['error'][:90]})" if record.get("error") else ""))
        records_by_url[url] = record
        save_output(list(records_by_url.values()), components_path)

    new_records = list(records_by_url.values())
    ok = sum(1 for r in new_records if r.get("status") == "gated_ok")
    parked = sum(1 for r in new_records if r.get("status") == "parked")
    print(f"[re-run] step4 summary: {ok} gated_ok, {parked} parked")

    # Step 5 build for the newly gated_ok jobs (resume artifacts)
    new_verified = [r for r in new_records
                    if r.get("status") == "gated_ok" and str(r.get("job_url") or "") in todo_urls]
    print(f"[re-run] building resumes for {len(new_verified)} newly gated_ok jobs")

    engine = find_latex_engine()
    resume_results = []
    seen_names = {}
    for record in new_verified:
        title = record.get("title") or "resume"
        name = safe_name(title)
        if name in seen_names:
            seen_names[name] += 1
            name = f"{name}-{seen_names[name]}"
        else:
            seen_names[name] = 1
        result = build_record(record, engine, name=name)
        result["file_stem"] = name
        resume_results.append(result)
        print(f"    resume -> {result['status']}" + (f" score={result['score']}" if result.get("score") is not None else "") + (f" ({result['build_error'][:80]})" if result.get("build_error") else ""))

    # Write step5 resume report (merge existing + new)
    old_report = {}
    if config.REPORT_PATH.exists():
        try:
            old_report = json.loads(config.REPORT_PATH.read_text(encoding="utf-8"))
        except Exception:
            old_report = {}
    old_results = {str(r.get("job_url") or ""): r for r in (old_report.get("results") or []) if isinstance(r, dict)}
    merged_results = []
    new_resume_by_url = {str(r.get("job_url") or ""): r for r in resume_results}
    for url, r in new_resume_by_url.items():
        merged_results.append(r)
    for url, old in old_results.items():
        if url not in new_resume_by_url:
            merged_results.append(old)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "v2",
        "total_jobs": len(merged_results),
        "results": merged_results,
    }
    config.REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Step 6 letters only for jobs whose resumes newly passed the gates.
    letter_records = new_verified
    print(f"[re-run] creating letters for {len(letter_records)} jobs")

    engine = find_latex_engine()
    results = []
    seen_stems = {}
    for record in letter_records:
        url = str(record.get("job_url") or "")
        label = str(record.get("title") or "?")[:60]
        print(f"[re-run] letter {label}")
        probe = letter_stem_for(str(record.get("title") or ""), str(record.get("company") or ""))
        build_stem = probe
        if probe:
            if probe in seen_stems:
                seen_stems[probe] += 1
                build_stem = f"{probe}-{seen_stems[probe]}"
            else:
                seen_stems[probe] = 1
        result = build_letter(record, kb, token, engine, stem_override=build_stem or None)
        if result.get("letter_error"):
            print(f"    -> letter parked: {result['letter_error'][:100]}")
        elif result.get("letter_gates_passed"):
            print(f"    -> letter verified -> {result.get('file_stem')}")
        results.append(result)

    # Merge letters report
    old_letters = {}
    if config.LETTERS_REPORT_PATH.exists():
        try:
            old_letters = json.loads(config.LETTERS_REPORT_PATH.read_text(encoding="utf-8"))
        except Exception:
            old_letters = {}
    old_letter_results = {str(r.get("job_url") or ""): r for r in (old_letters.get("results") or []) if isinstance(r, dict)}
    merged_letter_results = []
    new_letters_by_url = {str(r.get("job_url") or ""): r for r in results}
    for url, r in new_letters_by_url.items():
        merged_letter_results.append(r)
    for url, old in old_letter_results.items():
        if url not in new_letters_by_url:
            merged_letter_results.append(old)

    letters_report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "v2",
        "total_jobs": len(letter_records) + len([u for u in old_letter_results if u not in {str(r.get('job_url') or '') for r in results}]),
        "results": merged_letter_results,
    }
    config.LETTERS_REPORT_PATH.write_text(json.dumps(letters_report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Update approved_applications.csv with all results
    approved_apps = Path(OUT_DIR / "approved_applications.csv")
    write_approved_applications_csv(merged_results, merged_letter_results, approved_rows)

    # Final CSV with job_role, job_link, resume_location, cover_letter_location
    final_csv = OUT_DIR / "final_applications.csv"
    write_final_csv_from_results(merged_results, merged_letter_results, approved_rows, final_csv)
    validate_final_csv(final_csv, approved_rows)
    print(f"[re-run] final CSV -> {final_csv}")
    return 0


def write_approved_applications_csv(resume_results, letter_results, approved_rows):
    url_to_resume = {str(r.get("job_url") or ""): r for r in resume_results if isinstance(r, dict)}
    url_to_letter = {str(r.get("job_url") or ""): r for r in letter_results if isinstance(r, dict)}
    approved_by_url = {str(r.get("job_url") or "").strip(): r for r in approved_rows if str(r.get("job_url") or "").strip()}

    out_path = OUT_DIR / "approved_applications.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "job_link", "company", "job_role", "status", "score", "resume_pdf", "resume_pdf_exists",
            "resume_docx", "resume_docx_exists", "tailoring_applied", "letter_pdf", "letter_pdf_exists",
            "letter_docx", "letter_docx_exists", "letter_txt", "letter_txt_exists",
            "upload_slot", "notes", "missing_artifacts", "artifacts_complete",
        ])
        for url, row in approved_by_url.items():
            rr = url_to_resume.get(url, {})
            lr = url_to_letter.get(url, {})
            resume_pdf = rr.get("pdf") or ""
            resume_docx = rr.get("docx") or ""
            letter_pdf = (lr.get("artifacts") or {}).get("letter_pdf") or ""
            letter_docx = (lr.get("artifacts") or {}).get("letter_docx") or ""
            letter_txt = (lr.get("artifacts") or {}).get("letter_txt") or ""
            status = "verified" if (resume_pdf and letter_pdf) else ("parked" if not resume_pdf else "partial")
            missing = []
            if not resume_pdf:
                missing.append("resume_pdf")
            if not resume_docx:
                missing.append("resume_docx")
            if not letter_pdf:
                missing.append("letter_pdf")
            if not letter_txt:
                missing.append("letter_txt")
            writer.writerow([
                url,
                row.get("company", ""),
                row.get("job_role") or row.get("title") or "",
                status,
                rr.get("score", ""),
                resume_pdf,
                str(Path(resume_pdf).exists()).lower() if resume_pdf else "false",
                resume_docx,
                str(Path(resume_docx).exists()).lower() if resume_docx else "false",
                "true" if (rr.get("tailoring") not in (None, {})) else "false",
                letter_pdf,
                str(Path(letter_pdf).exists()).lower() if letter_pdf else "false",
                letter_docx,
                str(Path(letter_docx).exists()).lower() if letter_docx else "false",
                letter_txt,
                str(Path(letter_txt).exists()).lower() if letter_txt else "false",
                (lr.get("upload_slot") or ""),
                (lr.get("notes") or ""),
                "; ".join(missing),
                "true" if not missing else "false",
            ])
    print(f"[re-run] approved_applications.csv -> {out_path}")


def write_final_csv_from_results(resume_results, letter_results, approved_rows, final_csv):
    url_to_resume = {str(r.get("job_url") or ""): r for r in resume_results if isinstance(r, dict)}
    url_to_letter = {str(r.get("job_url") or ""): r for r in letter_results if isinstance(r, dict)}
    approved_by_url = {str(r.get("job_url") or "").strip(): r for r in approved_rows if str(r.get("job_url") or "").strip()}

    with final_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["job_role", "job_link", "resume_location", "cover_letter_location"])
        for url, row in approved_by_url.items():
            rr = url_to_resume.get(url, {})
            lr = url_to_letter.get(url, {})
            resume_pdf = rr.get("pdf") or ""
            letter_pdf = (lr.get("artifacts") or {}).get("letter_pdf") or ""
            role = row.get("job_role") or row.get("title") or ""
            writer.writerow([role, url, resume_pdf, letter_pdf])
    print(f"[re-run] final_applications.csv -> {final_csv}")


def validate_final_csv(final_csv, approved_rows):
    expected_header = ["job_role", "job_link", "resume_location", "cover_letter_location"]
    with final_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != expected_header:
            raise RuntimeError(f"final CSV columns mismatch: {reader.fieldnames!r}")
        rows = list(reader)
    approved_urls = [str(r.get("job_url") or "").strip() for r in approved_rows]
    output_urls = [r["job_link"] for r in rows]
    if output_urls != approved_urls:
        raise RuntimeError("final CSV URL sequence does not exactly match the approved CSV")
    missing_paths = []
    for row in rows:
        for field in ("resume_location", "cover_letter_location"):
            path = row[field]
            if path and not Path(path).is_file():
                missing_paths.append((row["job_link"], field, path))
    parked = [r for r in rows if not r["resume_location"] or not r["cover_letter_location"]]
    print(f"[verify] final CSV header exact; rows={len(rows)}; approved URLs exact={len(output_urls)==len(approved_urls)}")
    print(f"[verify] populated paths missing on disk: {len(missing_paths)}; rows with unresolved output(s): {len(parked)}")
    if missing_paths:
        raise RuntimeError(f"final CSV contains paths missing on disk: {missing_paths[:3]}")
    for row in parked:
        print(f"[verify] unresolved: {row['job_role']} | {row['job_link']} | resume={bool(row['resume_location'])} letter={bool(row['cover_letter_location'])}")


def write_final_csv(records, approved_rows):
    # Fallback if nothing retried
    final_csv = OUT_DIR / "final_applications.csv"
    url_to_resume = {}
    url_to_letter = {}
    if config.REPORT_PATH.exists():
        try:
            report = json.loads(config.REPORT_PATH.read_text(encoding="utf-8"))
            url_to_resume = {str(r.get("job_url") or ""): r for r in (report.get("results") or []) if isinstance(r, dict)}
        except Exception:
            pass
    if config.LETTERS_REPORT_PATH.exists():
        try:
            report = json.loads(config.LETTERS_REPORT_PATH.read_text(encoding="utf-8"))
            url_to_letter = {str(r.get("job_url") or ""): r for r in (report.get("results") or []) if isinstance(r, dict)}
        except Exception:
            pass
    approved_by_url = {str(r.get("job_url") or "").strip(): r for r in approved_rows if str(r.get("job_url") or "").strip()}
    with final_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["job_role", "job_link", "resume_location", "cover_letter_location"])
        for url, row in approved_by_url.items():
            rr = url_to_resume.get(url, {})
            lr = url_to_letter.get(url, {})
            resume_pdf = rr.get("pdf") or ""
            letter_pdf = (lr.get("artifacts") or {}).get("letter_pdf") or ""
            role = row.get("job_role") or row.get("title") or ""
            writer.writerow([role, url, resume_pdf, letter_pdf])
    print(f"[re-run] final_applications.csv (fallback) -> {final_csv}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
