"""Bosch pipeline step 5: build the final per-job resumes (PDF + DOCX).

Reuses the bundled assembler program_files/5_create_resume.py unchanged -
template filling, LaTeX escaping, tectonic compile and DOCX mirror all come
from that module. Only the I/O locations are redirected:

  master job list : program_files/output_bosch/todays_overall_jobs.csv
                    (written here from the step-4 adapted CSV)
  component stores: program_files/output_bosch/{career_objective,experience,
                    projects,skills}.json (written by Bosch step 4)
  outputs         : program_files/output_bosch/resume/{tex,pdf,docx}/
  report          : program_files/output_bosch/resume_report.json

Exits 0 only when every Bosch resume compiled successfully.

Run directly (from anywhere): python 5_final_resume.py
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd

# Self-contained: PROJECT_ROOT is this folder itself, which bundles
# program_files/, sub_program_files/ and tools/ (no outside project needed).
PROJECT_ROOT = Path(__file__).resolve().parent
BOSCH_OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output_bosch"
OUTPUT_DIR = BOSCH_OUTPUT_DIR  # the reused builder resolves stores under this
ADAPTED_CSV = BOSCH_OUTPUT_DIR / "2_filted_jobs.csv"
MASTER_BOSCH_CSV = BOSCH_OUTPUT_DIR / "todays_overall_jobs.csv"

sys.path.insert(0, str(PROJECT_ROOT / "program_files"))

_builder = importlib.import_module("5_create_resume")


def write_master_csv() -> int:
    """Copy the step-4 adapted CSV to the master-list location step 5 reads."""
    frame = pd.read_csv(ADAPTED_CSV, keep_default_na=False)
    frame.to_csv(MASTER_BOSCH_CSV, index=False, encoding="utf-8")
    print(f"[STEP5] master job list -> {MASTER_BOSCH_CSV} ({len(frame)} job(s))")
    return len(frame)


def redirect_paths() -> None:
    """Point the existing builder's path globals at the Bosch output directory."""
    _builder.OUTPUT_DIR = BOSCH_OUTPUT_DIR
    _builder.TEX_DIR = BOSCH_OUTPUT_DIR / "resume" / "tex"
    _builder.PDF_DIR = BOSCH_OUTPUT_DIR / "resume" / "pdf"
    _builder.DOCX_DIR = BOSCH_OUTPUT_DIR / "resume" / "docx"


def main() -> int:
    """Build every Bosch resume via the existing assembler; return its exit code."""
    write_master_csv()
    redirect_paths()
    return int(_builder.main())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
