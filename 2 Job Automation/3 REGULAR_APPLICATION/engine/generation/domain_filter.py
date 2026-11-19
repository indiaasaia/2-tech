"""Domain gate for the v2 pre-step: keep or eliminate BEFORE any resume work.

Two deterministic stages (both configurable in knowledge_base/domain_filters.json):

Stage 1 - domain families (keyword test).
  The user's target universe is a FAMILY of domains, not a skill list:
  software, AI/data, automation, computer hardware/IoT/robotics, finance
  (banking/trading/investment), and business roles with a tech/AI/software angle.
  Pure business administration, other engineering branches, health, hospitality,
  logistics, retail etc. get no family signal and fall through to stage 2.

Stage 2 - scored skill alignment (generation/scored_filter.py).
  A family-less job is kept only when >= min_skill_alignment (default 0.60) of
  its demanded skills are skills the candidate is licensed to claim, so jobs
  "way outside the domain" are eliminated without burning analyst/generator
  LLM calls or build time. The 60% bar keeps the net LOOSE: overlapping jobs
  survive, truly alien ones (mechanical, health, hospitality...) drop out.

Decision logic stage 1 (deliberately LOOSE, per the user's instruction):
  1. Family signal: any family keyword (config buckets) in title, tasks,
     requirements, or profile text. Needs-tech business terms count only when
     another family also signals (business + AI/software = keep; pure = out).
  2. Out-of-domain identity: an out_identity keyword in the TITLE with no
     family signal anywhere eliminates the job outright (title says what the
     job IS; JD boilerplate like "constructive feedback culture" must not).
  3. Dominance guard: out-identity hits >= 2 while family hits <= 1 -> out.
     (Keeps jobs like "Coating development" with one stray "automation" out.)
Manual overrides: allowlist file lines (job_url substring) force KEEP.
Every decision is written to output/applications/domain_filter_report.json with reasons
and (for stage-2 eliminations) the full alignment score breakdown.
"""
from __future__ import annotations

import functools
import json
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from engine import config

FILTER_CONFIG_PATH = config.PACKAGE_ROOT / "knowledge_base" / "domain_filters.json"
ALLOWLIST_PATH = config.PACKAGE_ROOT / "knowledge_base" / "domain_allowlist.txt"
REPORT_PATH = config.OUTPUT_DIR / "domain_filter_report.json"

# Job CSV columns whose text carries the actual work content.
TEXT_COLUMNS = ("title", "company", "job_description", "requirements",
                "your_tasks", "applicant_profile", "what_they_offer", "snippet")

TECH_BUSINESS = "tech_business"
TECH_KEYS = {"tech_business_direct", "tech_business_needs_tech"}
_FAMILY_ALIASES = {
    "tech_business_direct": TECH_BUSINESS,
    "tech_business_needs_tech": TECH_BUSINESS,
}

def _load_scored_filter():
    """Import the scored stage lazily (it imports kb_loader; keep import cheap)."""
    from engine.generation import scored_filter
    return scored_filter


def load_filter_config(path: Path = FILTER_CONFIG_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    buckets: dict[str, list[str]] = {}
    for family, spec in (data.get("families") or {}).items():
        keys = [str(k).lower() for k in (spec.get("any") or []) if str(k).strip()]
        if keys:
            buckets[family] = keys
    return buckets


def load_allowlist(path: Path = ALLOWLIST_PATH) -> list[str]:
    if not path.exists():
        return []
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keys.append(line.lower())
    return keys


@functools.lru_cache(maxsize=2048)
def _compile_boundary_pattern(k: str) -> re.Pattern:
    return re.compile(rf"(?<![a-zA-Z0-9_äöüÄÖÜß]){re.escape(k)}(?![a-zA-Z0-9_äöüÄÖÜß])", re.IGNORECASE)


def _bucket_hits(norm_text: str, keys: list[str]) -> list[str]:
    return sorted({k for k in keys if _compile_boundary_pattern(k).search(norm_text)})


def classify_job(job: dict, buckets: dict[str, list[str]],
                 scored: bool = True) -> dict:
    """Decide keep/eliminate for one job; returns the report record.

    scored=True (default): a family-less job falls through to stage 2, the
    60% skill-alignment score against the candidate KB. scored=False (loose
    mode) restores the old behavior: no family signal -> eliminate.
    """
    title = str(job.get("title") or "")
    parts = [title]
    for col in TEXT_COLUMNS[1:]:
        value = str(job.get(col) or "")
        if value:
            parts.append(value)
    # normalize once: lowercase + collapse whitespace (keywords are flat phrases)
    full_norm = " ".join(" ".join(parts).lower().split())
    title_norm = " ".join(title.lower().split())

    # 1. out-of-domain identity keys (never a positive signal)
    out_keys = buckets.get("out_identity", [])
    out_hits_title = _bucket_hits(title_norm, out_keys)
    out_hits_full = _bucket_hits(full_norm, out_keys)

    # 2. family signals over the full text (out_identity excluded)
    hits: dict[str, list[str]] = {}
    for family, keys in buckets.items():
        if family == "out_identity":
            continue
        found = _bucket_hits(full_norm, keys)
        if found:
            hits[family] = found

    direct_hits = hits.get("tech_business_direct", [])
    other_families = [f for f in hits if f not in TECH_KEYS]

    # needs-tech business terms only count when a real family also signals
    # (business administration + AI/software/automation = keep; pure = out)
    effective_families: list[str] = []
    for family in hits:
        if family == "tech_business_needs_tech" and not other_families and not direct_hits:
            continue
        effective_families.append(_FAMILY_ALIASES.get(family, family))
    effective_families = sorted(set(effective_families))

    # family keywords present in the TITLE itself (title = the job's identity)
    title_family_keys = [k for fam, keys in buckets.items()
                         if fam != "out_identity" for k in keys]
    title_family_hits = _bucket_hits(title_norm, title_family_keys)

    # 3. decision. Allowlist first: a manual override always keeps.
    # (Allowlist keys may be job_url substrings, so scan the URL too.)
    allowlist = load_allowlist()
    decision, reason = "keep", ""
    score_detail: dict | None = None
    allow_norm = (full_norm + " " + str(job.get("job_url") or "")).lower()
    if any(k in allow_norm for k in allowlist):
        reason = "allowlist match"
    elif out_hits_title and not title_family_hits:
        # JD boilerplate ('agile startup', 'feedback culture') must not save a
        # job whose TITLE identifies another domain. This beats the scored
        # fallback: the title already says the job is outside the universe.
        decision, reason = "eliminate", f"title is other-domain: {out_hits_title}"
    elif not effective_families:
        if scored:
            sf = _load_scored_filter()
            verdict = sf.classify_scored(job)
            score_detail = verdict["score"]
            decision, reason = verdict["decision"], verdict["reason"]
        else:
            decision, reason = ("eliminate",
                                "no software/AI/automation/hardware/finance/tech-business signal")
    elif (out_hits_title or len(out_hits_full) >= 2) and not title_family_hits and len(effective_families) <= 1:
        decision, reason = ("eliminate",
                            f"other-domain dominates (title_hits: {out_hits_title}; out-hits: {len(out_hits_full)}, "
                            f"family hits: {len(effective_families)})")

    if decision == "keep" and not reason:
        reason = "family signal: " + ", ".join(effective_families)

    return {
        "title": title,
        "company": str(job.get("company") or ""),
        "job_url": str(job.get("job_url") or ""),
        "decision": decision,
        "reason": reason,
        "families_matched": effective_families,
        "family_hits": hits,
        "out_identity_hits_title": out_hits_title,
        "out_identity_hits_full": out_hits_full,
        "score": score_detail,
    }


def run_filter(jobs: list[dict], buckets: dict[str, list[str]] | None = None,
               scored: bool = True) -> tuple[list[dict], list[dict], list[dict]]:
    """Classify all jobs (stage 1 + optional stage 2). Returns (kept, eliminated, records)."""
    buckets = buckets or load_filter_config()
    kept: list[dict] = []
    eliminated: list[dict] = []
    records: list[dict] = []
    for job in jobs:
        record = classify_job(job, buckets, scored=scored)
        records.append(record)
        (kept if record["decision"] == "keep" else eliminated).append(job)
    return kept, eliminated, records


def write_report(records: list[dict], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> int:
    from engine.run_step4 import load_jobs
    config.ensure_utf8_stdout()
    jobs = load_jobs()
    kept, eliminated, records = run_filter(jobs, scored=True)
    out = write_report(records)
    print(f"[V2] domain filter: {len(kept)} kept, {len(eliminated)} eliminated (report -> {out})")
    for rec in records:
        mark = "KEEP " if rec["decision"] == "keep" else "CUT  "
        score = rec.get("score")
        extra = f" [{score['alignment_ratio']:.0%}]" if score else ""
        print(f"  {mark} {rec['title'][:50]:50}{extra} {rec['reason'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
