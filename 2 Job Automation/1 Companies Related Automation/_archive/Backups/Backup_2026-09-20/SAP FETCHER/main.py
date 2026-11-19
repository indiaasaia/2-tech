"""SAP pipeline runner: fetch -> filter by language -> keys -> components -> resumes.

This folder is fully self-contained: it bundles its own copies of the resume
stages, prompts, LLM helper, Ollama keys, LaTeX template and tectonic.exe
(program_files/, sub_program_files/, tools/), so it runs from anywhere with
no outside project needed. Just keep the folder structure intact.

Runs the five SAP steps in order. A failure in one step is reported with a
traceback and does not stop the others; the exit code is 0 only when every
step succeeded.

  1_sap_job_fetcher.py        -> sap_results.csv (all jobs, full details)
  2_language_differntiate.py  -> Language_Filter / Filter_Evidence columns
  3_ollama_keys.py            -> sub_program_files/active_ollama_keys.json
  4_resume_create.py          -> program_files/output_sap/... components
  5_final_resume.py           -> program_files/output_sap/resume/{pdf,docx}

Run (from anywhere): python main.py   (inside this folder)
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent  # self-contained: this folder is the project root
SAP_DIR = PROJECT_ROOT

sys.path.insert(0, str(SAP_DIR))


def _import_step(module_name: str, function_name: str) -> Callable:
    """Import a pipeline-step function; exits with a clear message if that fails."""
    try:
        module = importlib.import_module(module_name)
        return getattr(module, function_name)
    except Exception as exc:  # noqa: BLE001 - report any import problem, not just ImportError
        print(f"[MAIN] ERROR importing {module_name}.{function_name}: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc


def run_step(name: str, fn: Callable) -> bool:
    """Run one pipeline step, catching and printing any error with a traceback."""
    print(f"\n=== {name} ===")
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - any step failure must be caught and reported
        print(f"[MAIN] {name} FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False
    print(f"[MAIN] {name} finished (returned {result})")
    return True


def main() -> int:
    steps = [
        ("STEP 1 | fetch all SAP werkstudent jobs", _import_step("1_sap_job_fetcher", "sap_job_fetcher")),
        ("STEP 2 | language filter (ENGLISH_OK / GERMAN_REQUIRED)", _import_step("2_language_differntiate", "classify_jobs")),
        ("STEP 3 | test ollama keys", _import_step("3_ollama_keys", "test_ollama_keys")),
        ("STEP 4 | resume components for English-friendly jobs", _import_step("4_resume_create", "main")),
        ("STEP 5 | build final resumes (pdf + docx)", _import_step("5_final_resume", "main")),
    ]

    results = [(name, run_step(name, fn)) for name, fn in steps]
    ok = all(success for _, success in results)

    print("\n=== SUMMARY ===")
    for name, success in results:
        print(f"  [{'OK  ' if success else 'FAIL'}] {name}")
    print(f"SAP pipeline {'SUCCESS' if ok else 'HAD FAILURES'} (exit code {0 if ok else 1})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
