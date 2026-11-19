"""Configuration for auto-application-workingstudent pipeline.

Dedicated pipeline for workingstudentjobs.de with:
  1. workingstudentjobs.de scraping only
  2. 24-hour recency filter
  3. Pre-screening check: drop already-applied jobs
  4. LLM screening (role type, German level <= A2, Germany, tech domain)
  5. JD analysis & resume tailoring
  6. LaTeX resume build & G1-G4 verification gates
  7. Cover letter generation (Anschreiben) & L1-L4 verification gates
  8. Dashboard generation
  9. Auto-application dispatch interface (modular & extensible)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Paths
MODULE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_ROOT.parent

# Ensure project root is in sys.path so engine and steps can be imported
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Data & Output paths
DATA_DIR = MODULE_ROOT / "data"
APPLICATIONS_DIR = DATA_DIR / "applications"

APPLIED_JSON = DATA_DIR / "applied_jobs.json"
APPLIED_CSV = DATA_DIR / "applied_jobs.csv"

FETCHED_CSV = DATA_DIR / "fetched_jobs.csv"
FILTERED_CSV = DATA_DIR / "filtered_jobs.csv"
UNAPPLIED_CSV = DATA_DIR / "unapplied_jobs.csv"
SCREENED_CSV = DATA_DIR / "screened_jobs.csv"
SCREENING_REPORT_CSV = DATA_DIR / "screening_report.csv"
SCREENING_CACHE_JSON = DATA_DIR / "screening_cache.json"

DASHBOARD_HTML = MODULE_ROOT / "dashboard.html"
DATA_DASHBOARD_HTML = DATA_DIR / "dashboard.html"

# Engine Knowledge Base & Keys
KB_PATH = PROJECT_ROOT / "engine" / "knowledge_base" / "candidate_kb.json"
KEYS_DIR = PROJECT_ROOT / "keys"
KEYS_FILE = KEYS_DIR / "ollama_keys.json"
ACTIVE_KEYS_FILE = KEYS_DIR / "active_ollama_keys.json"

# Documents
ENROLMENT_CERT = PROJECT_ROOT / "documents" / "certificate_of_enrolment_small.pdf"

# workingstudentjobs.de scraping settings
WSJ_BASE_URL = "https://www.workingstudentjobs.de/"
WSJ_SEARCH_TEMPLATE = (
    "https://www.workingstudentjobs.de/?employment_type=working-student,internship"
    "&field=tech,operations&page={page}"
)
DEFAULT_POSTING_AGE_DAYS = 1.0
DEFAULT_MAX_PAGES = 6
WSJ_TIMEOUT_SECONDS = 30
WSJ_RETRIES = 3
WSJ_DELAY_SECONDS = 1.0
WSJ_USER_AGENT = os.getenv(
    "JOB_AUTOMATION_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)

# Standard CSV columns
COMMON_COLUMNS = [
    "source", "source_job_id", "title", "company", "location", "posted_time", "job_url",
    "company_url", "snippet", "scraped_at_utc", "detail_company_name", "detail_location",
    "detail_contract_type", "detail_work_type", "detail_online_date", "job_description",
    "applicant_profile", "what_they_offer", "about_us", "your_tasks", "requirements", "we_offer",
    "predicted_salary", "details_fetched", "detail_error"
]


def ensure_dirs() -> None:
    """Ensure all required directories exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_utf8_stdout() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
