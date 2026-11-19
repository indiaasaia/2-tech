"""Application triage: rank verified resumes and shortlist by fit score.

Real-world policy (honest fit, V7-calibration spirit): the scorecard measures
how much of a JD's REQUIRED + PREFERRED vocabulary the truthful resume covers.
A low score is real information — it means the honest resume will lose to a
candidate whose experience genuinely matches. Triage therefore ranks jobs and
recommends effort where fit is real:

  strong    >= STRONG_THRESHOLD  (default 80): apply-first
  good      >= GOOD_THRESHOLD    (default 65): apply
  weak      >= WEAK_THRESHOLD    (default 50): optional
  poor      <  WEAK_THRESHOLD:              deprioritize
Non-skill criteria (enrollment, hours, language levels) are in the gap report,
never in the score, so tiers stay comparable across jobs.

Policy v3 (2026-10-17): every resume carries 100% of its job keywords, so the
score alone no longer separates jobs. Each entry also gets `kb_backed_share`
(share of the job's technical keywords the KB really backs) and a fit tier:
  strong  >= 0.6 | good >= 0.4 | stretch < 0.4
The shortlist is sorted by that share first; `prep_terms` lists what to learn
before an interview.

Writes output/applications/shortlist.json sorted best-first with per-job tier, score and
top gaps — the file the dashboard and any auto-apply step should consume.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from engine import config

STRONG_THRESHOLD = 80.0
GOOD_THRESHOLD = 65.0
WEAK_THRESHOLD = 50.0

TIERS = (("strong", STRONG_THRESHOLD), ("good", GOOD_THRESHOLD), ("weak", WEAK_THRESHOLD), ("poor", 0.0))


def tier_for(score: float | None) -> str:
    if score is None:
        return "poor"
    for tier, floor in TIERS:
        if score >= floor:
            return tier
    return "poor"


def _top_gaps(gap_report: dict | None, limit: int = 4) -> list[str]:
    if not gap_report:
        return []
    missing = list(gap_report.get("missing_required") or [])
    preferred = list(gap_report.get("missing_preferred") or [])
    return (missing + preferred)[:limit]


def build_shortlist(results: list[dict]) -> dict:
    """Ranked shortlist over step-5 result records (verified jobs only)."""
    entries = []
    for record in results:
        if record.get("status") != "verified":
            continue
        score = record.get("score")
        share = record.get("kb_backed_share")
        entries.append({
            "title": record.get("title", ""),
            "company": record.get("company", ""),
            "job_url": record.get("job_url", ""),
            "score": score,
            "tier": tier_for(score if isinstance(score, (int, float)) else None),
            "keyword_coverage": record.get("keyword_coverage"),
            "kb_backed_share": share,
            "fit_tier": fit_tier_for(share),
            "prep_terms": list(record.get("prep_terms") or []),
            "required_coverage": record.get("required_coverage"),
            "preferred_coverage": record.get("preferred_coverage"),
            "top_gaps": _top_gaps(record.get("gap_report")),
            "pdf": record.get("pdf", ""),
            "docx": record.get("docx", ""),
        })
    # real fit first (share of job keywords the KB backs), then the scorecard
    entries.sort(key=lambda e: (-(e["kb_backed_share"] or 0.0), -(e["score"] or 0.0), e["title"]))
    summary: dict[str, int] = {}
    fit_counts: dict[str, int] = {}
    for entry in entries:
        summary[entry["tier"]] = summary.get(entry["tier"], 0) + 1
        if entry["fit_tier"]:
            fit_counts[entry["fit_tier"]] = fit_counts.get(entry["fit_tier"], 0) + 1
    full = sum(1 for e in entries if e["keyword_coverage"] == 1.0)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy": ("every resume carries 100% of its job keywords; rank by the share the "
                   "candidate's KB really backs, apply strong-fit first, prepare prep_terms"),
        "counts": {"verified": len(entries), **summary},
        "fit_counts": fit_counts,
        "recommendation": (
            f"{full}/{len(entries)} resume(s) carry every job keyword. Apply to all; start with the "
            f"{fit_counts.get('strong', 0)} strong-fit job(s). {fit_counts.get('stretch', 0)} stretch job(s) "
            f"need the most interview preparation (see prep_terms)."
        ),
        "jobs": entries,
    }


FIT_STRONG = 0.6
FIT_GOOD = 0.4


def fit_tier_for(share: float | None) -> str:
    """strong / good / stretch by KB-backed keyword share ('' when not measured)."""
    if share is None:
        return ""
    if share >= FIT_STRONG:
        return "strong"
    return "good" if share >= FIT_GOOD else "stretch"


def write_shortlist(results: list[dict], path: Path | None = None) -> dict:
    """Build + persist output/applications/shortlist.json; returns the payload."""
    payload = build_shortlist(results)
    target = path or (config.OUTPUT_DIR / "shortlist.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
