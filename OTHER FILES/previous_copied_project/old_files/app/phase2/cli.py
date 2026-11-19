"""CLI entry point for standalone JOB_AUTOMATION Phase 2."""
from __future__ import annotations

import argparse
from pathlib import Path

from app.core import config
from app.phase2 import resume_generator as phase2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JOB_AUTOMATION Phase 2 resume generation")
    parser.add_argument("--input-csv", type=Path, default=config.COMBINED_CSV)
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N jobs")
    parser.add_argument("--no-pdf", action="store_true", help="Write LaTeX only; skip PDF compilation")
    parser.add_argument("--no-llm", action="store_true", help="Skip Ollama and use the truthful local template")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    results = phase2.run_phase2(args.input_csv, args.limit, compile_pdf=not args.no_pdf, use_llm=not args.no_llm)
    print(f"[PHASE2] processed {len(results)} jobs")
    for result in results:
        print(f"[PHASE2] {result['company']} | {result['title']} | pdf={result['pdf']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
