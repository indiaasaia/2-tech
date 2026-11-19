"""JD analyst: 1 LLM call -> strict-JSON structured requirement extraction.

Prompt includes the three V6 patches (language-requirement rule with worked
example; preferred-tier guidance; <=4-word verbatim items). Whatever the model
still misses, the deterministic post-check fixes (V7 §4).
"""
from __future__ import annotations

import time

from pydantic import BaseModel, Field, ValidationError

from resume_content_improve_research.generation.llm import call_llm, extract_json

DESCRIPTION_LIMIT = 6000  # chars of job_description sent to the model (v1 parity)


class LanguageRequirement(BaseModel):
    """One JD language requirement.

    The analyst schema only understands English/German (the resume prints only
    those two meaningfully); other languages the JD mentions are kept verbatim
    in the `other` field so the gap report can surface them without blocking
    schema validation (measured: a JD asking for Hebrew parked the whole job).
    """
    language: str = Field(pattern="(?i)^(english|german|other)$")
    level: str | None = None
    other: str | None = None


class JDAnalysis(BaseModel):
    """Strict schema for the analyst output (validated with pydantic)."""
    title_core: str = ""
    language: str = Field(default="en", pattern="^(en|de)$")
    required: list[str] = Field(default_factory=list, max_length=12)
    preferred: list[str] = Field(default_factory=list, max_length=10)
    tools: list[str] = Field(default_factory=list, max_length=15)
    languages_required: list[LanguageRequirement] = Field(default_factory=list, max_length=2)
    years_experience: int | None = None
    domain: str = ""
    knockouts: list[str] = Field(default_factory=list, max_length=5)

    model_config = {"extra": "ignore"}


ANALYST_PROMPT = """You are a precise job-description analyst. Extract structured data from the posting below.
Return ONLY valid JSON, exactly this schema, no markdown, no explanation:
{"title_core": "...", "language": "en|de",
 "required": ["verbatim hard requirement terms, max 4 words each, max 10 items"],
 "preferred": ["verbatim nice-to-have terms, max 4 words each, max 8 items"],
 "tools": ["named tools/technologies/software/frameworks, verbatim, max 12 items"],
 "languages_required": [{"language": "English or German", "level": "e.g. B2, C1, fluent, business, native, or null"}],
 "years_experience": number or null,
 "domain": "one-phrase domain label",
 "knockouts": ["hard knockout criteria like degree or visa, max 3, or empty"]}

Rules:
1. Copy tool names EXACTLY as the posting writes them.
2. LANGUAGE RULE: if the posting mentions ANY language requirement (English OR German,
   any level incl. "basic", "fluency", "business level", "ideally german"), it MUST appear
   in languages_required. Example: a posting saying "ideally english and german" must yield
   "languages_required": [{"language": "English", "level": null}, {"language": "German", "level": null}].
3. TIER RULE: distinguish required (must-have section) from preferred ("nice to have",
   "ideally", "bonus", "plus", "desirable"). When unsure, a term from the must-have section
   is required; a term from anywhere else is preferred.
4. Items are SHORT: at most 4 words each (single skill/term, not sentences).
5. If the posting has no description text, set language "en" and leave lists empty.

JOB POSTING:
Title: {{TITLE}}
Description: {{DESCRIPTION}}"""


def build_prompt(title: str, description: str) -> str:
    return ANALYST_PROMPT.replace("{{TITLE}}", (title or "").strip()).replace(
        "{{DESCRIPTION}}", (description or "")[:DESCRIPTION_LIMIT]
    )


def parse_analysis(raw_json: dict | None) -> JDAnalysis:
    """Validate raw JSON into JDAnalysis; raises ValueError with details on failure.

    Non-English/German language entries are coerced to language='other' with the
    original name preserved in `other` (they become gap-report rows, not gates).
    """
    if raw_json is None:
        raise ValueError("no JSON object in analyst reply")
    for entry in raw_json.get("languages_required", []) or []:
        if isinstance(entry, dict):
            name = str(entry.get("language") or "").strip()
            if name and name.lower() not in ("english", "german"):
                entry["language"] = "other"
                entry["other"] = name
    try:
        return JDAnalysis.model_validate(raw_json)
    except ValidationError as exc:
        raise ValueError(f"analyst JSON failed schema: {exc.errors()[:4]}") from exc


def analyze_job(
    title: str,
    description: str,
    token: str,
    repair_attempts: int = 1,
    network_attempts: int = 2,
) -> tuple[JDAnalysis, dict]:
    """Run the analyst call(s) for one job; returns (analysis, meta).

    One call; on invalid output, `repair_attempts` repair calls are made with the
    error appended. Empty replies (transient free-tier truncations) get one more
    full retry at temperature 0. The caller applies the deterministic post-check.
    meta: {calls, latency_s, repair_used, error}.
    """
    meta: dict = {"calls": 0, "latency_s": 0.0, "repair_used": 0, "error": ""}
    prompt = build_prompt(title, description)
    start = time.time()
    error = ""
    for network_attempt in range(network_attempts):
        raw = call_llm(prompt, token, temperature=0.1, max_tokens=1600)
        meta["calls"] += 1
        try:
            analysis = parse_analysis(extract_json(raw))
            meta["latency_s"] = round(time.time() - start, 1)
            return analysis, meta
        except ValueError as exc:
            error = str(exc)
            if "no JSON object" in error and network_attempt < network_attempts - 1:
                continue  # transient empty/truncated reply -> one clean retry
            break
    for _ in range(repair_attempts):
        meta["repair_used"] += 1
        meta["calls"] += 1
        repair_prompt = (
            prompt
            + "\n\nYOUR PREVIOUS REPLY WAS INVALID: "
            + error[:400]
            + "\nReturn ONLY corrected valid JSON matching the schema. No other text."
        )
        raw = call_llm(repair_prompt, token, temperature=0.0, max_tokens=1600)
        try:
            analysis = parse_analysis(extract_json(raw))
            meta["latency_s"] = round(time.time() - start, 1)
            return analysis, meta
        except ValueError as exc:
            error = str(exc)
    meta["latency_s"] = round(time.time() - start, 1)
    meta["error"] = error
    raise LLMAnalysisError(error)


class LLMAnalysisError(RuntimeError):
    """Analyst could not produce valid JSON even after repair calls."""
