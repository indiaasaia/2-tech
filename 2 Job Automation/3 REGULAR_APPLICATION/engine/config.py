"""Shared configuration for the resume-content engine.

All paths, template tokens, and constants used by the generation and
verification layers live here so the orchestrators, gates, and tests
agree on a single set of values.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The package root is REGULAR_APPLICATION/engine/; PROJECT_ROOT is REGULAR_APPLICATION/.
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

KB_PATH = PACKAGE_ROOT / "knowledge_base" / "candidate_kb.json"
KB_DIR = PACKAGE_ROOT / "knowledge_base"
ESCO_DIR = KB_DIR / "esco"
ALIAS_MAP_PATH = KB_DIR / "alias_map.json"

# v3 (plan v3 §3.1): headline, profile, category skill rows, bullets, <=2 pages.
# core_resume_template_v2.tex is kept for reference only.
TEMPLATE_TEX = PACKAGE_ROOT / "templates" / "core_resume_template_v3.tex"

# German cover letter (Anschreiben) templates: DIN 5008-style one-pagers.
LETTER_TEMPLATE_DE = PACKAGE_ROOT / "templates" / "cover_letter_template_de.tex"
LETTER_TEMPLATE_EN = PACKAGE_ROOT / "templates" / "cover_letter_template_en.tex"

# Engine output tree: verified artifacts, reports, and the park/failed quarantine.
OUTPUT_DIR = PROJECT_ROOT / "output" / "applications"
TEX_DIR = OUTPUT_DIR / "resume" / "tex"
PDF_DIR = OUTPUT_DIR / "resume" / "pdf"
DOCX_DIR = OUTPUT_DIR / "resume" / "docx"
LETTERS_TEX_DIR = OUTPUT_DIR / "letters" / "tex"
LETTERS_PDF_DIR = OUTPUT_DIR / "letters" / "pdf"
LETTERS_DOCX_DIR = OUTPUT_DIR / "letters" / "docx"
LETTERS_TXT_DIR = OUTPUT_DIR / "letters" / "textfield"
LETTERS_REPORT_PATH = OUTPUT_DIR / "letters_report.json"   # step-6 letters report
BUNDLES_PATH = OUTPUT_DIR / "application_bundles.json"     # step-6 per-portal manifest
RUNS_FAILED_DIR = OUTPUT_DIR / "failed"
REPORT_PATH = OUTPUT_DIR / "resume_report.json"

# Pipeline inputs written by steps 1-2b (steps/fetch_jobs.py, filter_jobs.py, screen_jobs.py).
# The engine reads the SCREENED list (role type, German requirement, country checked).
STEPS_OUTPUT_DIR = PROJECT_ROOT / "output" / "jobs"
FILTERED_JOBS_CSV = STEPS_OUTPUT_DIR / "screened_jobs.csv"
MASTER_JOBS_CSV = STEPS_OUTPUT_DIR / "fetched_jobs.csv"

# Ollama keys: keys/ollama_keys.json (yours), keys/active_ollama_keys.json (written by step 3).
KEYS_DIR = PROJECT_ROOT / "keys"

# Posting columns the cover-letter engine reads deterministically (step 6). The
# filtered-jobs CSV carries detail_* fields the letter needs (company legal
# form, location for the address block) — the components store does not.
LETTER_POSTING_COLS = (
    "title", "company", "detail_company_name", "source", "source_job_id",
    "job_url", "location", "detail_location", "job_description", "requirements",
    "your_tasks", "applicant_profile", "about_us", "what_they_offer", "snippet",
)

# Extra documents an ad may ask for (plan v3 §6: 6/36 ads ask for an enrolment
# certificate, 5/36 for transcripts/certificates). None = not provided yet; the
# application bundle then lists it as missing for the ads that request it.
APPLICATION_DOCUMENTS = {
    "enrolment_certificate": PROJECT_ROOT / "documents" / "certificate_of_enrolment_small.pdf",
    "transcript": None,      # e.g. PROJECT_ROOT / "documents" / "transcript_of_records.pdf"
    "certificates": None,    # e.g. PROJECT_ROOT / "documents" / "bachelor_degree_certificate.pdf"
}

TECTONIC_CANDIDATES = (
    PROJECT_ROOT / "tools" / "tectonic.exe",
)

OLLAMA_HOST = "https://ollama.com"
OLLAMA_MODEL = "gpt-oss:120b"

# LLM call budget per job (analyst + generator + repair retries, V2 A6 / V7).
MAX_ANALYST_CALLS = 2      # 1 real + 1 JSON repair
MAX_GENERATOR_CALLS = 3    # 1 per constrained prompt group
MAX_REPAIR_RETRIES = 2     # gate -> regenerate iterations per generator call

# Gates (measured in V3/V4/V5/V6).
WORD_COUNT_MIN = 200       # per resume; V5 segmentation collapse was 154
WORD_COUNT_MAX = 1400      # 2 pages (plan v3: allow page 2 rather than drop keywords)
REQUIRED_SECTIONS = 6      # G1: at least this many section titles detectable
MAX_PAGES = 2              # German norm accepts 2 pages; page 1 carries headline -> experience

# Scorecard weights (FINAL_MODEL 3.3; no embedding term — rejected by V5).
SCORE_WEIGHTS = {
    "required_coverage": 40,
    "preferred_coverage": 20,
    "parse_fidelity": 15,
    "format_checks": 10,
    "experience_relevance": 10,
    "naturalness": 5,
}
SCORE_REGENERATE_THRESHOLD = 70
REQUIRED_COVERAGE_THRESHOLD = 0.8
MAX_REGENERATION_ITERATIONS = 2
ACCEPT_IMPROVEMENT_DELTA = 2

# Honest coverage calibration (V7): missing requirements go to the gap report.
COVERAGE_FUZZY_THRESHOLD = 92   # rapidfuzz token_set_ratio >= 92

# Digit rule: dates + KB-licensed numbers; spelled-out numbers checked too (V6).
DATE_YEARS_ALLOWED = {str(y) for y in range(2019, 2027)}

# Cover-letter tokens — separate namespace (@@CL_*@@) from the resume tokens;
# the same longest-first filler rules apply (no token is a substring of another).
CL_TOKENS = {
    "cl_sender_name": "@@CL_SENDER_NAME@@",
    "cl_sender_address": "@@CL_SENDER_ADDRESS@@",
    "cl_sender_contact": "@@CL_SENDER_CONTACT@@",
    "cl_sender_links": "@@CL_SENDER_LINKS@@",
    "cl_company_block": "@@CL_COMPANY_BLOCK@@",   # multiline -> filled line-wise
    "cl_date_line": "@@CL_DATE_LINE@@",
    "cl_subject": "@@CL_SUBJECT@@",
    "cl_salutation": "@@CL_SALUTATION@@",
    "cl_opening": "@@CL_OPENING@@",
    "cl_fit": "@@CL_FIT@@",
    "cl_motivation": "@@CL_MOTIVATION@@",
    "cl_closing": "@@CL_CLOSING@@",
    "cl_signoff": "@@CL_SIGNOFF@@",
    "cl_name_print": "@@CL_NAME_PRINT@@",
}
CL_ALL_TOKENS = tuple(CL_TOKENS.values())

# Letter body limits (German one-page norm; MEASURED: real LLM bodies on real
# postings land at ~110-160 words — 4×55 per-paragraph caps top out at ~220).
# 180 (the old value) parked healthy one-pagers; 100/330 is the honest window.
LETTER_WORD_MIN = 100     # L1: below this the letter reads as a stub
LETTER_WORD_MAX = 330     # L1: above this the one-page norm is at risk
# L1 per-paragraph cap. Letter v3: the deterministic logistics paragraph (enrolment,
# hours, permit, interview offer) runs ~70-80 words; generated ones aim for <= 70.
LETTER_PARAGRAPH_MAX = 90

# Template tokens — collision-proof @@NAME@@ style (V4's replacement-order bug).
# v3 template (plan v3 §3.1): block tokens filled with pre-rendered LaTeX from
# templates/render.py, so variable bullets/skill rows need no fixed token slots.
TOKENS = {
    "pdf_title": "@@PDF_TITLE@@",
    "name": "@@NAME@@",
    "headline": "@@HEADLINE@@",
    "contact_line": "@@CONTACT_LINE@@",
    "availability": "@@AVAILABILITY@@",
    "profile": "@@PROFILE@@",
    "skills_rows": "@@SKILLS_ROWS@@",
    "experience": "@@EXPERIENCE@@",
    "projects": "@@PROJECTS@@",
    "education": "@@EDUCATION@@",
    "research": "@@RESEARCH@@",
    "achievements": "@@ACHIEVEMENTS@@",
    "certifications": "@@CERTIFICATIONS@@",
    "additional_projects": "@@ADDITIONAL_PROJECTS@@",
    "spoken_languages": "@@SPOKEN_LANGUAGES@@",
}

ALL_TOKENS = tuple(TOKENS.values())


def ensure_utf8_stdout() -> None:
    """Windows consoles choke on umlauts; every entry point calls this."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - reconfigure can fail on exotic streams
        pass
