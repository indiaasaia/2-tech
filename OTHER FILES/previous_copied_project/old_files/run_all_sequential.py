"""Run finalized jobs one at a time through Phase 2 and Phase 3."""
from __future__ import annotations

import argparse
from pathlib import Path

from app.core import config
from app.workflow import run_sequential


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Process each finalized job completely through resume and cover letter generation")
    parser.add_argument("--input-csv", type=Path, default=config.COMBINED_CSV)
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N finalized jobs")
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic truthful fallback generation")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF compilation")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    results = run_sequential(args.input_csv, args.limit, use_llm=not args.no_llm, compile_pdfs=not args.no_pdf)
    complete = sum(item["application_status"] == "ready_for_review" for item in results)
    print(f"[WORKFLOW] completed {complete}/{len(results)} applications")
    print(f"[WORKFLOW] manifest: {config.APPLICATIONS_CSV}")
    return 0 if complete == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
