"""CLI for JOB_AUTOMATION Phase 3."""
from __future__ import annotations

import argparse
from pathlib import Path

from app.core import config
from app.phase3 import application_generator as phase3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate tailored cover letters and application manifest")
    parser.add_argument("--input-csv", type=Path, default=config.COMBINED_CSV)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic truthful letters")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF compilation")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    results = phase3.run_phase3(args.input_csv, args.limit, use_llm=not args.no_llm, compile_pdfs=not args.no_pdf)
    print(f"[PHASE3] processed {len(results)} jobs; PDFs={sum(bool(x['pdf']) for x in results)}")
    for item in results:
        print(f"[PHASE3] {item['company']} | {item['title']} | pdf={item['pdf']}")
    print(f"[PHASE3] manifest: {config.APPLICATIONS_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
