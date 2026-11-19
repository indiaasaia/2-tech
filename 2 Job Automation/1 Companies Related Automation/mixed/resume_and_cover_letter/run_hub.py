"""Unified Resume and Cover Letter Hub Runner (Steps 4 + 5 + 6).

Runs the V2 engine for any company with full per-company state isolation:
  Step 4: LLM component generation & letter_input capture (KB-grounded)
  Step 5: Resume compilation (tectonic), G1-G3 verification gates, scorecard
  Step 6: Cover letter generation (DIN 5008 de/en), L1-L4 gates, bundles

State outputs:
  output_v2/state/components_v2_<company>.json
  output_v2/state/resume_report_<company>.json
  output_v2/state/letters_report_<company>.json
  output_v2/state/application_bundles_<company>.json
  output_v2/state/job_bundle_map_<company>.csv
  output_v2/resume_<company>/{pdf, docx, tex}
  output_v2/letters_<company>/{pdf, docx, tex, textfield}
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prepare_jobs import prepare_for_company

OUTPUT_V2 = ROOT / "program_files" / "output_v2"
STATE_DIR = OUTPUT_V2 / "state"


ALIASES = {
    "siemens": ["siemens", "simense"],
    "simense": ["simense", "siemens"],
    "siemens_energy": ["siemens_energy", "simense_energy"],
    "simense_energy": ["simense_energy", "siemens_energy"],
}


def _state_path(kind: str, company: str) -> Path:
    candidates = ALIASES.get(company.lower(), [company.lower()])
    for cand in candidates:
        p = STATE_DIR / f"{kind}_{cand}.json"
        if p.exists():
            return p
    return STATE_DIR / f"{kind}_{company}.json"


def restore_state(company: str) -> None:
    """Restore this company's persistent state files into single-slot engine paths."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    slot_comp = OUTPUT_V2 / "components_v2.json"
    state_comp = _state_path("components_v2", company)

    if state_comp.exists():
        shutil.copy2(state_comp, slot_comp)
        print(f"[hub] Restored {state_comp.name} -> {slot_comp.name}")
    else:
        if slot_comp.exists():
            slot_comp.unlink()

    for kind in ("resume_report", "shortlist", "letters_report", "application_bundles"):
        slot = OUTPUT_V2 / f"{kind}.json"
        st = _state_path(kind, company)
        if st.exists():
            shutil.copy2(st, slot)


def clear_shared_builds() -> None:
    """Empty shared build dirs so artifacts are completely pristine for the run."""
    for sub in ("resume", "letters"):
        d = OUTPUT_V2 / sub
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def snapshot_state(company: str) -> None:
    """Snapshot engine single-slot outputs into per-company persistent folders."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    for kind in ("components_v2", "resume_report", "shortlist", "letters_report", "application_bundles"):
        src = OUTPUT_V2 / f"{kind}.json"
        if src.exists():
            shutil.copy2(src, _state_path(kind, company))

    # Snapshot resume artifacts
    for sub in ("tex", "pdf", "docx"):
        src_d = OUTPUT_V2 / "resume" / sub
        if src_d.exists() and any(src_d.iterdir()):
            dest_d = OUTPUT_V2 / f"resume_{company}" / sub
            dest_d.parent.mkdir(parents=True, exist_ok=True)
            if dest_d.exists():
                shutil.rmtree(dest_d)
            shutil.copytree(src_d, dest_d)

    # Snapshot letter artifacts
    for sub in ("tex", "pdf", "docx", "textfield"):
        src_d = OUTPUT_V2 / "letters" / sub
        if src_d.exists() and any(src_d.iterdir()):
            dest_d = OUTPUT_V2 / f"letters_{company}" / sub
            dest_d.parent.mkdir(parents=True, exist_ok=True)
            if dest_d.exists():
                shutil.rmtree(dest_d)
            shutil.copytree(src_d, dest_d)


def write_bundle_map(company: str) -> Path | None:
    """Write state/job_bundle_map_<company>.csv combining resume and cover letter artifacts."""
    resume_rep_path = _state_path("resume_report", company)
    letters_rep_path = _state_path("letters_report", company)
    bundles_path = _state_path("application_bundles", company)

    if not resume_rep_path.exists():
        return None

    resume_rep = json.loads(resume_rep_path.read_text(encoding="utf-8"))
    letters_rep = json.loads(letters_rep_path.read_text(encoding="utf-8")) if letters_rep_path.exists() else {}
    bundles = json.loads(bundles_path.read_text(encoding="utf-8")) if bundles_path.exists() else {}

    letters_by_url = {
        str(r.get("job_url") or ""): r
        for r in letters_rep.get("results", [])
        if isinstance(r, dict)
    }
    bundles_by_url = {
        str(b.get("job_url") or ""): b
        for b in bundles.get("bundles", [])
        if isinstance(b, dict)
    }

    rows: list[dict] = []
    for r in resume_rep.get("results", []):
        url = str(r.get("job_url") or "")
        stem = r.get("file_stem")
        pdf_path = OUTPUT_V2 / f"resume_{company}" / "pdf" / f"{stem}.pdf" if stem else None
        docx_path = OUTPUT_V2 / f"resume_{company}" / "docx" / f"{stem}.docx" if stem else None

        if r.get("status") == "verified" and pdf_path and pdf_path.is_file():
            let = letters_by_url.get(url, {})
            bundle = bundles_by_url.get(url, {})

            let_stem = let.get("file_stem")
            let_pdf = OUTPUT_V2 / f"letters_{company}" / "pdf" / f"{let_stem}.pdf" if let_stem else None
            let_txt = OUTPUT_V2 / f"letters_{company}" / "textfield" / f"{let_stem}.txt" if let_stem else None

            rows.append({
                "job_url": url,
                "status": "OK",
                "score": r.get("score", ""),
                "title": r.get("title", ""),
                "company": r.get("company", ""),
                "resume_pdf": str(pdf_path),
                "resume_docx": str(docx_path) if docx_path and docx_path.is_file() else "",
                "letter_pdf": str(let_pdf) if let_pdf and let_pdf.is_file() else "",
                "letter_txt": str(let_txt) if let_txt and let_txt.is_file() else "",
                "bundle_ready": "YES" if (let_pdf and let_pdf.is_file()) else "RESUME_ONLY",
            })

    if not rows:
        return None

    map_path = STATE_DIR / f"job_bundle_map_{company}.csv"
    fieldnames = ["job_url", "status", "score", "title", "company", "resume_pdf", "resume_docx", "letter_pdf", "letter_txt", "bundle_ready"]
    with map_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[hub] {company}: bundle map -> {map_path.name} ({len(rows)} verified application bundle(s))")
    return map_path


def run_hub(
    company: str,
    limit: int | None = None,
    jobs: str | None = None,
    force: bool = False,
    force_letters: bool = False,
    build_only: bool = False,
    no_letters: bool = False,
) -> int:
    """Run steps 4, 5, and 6 for a company."""
    started = time.time()
    company_id = company.lower()

    if not build_only:
        prepare_for_company(company_id, force=force, limit=limit)

    restore_state(company_id)
    clear_shared_builds()

    from resume_content_improve_research import run_step4, run_step5, run_step6

    if build_only:
        print(f"[hub] {company_id}: build-only mode -> skipping Step 4 (LLM generation)")
        step4_rc = 0
    else:
        print(f"\n[hub] == STEP 4 | Analysis & Constrained Components ({company_id}) ==")
        step4_rc = run_step4.run_pipeline(limit=limit, jobs=jobs, force=force)

    print(f"\n[hub] == STEP 5 | Build Resumes & Scorecard ({company_id}) ==")
    step5_rc = run_step5.main(limit=limit, jobs=jobs)

    step6_rc = 0
    if not no_letters:
        print(f"\n[hub] == STEP 6 | Create Cover Letters & Application Bundles ({company_id}) ==")
        step6_rc = run_step6.run_pipeline(jobs=jobs, force=force_letters, limit=limit)

    snapshot_state(company_id)
    write_bundle_map(company_id)

    elapsed = time.time() - started
    print(f"\n[hub] {company_id}: completed in {elapsed:.1f}s (step4={step4_rc}, step5={step5_rc}, step6={step6_rc})")
    return 0 if (step4_rc == 0 and step5_rc == 0 and step6_rc == 0) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified resume and cover letter hub")
    parser.add_argument("company", help="company id (e.g. bosch, mercedes, infineon, sap, bmw...)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--jobs", type=str, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-letters", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--no-letters", action="store_true")
    args = parser.parse_args()

    sys.exit(run_hub(
        company=args.company,
        limit=args.limit,
        jobs=args.jobs,
        force=args.force,
        force_letters=args.force_letters,
        build_only=args.build_only,
        no_letters=args.no_letters,
    ))
