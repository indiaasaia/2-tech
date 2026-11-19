"""Bosch pipeline runner: fetch -> language filter -> keys -> components -> resumes -> apply.

This folder is fully self-contained: it bundles its own copies of the resume
stages, prompts, LLM helper, Ollama keys, LaTeX template and tectonic.exe
(program_files/, sub_program_files/, tools/), so it runs from anywhere with
no outside project needed. Just keep the folder structure intact.

Runs the Bosch steps in order. A failure in one step is reported with a
traceback and does not stop the others; the exit code is 0 only when every
step succeeded.

  1_bosch_Jobs_fetching.py    -> BOSCH_results.csv + BOSCH_jobs_detailed.csv
                                 + BOSCH_jobs_full.json (all jobs, full details)
  2_language_differntiate.py  -> Language_Filter / Filter_Evidence columns (in place)
  3_ollama_keys.py            -> sub_program_files/active_ollama_keys.json
  4_resume_create.py          -> program_files/output_bosch/... components
  5_final_resume.py           -> program_files/output_bosch/resume/{pdf,docx}
  6_apply_to_jobs.py          -> program_files/output_bosch/apply_report.json
                                 (dry-run by default; use 6_apply_to_jobs.py
                                 --submit for real applications)

Run (from anywhere): python main.py   (inside this folder)
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent  # self-contained: this folder is the project root

sys.path.insert(0, str(PROJECT_ROOT))


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


def fetch_all_bosch_jobs() -> int:
    """Step 1: list page + detail fetch. The two functions are chained here
    because enrich_jobs_with_details(jobs) consumes sap_job_fetcher()'s list.
    Returns the number of failed detail fetches (0 = everything fetched)."""
    module = importlib.import_module("1_bosch_Jobs_fetching")
    jobs = module.sap_job_fetcher()
    print(f"[MAIN] fetched {len(jobs)} job listing(s); enriching every job ...")
    records, failed = module.enrich_jobs_with_details(jobs)
    return len(failed)  # 0 failures keeps the whole step green


def main() -> int:
    steps = [
        ("STEP 1 | fetch all Bosch student jobs (list + details)", fetch_all_bosch_jobs),
        ("STEP 2 | language filter (ENGLISH_OK / GERMAN_REQUIRED)", _import_step("2_language_differntiate", "classify_jobs")),
        ("STEP 3 | test ollama keys", _import_step("3_test_ollama_keys", "test_ollama_keys")),
        ("STEP 4 | resume components for English-friendly jobs", _import_step("4_resume_create", "main")),
        ("STEP 5 | build final resumes (pdf + docx)", _import_step("5_final_resume", "main")),
    ]

    results = [(name, run_step(name, fn)) for name, fn in steps]
    ok = all(success for _, success in results)

    print("\n=== SUMMARY ===")
    for name, success in results:
        print(f"  [{'OK  ' if success else 'FAIL'}] {name}")
    print(f"Bosch pipeline {'SUCCESS' if ok else 'HAD FAILURES'} (exit code {0 if ok else 1})")
    print("Next: python 6_apply_to_jobs.py            # dry-run the configured job")
    print("      python 6_apply_to_jobs.py --all      # dry-run every tailored job")
    print("      python 6_apply_to_jobs.py --submit   # real submission (asks YES)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
