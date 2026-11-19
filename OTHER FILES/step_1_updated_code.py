"""Fully self-contained Stage 1 fetcher — zero project dependencies.

This script is 100% standalone: it does not import anything from this
repository (no ``src.*`` modules, no config files, no other files). All
configuration, models, URL/text helpers, and both source fetchers are
inlined below. It runs with the Python standard library alone.

Behavior:

1. Fetch listing pages from both sources in parallel.
2. Remove only obvious listing-level rejects before detail requests.
3. Reuse recent detail responses from a persistent JSON cache.
4. Fetch Working Student details with bounded concurrency (urllib only).
5. Fetch StepStone details with one reused browser when needed.
6. Write the enriched raw records to a separate CSV output.

The only optional third-party package is ``selenium``: it is required just
for the StepStone source (the site needs a real browser). If it is not
installed, StepStone fails cleanly and the other source still runs. Every
other source path uses only the standard library.

Configuration: the script first tries the repository's ``config/settings.json``
and ``config/filters.json`` (resolved from the script's own location) and
falls back to sensible built-in defaults when those files are missing, so it
runs even when copied anywhere on disk.

Examples::

    python program_files/step_1_updated_code.py
    python program_files/step_1_updated_code.py --detail-mode none
    python program_files/step_1_updated_code.py --detail-workers 2 --cache-ttl-hours 24
    python program_files/step_1_updated_code.py --detail-mode all --no-cache
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urljoin, urlparse, urlsplit, urlunsplit, urlunparse
from urllib.request import Request, urlopen

# Resolve paths from this file, not from the caller's current working directory.
PROGRAM_FILES_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PROGRAM_FILES_DIR.parent
DEFAULT_OUTPUT_CSV = PROGRAM_FILES_DIR / "output" / "step_1_updated_jobs.csv"
DEFAULT_CACHE = PROJECT_ROOT / "data" / "cache" / "step1_detail_cache.json"


# ---------------------------------------------------------------------------
# Inlined helpers from src.models.job
# ---------------------------------------------------------------------------

TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        try:
            if value != value:
                return ""
        except Exception:
            pass
    return re.sub(r"\s+", " ", str(value)).strip()


def canonical_url(value: Any) -> str:
    raw = clean_text(value)
    if not raw:
        return ""
    parsed = urlsplit(raw)
    query = sorted((key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key.casefold() not in TRACKING_KEYS)
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path.rstrip("/"), urlencode(query), ""))


# ---------------------------------------------------------------------------
# Inlined helper from src.processing.normalizer
# ---------------------------------------------------------------------------

def parse_publication_date(value: Any, now: datetime | None = None) -> str:
    text = clean_text(value)
    if not text:
        return ""
    current = now or datetime.now(timezone.utc)
    lowered = text.casefold()
    if lowered in {"now", "just now", "today", "heute"}:
        return current.isoformat(timespec="seconds")
    if lowered in {"yesterday", "gestern"}:
        return (current - timedelta(days=1)).isoformat(timespec="seconds")
    match = re.search(r"(\d+)\s*(minute|minutes|hour|hours|day|days|week|weeks|minuten|stunde|stunden|tag|tage|tagen|woche|wochen)", lowered)
    units = {"minute": 60, "minutes": 60, "minuten": 60, "hour": 3600, "hours": 3600, "stunde": 3600, "stunden": 3600, "day": 86400, "days": 86400, "tag": 86400, "tage": 86400, "tagen": 86400, "week": 604800, "weeks": 604800, "woche": 604800, "wochen": 604800}
    if match:
        return (current - timedelta(seconds=int(match.group(1)) * units[match.group(2)])).isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Inlined configuration from src.config.loader
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON configuration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Configuration must be an object: {path}")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative number") from exc
    if number < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return number


@dataclass(frozen=True)
class SourceSettings:
    enabled: bool
    max_pages: int
    fetch_details: bool
    page_delay_seconds: float = 0.0
    wait_seconds: int = 30
    empty_page_stop_streak: int = 2
    request_timeout_seconds: int = 30
    retries: int = 3
    delay_seconds: float = 0.0
    user_agent: str = ""
    headless: bool = True


@dataclass(frozen=True)
class AISettings:
    enabled: bool
    provider: str
    host: str
    model: str
    timeout_seconds: int
    retries: int
    retry_delay_seconds: float


@dataclass(frozen=True)
class PipelineSettings:
    source: str
    manual_review: bool
    continue_on_source_error: bool
    analyze_rule_rejected_jobs: bool


@dataclass(frozen=True)
class Paths:
    data_dir: Path
    raw_dir: Path
    processed_dir: Path
    final_dir: Path
    logs_dir: Path


@dataclass(frozen=True)
class Settings:
    stepstone: SourceSettings
    working_student: SourceSettings
    ai: AISettings
    pipeline: PipelineSettings
    paths: Paths


@dataclass(frozen=True)
class Filters:
    target_categories: tuple[str, ...]
    target_keywords: tuple[str, ...]
    acceptable_employment_types: tuple[str, ...]
    target_locations: tuple[str, ...]
    work_modes: tuple[str, ...]
    minimum_experience_years: float | None
    maximum_experience_years: float | None
    required_keywords: tuple[str, ...]
    excluded_keywords: tuple[str, ...]
    excluded_companies: tuple[str, ...]
    language_requirements: dict[str, Any]
    maximum_job_age_days: float
    minimum_score: int
    review_score_floor: int
    ai_keep_confidence: float
    max_jobs_to_keep: int | None
    manual_review: bool
    unknown_date_decision: str
    missing_description_decision: str


# Built-in defaults used when config/settings.json is missing, so the script
# runs completely standalone. Values mirror the repository's config file.
_DEFAULT_SETTINGS: dict[str, Any] = {
    "sources": {
        "stepstone": {
            "enabled": True,
            "max_pages": 2,
            "fetch_details": True,
            "headless": True,
            "page_delay_seconds": 1.0,
            "wait_seconds": 20,
            "empty_page_stop_streak": 2,
        },
        "working_student": {
            "enabled": True,
            "max_pages": 3,
            "fetch_details": True,
            "request_timeout_seconds": 30,
            "retries": 3,
            "delay_seconds": 1.0,
            "empty_page_stop_streak": 2,
            "user_agent": "Mozilla/5.0 (compatible; JobStage1/1.0)",
        },
    },
    "ai": {
        "enabled": True,
        "provider": "ollama_cloud",
        "host": "https://ollama.com",
        "model": "gpt-oss:120b",
        "timeout_seconds": 120,
        "retries": 2,
        "retry_delay_seconds": 2.0,
    },
    "pipeline": {
        "source": "both",
        "manual_review": True,
        "continue_on_source_error": True,
        "analyze_rule_rejected_jobs": False,
    },
    "paths": {
        "data_dir": "data",
        "raw_dir": "data/raw",
        "processed_dir": "data/processed",
        "final_dir": "data/final",
        "logs_dir": "data/logs",
    },
}

# Built-in defaults used when config/filters.json is missing.
_DEFAULT_FILTERS: dict[str, Any] = {
    "target_categories": ["artificial intelligence", "machine learning", "software engineering", "backend", "data science", "data engineering", "llm", "natural language processing", "computer vision"],
    "target_keywords": ["python", "fastapi", "django", "sql", "machine learning", "deep learning", "data engineering", "backend", "rest api", "docker", "llm"],
    "acceptable_employment_types": ["working student", "werkstudent", "internship", "intern", "student job", "part time"],
    "target_locations": ["Germany"],
    "work_modes": [],
    "minimum_experience_years": None,
    "maximum_experience_years": None,
    "required_keywords": [],
    "excluded_keywords": [],
    "excluded_companies": [],
    "language_requirements": {"preferred": ["English"], "required": [], "candidate_languages": ["English"]},
    "maximum_job_age_days": 4,
    "minimum_score": 55,
    "review_score_floor": 35,
    "ai_keep_confidence": 0.70,
    "max_jobs_to_keep": None,
    "manual_review": True,
    "unknown_date_decision": "REVIEW",
    "missing_description_decision": "REVIEW",
}


def _resolve_path(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _find_config(name: str) -> Path | None:
    """Look for a config file next to the repository, tolerating its absence."""
    candidates = [PROJECT_ROOT / "config" / name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from config/settings.json, or use built-in defaults."""
    config_path = path or _find_config("settings.json")
    if config_path is None:
        raw = _DEFAULT_SETTINGS
    else:
        raw = _read_json(config_path)
    sources = raw.get("sources", {})
    step = sources.get("stepstone", {})
    wsj = sources.get("working_student", {})
    stepstone = SourceSettings(
        enabled=bool(step.get("enabled", True)),
        max_pages=_positive_int(int(os.getenv("JOB_STAGE1_STEPSTONE_MAX_PAGES", step.get("max_pages", 2))), "stepstone.max_pages"),
        fetch_details=bool(step.get("fetch_details", True)),
        page_delay_seconds=_nonnegative_float(step.get("page_delay_seconds", 1), "stepstone.page_delay_seconds"),
        wait_seconds=_positive_int(int(step.get("wait_seconds", 20)), "stepstone.wait_seconds"),
        empty_page_stop_streak=_positive_int(int(step.get("empty_page_stop_streak", 2)), "stepstone.empty_page_stop_streak"),
        headless=bool(step.get("headless", True)),
    )
    working_student = SourceSettings(
        enabled=bool(wsj.get("enabled", True)),
        max_pages=_positive_int(int(os.getenv("JOB_STAGE1_WSJ_MAX_PAGES", wsj.get("max_pages", 3))), "working_student.max_pages"),
        fetch_details=bool(wsj.get("fetch_details", True)),
        request_timeout_seconds=_positive_int(int(wsj.get("request_timeout_seconds", 30)), "working_student.request_timeout_seconds"),
        retries=_positive_int(int(wsj.get("retries", 3)), "working_student.retries"),
        delay_seconds=_nonnegative_float(wsj.get("delay_seconds", 1), "working_student.delay_seconds"),
        empty_page_stop_streak=_positive_int(int(wsj.get("empty_page_stop_streak", 2)), "working_student.empty_page_stop_streak"),
        user_agent=str(wsj.get("user_agent", "")),
    )
    ai_raw = raw.get("ai", {})
    ai = AISettings(
        enabled=bool(ai_raw.get("enabled", True)),
        provider=str(ai_raw.get("provider", "ollama_cloud")),
        host=os.getenv("JOB_STAGE1_AI_HOST", str(ai_raw.get("host", "https://ollama.com"))).rstrip("/"),
        model=os.getenv("JOB_STAGE1_AI_MODEL", str(ai_raw.get("model", "gpt-oss:120b"))),
        timeout_seconds=_positive_int(int(ai_raw.get("timeout_seconds", 120)), "ai.timeout_seconds"),
        retries=int(ai_raw.get("retries", 2)),
        retry_delay_seconds=_nonnegative_float(ai_raw.get("retry_delay_seconds", 2), "ai.retry_delay_seconds"),
    )
    if ai.retries < 0:
        raise ValueError("ai.retries must not be negative")
    pipeline_raw = raw.get("pipeline", {})
    pipeline = PipelineSettings(
        source=str(pipeline_raw.get("source", "both")),
        manual_review=bool(pipeline_raw.get("manual_review", True)),
        continue_on_source_error=bool(pipeline_raw.get("continue_on_source_error", True)),
        analyze_rule_rejected_jobs=bool(pipeline_raw.get("analyze_rule_rejected_jobs", False)),
    )
    paths_raw = raw.get("paths", {})
    defaults = {"data_dir": "data", "raw_dir": "data/raw", "processed_dir": "data/processed", "final_dir": "data/final", "logs_dir": "data/logs"}
    paths = Paths(**{
        name: _resolve_path(str(paths_raw.get(name, defaults[name])), PROJECT_ROOT)
        for name in defaults
    })
    return Settings(stepstone, working_student, ai, pipeline, paths)


def load_filters(path: Path | None = None) -> Filters:
    """Load filters from config/filters.json, or use built-in defaults."""
    config_path = path or _find_config("filters.json")
    if config_path is None:
        raw = _DEFAULT_FILTERS
    else:
        raw = _read_json(config_path)
    lists = {}
    for name in ("target_categories", "target_keywords", "acceptable_employment_types", "target_locations", "work_modes", "required_keywords", "excluded_keywords", "excluded_companies"):
        value = raw.get(name, _DEFAULT_FILTERS.get(name, []))
        if not isinstance(value, list):
            raise ValueError(f"filters.{name} must be an array")
        lists[name] = tuple(str(item).strip() for item in value if str(item).strip())
    min_years = raw.get("minimum_experience_years", _DEFAULT_FILTERS.get("minimum_experience_years"))
    max_years = raw.get("maximum_experience_years", _DEFAULT_FILTERS.get("maximum_experience_years"))
    minimum_score = int(raw.get("minimum_score", 55))
    review_floor = int(raw.get("review_score_floor", 35))
    confidence = float(raw.get("ai_keep_confidence", 0.7))
    if not 0 <= minimum_score <= 100 or not 0 <= review_floor <= 100 or review_floor > minimum_score:
        raise ValueError("score thresholds must be ordered from 0 to 100 with review_score_floor <= minimum_score")
    if not 0 <= confidence <= 1:
        raise ValueError("ai_keep_confidence must be between 0 and 1")
    max_keep = raw.get("max_jobs_to_keep", _DEFAULT_FILTERS.get("max_jobs_to_keep"))
    if max_keep is not None:
        max_keep = _positive_int(int(max_keep), "max_jobs_to_keep")
    decision_values = {"KEEP", "REMOVE", "REVIEW"}
    unknown = str(raw.get("unknown_date_decision", "REVIEW")).upper()
    missing = str(raw.get("missing_description_decision", "REVIEW")).upper()
    if unknown not in decision_values or missing not in decision_values:
        raise ValueError("date/description decisions must be KEEP, REMOVE, or REVIEW")
    language = raw.get("language_requirements", {})
    if not isinstance(language, dict):
        raise ValueError("language_requirements must be an object")
    return Filters(
        **lists,
        minimum_experience_years=None if min_years is None else float(min_years),
        maximum_experience_years=None if max_years is None else float(max_years),
        language_requirements=language,
        maximum_job_age_days=_nonnegative_float(raw.get("maximum_job_age_days", 4), "maximum_job_age_days"),
        minimum_score=minimum_score,
        review_score_floor=review_floor,
        ai_keep_confidence=confidence,
        max_jobs_to_keep=max_keep,
        manual_review=bool(raw.get("manual_review", True)),
        unknown_date_decision=unknown,
        missing_description_decision=missing,
    )


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

PREFERRED_COLUMNS = [
    "source",
    "source_job_id",
    "title",
    "company",
    "location",
    "job_url",
    "application_url",
    "posted_time",
    "scraped_at_utc",
    "detail_contract_type",
    "detail_work_type",
    "job_description",
    "requirements",
    "applicant_profile",
    "your_tasks",
    "what_they_offer",
    "about_us",
    "predicted_salary",
    "details_fetched",
    "detail_error",
    "optimization_status",
    "optimization_reasons",
    "details_cached",
]


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def write_jobs_csv(rows: list[dict[str, Any]], output_csv: Path) -> int:
    """Write all raw fields while keeping the common columns easy to inspect."""
    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    keys: set[str] = set()
    for row in rows:
        keys.update(row)
    fieldnames = [name for name in PREFERRED_COLUMNS if name in keys]
    fieldnames.extend(sorted(keys - set(fieldnames)))
    if not fieldnames:
        fieldnames = PREFERRED_COLUMNS
    with output_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({key: _csv_value(row.get(key)) for key in fieldnames} for row in rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Listing-level prefilter helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any, now: datetime) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    normalized = parse_publication_date(text, now=now)
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_text(row: dict[str, Any]) -> str:
    values = (
        row.get("title"),
        row.get("company"),
        row.get("location"),
        row.get("employment_type"),
        row.get("detail_contract_type"),
        row.get("work_mode"),
        row.get("detail_work_type"),
        row.get("posted_time"),
        row.get("snippet"),
    )
    return " ".join(clean_text(value) for value in values if clean_text(value)).casefold()


def _contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    return any(clean_text(term).casefold() in text for term in terms if clean_text(term))


def _location_matches(location: str, targets: tuple[str, ...]) -> bool:
    if not targets or not clean_text(location):
        return True
    value = clean_text(location).casefold()
    for target in targets:
        normalized = clean_text(target).casefold()
        if normalized in {"germany", "de"}:
            if any(alias in value for alias in ("germany", "deutschland", ", de", " de", "de")):
                return True
        elif normalized in value:
            return True
    return False


def _listing_fingerprint(row: dict[str, Any]) -> str:
    """Identify listing changes without including volatile timestamps."""
    payload = {
        key: row.get(key, "")
        for key in (
            "source",
            "source_job_id",
            "title",
            "company",
            "location",
            "job_url",
            "posted_time",
            "employment_type",
            "snippet",
        )
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _cache_key(row: dict[str, Any]) -> str:
    source = clean_text(row.get("source")).casefold()
    url = canonical_url(row.get("job_url")) or clean_text(row.get("job_url")).casefold()
    return f"{source}|{url}"


class DetailCache:
    """Small atomic JSON cache written only by the coordinating thread."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.entries: dict[str, dict[str, Any]] = {}
        self.dirty = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(value, dict) and isinstance(value.get("entries"), dict):
            self.entries = {str(key): item for key, item in value["entries"].items() if isinstance(item, dict)}

    def get(self, row: dict[str, Any], ttl: timedelta) -> dict[str, Any] | None:
        entry = self.entries.get(_cache_key(row))
        if not entry:
            return None
        fetched_at = _parse_datetime(entry.get("fetched_at_utc"), _utc_now())
        if fetched_at is None or _utc_now() - fetched_at > ttl:
            return None
        if entry.get("listing_fingerprint") != _listing_fingerprint(row):
            return None
        detail = entry.get("detail")
        return dict(detail) if isinstance(detail, dict) else None

    def put(self, row: dict[str, Any], detail: dict[str, Any]) -> None:
        self.entries[_cache_key(row)] = {
            "fetched_at_utc": _utc_now().isoformat(),
            "listing_fingerprint": _listing_fingerprint(row),
            "detail": detail,
        }
        self.dirty = True

    def save(self) -> None:
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "updated_at_utc": _utc_now().isoformat(),
            "entries": self.entries,
        }
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False, prefix=".step1-cache-") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
                handle.write("\n")
                temporary = Path(handle.name)
            temporary.replace(self.path)
            self.dirty = False
        finally:
            if temporary and temporary.exists():
                temporary.unlink(missing_ok=True)


def _prefilter_listing(row: dict[str, Any], filters: Filters, now: datetime) -> tuple[bool, list[str]]:
    """Reject only rules that can be proven from listing-level information."""
    reasons: list[str] = []
    url = clean_text(row.get("job_url"))
    if not url:
        reasons.append("missing job URL")

    posted = _parse_datetime(row.get("posted_time") or row.get("publication_date"), now)
    if posted is not None:
        age = now - posted
        if age < timedelta(0) or age > timedelta(days=filters.maximum_job_age_days):
            reasons.append(f"publication date outside {filters.maximum_job_age_days:g}-day window")

    location = clean_text(row.get("location") or row.get("detail_location"))
    if location and not _location_matches(location, filters.target_locations):
        reasons.append("listing location does not match configured locations")

    text = _record_text(row)
    employment_value = clean_text(row.get("employment_type") or row.get("detail_contract_type"))
    if employment_value and filters.acceptable_employment_types and not _contains_any(text, filters.acceptable_employment_types):
        reasons.append("explicit listing employment type does not match configured types")

    excluded = [term for term in filters.excluded_keywords if clean_text(term).casefold() in text]
    company = clean_text(row.get("company")).casefold()
    excluded.extend(term for term in filters.excluded_companies if clean_text(term).casefold() in company)
    if excluded:
        reasons.append("excluded listing terms: " + ", ".join(dict.fromkeys(excluded)))
    return bool(reasons), list(dict.fromkeys(reasons))


def _needs_details(row: dict[str, Any], source: str, filters: Filters) -> bool:
    """Choose detail candidates without discarding sparse-source records."""
    text = _record_text(row)
    target_hit = _contains_any(text, filters.target_categories + filters.target_keywords)
    employment_hit = _contains_any(text, filters.acceptable_employment_types)
    missing_date = _parse_datetime(row.get("posted_time") or row.get("publication_date"), _utc_now()) is None
    missing_location = not clean_text(row.get("location") or row.get("detail_location"))
    missing_employment = not clean_text(row.get("employment_type") or row.get("detail_contract_type"))

    # WorkingStudent listing pages intentionally expose mostly links; details are
    # the only reliable place for title, date, location, and JSON-LD content.
    if source == "working_student" and (missing_date or missing_location or missing_employment):
        return True
    return target_hit or employment_hit or missing_date or missing_location or missing_employment


# ---------------------------------------------------------------------------
# Inlined fetcher: workingstudentjobs.de (stdlib only)
# ---------------------------------------------------------------------------

class HTMLCaptureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.jsonld: list[str] = []
        self.text: list[str] = []
        self._in_script = False
        self._json_script = False
        self._script_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "a" and values.get("href"):
            self.links.append(values["href"])
        if tag.lower() == "script":
            self._in_script = True
            self._json_script = values.get("type", "").lower() == "application/ld+json"
            self._script_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            if self._json_script:
                self.jsonld.append("".join(self._script_text))
            self._in_script = False
            self._json_script = False
            self._script_text = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_text.append(data)
        else:
            value = re.sub(r"\s+", " ", unescape(data)).strip()
            if value:
                self.text.append(value)


def is_job_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc.casefold() not in {"workingstudentjobs.de", "www.workingstudentjobs.de"}:
        return False
    slug = parsed.path.rstrip("/").removeprefix("/jobs/")
    return parsed.path.rstrip("/").startswith("/jobs/") and "/" not in slug and bool(re.search(r"-[0-9a-f]{8}$", slug, re.I))


def _clean(value: Any) -> str:
    if isinstance(value, str):
        value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
        value = re.sub(r"<[^>]+>", " ", unescape(value))
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, list):
        return "; ".join(item for item in (_clean(x) for x in value) if item)
    if isinstance(value, dict):
        return _clean(value.get("name") or value.get("value") or value.get("addressLocality") or "")
    return str(value or "").strip()


def _objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _job_posting(parser: HTMLCaptureParser) -> dict[str, Any] | None:
    for raw in parser.jsonld:
        try:
            value = json.loads(raw.strip())
        except (TypeError, json.JSONDecodeError):
            continue
        for obj in _objects(value):
            types = obj.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                return obj
    return None


def _location(value: Any) -> str:
    if not isinstance(value, dict):
        return _clean(value)
    address = value.get("address") or value
    if not isinstance(address, dict):
        return _clean(address)
    return ", ".join(_clean(address.get(key)) for key in ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry") if _clean(address.get(key)))


def _slug_title(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").split("/", 2)[-1]
    return re.sub(r"-[0-9a-f]{8}$", "", slug, flags=re.I).replace("-", " ").title()


def parse_detail(url: str, html: str) -> dict[str, Any]:
    parser = HTMLCaptureParser()
    parser.feed(html)
    row: dict[str, Any] = {"source": "workingstudentjobs.de", "source_job_id": url.rsplit("-", 1)[-1], "job_url": url, "scraped_at_utc": datetime.now(timezone.utc).isoformat()}
    job = _job_posting(parser)
    if job:
        organization = job.get("hiringOrganization") or {}
        row.update({
            "title": _clean(job.get("title") or job.get("headline")) or _slug_title(url),
            "company": _clean(organization.get("name") if isinstance(organization, dict) else organization),
            "company_url": _clean(organization.get("url") if isinstance(organization, dict) else ""),
            "location": _location(job.get("jobLocation")),
            "posted_time": _clean(job.get("datePosted")),
            "detail_contract_type": _clean(job.get("employmentType")),
            "job_description": _clean(job.get("description")),
            "requirements": _clean(job.get("qualifications") or job.get("experienceRequirements")),
            "applicant_profile": _clean(job.get("qualifications") or job.get("experienceRequirements")),
            "your_tasks": _clean(job.get("responsibilities")),
            "what_they_offer": _clean(job.get("jobBenefits") or job.get("benefits")),
            "predicted_salary": _clean(job.get("baseSalary")),
            "details_fetched": "true" if _clean(job.get("description")) else "false",
        })
    else:
        visible = "\n".join(parser.text)
        row.update({"title": _slug_title(url), "job_description": visible[:10000], "your_tasks": visible[:10000], "details_fetched": "true" if visible else "false"})
        if not visible:
            row["detail_error"] = "no JSON-LD or visible text found"
    row.setdefault("title", _slug_title(url))
    return row


class WorkingStudentFetcher:
    name = "workingstudentjobs.de"
    base_url = "https://www.workingstudentjobs.de/"
    search_template = "https://www.workingstudentjobs.de/?employment_type=working-student,internship&field=tech,operations&page={page}"

    def __init__(self, settings: SourceSettings, getter: Callable[..., Any] | None = None) -> None:
        self.settings = settings
        self.getter = getter or self._stdlib_get

    @staticmethod
    def _stdlib_get(url: str, headers: dict[str, str], timeout: int) -> Any:
        request = Request(url, headers=headers)
        response = urlopen(request, timeout=timeout)
        class Response:
            ok = 200 <= response.status < 300
            text = response.read().decode("utf-8", errors="replace")
        return Response()

    def _get(self, url: str) -> str | None:
        for attempt in range(self.settings.retries):
            try:
                response = self.getter(url, headers={"User-Agent": self.settings.user_agent, "Accept-Language": "en-US,en;q=0.9,de;q=0.8"}, timeout=self.settings.request_timeout_seconds)
                if response.ok:
                    return response.text
            except Exception:
                pass
            if attempt + 1 < self.settings.retries:
                time.sleep(self.settings.delay_seconds * (attempt + 1))
        return None

    def fetch(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        empty_streak = 0
        for page in range(1, self.settings.max_pages + 1):
            html = self._get(self.search_template.format(page=page))
            parser = HTMLCaptureParser()
            if html:
                parser.feed(html)
            links = []
            for href in parser.links:
                absolute = urljoin(self.base_url, href)
                if is_job_url(absolute) and absolute not in seen:
                    seen.add(absolute)
                    links.append(absolute)
            if links:
                rows.extend({"source": self.name, "source_job_id": url.rsplit("-", 1)[-1], "job_url": url, "scraped_at_utc": datetime.now(timezone.utc).isoformat()} for url in links)
                empty_streak = 0
            else:
                empty_streak += 1
            if empty_streak >= self.settings.empty_page_stop_streak:
                break
            if page < self.settings.max_pages:
                time.sleep(self.settings.delay_seconds)
        if self.settings.fetch_details:
            for index, row in enumerate(rows):
                html = self._get(row["job_url"])
                if html:
                    row.update(parse_detail(row["job_url"], html))
                else:
                    row["detail_error"] = "detail request failed after retries"
                if index + 1 < len(rows):
                    time.sleep(self.settings.delay_seconds)
        return rows


# ---------------------------------------------------------------------------
# Inlined fetcher: stepstone.de (selenium optional, lazy)
# ---------------------------------------------------------------------------

class StepStoneFetcher:
    name = "stepstone"
    # No site-level age facet: job freshness is enforced by the configurable
    # `maximum_job_age_days` filter (single source of truth).
    search_base = "https://www.stepstone.de/work/{keyword}?action=facet_deselected%3bsectors%3b21000&fdl=en&searchOrigin=Resultlist_top-search"
    keywords = ["werkstudent", "working student", "intern", "internship", "studentische Hilfskraft", "praktikum", "Praktikant"]
    card_selector = "article[data-testid='job-item']"

    def __init__(self, settings: SourceSettings, driver_factory: Any | None = None) -> None:
        self.settings = settings
        self.driver_factory = driver_factory or self._driver

    def build_search_urls(self) -> list[str]:
        return [self.search_base.format(keyword=quote(term.strip().replace(" ", "-"), safe="")) for term in self.keywords]

    @staticmethod
    def build_page_url(base_url: str, page: int) -> str:
        # Mirror the site's own pagination link order: ?page=N&action=...
        parsed = urlparse(base_url)
        query = parse_qs(parsed.query)
        ordered = {"page": [str(page)], **query}
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(ordered, doseq=True), parsed.fragment))

    @staticmethod
    def _driver(headless: bool):
        # StepStone's edge rejects automated Chrome over HTTP/2 with
        # ERR_HTTP2_PROTOCOL_ERROR; forcing HTTP/1.1 (--disable-http2, --disable-quic)
        # plus standard anti-automation flags makes pages load reliably.
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "StepStone requires the optional 'selenium' package. Install it "
                "(pip install selenium) or skip the stepstone source (--source working_student)."
            ) from exc
        options = Options()
        options.add_argument("--window-size=1600,1200")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-http2")
        options.add_argument("--disable-quic")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--lang=en-US")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        if headless:
            options.add_argument("--headless=new")
        return webdriver.Chrome(options=options)

    @staticmethod
    def _text(parent: Any, selector: str) -> str:
        try:
            elements = parent.find_elements("css selector", selector)
            return elements[0].text.strip() if elements else ""
        except Exception:
            return ""

    @staticmethod
    def _attr(parent: Any, selector: str, name: str) -> str:
        try:
            elements = parent.find_elements("css selector", selector)
            return str(elements[0].get_attribute(name) or "").strip() if elements else ""
        except Exception:
            return ""

    def _wait_for_cards(self, driver: Any, timeout_seconds: float) -> bool:
        """Poll until listing cards render (or timeout). Returns True if cards appeared."""
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while time.monotonic() < deadline:
            try:
                if driver.find_elements("css selector", self.card_selector):
                    time.sleep(1.0)  # let the result list settle
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def _wait_for_details(self, driver: Any, selectors: list[str], timeout_seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while time.monotonic() < deadline:
            for selector in selectors:
                if self._text(driver, selector):
                    return True
            time.sleep(0.5)
        return False

    def _cards(self, driver: Any) -> list[dict[str, Any]]:
        try:
            cards = driver.find_elements("css selector", self.card_selector)
        except Exception:
            return []
        stamp = datetime.now(timezone.utc).isoformat()
        return [{
            "source": self.name,
            "source_job_id": str(card.get_attribute("id") or ""),
            "title": self._text(card, 'a[data-testid="job-item-title"]'),
            "company": self._text(card, '[data-at="job-item-company-name"]'),
            "location": self._text(card, '[data-at="job-item-location"]'),
            "posted_time": self._text(card, "time"),
            "job_url": self._attr(card, 'a[data-testid="job-item-title"]', "href"),
            "company_url": self._attr(card, 'a[data-at="company-logo"]', "href"),
            "snippet": self._text(card, '[data-at="jobcard-content"]'),
            "scraped_at_utc": stamp,
        } for card in cards]

    def _details(self, driver: Any, url: str) -> dict[str, Any]:
        try:
            driver.get(url)
        except Exception as exc:
            return {"details_fetched": "false", "detail_error": f"load error: {type(exc).__name__}"}
        description_selectors = [".at-section-text-description-content", '[data-at="section-text-description"]', '[data-testid="job-ad-content"]']
        self._wait_for_details(driver, description_selectors, timeout_seconds=10)
        def first(selectors: list[str]) -> str:
            for selector in selectors:
                value = self._text(driver, selector)
                if value:
                    return value
            return ""
        description = first(description_selectors)
        profile = first([".at-section-text-profile", '[data-at="section-text-profile"]'])
        offer = first([".at-section-text-benefits", '[data-at="section-text-benefits"]'])
        return {
            "detail_company_name": first(['[data-at="metadata-company-name"]']),
            "detail_location": first(['[data-at="metadata-location"]']),
            "detail_contract_type": first(['[data-at="metadata-contract-type"]']),
            "detail_work_type": first(['[data-at="metadata-work-type"]']),
            "detail_online_date": first(['[data-at="metadata-online-date"]']),
            "job_description": description,
            "applicant_profile": profile,
            "what_they_offer": offer,
            "about_us": first(['div[data-at="section-text-introduction"]']),
            "your_tasks": description,
            "requirements": profile,
            "we_offer": offer,
            "predicted_salary": first(['.at-predicted-salary-range']),
            "details_fetched": "true" if description or profile or offer else "false",
            "detail_error": "" if description or profile or offer else "no detail text found",
        }

    def fetch(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        transport_error = False
        driver = self.driver_factory(self.settings.headless)
        try:
            for base_url in self.build_search_urls():
                empty_streak = 0
                for page in range(1, self.settings.max_pages + 1):
                    url = self.build_page_url(base_url, page)
                    try:
                        driver.get(url)
                        transport_ok = True
                    except Exception:
                        transport_error = True
                        transport_ok = False
                    page_rows: list[dict[str, Any]] = []
                    if transport_ok and self._wait_for_cards(driver, self.settings.wait_seconds):
                        page_rows = self._cards(driver)
                    if not page_rows:
                        empty_streak += 1
                        if empty_streak >= self.settings.empty_page_stop_streak:
                            break
                        continue
                    empty_streak = 0
                    for row in page_rows:
                        if row["job_url"] and row["job_url"] not in seen:
                            seen.add(row["job_url"])
                            rows.append(row)
                    time.sleep(self.settings.page_delay_seconds)
            if self.settings.fetch_details and rows:
                for row in rows:
                    row.update(self._details(driver, row["job_url"]))
        finally:
            try:
                driver.quit()
            except Exception:
                pass
        if not rows and transport_error and self.settings.headless:
            retry_settings = SourceSettings(**{**self.settings.__dict__, "headless": False})
            return StepStoneFetcher(retry_settings, self.driver_factory).fetch()
        return rows


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_thread_state = threading.local()


def _wsj_get(url: str, settings: SourceSettings) -> str:
    """Fetch one detail page using plain urllib with per-thread pacing."""
    attempts = max(1, settings.retries)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            previous = getattr(_thread_state, "last_request_at", None)
            if previous is not None and settings.delay_seconds > 0:
                elapsed = time.monotonic() - previous
                if elapsed < settings.delay_seconds:
                    time.sleep(settings.delay_seconds - elapsed)
            _thread_state.last_request_at = time.monotonic()
            headers = {
                "User-Agent": settings.user_agent,
                "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
            }
            request = Request(url, headers=headers)
            with urlopen(request, timeout=settings.request_timeout_seconds) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"HTTP {response.status}")
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - bounded source retry
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(settings.delay_seconds * (attempt + 1))
    raise RuntimeError(f"detail request failed after {attempts} attempt(s): {last_error}") from last_error


def _fetch_working_student_detail(url: str, settings: SourceSettings) -> dict[str, Any]:
    html = _wsj_get(url, settings)
    return parse_detail(url, html)


def _fetch_listing_source(name: str, settings: Any, fetcher_factory: Callable[[str, SourceSettings], Any] | None = None) -> list[dict[str, Any]]:
    source_settings = settings.stepstone if name == "stepstone" else settings.working_student
    listing_settings = replace(source_settings, fetch_details=False)
    if fetcher_factory is not None:
        fetcher = fetcher_factory(name, listing_settings)
    elif name == "stepstone":
        fetcher = StepStoneFetcher(listing_settings)
    else:
        fetcher = WorkingStudentFetcher(listing_settings)
    return fetcher.fetch() or []


def _fetch_listings_in_parallel(
    selected: list[str],
    settings: Any,
    fetcher_factory: Callable[[str, SourceSettings], Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    if not selected:
        return rows, errors
    with ThreadPoolExecutor(max_workers=min(2, len(selected)), thread_name_prefix="step1-listing") as executor:
        futures = {
            executor.submit(_fetch_listing_source, name, settings, fetcher_factory): name
            for name in selected
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                fetched = future.result()
                for row in fetched:
                    row.setdefault("source", name)
                rows.extend(fetched)
                print(f"[STEP1-UPDATED] {name}: {len(fetched)} listing records")
            except Exception as exc:  # noqa: BLE001 - isolate independent sources
                errors[name] = f"{type(exc).__name__}: {exc}"
                print(f"[STEP1-UPDATED] ERROR {name}: {errors[name]}", file=sys.stderr)
    return rows, errors


def _deduplicate_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    duplicates = 0
    for row in rows:
        url = canonical_url(row.get("job_url"))
        key = f"url:{url}" if url else f"source-id:{row.get('source')}:{row.get('source_job_id')}"
        if key not in by_key:
            by_key[key] = dict(row)
            order.append(key)
            continue
        duplicates += 1
        existing = by_key[key]
        for field, incoming in row.items():
            current = existing.get(field)
            if not clean_text(current) or len(_csv_value(incoming)) > len(_csv_value(current)):
                existing[field] = incoming
    return [by_key[key] for key in order], duplicates


def _apply_detail(row: dict[str, Any], detail: dict[str, Any], cached: bool) -> None:
    row.update(detail)
    row["details_cached"] = "true" if cached else "false"
    row["optimization_status"] = "detail_cached" if cached else "detail_fetched"
    row["optimization_reasons"] = "reused detail cache" if cached else "detail fetched after listing prefilter"


def _fetch_stepstone_details(
    rows: list[dict[str, Any]],
    settings: SourceSettings,
    cache: DetailCache,
    ttl: timedelta,
    use_cache: bool,
) -> tuple[int, int, int]:
    misses: list[dict[str, Any]] = []
    cache_hits = 0
    for row in rows:
        detail = cache.get(row, ttl) if use_cache else None
        if detail is not None:
            _apply_detail(row, detail, cached=True)
            cache_hits += 1
        else:
            misses.append(row)
    if not misses:
        return cache_hits, 0, 0

    fetcher = StepStoneFetcher(settings)
    driver: Any | None = None
    fetched = 0
    failures = 0
    try:
        driver = fetcher.driver_factory(settings.headless)
        for row in misses:
            try:
                detail = fetcher._details(driver, row["job_url"])
                _apply_detail(row, detail, cached=False)
                cache.put(row, detail)
                fetched += 1
            except Exception as exc:  # noqa: BLE001 - one job must not stop the batch
                row["details_cached"] = "false"
                row["optimization_status"] = "detail_failed"
                row["optimization_reasons"] = "detail request failed"
                row["detail_error"] = f"{type(exc).__name__}: {exc}"
                failures += 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
    return cache_hits, fetched, failures


def _fetch_working_student_details(
    rows: list[dict[str, Any]],
    settings: SourceSettings,
    cache: DetailCache,
    ttl: timedelta,
    use_cache: bool,
    workers: int,
) -> tuple[int, int, int]:
    misses: list[dict[str, Any]] = []
    cache_hits = 0
    for row in rows:
        detail = cache.get(row, ttl) if use_cache else None
        if detail is not None:
            _apply_detail(row, detail, cached=True)
            cache_hits += 1
        else:
            misses.append(row)
    if not misses:
        return cache_hits, 0, 0

    fetched = 0
    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="step1-detail") as executor:
        futures = {
            executor.submit(_fetch_working_student_detail, row["job_url"], settings): row
            for row in misses
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                detail = future.result()
                _apply_detail(row, detail, cached=False)
                cache.put(row, detail)
                fetched += 1
            except Exception as exc:  # noqa: BLE001 - preserve failed rows for review
                row["details_cached"] = "false"
                row["optimization_status"] = "detail_failed"
                row["optimization_reasons"] = "detail request failed"
                row["detail_error"] = f"{type(exc).__name__}: {exc}"
                failures += 1
    return cache_hits, fetched, failures


def fetch_jobs(
    output_csv: Path = DEFAULT_OUTPUT_CSV,
    source: str = "both",
    detail_mode: str = "selective",
    cache_path: Path = DEFAULT_CACHE,
    cache_ttl_hours: float = 24.0,
    detail_workers: int = 3,
    use_cache: bool = True,
    settings: Any | None = None,
    filters: Filters | None = None,
    fetcher_factory: Callable[[str, SourceSettings], Any] | None = None,
) -> dict[str, Any]:
    """Run the optimized fetch workflow and return metrics."""
    if source not in {"both", "stepstone", "working_student"}:
        raise ValueError("source must be one of: both, stepstone, working_student")
    if detail_mode not in {"selective", "all", "none"}:
        raise ValueError("detail_mode must be selective, all, or none")
    if cache_ttl_hours < 0:
        raise ValueError("cache_ttl_hours must not be negative")
    if detail_workers < 1:
        raise ValueError("detail_workers must be positive")

    settings = settings or load_settings()
    filters = filters or load_filters()
    selected = [source] if source != "both" else ["stepstone", "working_student"]
    selected = [
        name for name in selected
        if (settings.stepstone if name == "stepstone" else settings.working_student).enabled
    ]
    started = time.monotonic()
    listing_rows, source_errors = _fetch_listings_in_parallel(selected, settings, fetcher_factory)
    unique_rows, duplicates = _deduplicate_rows(listing_rows)
    now = _utc_now()
    detail_rows: dict[str, list[dict[str, Any]]] = {"stepstone": [], "working_student": []}
    hard_rejected = 0
    detail_skipped = 0

    for row in unique_rows:
        raw_source = clean_text(row.get("source")).casefold()
        source_name = "working_student" if raw_source in {"working_student", "workingstudentjobs.de", "workingstudent", "wsj"} or "workingstudentjobs" in clean_text(row.get("job_url")).casefold() else "stepstone"
        rejected, reasons = _prefilter_listing(row, filters, now)
        if rejected:
            row["optimization_status"] = "listing_rejected"
            row["optimization_reasons"] = "; ".join(reasons)
            row["details_cached"] = "false"
            hard_rejected += 1
            continue
        should_detail = detail_mode == "all" or (detail_mode == "selective" and _needs_details(row, source_name, filters))
        if should_detail and clean_text(row.get("job_url")):
            row["optimization_status"] = "detail_queued"
            row["optimization_reasons"] = "listing passed cheap prefilter"
            detail_rows[source_name].append(row)
        else:
            row["optimization_status"] = "listing_only"
            row["optimization_reasons"] = "details skipped by detail mode/prefilter"
            row["details_cached"] = "false"
            detail_skipped += 1

    cache = DetailCache(Path(cache_path))
    ttl = timedelta(hours=cache_ttl_hours)
    cache_hits = detail_fetched = detail_failures = 0
    if detail_mode != "none":
        step_settings = settings.stepstone
        wsj_settings = settings.working_student
        if detail_rows["stepstone"]:
            hits, fetched, failures = _fetch_stepstone_details(detail_rows["stepstone"], step_settings, cache, ttl, use_cache)
            cache_hits += hits
            detail_fetched += fetched
            detail_failures += failures
        if detail_rows["working_student"]:
            hits, fetched, failures = _fetch_working_student_details(detail_rows["working_student"], wsj_settings, cache, ttl, use_cache, detail_workers)
            cache_hits += hits
            detail_fetched += fetched
            detail_failures += failures
    cache.save()

    # Keep source order stable in the output even though listing fetches and
    # detail futures complete in parallel.
    write_jobs_csv(unique_rows, Path(output_csv))
    summary = {
        "source": source,
        "detail_mode": detail_mode,
        "listing_records": len(listing_rows),
        "unique_records": len(unique_rows),
        "duplicates_removed": duplicates,
        "listing_rejected": hard_rejected,
        "detail_candidates": len(detail_rows["stepstone"]) + len(detail_rows["working_student"]),
        "detail_skipped": detail_skipped,
        "detail_cache_hits": cache_hits,
        "detail_fetched": detail_fetched,
        "detail_failures": detail_failures,
        "duration_seconds": round(time.monotonic() - started, 3),
        "source_errors": source_errors,
        "output_csv": str(Path(output_csv)),
        "cache_path": str(Path(cache_path)),
    }
    if not unique_rows:
        if source_errors:
            raise RuntimeError(f"all selected sources failed: {source_errors}")
        raise RuntimeError("all selected sources returned zero jobs")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone Stage 1 listing/detail fetcher (zero project dependencies)")
    parser.add_argument("--source", choices=("both", "stepstone", "working_student"), default="both")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--cache-ttl-hours", type=float, default=24.0)
    parser.add_argument("--detail-workers", type=int, default=3)
    parser.add_argument("--detail-mode", choices=("selective", "all", "none"), default="selective")
    parser.add_argument("--no-cache", action="store_true", help="Do not read existing cached detail records")
    parser.add_argument("--no-details", action="store_true", help="Alias for --detail-mode none")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    detail_mode = "none" if args.no_details else args.detail_mode
    try:
        summary = fetch_jobs(
            output_csv=args.output,
            source=args.source,
            detail_mode=detail_mode,
            cache_path=args.cache,
            cache_ttl_hours=args.cache_ttl_hours,
            detail_workers=args.detail_workers,
            use_cache=not args.no_cache,
        )
    except Exception as exc:  # noqa: BLE001 - CLI entry point reports cleanly
        print(f"[STEP1-UPDATED] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())