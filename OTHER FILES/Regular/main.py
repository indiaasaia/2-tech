"""Run the end-to-end job-to-application pipeline (steps 1-6)."""
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
    """Run one pipeline step, catching errors and treating nonzero codes as failures."""
    print(f"\n=== {name} ===")
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - report any stage failure with traceback
        print(f"[MAIN] {name} FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False
    success = not (isinstance(result, int) and not isinstance(result, bool) and result != 0)
    print(f"[MAIN] {name} {'finished' if success else 'FAILED'} (returned {result})")
    return success


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="scrape jobs and build verified application documents")
    parser.add_argument("--limit", type=int, default=None, help="process only the first N jobs in step 4")
    parser.add_argument("--jobs", type=str, default=None, help="comma-separated job URL substrings")
    parser.add_argument("--force", action="store_true", help="regenerate previously successful resume components")
    parser.add_argument("--no-tailor", action="store_true", help="disable deterministic per-job tailoring")
    parser.add_argument("--no-domain-filter", action="store_true", help="process jobs without the domain gate")
    parser.add_argument("--loose-filter", action="store_true", help="use keyword-only domain filtering")
    parser.add_argument("--force-letters", action="store_true", help="rebuild existing cover letters")
    args = parser.parse_args(argv)
    step4_options = {key: getattr(args, key) for key in (
        "limit", "jobs", "force", "no_tailor", "no_domain_filter", "loose_filter")}

    step1 = _import_step("1_fetch_jobs", "fetch_jobs")
    step2 = _import_step("2_filter_jobs", "filter_jobs")
    step3 = _import_step("3_test_ollama_keys", "test_ollama_keys")
    step4_module = importlib.import_module("resume_content_improve_research.run_step4")
    step5 = importlib.import_module("resume_content_improve_research.run_step5").main
    step6_module = importlib.import_module("resume_content_improve_research.run_step6")

    stages = [
        ("STEP 1 | fetch jobs", step1),
        ("STEP 2 | filter fresh jobs", step2),
        ("STEP 3 | validate Ollama keys", step3),
        ("STEP 4 | analyze and generate gated resume components", lambda: step4_module.run_pipeline(**step4_options)),
        ("STEP 5 | build and verify resumes", step5),
        ("STEP 6 | create cover letters and application bundles",
         lambda: step6_module.run_pipeline(jobs=args.jobs, force=args.force_letters)),
    ]

    results: list[tuple[str, bool]] = []
    for name, fn in stages:
        success = run_step(name, fn)
        results.append((name, success))
        if not success:
            print(f"[MAIN] stopping: downstream stages depend on {name}")
            break

    ok = len(results) == len(stages) and all(success for _, success in results)
    print("\n=== SUMMARY ===")
    for name, success in results:
        print(f"  [{'OK  ' if success else 'FAIL'}] {name}")
    for name, _ in stages[len(results):]:
        print(f"  [SKIP] {name}")
    print(f"pipeline {'SUCCESS' if ok else 'HAD FAILURES'} (exit code {0 if ok else 1})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())