"""Main CLI Entrypoint for auto-application-workingstudent.

Usage:
    python run.py                     # Fetch last 24h from workingstudentjobs.de, filter, check applied, screen, build, dash
    python run.py --dashboard         # Launch the Apple-style live web dashboard server
    python run.py --days 1            # Specify rolling day window (e.g. 1 = 24h, 2 = 48h)
    python run.py --pages 6           # Max listing pages to scrape
    python run.py --skip-fetch        # Reuse existing data without re-scraping
    python run.py --force             # Regenerate all documents
    python run.py --auto-apply        # Activate live auto application (default is safe dry-run staging)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root and local module to sys.path
MODULE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_ROOT.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

import pipeline_runner


def main() -> int:
    if "--dashboard" in sys.argv or "--server" in sys.argv:
        import server
        server.main()
        return 0
    return pipeline_runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
