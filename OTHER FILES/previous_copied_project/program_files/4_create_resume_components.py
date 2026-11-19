"""Step 4: create the per-job resume components (pipeline stage for resume sections).

Runs the four generation stages from sub_program_files/resume_content against the
filtered jobs CSV (program_files/output/2_filted_jobs.csv):

  1_career_objective.py -> program_files/output/career_objective.json
  2_experience.py       -> program_files/output/experience.json
  3_projects.py         -> program_files/output/projects.json
  4_skills.py           -> program_files/output/skills.json

Each stage calls the Ollama model via ollama_request_response and manages its own
TEST_JOB_LIMIT constant (open the stage file to change it). A stage failure is
reported with a traceback and does not stop the other stages. Exits 0 only when
every stage succeeded.

Run directly: python program_files/4_create_resume_components.py
"""
from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESUME_CONTENT_DIR = PROJECT_ROOT / "sub_program_files" / "resume_content"
OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output"

sys.path.insert(0, str(RESUME_CONTENT_DIR))

# (label, module name in resume_content, output file, records key, error field)
SUBSTAGES = [
    ("1 career objective", "1_career_objective", "career_objective.json", "objectives", "objective_error"),
    ("2 experience", "2_experience", "experience.json", "experiences", "experience_error"),
    ("3 projects", "3_projects", "projects.json", "projects", "projects_error"),
    ("4 skills", "4_skills", "skills.json", "skills", "skills_error"),
]


def run_substage(label: str, module_name: str) -> bool:
    """Import and run one stage module; True when its main() exited 0."""
    print(f"\n=== STEP 4 | {label} ===")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 - report any import problem clearly
        print(f"[STEP4] ERROR importing {module_name}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False
    try:
        code = module.main()
        return int(code or 0) == 0
    except SystemExit as exc:  # stage __main__-style exits
        return int(exc.code or 0) == 0
    except Exception as exc:  # noqa: BLE001 - one stage must not stop the others
        print(f"[STEP4] {label} FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False


def summarize() -> None:
    """Report how many records each output JSON holds and how many need review."""
    print("\n=== STEP 4 | SUMMARY ===")
    for _, _, file_name, records_key, error_field in SUBSTAGES:
        path = OUTPUT_DIR / file_name
        if not path.exists():
            print(f"  [MISSING] {file_name}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [ERROR] {file_name}: {exc}")
            continue
        records = payload.get(records_key, [])
        flagged = sum(1 for record in records if record.get(error_field))
        print(f"  [OK] {file_name}: {len(records)} record(s), {flagged} flagged for review")


def main() -> int:
    """Run all four resume-component stages and summarize; 0 when all succeeded."""
    results = [(label, run_substage(label, module_name)) for label, module_name, _, _, _ in SUBSTAGES]
    ok = all(success for _, success in results)

    summarize()

    print("\n=== STEP 4 | RESULT ===")
    for label, success in results:
        print(f"  [{'OK  ' if success else 'FAIL'}] {label}")
    print(f"step 4 {'SUCCESS' if ok else 'HAD FAILURES'} (exit code {0 if ok else 1})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
