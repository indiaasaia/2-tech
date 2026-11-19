"""SAP pipeline step 4: keep English-friendly jobs and generate resume components.

Two parts:
  A) Language filter: run 2_language_differntiate.py over sap_results.csv
     (adds Language_Filter + Filter_Evidence columns in place) and keep only
     the ENGLISH_OK jobs.
  B) Resume components: map the SAP CSV onto the column schema the resume
     generators expect (source/title/company/location/posted_time/job_url/
     job_description), write program_files/output_sap/2_filted_jobs.csv, and
     run the four generation stages from sub_program_files/resume_content
     (1_career_objective, 2_experience, 3_projects, 4_skills) against that
     file. All outputs use the same file names as the original project but
     live in program_files/output_sap/ inside this folder.

This folder is fully self-contained (own copies of the resume stages,
prompts, LLM helper, keys and tectonic).

Every stage runs via its main(input_csv=..., output_json=...) signature, so the
generation logic itself is 100% the existing code. One failed stage is reported
and does not stop the others. Exits 0 only when every stage succeeded.

Run directly (from anywhere): python 4_resume_create.py
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import pandas as pd

# Self-contained: PROJECT_ROOT is this folder itself, which bundles
# program_files/, sub_program_files/ and tools/ (no outside project needed).
PROJECT_ROOT = Path(__file__).resolve().parent
SAP_DIR = PROJECT_ROOT
# All SAP artifacts live in their own output directory, so the main
# pipeline's program_files/output is never touched.
SAP_OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output_sap"

SAP_RESULTS_CSV = SAP_DIR / "sap_results.csv"
ADAPTED_CSV = SAP_OUTPUT_DIR / "2_filted_jobs.csv"

sys.path.insert(0, str(SAP_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "sub_program_files"))
sys.path.insert(0, str(PROJECT_ROOT / "sub_program_files" / "resume_content"))

# (label, module name, output json inside output_sap)
STAGES = [
    ("1 career objective", "1_career_objective", "career_objective.json"),
    ("2 experience", "2_experience", "experience.json"),
    ("3 projects", "3_projects", "projects.json"),
    ("4 skills", "4_skills", "skills.json"),
]

# SAP CSV -> resume-generator column schema. source marks the rows for step 5.
COLUMN_MAP = {
    "Job Title": "title",
    "Link": "job_url",
    "Description": "job_description",
    "Location": "location",
}
COMPANY_VALUE = "SAP"


def language_filter() -> int:
    """Classify sap_results.csv in place and keep only ENGLISH_OK jobs.

    Returns the number of English-friendly jobs.
    """
    lang = importlib.import_module("2_language_differntiate")
    rows = lang.classify_jobs(str(SAP_RESULTS_CSV))
    english = [r for r in rows if r.get("Language_Filter") == "ENGLISH_OK"]
    print(f"[STEP4] language filter: {len(english)}/{len(rows)} job(s) are ENGLISH_OK")
    if not english:
        raise RuntimeError("no ENGLISH_OK jobs in sap_results.csv - nothing to do")
    return len(english)


def build_adapted_csv() -> int:
    """Map ENGLISH_OK SAP rows onto the resume-generator schema.

    Returns the number of jobs written.
    """
    frame = pd.read_csv(SAP_RESULTS_CSV, keep_default_na=False, encoding="utf-8-sig")
    frame = frame[frame["Language_Filter"] == "ENGLISH_OK"].reset_index(drop=True)

    adapted = pd.DataFrame({
        "source": "sap",
        "title": frame["Job Title"],
        "company": COMPANY_VALUE,
        "location": frame["Location"],
        "posted_time": frame["Posted Date"],
        "job_url": frame["Link"],
        "job_description": frame["Description"],
    })
    # The generators truncate to the first N chars themselves; drop exact
    # duplicate postings (SAP lists the same job twice with different IDs).
    adapted = adapted.drop_duplicates(subset=["job_description"]).reset_index(drop=True)

    if adapted.empty:
        raise RuntimeError("no English-friendly jobs survived de-duplication")

    SAP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    adapted.to_csv(ADAPTED_CSV, index=False, encoding="utf-8")
    print(f"[STEP4] wrote {len(adapted)} English-friendly SAP job(s) -> {ADAPTED_CSV}")
    return len(adapted)


def _usable_records(output_json: Path) -> tuple[int, int]:
    """Count (usable, flagged) records in a stage output JSON."""
    import json

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    for key in ("objectives", "experiences", "projects", "skills"):
        records = payload.get(key)
        if records is not None:
            break
    else:
        return 0, 0
    error_fields = ("objective_error", "experience_error", "projects_error", "skills_error")
    error_field = next((f for f in error_fields if records and f in records[0]), None)
    if error_field is None:
        return len(records), 0
    usable = sum(1 for r in records if not r.get(error_field))
    return usable, len(records) - usable


def run_stage(label: str, module_name: str, output_json_name: str) -> bool:
    """Run one existing generation stage with SAP input/output paths.

    The stage exit code alone is too strict: e.g. 4_skills returns 1 when a
    job is merely flagged for review (thin section), while the record is still
    saved and step 5 excludes flagged jobs anyway. So the stage counts as OK
    when it did not crash AND at least one usable record was saved.
    """
    print(f"\n=== STEP 4 | {label} ===")
    output_json = SAP_OUTPUT_DIR / output_json_name
    try:
        module = importlib.import_module(module_name)
        module.main(input_csv=ADAPTED_CSV, output_json=output_json)
    except SystemExit as exc:  # stage __main__-style exits
        if int(exc.code or 0) not in (0, 1):
            print(f"[STEP4] {label} FAILED: abnormal exit {exc.code}")
            return False
    except Exception as exc:  # noqa: BLE001 - one stage must not stop the others
        print(f"[STEP4] {label} FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False

    try:
        usable, flagged = _usable_records(output_json)
    except Exception as exc:  # noqa: BLE001 - unreadable output = stage failure
        print(f"[STEP4] {label} FAILED: output unreadable: {exc}")
        return False
    if usable == 0:
        print(f"[STEP4] {label} FAILED: no usable records in {output_json.name}")
        return False
    print(f"[STEP4] {label}: {usable} usable, {flagged} flagged for review -> OK")
    return True


def main() -> int:
    """Filter by language, adapt the schema, run all four stages; exit code."""
    language_filter()
    build_adapted_csv()

    results = [(label, run_stage(label, module_name, output_json))
               for label, module_name, output_json in STAGES]
    ok = all(success for _, success in results)

    print("\n=== STEP 4 | SUMMARY ===")
    for label, success in results:
        print(f"  [{'OK  ' if success else 'FAIL'}] {label}")
    print(f"step 4 (SAP) {'SUCCESS' if ok else 'HAD FAILURES'} (exit code {0 if ok else 1})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
