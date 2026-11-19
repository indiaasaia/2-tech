"""Central configuration for the standalone JOB_AUTOMATION package."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
TOOLS_DIR = PROJECT_DIR / "tools"
BUNDLED_TECTONIC = TOOLS_DIR / "tectonic.exe"
DATA_DIR = PROJECT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
OUTPUT_DIR = DATA_DIR / "output"
PROFILE_JSON = DATA_DIR / "candidate_profile.json"

# Phase 1
STEPSTONE_SEARCH_BASE = "https://www.stepstone.de/work/{keyword}?action=facet_deselected%3bsectors%3b21000&ag=age_1&fdl=en&searchOrigin=Resultlist_top-search"
STEPSTONE_SEARCH_KEYWORDS = ["werkstudent", "working student", "intern", "internship", "studentische Hilfskraft", "praktikum", "Praktikant"]
STEPSTONE_MAX_PAGES = int(os.getenv("JOB_AUTOMATION_STEPSTONE_MAX_PAGES", "10"))
STEPSTONE_FETCH_DETAILS = os.getenv("JOB_AUTOMATION_STEPSTONE_DETAILS", "1") != "0"
STEPSTONE_HEADLESS = os.getenv("JOB_AUTOMATION_HEADLESS", "1") != "0"
STEPSTONE_EMPTY_PAGE_STOP_STREAK = 2
STEPSTONE_PAGE_DELAY_SECONDS = float(os.getenv("JOB_AUTOMATION_STEPSTONE_DELAY", "2"))
STEPSTONE_WAIT_SECONDS = 20
WSJ_BASE_URL = "https://www.workingstudentjobs.de/"
WSJ_SEARCH_TEMPLATE = "https://www.workingstudentjobs.de/?employment_type=working-student,internship&field=tech,operations&page={page}"
WSJ_MAX_PAGES = int(os.getenv("JOB_AUTOMATION_WSJ_MAX_PAGES", "30"))
WSJ_FETCH_DETAILS = os.getenv("JOB_AUTOMATION_WSJ_DETAILS", "1") != "0"
WSJ_EMPTY_PAGE_STOP_STREAK = 2
WSJ_DELAY_SECONDS = float(os.getenv("JOB_AUTOMATION_WSJ_DELAY", "1"))
WSJ_TIMEOUT_SECONDS = 30
WSJ_RETRIES = 3
WSJ_USER_AGENT = os.getenv("JOB_AUTOMATION_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36")
MAX_POSTING_AGE_DAYS = 4.0

# Outputs
STEPSTONE_CSV = OUTPUT_DIR / "stepstone_jobs.csv"
WORKINGSTUDENT_CSV = OUTPUT_DIR / "workingstudent_jobs.csv"
COMBINED_CSV = OUTPUT_DIR / "jobs.csv"
PHASE1_COMBINED_CSV = OUTPUT_DIR / "phase1_jobs_combined.csv"
REPORT_JSON = OUTPUT_DIR / "phase1_report.json"
ACTIVITY_LOG = OUTPUT_DIR / "activity.log"
PHASE2_DIR = DATA_DIR / "phase2"
COMPONENTS_DIR = PHASE2_DIR / "components"
RESUME_DIR = PHASE2_DIR / "resumes"
TEX_DIR = RESUME_DIR / "tex"
PDF_DIR = RESUME_DIR / "pdf"
PHASE2_REPORT = PHASE2_DIR / "phase2_report.json"
PHASE3_DIR = DATA_DIR / "phase3"
PHASE3_REPORT = PHASE3_DIR / "phase3_report.json"
APPLICATIONS_CSV = OUTPUT_DIR / "applications.csv"
OLLAMA_HOST = os.getenv("JOB_AUTOMATION_OLLAMA_HOST", os.getenv("OLLAMA_HOST", "https://ollama.com"))
OLLAMA_MODEL = os.getenv("JOB_AUTOMATION_OLLAMA_MODEL", os.getenv("OLLAMA_MODEL", "gpt-oss:120b"))
OLLAMA_TIMEOUT_SECONDS = 300
API_KEY_FILE_CANDIDATES = (PROJECT_DIR / "api_key", PROJECT_DIR.parent / "OLD_FILES" / "api_key")
COMMON_COLUMNS = ["source", "source_job_id", "title", "company", "location", "posted_time", "job_url", "company_url", "snippet", "scraped_at_utc", "detail_company_name", "detail_location", "detail_contract_type", "detail_work_type", "detail_online_date", "job_description", "applicant_profile", "what_they_offer", "about_us", "your_tasks", "requirements", "we_offer", "predicted_salary", "details_fetched", "detail_error"]

for directory in (RAW_DIR, OUTPUT_DIR, PHASE2_DIR, COMPONENTS_DIR, RESUME_DIR, TEX_DIR, PDF_DIR, PHASE3_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def find_latex_compiler() -> str | None:
    """Locate a LaTeX compiler: project tectonic, OLD_FILES tectonic, then PATH (tectonic -> pdflatex)."""
    for candidate in (
        os.getenv("JOB_AUTOMATION_TECTONIC", "").strip(),
        str(BUNDLED_TECTONIC),
        str(PROJECT_DIR.parent / "OLD_FILES" / "tectonic.exe"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return shutil.which("tectonic") or shutil.which("pdflatex")
