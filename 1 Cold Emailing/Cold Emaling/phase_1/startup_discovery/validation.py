"""Structural validation of Gemini's candidate output.

The prompt's quality rules become enforced checks here:
- required evidence fields must be present and meaningful (the no-guessing
  rule — "Not verified." is NOT acceptable for English/student evidence)
- hiring_probability_score must be an integer >= min_hiring_score
- website must be a plausible URL
- location and at least one source URL are required
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

# Fields where "Not verified." is NOT acceptable — without evidence the
# company must not be returned.
REQUIRED_EVIDENCE_FIELDS = ("english_hiring_evidence", "student_intern_evidence")

# Values that count as "no evidence".
_EMPTY_TOKENS = {
    "", "not verified", "not verified.", "n/a", "na", "none", "unknown",
    "not available", "not found", "no evidence", "not applicable", "-",
}

_URL_RE = re.compile(r"^https?://", flags=re.IGNORECASE)


class ParseError(Exception):
    """The model output could not be parsed as the expected JSON envelope."""


def _clean(value) -> str:
    return str(value or "").strip()


def validate_candidate(candidate: dict, min_score: int) -> tuple[bool, list[str]]:
    """Return (is_acceptable, problems). Everything must hold for acceptance."""
    problems: list[str] = []

    name = _clean(candidate.get("company_name"))
    if not name:
        problems.append("company_name missing")

    website = _clean(candidate.get("website"))
    if not website:
        problems.append("website missing")
    elif not _URL_RE.match(website):
        problems.append(f"website is not a URL: {website!r}")
    else:
        host = urlparse(website).netloc.lower()
        if "." not in host or " " in host:
            problems.append(f"website has no valid domain: {website!r}")

    location = _clean(candidate.get("location"))
    if not location:
        problems.append("location missing")

    for field in REQUIRED_EVIDENCE_FIELDS:
        value = _clean(candidate.get(field)).lower()
        if value in _EMPTY_TOKENS:
            problems.append(f"{field} missing or empty")

    raw_score = candidate.get("hiring_probability_score")
    try:
        score = int(raw_score)
    except (TypeError, ValueError):
        problems.append(f"hiring_probability_score not an integer: {raw_score!r}")
        score = None
    if score is not None:
        if not (0 <= score <= 100):
            problems.append(f"hiring_probability_score out of range: {score}")
        elif score < min_score:
            problems.append(f"hiring_probability_score {score} below minimum {min_score}")

    sources = candidate.get("sources")
    if not isinstance(sources, list) or not any(_clean(s) for s in sources):
        problems.append("sources missing or empty")

    return (not problems, problems)


def extract_json(text: str) -> dict:
    """Robustly extract the (first) JSON object from model output.

    Tolerates markdown fences and prose surrounding the JSON payload.
    """
    if not text:
        raise ParseError("empty model output")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ParseError("no JSON object found in model output")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ParseError(f"model output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ParseError("JSON payload is not an object")
    return data


def parse_response(raw_text: str, min_score: int) -> tuple[list[dict], list[tuple[dict, list[str]]], str]:
    """Parse + validate a model response.

    Returns (accepted, rejected, notes) where each rejected entry carries
    its validation problems for inspectability.
    """
    data = extract_json(raw_text)
    companies = data.get("companies", [])
    if not isinstance(companies, list):
        raise ParseError("'companies' is not a list")
    notes = _clean(data.get("notes"))

    accepted: list[dict] = []
    rejected: list[tuple[dict, list[str]]] = []
    for entry in companies:
        if not isinstance(entry, dict):
            rejected.append((entry, ["entry is not an object"]))
            continue
        ok, problems = validate_candidate(entry, min_score)
        if ok:
            accepted.append(entry)
        else:
            rejected.append((entry, problems))
    return accepted, rejected, notes
