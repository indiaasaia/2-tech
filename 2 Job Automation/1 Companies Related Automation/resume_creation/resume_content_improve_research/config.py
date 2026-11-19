"""Shared configuration for the resume-content engine.

All paths, template tokens, and constants used by the generation and
verification layers live here so the orchestrators, gates, and tests
agree on a single set of values.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The package root is resume_content_improve_research/.
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

KB_PATH = PACKAGE_ROOT / "knowledge_base" / "candidate_kb.json"
KB_DIR = PACKAGE_ROOT / "knowledge_base"
ESCO_DIR = KB_DIR / "esco"
ALIAS_MAP_PATH = KB_DIR / "alias_map.json"

TEMPLATE_TEX = PACKAGE_ROOT / "templates" / "core_resume_template_v2.tex"

# Engine output tree: verified artifacts, reports, and the park/failed quarantine.
OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output_v2"
TEX_DIR = OUTPUT_DIR / "resume" / "tex"
PDF_DIR = OUTPUT_DIR / "resume" / "pdf"
DOCX_DIR = OUTPUT_DIR / "resume" / "docx"
RUNS_FAILED_DIR = OUTPUT_DIR / "failed"
REPORT_PATH = OUTPUT_DIR / "resume_report.json"

# Pipeline inputs written by steps 1-2 (program_files/output).
STEPS_OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output"
FILTERED_JOBS_CSV = STEPS_OUTPUT_DIR / "2_filted_jobs.csv"
MASTER_JOBS_CSV = STEPS_OUTPUT_DIR / "todays_overall_jobs.csv"

TECTONIC_CANDIDATES = (
    PROJECT_ROOT / "old_files" / "tools" / "tectonic.exe",
    PROJECT_ROOT / "tools" / "tectonic.exe",
)

OLLAMA_HOST = "https://ollama.com"
OLLAMA_MODEL = "gpt-oss:120b"

# LLM call budget per job (analyst + generator + repair retries, V2 A6 / V7).
MAX_ANALYST_CALLS = 2      # 1 real + 1 JSON repair
MAX_GENERATOR_CALLS = 3    # 1 per constrained prompt group
MAX_REPAIR_RETRIES = 2     # gate -> regenerate iterations per generator call

# Gates (measured in V3/V4/V5/V6).
WORD_COUNT_MIN = 200       # per resume (1 page); V5 segmentation collapse was 154
WORD_COUNT_MAX = 800
REQUIRED_SECTIONS = 6      # G1: at least this many section titles detectable

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

# Template tokens — collision-proof @@NAME@@ style (V4's replacement-order bug).
TOKENS = {
    "career_objective": "@@CAREER_OBJECTIVE@@",
    "role_1": "@@ROLE_1@@",
    "company_1": "@@COMPANY_1@@",
    "location_1": "@@LOCATION_1@@",
    "dates_1": "@@DATES_1@@",
    "description_1": "@@DESCRIPTION_1@@",
    "skills_1": "@@SKILLS_1@@",
    "role_2": "@@ROLE_2@@",
    "company_2": "@@COMPANY_2@@",
    "location_2": "@@LOCATION_2@@",
    "dates_2": "@@DATES_2@@",
    "description_2": "@@DESCRIPTION_2@@",
    "skills_2": "@@SKILLS_2@@",
    "project_1": "@@PROJECT_TITLE_1@@",
    "project_desc_1": "@@PROJECT_DESC_1@@",
    "project_skills_1": "@@PROJECT_SKILLS_1@@",
    "project_2": "@@PROJECT_TITLE_2@@",
    "project_desc_2": "@@PROJECT_DESC_2@@",
    "project_skills_2": "@@PROJECT_SKILLS_2@@",
    "languages": "@@LANGUAGES@@",
    "specialized_areas": "@@SPECIALIZED_AREAS@@",
    "skills_area_1_label": "@@SKILLS_AREA_1_LABEL@@",
    "skills_area_1": "@@SKILLS_AREA_1@@",
    "skills_area_2_label": "@@SKILLS_AREA_2_LABEL@@",
    "skills_area_2": "@@SKILLS_AREA_2@@",
}

ALL_TOKENS = tuple(TOKENS.values())


def ensure_utf8_stdout() -> None:
    """Windows consoles choke on umlauts; every entry point calls this."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - reconfigure can fail on exotic streams
        pass
