"""Central path resolution.

Everything the control center touches is resolved from the repository root
here, so the app never depends on the working directory it was started in.
"""
from __future__ import annotations

from pathlib import Path

# streamlit_app/core/paths.py -> parents[2] is the repository root.
ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "streamlit_app"

PHASE1_DIR = ROOT / "phase_1"
PHASE2_DIR = ROOT / "phase_2"
PHASE3_DIR = ROOT / "phase_3"

SETTINGS_PATH = APP_DIR / "settings.json"

# --- Phase 1 (startup discovery) ---
PHASE1_CSV = PHASE1_DIR / "data" / "discovered_companies.csv"
PHASE1_PROMPT = PHASE1_DIR / "prompts" / "discovery_prompt.md"

# --- Phase 2 (contact discovery) ---
# Phase 2's input is Phase 1's output (phase_1/data/discovered_companies.csv);
# the control center points both at the same file so the pipeline is linked out of the box.
PHASE2_COMPANIES = PHASE1_CSV
PHASE2_RESULTS = PHASE2_DIR / "data" / "contact_discovery_results.csv"
PHASE2_OUTCOMES = PHASE2_DIR / "data" / "contact_discovery_outcomes.csv"
PHASE2_PROMPT = PHASE2_DIR / "prompts" / "contact_discovery_prompt.md"
PHASE2_REPEAT_PROMPT = PHASE2_DIR / "prompts" / "contact_discovery_repeat_prompt.md"

# --- Phase 3 (email sender) ---
PHASE3_ENV = PHASE3_DIR / ".env"
PHASE3_EMAIL_TEXT = PHASE3_DIR / "email_text.py"
PHASE3_SEND_SCRIPT = PHASE3_DIR / "send_emails.py"
PHASE3_HISTORY = PHASE3_DIR / "sent_history.csv"

# --- Campaign, Live Status & Tracking ---
PHASE3_CAMPAIGN_LOG = PHASE3_DIR / "data" / "campaign_log.csv"
PHASE3_TRACKING_CSV = PHASE3_DIR / "data" / "tracking.csv"
PHASE3_LIVE_STATUS = PHASE3_DIR / "data" / "live_status.json"
PHASE3_LIVE_LOG = PHASE3_DIR / "data" / "live_process.log"
PHASE3_HOOKS_CSV = PHASE3_DIR / "data" / "email_hooks.csv"
PHASE3_QUEUED_CSV = PHASE3_DIR / "contacts_to_send.csv"
PHASE3_STATE_JSON = PHASE3_DIR / "state.json"

# --- Dry-run demo files (kept separate so a simulation never touches the
# real campaign CSVs; phase_2/.gitignore already ignores data/*.csv) ---
DEMO_COMPANIES = PHASE2_DIR / "data" / "_demo_companies.csv"
DEMO_RESULTS = PHASE2_DIR / "data" / "_demo_results.csv"
DEMO_OUTCOMES = PHASE2_DIR / "data" / "_demo_outcomes.csv"
