"""Launch the Streamlit dashboard on Windows with the selector asyncio event loop.

The default proactor loop crashes with "OSError: [WinError 64]" when a client
connection is aborted mid-accept (e.g. a preview pane reloading), killing the
server. The selector loop does not have this problem.

Run:  python run_dashboard.py
"""
from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from streamlit.web import cli as stcli  # noqa: E402

if __name__ == "__main__":
    sys.argv = [
        "streamlit", "run", "program_files/6_dashboard.py",
        "--server.port", "8599",
        "--server.headless", "true",
    ]
    sys.exit(stcli.main())
