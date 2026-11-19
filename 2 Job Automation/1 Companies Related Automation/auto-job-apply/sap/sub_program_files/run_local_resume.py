"""Master runner for local resume generation stages (1 to 5).

Runs:
  1. sub_program_files/resume_content/1_career_objective.py
  2. sub_program_files/resume_content/2_experience.py
  3. sub_program_files/resume_content/3_projects.py
  4. sub_program_files/resume_content/4_skills.py
  5. sub_program_files/resume_content/5_create_resume.py

Outputs:
  - sub_program_files/output/*.json
  - sub_program_files/output/resume/pdf/*.pdf
  - sub_program_files/output/job_resume_map_local.csv
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGES = [
    ("1. Career Objective", ROOT / "resume_content" / "1_career_objective.py"),
    ("2. Experience", ROOT / "resume_content" / "2_experience.py"),
    ("3. Projects", ROOT / "resume_content" / "3_projects.py"),
    ("4. Skills", ROOT / "resume_content" / "4_skills.py"),
    ("5. Build LaTeX & PDFs", ROOT / "resume_content" / "5_create_resume.py"),
]


def run_local_pipeline() -> int:
    print("=== LOCAL RESUME GENERATION PIPELINE ===")
    for name, script in STAGES:
        print(f"\n--- Running Stage: {name} ---")
        if not script.exists():
            print(f"ERROR: Stage script not found: {script}")
            return 1
        res = subprocess.run([sys.executable, str(script)], check=False)
        if res.returncode != 0:
            print(f"ERROR: Stage failed with returncode {res.returncode}: {name}")
            return res.returncode
    print("\n=== LOCAL RESUME GENERATION COMPLETE ===")
    return 0


if __name__ == "__main__":
    sys.exit(run_local_pipeline())
