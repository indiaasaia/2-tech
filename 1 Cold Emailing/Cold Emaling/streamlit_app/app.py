"""Freebuff Outreach Control Center — Streamlit entry point.

Run from the repository root:

    streamlit run streamlit_app/app.py

Tabs: Overview · Run · Prompts · Settings · Results
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# The app may be started from anywhere; anchor cwd at the repo root so every
# relative path inside the phases behaves like the CLI.
os.chdir(ROOT)
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from pages import live_dashboard, overview, prompts, results, run, settings_page  # noqa: E402

st.set_page_config(page_title="Outreach Control Center", page_icon="🚀", layout="wide")

PAGES = {
    "🚀 Live Dashboard": live_dashboard.render,
    "📊 Pipeline Overview": overview.render,
    "▶ Phase Runners": run.render,
    "✏️ Prompts": prompts.render,
    "⚙️ Settings": settings_page.render,
    "📂 Results Explorer": results.render,
}


def main() -> None:
    with st.sidebar:
        st.title("🚀 Outreach Control Center")
        st.caption("Cold-outreach pipeline: companies → contacts → emails")
        page = st.radio("Navigate", list(PAGES), key="page")
        st.divider()
        st.caption("Editable: prompts · API keys · cities\nLive: run + results")

    # Let pages know when the user switched to them, so unsaved drafts (e.g.
    # the Settings form) are reset and always reflect what is on disk.
    st.session_state["_page_changed"] = st.session_state.get("_prev_page") != page
    st.session_state["_prev_page"] = page

    PAGES[page]()


if __name__ == "__main__":
    main()
