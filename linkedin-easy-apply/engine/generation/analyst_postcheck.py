"""Deterministic analyst post-check: LLM proposes, code disposes (V7 §4).

Measured reason this exists: the analyst returned languages_required [] on a JD
literally saying "ideally english and german", and sentence-length required items.
The post-check is deterministic: regex language sweep, dedupe, item-length tiers.
"""
from __future__ import annotations

import re

from engine.generation.analyst import JDAnalysis

# Language-requirement sweep: (pattern, language, default_level)
_LANGUAGE_PATTERNS: list[tuple[str, str, str | None]] = [
    (r"(?i)\bgerman\b[^.;]{0,40}\b(c1|c2|b2|b1|a2|fluent|verhandlungssicher|business|native)\b", "German", None),
    (r"(?i)\b(c1|c2|b2|b1|fluent|verhandlungssicher|business.level)\b[^.;]{0,40}\bgerman\b", "German", None),
    (r"(?i)\bgerman(?:\s+language)?\s*(?:knowledge|skills|proficiency|level)?\s*(?:at|of)?\s*(?:least)?\s*(b1|b2|c1|a2)?", "German", None),
    (r"(?i)\bdeutschkund|deutsche sprachkenntnisse|sprachkenntnisse.{0,30}deutsch", "German", None),
    (r"(?i)\bgerman\b", "German", None),
    (r"(?i)\benglish\b[^.;]{0,40}\b(c1|c2|b2|b1|fluent|business|native)\b", "English", None),
    (r"(?i)\b(business.level|fluent)\b[^.;]{0,30}\benglish\b", "English", None),
    (r"(?i)\benglish\b", "English", None),
]

_WORD_LIMIT_REQUIRED = 4
_WORD_LIMIT_PREFERRED = 5
_WORD_LIMIT_TOOLS = 6

# Common systems acronyms the analyst misses as tools (V6: 'rexx' was found by the
# LLM but HRIS/CRM-class enterprise systems slip through as prose).
_KNOWN_SYSTEM_ACRONYMS = (
    "HRIS", "HRM", "CRM", "ERP", "ATS", "CMS", "PIM", "MES", "SCADA", "PLM",
    "BI", "ETL", "MLOps", "DevOps", "CI", "CD", "CI/CD", "POS", "LMS", "DMS",
    "API", "REST", "GraphQL", "SQL", "NoSQL", "KPI", "OKR", "SaaS", "PaaS",
)

# Non-tool vocabulary that must never become a mirrorable tool.
_TOOL_DROP_RE = re.compile(
    r"(?i)^(\d+(?:[.,]\d+)?\s*%?|\d{4}|[\d\s+%.,:/-]+|hours?|hrs?|stunden?|weeks?|months?|years?|"
    r"full.time|part.time|remote|hybrid|onsite|on.site|e\s?mail|phone|team|english|german)$"
)


def _sweep_languages(text: str, analysis: JDAnalysis) -> list[str]:
    """Force-insert language requirements the model missed; return fixes applied."""
    fixes: list[str] = []
    have = {entry.language.lower() for entry in analysis.languages_required}
    for pattern, language, default_level in _LANGUAGE_PATTERNS:
        if language.lower() in have:
            continue
        match = re.search(pattern, text)
        if not match:
            continue
        level = default_level
        if level is None:
            level_match = re.search(r"\b(b1|b2|c1|c2|a1|a2)\b", match.group(0), re.IGNORECASE)
            level = level_match.group(1).upper() if level_match else None
            if level is None and re.search(r"(?i)fluent|verhandlungssicher|business", match.group(0)):
                level = "fluent"
            if level is None and re.search(r"(?i)native|muttersprache", match.group(0)):
                level = "native"
        analysis.languages_required.append(
            type(analysis.languages_required[0])(language=language, level=level)
            if analysis.languages_required
            else _make_language(language, level)
        )
        have.add(language.lower())
        fixes.append(f"force-inserted language requirement: {language} ({level or 'level not stated'})")
    # canonical order: English first, then German
    analysis.languages_required.sort(key=lambda e: 0 if e.language.lower() == "english" else 1)
    return fixes


def _make_language(language: str, level: str | None):
    from engine.generation.analyst import LanguageRequirement

    return LanguageRequirement(language=language, level=level)


def _shorten(items: list[str], limit: int, bucket: str, fixes: list[str]) -> None:
    """Drop over-long items (deterministic tier enforcement, V7 patch 3)."""
    kept: list[str] = []
    for item in items:
        if len(item.split()) <= limit:
            kept.append(item)
        else:
            fixes.append(f"{bucket}: dropped over-long item ({len(item.split())} words): {item!r}")
    items[:] = kept


def _dedupe(items: list[str], bucket: str, fixes: list[str]) -> None:
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        key = re.sub(r"[^a-z0-9+#. ]", "", item.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            kept.append(item)
        elif item.strip():
            fixes.append(f"{bucket}: removed duplicate {item!r}")
    items[:] = kept


def _drop_tools_from_required(analysis: JDAnalysis, fixes: list[str]) -> None:
    """A bare tool name in `required` that is already in `tools` stays in tools only."""
    tool_keys = {re.sub(r"[^a-z0-9+#. ]", "", t.lower()).strip() for t in analysis.tools}
    kept: list[str] = []
    for item in analysis.required:
        if re.sub(r"[^a-z0-9+#. ]", "", item.lower()).strip() in tool_keys and len(item.split()) == 1:
            fixes.append(f"required: single-tool item {item!r} is covered by tools")
            continue
        kept.append(item)
    analysis.required[:] = kept


def _sweep_system_tools(analysis: JDAnalysis, job_text: str, fixes: list[str]) -> None:
    """Force-insert known system acronyms found in the JD; drop junk tool entries."""
    have = {re.sub(r"[^a-z0-9]", "", t.lower()) for t in analysis.tools}
    for acronym in _KNOWN_SYSTEM_ACRONYMS:
        key = re.sub(r"[^a-z0-9]", "", acronym.lower())
        if key in have:
            continue
        if re.search(rf"\b{re.escape(acronym)}\b", job_text, re.IGNORECASE):
            analysis.tools.append(acronym)
            have.add(key)
            fixes.append(f"tools: force-inserted system acronym {acronym}")
    # drop non-tools (numbers, time units, soft words)
    kept: list[str] = []
    for tool in analysis.tools:
        if _TOOL_DROP_RE.match(tool.strip()):
            fixes.append(f"tools: dropped non-tool entry {tool!r}")
        else:
            kept.append(tool)
    analysis.tools[:] = kept


def postcheck(analysis: JDAnalysis, job_text: str) -> list[str]:
    """Enforce the deterministic rules in place; returns a log of fixes applied."""
    fixes: list[str] = []
    fixes += _sweep_languages(job_text, analysis)
    _sweep_system_tools(analysis, job_text, fixes)
    _dedupe(analysis.required, "required", fixes)
    _dedupe(analysis.preferred, "preferred", fixes)
    _dedupe(analysis.tools, "tools", fixes)
    _shorten(analysis.required, _WORD_LIMIT_REQUIRED, "required", fixes)
    _shorten(analysis.preferred, _WORD_LIMIT_PREFERRED, "preferred", fixes)
    _shorten(analysis.tools, _WORD_LIMIT_TOOLS, "tools", fixes)
    _drop_tools_from_required(analysis, fixes)
    if analysis.language not in ("en", "de"):
        analysis.language = "en"
        fixes.append("language: reset to en")
    # Posting language by function-word counts, in BOTH directions. The former
    # heuristic ("any umlaut + any German function word" in the first 3000 chars)
    # flipped an English Deutsche Bank ad to German on one "Düsseldorf" + one "und"
    # (245 English vs 2 German function words) -> a German letter for an English ad.
    detected = detect_posting_language(job_text)
    if detected and detected != analysis.language:
        fixes.append(f"language: corrected {analysis.language} -> {detected} (function-word count)")
        analysis.language = detected
    return fixes


_EN_WORDS = re.compile(r"(?i)\b(?:the|and|of|to|you|your|with|our|for|is|are|we|in|will|as|on)\b")
_DE_WORDS = re.compile(r"(?i)\b(?:der|die|das|und|mit|für|wir|ist|sind|ein|eine|zu|von|bei|auf|sie|ihre|du|deine|oder)\b")


def detect_posting_language(text: str) -> str | None:
    """'de' / 'en' when the posting's function words clearly favour one language
    (at least 2x and at least 4 hits), else None (keep the analyst's label)."""
    english = len(_EN_WORDS.findall(text or ""))
    german = len(_DE_WORDS.findall(text or ""))
    if german >= 4 and german >= 2 * english:
        return "de"
    if english >= 4 and english >= 2 * german:
        return "en"
    return None


def analysis_to_dict(analysis: JDAnalysis) -> dict:
    """Serial analysis for the component stores and reports."""
    data = analysis.model_dump()
    return data
