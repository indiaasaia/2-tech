"""Settings for the two job sources (Stepstone, workingstudentjobs.de).

Environment variables override the defaults without editing this file.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]          # REGULAR_APPLICATION/
JOBS_DIR = PROJECT_DIR / "output" / "jobs"
ACTIVITY_LOG = PROJECT_DIR / "output" / "logs" / "activity.log"
STEPSTONE_CSV = JOBS_DIR / "raw_stepstone_jobs.csv"
WORKINGSTUDENT_CSV = JOBS_DIR / "raw_workingstudentjobs.csv"

# Default posting age when a caller passes none (run.py always passes --days).
MAX_POSTING_AGE_DAYS = 1.0

# --- Stepstone (Selenium + Chrome) ---------------------------------------
# {age} is filled by stepstone_age_param(): Stepstone's own "posted within"
# facet (age_1 = last 24 hours, age_7 = last 7 days); wider windows use no facet.
STEPSTONE_SEARCH_BASE = ("https://www.stepstone.de/work/{keyword}?fdl=en"
                         "{age}&searchOrigin=Resultlist_top-search")
STEPSTONE_SEARCH_KEYWORDS = [
    "werkstudent IT",
    "working student software",
    "werkstudent informatik",
    "werkstudent data",
    "working student AI",
    "internship software",
    "internship data",
    "praktikum informatik",
    "praktikum softwareentwicklung",
    "working student automation",
]
STEPSTONE_MAX_PAGES = int(os.getenv("JOB_AUTOMATION_STEPSTONE_MAX_PAGES", "10"))
STEPSTONE_FETCH_DETAILS = os.getenv("JOB_AUTOMATION_STEPSTONE_DETAILS", "1") != "0"
STEPSTONE_HEADLESS = os.getenv("JOB_AUTOMATION_HEADLESS", "1") != "0"
STEPSTONE_EMPTY_PAGE_STOP_STREAK = 2
STEPSTONE_PAGE_DELAY_SECONDS = float(os.getenv("JOB_AUTOMATION_STEPSTONE_DELAY", "2"))
STEPSTONE_WAIT_SECONDS = 20

# --- workingstudentjobs.de (plain HTTP) --------------------------------------
WSJ_BASE_URL = "https://www.workingstudentjobs.de/"
WSJ_SEARCH_TEMPLATE = ("https://www.workingstudentjobs.de/?employment_type=working-student,internship"
                       "&field=tech,operations&page={page}")
WSJ_MAX_PAGES = int(os.getenv("JOB_AUTOMATION_WSJ_MAX_PAGES", "6"))     # for 1 day; run.py scales it
WSJ_FETCH_DETAILS = os.getenv("JOB_AUTOMATION_WSJ_DETAILS", "1") != "0"
WSJ_EMPTY_PAGE_STOP_STREAK = 2
WSJ_DELAY_SECONDS = float(os.getenv("JOB_AUTOMATION_WSJ_DELAY", "1"))
WSJ_TIMEOUT_SECONDS = 30
WSJ_RETRIES = 3
WSJ_USER_AGENT = os.getenv("JOB_AUTOMATION_USER_AGENT",
                           "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36")

COMMON_COLUMNS = ["source", "source_job_id", "title", "company", "location", "posted_time", "job_url",
                  "company_url", "snippet", "scraped_at_utc", "detail_company_name", "detail_location",
                  "detail_contract_type", "detail_work_type", "detail_online_date", "job_description",
                  "applicant_profile", "what_they_offer", "about_us", "your_tasks", "requirements", "we_offer",
                  "predicted_salary", "details_fetched", "detail_error"]


def stepstone_age_param(days: float) -> str:
    """Stepstone's posted-within facet for a window of `days` ('' = no facet)."""
    if days <= 1:
        return "&ag=age_1"
    if days <= 7:
        return "&ag=age_7"
    return ""


def wsj_pages_for(days: float) -> int:
    """workingstudentjobs.de lists newest first; a wider window needs more pages."""
    return min(40, WSJ_MAX_PAGES + int(max(0.0, days - 1) * 3))
