"""Scorecard (FINAL_MODEL 3.3): 0-100, gates mandatory, iteration rule, gap report.

  40 required coverage | 20 preferred coverage | 15 parse fidelity
  10 format checks     | 10 experience relevance | 5 naturalness
Experience relevance: deterministic proxy over claimable overlap (the sampled
LLM critic is optional and budget-capped; the deterministic floor ships first).
Iteration rule: regenerate only if score < 70 or required < 0.8; max 2 iterations;
accept a regenerated v2 only if score(v2) > score(v1) + 2 with G2 clean both times.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from resume_content_improve_research import config
from resume_content_improve_research.generation.claimable_set import ClaimableSet
from resume_content_improve_research.generation.normalize import normalize_skill
from resume_content_improve_research.verification.coverage import CoverageResult, gap_report


@dataclass
class Scorecard:
    total: float = 0.0
    gates_passed: bool = False
    breakdown: dict[str, float] = field(default_factory=dict)
    required_coverage: float = 0.0
    preferred_coverage: float = 0.0
    gaps: dict = field(default_factory=dict)
    needs_regeneration: bool = False


def experience_relevance(intent_text: str, analysis: dict, cset: ClaimableSet) -> float:
    """Deterministic proxy 0-1: share of SKILL required terms covered by OWNABLE skills.

    Mirrors what the 1-call LLM critic would judge (does the profile fit the JD?),
    without spending a call; the sampled critic can replace this later.
    Eligibility criteria (enrollment, hours, location, soft skills) are excluded —
    they say nothing about skill fit and dragged the proxy toward 0 for matching jobs.
    """
    from resume_content_improve_research.verification.coverage import INELIGIBLE_TERM_RE

    norm_text = intent_text.lower()
    ownable = cset.ownable()
    required = [t for t in analysis.get("required", []) if not INELIGIBLE_TERM_RE.search(str(t))]
    if not required:
        return 0.5
    hits = 0
    for term in required:
        key = normalize_skill(str(term)).lower()
        if key in norm_text or key in ownable or any(key in o or o in key for o in ownable):
            hits += 1
    return hits / len(required)


def format_checks(artifact_text: str, parse_result, page_count: int | None = None) -> float:
    """0-1 over measurable format properties (dates, sections, order, one page)."""
    checks = [
        bool(parse_result.dates_found),
        not parse_result.apostrophe_dates,
        len(parse_result.sections_found) >= 6,
        parse_result.reading_order_ok,
        parse_result.ligature_count == 0,
        not re.search(r"@@", artifact_text),
    ]
    if page_count is not None:
        checks.append(page_count == 1)
    return sum(1 for c in checks if c) / len(checks)


def parse_fidelity(parse_result, intent_text: str) -> float:
    """0-1: extracted fields vs intent (name, contact) + intent terms present in artifact."""
    field_ok = sum(1 for flag in (
        parse_result.name_extracted, parse_result.email_extracted, parse_result.phone_extracted
    ) if flag) / 3
    norm_artifact = re.sub(r"\s+", " ", parse_result.text.lower())
    intent_terms = [t for t in re.findall(r"[a-z][a-z+#.-]{3,}", intent_text.lower())]
    if not intent_terms:
        return field_ok
    sample = sorted(set(intent_terms))[:60]
    present = sum(1 for t in sample if t in norm_artifact)
    return 0.5 * field_ok + 0.5 * (present / len(sample))


def build_scorecard(
    gates_passed: bool,
    coverage: CoverageResult,
    parse_result,
    artifact_text: str,
    intent_text: str,
    analysis: dict,
    cset: ClaimableSet,
    page_count: int | None = None,
) -> Scorecard:
    weights = config.SCORE_WEIGHTS
    relevance = experience_relevance(intent_text, analysis, cset)
    fidelity = parse_fidelity(parse_result, intent_text)
    fmt = format_checks(artifact_text, parse_result, page_count=page_count)

    breakdown = {
        "required_coverage": round(weights["required_coverage"] * coverage.required_score, 1),
        "preferred_coverage": round(weights["preferred_coverage"] * coverage.preferred_score, 1),
        "parse_fidelity": round(weights["parse_fidelity"] * fidelity, 1),
        "format_checks": round(weights["format_checks"] * fmt, 1),
        "experience_relevance": round(weights["experience_relevance"] * relevance, 1),
        "naturalness": round(weights["naturalness"] * 0.6, 1),  # deterministic floor until critic runs
    }
    total = round(sum(breakdown.values()), 1)
    needs = (
        total < config.SCORE_REGENERATE_THRESHOLD
        or coverage.required_score < config.REQUIRED_COVERAGE_THRESHOLD
    )
    return Scorecard(
        total=total,
        gates_passed=gates_passed,
        breakdown=breakdown,
        required_coverage=round(coverage.required_score, 3),
        preferred_coverage=round(coverage.preferred_score, 3),
        gaps=gap_report(coverage, analysis),
        needs_regeneration=needs,
    )


def should_accept(candidate_score: float, previous_score: float, candidate_g2_clean: bool) -> bool:
    """Iteration accept rule (FINAL_MODEL 3.3)."""
    return candidate_g2_clean and candidate_score > previous_score + config.ACCEPT_IMPROVEMENT_DELTA
