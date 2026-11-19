"""Run the active pipeline: fetch jobs (step 1), filter (step 2), and test Ollama keys (step 3).

Each step runs independently: a failure in one step is reported with a traceback
and does not stop the others. Exits 0 only when every active step succeeds.
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent / "program_files"))


def _import_step(module_name: str, function_name: str) -> Callable:
    """Import a pipeline-step function; exits with a clear message if importing fails."""
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
        ("STEP 1 | fetch jobs", _import_step("1_fetch_jobs", "fetch_jobs")),
        ("STEP 2 | filter jobs (look-back window)", _import_step("2_filter_jobs", "filter_jobs")),
        ("STEP 3 | test ollama keys", _import_step("3_test_ollama_keys", "test_ollama_keys")),
        ("STEP 4 | resume components (objective, experience, projects, skills)", _import_step("4_create_resume_components", "main")),
        ("STEP 5 | build resumes (pdf + docx)", _import_step("5_create_resume", "main")),
    ]

    results = [(name, run_step(name, fn)) for name, fn in steps]
    ok = all(success for _, success in results)

    print("\n=== SUMMARY ===")
    for name, success in results:
        print(f"  [{'OK  ' if success else 'FAIL'}] {name}")
    print(f"pipeline {'SUCCESS' if ok else 'HAD FAILURES'} (exit code {0 if ok else 1})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())