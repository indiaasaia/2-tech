"""Mercedes pipeline runner: fetch -> filter/keys -> components -> resumes.

This folder is fully self-contained: it bundles its own copies of the resume
stages, prompts, LLM helper, Ollama keys, LaTeX template and tectonic.exe
(program_files/, sub_program_files/, tools/), so it runs from anywhere with
no outside project needed. Just keep the folder structure intact.

Pipeline (numbered by execution order; the resume stages run inside step 2):

  1_MERCEDES_Jobs_fetching.py     -> MERCEDES_results.csv / _detailed.csv / _full.json
  2_MERCEDES_create_resumes.py    -> program_files/output_mercedes/... components
                                     (language filter + schema bridge + 4 LLM stages)
  3_MERCEDES_ollama_keys.py       -> sub_program_files/active_ollama_keys.json
                                     (only needed when keys changed; step 2 re-checks)
  3_MERCEDES_final_resume.py      -> program_files/output_mercedes/resume/{pdf,docx}
  4_MERCEDES_job_apply.py         -> applies to ONE job with ITS OWN resume PDF

A failure in one step is reported with a traceback and does not stop the
others; the exit code is 0 only when every step succeeded.

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


def fetch_all_mercedes_jobs() -> int:
    """STEP 1 wrapper: fetch the job list, then enrich every job with details."""
    fetcher = importlib.import_module("1_MERCEDES_Jobs_fetching")
    jobs = fetcher.mercedes_job_fetcher()
    print(f"[MAIN] fetched {len(jobs)} listings; enriching with full details ...")
    records, failed = fetcher.enrich_mercedes_jobs_with_details(jobs)
    print(f"[MAIN] {len(records)} job(s) detailed, {len(failed)} failed")
    return len(records)


def main() -> int:
    steps = [
        ("STEP 1 | fetch all Mercedes werkstudent jobs", fetch_all_mercedes_jobs),
        ("STEP 2 | language filter + resume components", _import_step("2_MERCEDES_create_resumes", "main")),
        ("STEP 3 | test ollama keys", _import_step("3_MERCEDES_ollama_keys", "test_ollama_keys")),
        ("STEP 3b | build final resumes (pdf + docx)", _import_step("3_MERCEDES_final_resume", "main")),
    ]

    results = [(name, run_step(name, fn)) for name, fn in steps]
    ok = all(success for _, success in results)

    print("\n=== SUMMARY ===")
    for name, success in results:
        print(f"  [{'OK  ' if success else 'FAIL'}] {name}")
    print(f"Mercedes pipeline {'SUCCESS' if ok else 'HAD FAILURES'} (exit code {0 if ok else 1})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
