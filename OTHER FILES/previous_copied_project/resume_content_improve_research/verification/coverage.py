"""Deterministic coverage scorer over the PARSED artifact text (FINAL_MODEL 3.3).

Required/preferred coverage: exact match, then alias map, then rapidfuzz
token_set_ratio >= 92 against the extracted text (V5 §2 design; DE+EN lexicon
is the alias map + ESCO labels; no embeddings — killed by V5 measurement).
Honest-calibrated: missing terms go to the gap report, never fabricated (V7 §3).

Phrase-reality layer (added after the 21-job scored run): analysts emit phrases
like "Python programming" or "behavioral science knowledge" while resumes write
the bare skill. Matching is therefore graded:
  1. exact substring                    -> "exact"
  2. alias-map expansion                -> "alias"
  3. head-noun/filler-stripped variant  -> "alias"   ("python programming" -> "python")
  4. line-local token AND / window fuzzy-> "fuzzy"   (all content words in ONE line)
A term still counts as missing unless the ARTIFACT really contains it — the
stripping only removes boilerplate AROUND the skill, never the skill itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from resume_content_improve_research import config
from resume_content_improve_research.generation.normalize import (
    load_alias_map,
    normalize_skill,
    _norm as _normalize_key,
)


@dataclass
class CoverageResult:
    required_score: float = 0.0
    preferred_score: float = 0.0
    required_missing: list[str] = field(default_factory=list)
    preferred_missing: list[str] = field(default_factory=list)
    matched: dict[str, str] = field(default_factory=dict)  # term -> how it matched
    ineligible: list[str] = field(default_factory=list)    # eligibility criteria, not skills

# Eligibility/logistics criteria are NOT skill coverage and must not dilute the
# required-skill score (they can never honestly "match" a resume text): enrollment,
# work-hour schedules, location, contract type, soft requirements. Measured on the
# 21-job run: they drove scores to 0.0 for jobs whose real skills were covered.
# Soft traits ("fast learner", "willing to learn", "clear communication") added from
# the same run's gap reports — a deterministic scorer cannot honestly match them.
INELIGIBLE_TERM_RE = re.compile(
    r"(?i)(enrol|enroll|degree|bachelor|master|semester|student status|eligib|"
    r"hours?(?:\s+per\s+week)?|hours?/week|\d+\s*(?:h|hrs|hours)|month[s]?|year[s]? of|"
    r"immatrikuliert|einschreib|arbeitszeit|studium|"
    r"on-?site|on ?site|office|remotely|relocat|munich|berlin|hamburg|darmstadt|stuttgart|"
    r"paid internship|side projects?|driver'?s? licence|driver'?s? license|car|"
    r"physical|unrestricted|weekly visit|daily visit|availability|available|"
    r"fluent in english|business ability|team player|self-?driven|structured|reliable|proactive|"
    r"enthusiast|passionate|passion|curious|confident|"
    r"fast learner|quick learner|willing to|motivation|initiative|creativ|engaging|"
    r"communicat|analytical thinking|reliability|comfortable|organizational planning)"
)

# Head nouns / boilerplate AROUND a skill: the analyst writes "X programming",
# "knowledge of X", "experience with X"; the artifact writes "X" or "X: a, b, c".
# Stripping these never fabricates a match — the remaining core must still appear.
_HEAD_NOUN_RE = re.compile(
    r"(?i)\b(programming|development|knowledge|experience|experiences|skills?|"
    r"competenc\w*|proficienc\w*|abilit\w*|expertise|familiarity|understanding|"
    r"exposure|background|basics?|fundamentals?|kenntnisse?|erfahrung)\b"
)

# Filler words removed before the token-AND check (adjectives around the skill).
_FILLER_RE = re.compile(
    r"(?i)\b(very|good|strong|solid|proven|excellent|basic|advanced|deep|"
    r"comfortable|familiar|confidence|on|in|of|with|the|a|an|for|to|using|use|und)\b"
)

# Split points inside one requirement: "English and/or German" is two terms.
_CONNECTOR_SPLIT_RE = re.compile(r"(?:,|/|\band\b|\bor\b|\bund\b)+")


def _norm(text: str) -> str:
    text = re.sub(r"[^\w\s+.#-]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _singular(word: str) -> str:
    """Crude but consistent plural fold ('dashboards'->'dashboard', 'schemas'->'schema')."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _content_words(variant: str) -> list[str]:
    """Singularized content tokens (>=3 chars) of a stripped variant."""
    words = re.findall(r"[a-z0-9][a-z0-9+#.\-]*", variant.lower())
    return [w for w in (_singular(w) for w in words) if len(w) >= 3]


def _line_tokens(text: str) -> list[list[str]]:
    """Tokenized resume lines (case-folded, singularized) for line-local matching."""
    lines: list[list[str]] = []
    for line in text.splitlines():
        words = re.findall(r"[a-z0-9][a-z0-9+#.\-]*", line.lower())
        if words:
            lines.append([_singular(w) for w in words])
    return lines


def _variants(term: str) -> list[str]:
    """Normalized match candidates for one requirement phrase (order matters)."""
    base = _norm(str(term))
    variants = [base] if base else []
    stripped = _HEAD_NOUN_RE.sub(" ", base)
    stripped = _FILLER_RE.sub(" ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if stripped and stripped not in variants:
        variants.append(stripped)
    for part in _CONNECTOR_SPLIT_RE.split(base):
        part = part.strip()
        if not part:
            continue
        part = _HEAD_NOUN_RE.sub(" ", part)
        part = _FILLER_RE.sub(" ", part)
        part = re.sub(r"\s+", " ", part).strip()
        if part and part not in variants:
            variants.append(part)
    return variants


def _term_in_text(term: str, norm_text: str, raw_text_lower: str, lines: list[list[str]]) -> str | None:
    """Return the match type ('exact'|'alias'|'fuzzy') or None."""
    key = _norm(term)
    if not key:
        return None
    if key in norm_text:
        return "exact"
    # expand the term through the alias map (reverse direction: canonical -> its
    # aliases, since the artifact may legitimately use a listed alias form)
    alias_map = load_alias_map()
    candidates = {key}
    for alias, canonical in alias_map.items():
        if _normalize_key(canonical) == key:
            candidates.add(alias)
    canonical = normalize_skill(term).lower()
    candidates.add(canonical)
    candidates.discard("")
    candidates.discard(key)
    if any(candidate and candidate in norm_text for candidate in candidates):
        return "alias"
    # head-noun/filler-stripped variants ("python programming" -> "python")
    variants = _variants(term)
    for variant in variants:
        if variant != key and variant and variant in norm_text:
            return "alias"
    # line-local content-word AND: every content word of the term must appear in
    # ONE extracted line (handles "Programming Languages: Python, C++, SQL")
    best_variant = next((v for v in variants if v), "")
    words = _content_words(best_variant)
    if words:
        n = len(words)
        needed = set(words)
        for tokens in lines:
            if needed <= set(tokens):
                return "fuzzy"
        if 2 <= n <= 4:
            phrase = " ".join(words)
            for tokens in lines:
                for i in range(len(tokens) - n + 1):
                    window = " ".join(tokens[i:i + n])
                    if fuzz.token_set_ratio(phrase, window) >= config.COVERAGE_FUZZY_THRESHOLD:
                        return "fuzzy"
    # fuzzy >= 92 against artifact words (handles plurals and inflections)
    if len(key.split()) == 1 and len(key) >= 4:
        words = set(re.findall(r"[a-z][a-z+#.-]{3,}", raw_text_lower))
        for word in words:
            if fuzz.token_set_ratio(key, word) >= config.COVERAGE_FUZZY_THRESHOLD:
                return "fuzzy"
    return None


def score_coverage(artifact_text: str, analysis: dict) -> CoverageResult:
    """Score required/preferred coverage of the parsed artifact text."""
    result = CoverageResult()
    norm_text = _norm(artifact_text)
    raw_lower = artifact_text.lower()
    lines = _line_tokens(artifact_text)

    def cover(terms: list[str]) -> tuple[float, list[str], list[str]]:
        hits = 0
        missing: list[str] = []
        ineligible: list[str] = []
        eligible_count = 0
        for term in terms:
            if INELIGIBLE_TERM_RE.search(str(term)):
                ineligible.append(str(term))
                continue
            eligible_count += 1
            match_type = _term_in_text(str(term), norm_text, raw_lower, lines)
            if match_type:
                hits += 1
                result.matched[str(term)] = match_type
            else:
                missing.append(str(term))
        # Ineligible criteria are excluded from the denominator: they can never
        # honestly match a resume, and counting them dilutes the score of jobs
        # whose real skills ARE covered (the gap-report note always claimed this;
        # the arithmetic now agrees).
        score = (hits / eligible_count) if eligible_count else 1.0
        return score, missing, ineligible

    result.required_score, result.required_missing, result.ineligible = cover(analysis.get("required", []))
    result.preferred_score, result.preferred_missing, _ = cover(analysis.get("preferred", []))
    return result


def gap_report(coverage: CoverageResult, analysis: dict) -> dict:
    """The per-job gap report: genuinely-missing requirements, never fabricated (V7 §3)."""
    languages = [
        f"{l['language']}" + (f" ({l['level']})" if l.get("level") else "")
        for l in analysis.get("languages_required", [])
    ]
    language_gaps: list[str] = []
    spoken = {"english", "german", "hindi", "gujarati"}
    for entry in analysis.get("languages_required", []):
        language = str(entry.get("language", "")).lower()
        if language not in spoken:
            continue
        level = str(entry.get("level") or "").lower()
        if language == "german" and level and level not in ("a1", "a2", "basic", "beginner"):
            language_gaps.append(f"German {entry.get('level')} required — candidate has A2")
        # English is C2 (native), so English requirements are covered.
    return {
        "missing_required": coverage.required_missing,
        "missing_preferred": coverage.preferred_missing,
        "ineligible_criteria": coverage.ineligible,
        "language_gaps": language_gaps,
        "languages_required": languages,
        "note": ("Missing items are reported, never fabricated into the resume (V7 policy). "
                 "Ineligible criteria are job eligibility rules (enrollment, hours, location) "
                 "and soft traits — they cannot match a resume and are scored separately."),
    }
