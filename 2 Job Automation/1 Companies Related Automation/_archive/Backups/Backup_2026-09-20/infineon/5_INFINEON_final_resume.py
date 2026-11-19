"""Infineon pipeline step 5: build the final per-job resumes (PDF + DOCX).

Same method, same code as the Mercedes pipeline (folder twin). Reuses the
bundled assembler program_files/5_create_resume.py unchanged - template
filling, LaTeX escaping, tectonic compile and DOCX mirror all come from that
module. Only the I/O locations are redirected:

  master job list : program_files/output_infineon/todays_overall_jobs.csv
                    (written here from the step-4 adapted CSV)
  component stores: program_files/output_infineon/{career_objective,experience,
                    projects,skills}.json (written by Infineon step 4)
  outputs         : program_files/output_infineon/resume/{tex,pdf,docx}/
  report          : program_files/output_infineon/resume_report.json
                    plus job_resume_map.csv (job_url -> resume PDF, what the
                    apply step auto-picks from)

This folder is fully self-contained: every module, prompt, key and tool it
needs lives inside it. Exits 0 only when every Infineon resume compiled.

Run directly (from anywhere): python 5_INFINEON_final_resume.py
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pandas as pd

# Self-contained: PROJECT_ROOT is this folder itself, which bundles
# program_files/, sub_program_files/ and tools/ (no outside project needed).
PROJECT_ROOT = Path(__file__).resolve().parent
INFINEON_OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output_infineon"
ADAPTED_CSV = INFINEON_OUTPUT_DIR / "2_filted_jobs.csv"
MASTER_CSV = INFINEON_OUTPUT_DIR / "todays_overall_jobs.csv"

sys.path.insert(0, str(PROJECT_ROOT / "program_files"))

_builder = importlib.import_module("5_create_resume")


def write_master_csv() -> int:
    """Copy the step-4 adapted CSV to the master-list location step 5 reads."""
    frame = pd.read_csv(ADAPTED_CSV, keep_default_na=False)
    frame.to_csv(MASTER_CSV, index=False, encoding="utf-8")
    print(f"[STEP5] master job list -> {MASTER_CSV} ({len(frame)} job(s))")
    return len(frame)


def redirect_paths() -> None:
    """Point the existing builder's path globals at the Infineon output directory."""
    _builder.OUTPUT_DIR = INFINEON_OUTPUT_DIR
    _builder.TEX_DIR = INFINEON_OUTPUT_DIR / "resume" / "tex"
    _builder.PDF_DIR = INFINEON_OUTPUT_DIR / "resume" / "pdf"
    _builder.DOCX_DIR = INFINEON_OUTPUT_DIR / "resume" / "docx"
    _builder.TEMPLATE_TEX = PROJECT_ROOT / "sub_program_files" / "resume_content" / "core_resume_template.tex"
    _builder.TECTONIC_CANDIDATES = (
        PROJECT_ROOT / "tools" / "tectonic.exe",
    )


def write_job_resume_map() -> Path:
    """Convert resume_report.json into job_resume_map.csv (job_url -> resume PDF).

    Duplicate postings aliased in job_url_aliases.csv (same role listed under
    several pids) get a map row per posting URL, all pointing at the same
    tailored resume, so the apply step auto-picks for EVERY posting URL.
    """
    report = json.loads((INFINEON_OUTPUT_DIR / "resume_report.json").read_text(encoding="utf-8"))
    map_path = INFINEON_OUTPUT_DIR / "job_resume_map.csv"
    rows = []
    for record in report.get("results", []):
        status = "OK" if (record.get("pdf") and record.get("docx") and not record.get("error")) else "FAILED"
        rows.append({
            "job_url": record.get("job_url", ""),
            "title": record.get("title", ""),
            "resume_pdf": record.get("pdf", ""),
            "resume_docx": record.get("docx", ""),
            "status": status,
            "error": record.get("error", ""),
        })
        # Expand aliases for successfully built resumes.
        if status == "OK":
            aliases_path = INFINEON_OUTPUT_DIR / "job_url_aliases.csv"
            if aliases_path.exists():
                aliases = pd.read_csv(aliases_path, keep_default_na=False)
                for _, alias in aliases.iterrows():
                    if str(alias.get("kept_job_url") or "") == str(record.get("job_url") or ""):
                        rows.append({
                            "job_url": str(alias.get("dropped_job_url") or ""),
                            "title": str(record.get("title", "")) + " (duplicate posting)",
                            "resume_pdf": record.get("pdf", ""),
                            "resume_docx": record.get("docx", ""),
                            "status": "OK",
                            "error": "",
                        })
    pd.DataFrame(
        rows, columns=["job_url", "title", "resume_pdf", "resume_docx", "status", "error"]
    ).to_csv(map_path, index=False, encoding="utf-8")
    print(f"[STEP5] job->resume map ({len(rows)} rows incl. duplicate-posting aliases) -> {map_path}")
    return map_path


def main() -> int:
    """Build every Infineon resume via the existing assembler; return its exit code."""
    write_master_csv()
    redirect_paths()
    code = int(_builder.main())
    write_job_resume_map()
    return code


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
