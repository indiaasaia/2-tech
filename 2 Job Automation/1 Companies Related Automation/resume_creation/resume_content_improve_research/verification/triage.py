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

Writes output_v2/shortlist.json sorted best-first with per-job tier, score and
top gaps — the file the dashboard and any auto-apply step should consume.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from resume_content_improve_research import config

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
        entries.append({
            "title": record.get("title", ""),
            "company": record.get("company", ""),
            "job_url": record.get("job_url", ""),
            "score": score,
            "tier": tier_for(score if isinstance(score, (int, float)) else None),
            "required_coverage": record.get("required_coverage"),
            "preferred_coverage": record.get("preferred_coverage"),
            "top_gaps": _top_gaps(record.get("gap_report")),
            "pdf": record.get("pdf", ""),
            "docx": record.get("docx", ""),
        })
    entries.sort(key=lambda e: (-(e["score"] or 0.0), e["title"]))
    summary: dict[str, int] = {}
    for entry in entries:
        summary[entry["tier"]] = summary.get(entry["tier"], 0) + 1
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy": "rank verified resumes by honest-fit score; apply strong-first",
        "counts": {"verified": len(entries), **summary},
        "recommendation": (
            f"apply to the {summary.get('strong', 0)} strong-fit job(s) first; "
            f"{summary.get('weak', 0) + summary.get('poor', 0)} job(s) fall below the "
            f"{WEAK_THRESHOLD:.0f}-point effort line"
        ),
        "jobs": entries,
    }


def write_shortlist(results: list[dict], path: Path | None = None) -> dict:
    """Build + persist output_v2/shortlist.json; returns the payload."""
    payload = build_shortlist(results)
    target = path or (config.OUTPUT_DIR / "shortlist.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
