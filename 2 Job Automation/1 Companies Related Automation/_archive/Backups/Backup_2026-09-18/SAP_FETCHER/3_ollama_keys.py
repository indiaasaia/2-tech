"""SAP pipeline step 3: test the Ollama keys and keep the working ones.

Thin wrapper around the bundled key tester (program_files/3_test_ollama_keys.py
inside this folder) - same keys file (sub_program_files/ollama_keys.json),
same active-keys output (sub_program_files/active_ollama_keys.json), no
duplicated logic. Steps 4 and 5 read the active keys.

This folder is fully self-contained: every module, prompt, key and tool it
needs lives inside it. Run directly (from anywhere):
python 3_ollama_keys.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Self-contained: PROJECT_ROOT is this folder itself, which bundles
# program_files/, sub_program_files/ and tools/ (no outside project needed).
PROJECT_ROOT = Path(__file__).resolve().parent

# Make the existing pipeline modules importable (module name starts with a
# digit, so a plain "import 3_test_ollama_keys" is a syntax error).
sys.path.insert(0, str(PROJECT_ROOT / "program_files"))

import importlib

_step3 = importlib.import_module("3_test_ollama_keys")


def test_ollama_keys() -> int:
    """Run the existing key tester unchanged and return its result count."""
    return _step3.test_ollama_keys()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        # test_ollama_keys() returns the number of working keys.
        raise SystemExit(0 if test_ollama_keys() else 1)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[STEP3] FAILED: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc
