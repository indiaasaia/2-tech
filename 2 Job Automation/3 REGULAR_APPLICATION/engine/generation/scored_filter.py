"""Scored skill-alignment filter (v2 pre-step, stage 2 of the domain gate).

User instruction: keep the net LOOSE. A job survives stage 1 (domain families)
outright; only a family-less job falls through to this scored stage, and it is
eliminated only when LESS than min_skill_alignment (default 0.60) of its
demanded skills are skills the candidate is licensed to claim (KB skills +
aliases; normalized via normalize.py, so alias/ESCO resolution applies).

The target universe is "anything software / computer / hardware / AI /
automation" plus finance (banking / trading / investment) and business roles
with a tech angle - stage 1 already keeps those. Everything way outside the
domain (mechanical, health, hospitality, pure retail...) has no family signal,
demands unrelated skills, and drops out here BEFORE any LLM call.

Deterministic and free: no LLM, no embeddings. Every decision lands in
output/applications/domain_filter_report.json with the matched/missing demands so the
threshold can be tuned by editing domain_filters.json only.

Config (knowledge_base/domain_filters.json -> "scoring"):
  min_skill_alignment  keep a family-less job at ratio >= this (0.60)
  jd_demand_cap        at most N demanded skills counted per job (25)
  min_denominator      below N distinct demands the job is kept (avoid noise)
  industry_weight      score bonus per industry_keywords hit (0.5)
  industry_cap         maximum bonus (0.5) - tech employer helps, never decides
"""
from __future__ import annotations

import json
import sys
import re
from functools import lru_cache
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from engine import config
from engine.generation import kb_loader, normalize

# Same file domain_filter.py reads - imported lazily from it to avoid a cycle.
_FILTER_CONFIG = config.PACKAGE_ROOT / "knowledge_base" / "domain_filters.json"

# JD columns whose text carries demanded skills (title excluded: titles name the
# ROLE, not demands; kept in the report record for traceability).
JD_TEXT_COLUMNS = ("job_description", "requirements", "your_tasks",
                   "applicant_profile", "what_they_offer")

# "experience with X" / "Kenntnisse in X" style phrases grab the object of the
# sentence; without a boundary marker 'matlab' would match inside 'automatically'.
_DEMAND_BOUNDARY = re.compile(r"[\s;,/()\[\].·•|]|^|$")

# Degree words: when the JD demands one of these fields and the KB lists a
# degree in the same field, that demand counts as matched (once per job).
_DEGREE_FIELDS = {
    "computer": ("computer science", "informatik", "computer engineering",
                 "computing", "angewandte informatik"),
    "artificial intelligence": ("artificial intelligence", "ai", "ki",
                                "machine learning", "maschinelles lernen",
                                "data science"),
    "software": ("software engineering", "softwareentwicklung"),
    "information systems": ("information systems", "wirtschaftsinformatik"),
    "business": ("business administration", "betriebswirtschaft", "bwl",
                 "business", "management"),
    "finance": ("finance", "finanzen", "financial", "banking",
                "investment", "economics", "volkswirtschaft"),
    "engineering": ("engineering", "ingenieurwesen", "ingenieur"),
}

_CANDIDATE_DEGREE_FIELDS = {
    "computer",        # BE Computer Engineering
    "artificial intelligence",  # MS Artificial Intelligence
}


@lru_cache(maxsize=1)
def load_scoring_config(path_str: str | None = None) -> dict:
    """{min_skill_alignment, jd_demand_cap, min_denominator, industry_weight,
    industry_cap, demand_tools, industry_keywords} from domain_filters.json."""
    path = Path(path_str) if path_str else _FILTER_CONFIG
    data = json.loads(path.read_text(encoding="utf-8"))
    scoring = data.get("scoring") or {}
    cfg = {
        "min_skill_alignment": float(scoring.get("min_skill_alignment", 0.60)),
        "jd_demand_cap": int(scoring.get("jd_demand_cap", 25)),
        "min_denominator": int(scoring.get("min_denominator", 4)),
        "industry_weight": float(scoring.get("industry_weight", 0.5)),
        "industry_cap": float(scoring.get("industry_cap", 0.5)),
        "demand_tools": [str(k).lower() for k in (data.get("demand_tools") or {}).get("any", []) if str(k).strip()],
        "industry_keywords": [str(k).lower() for k in (data.get("industry_keywords") or {}).get("any", []) if str(k).strip()],
    }
    return cfg


def _normalize_skill_key(term: str) -> str:
    return normalize.normalize_skill(term)


@lru_cache(maxsize=1)
def candidate_skill_keys() -> frozenset[str]:
    """Lowercased normalized KB-licensed skills (+ aliases resolved) as a set."""
    kb = kb_loader.load_kb()
    return frozenset(k.lower() for k in kb_loader.global_skill_names(kb))


@lru_cache(maxsize=1)
def demand_tool_keys() -> frozenset[str]:
    """Lowercased demand_tools from the config (unclaimable demanded skills)."""
    return frozenset(load_scoring_config()["demand_tools"])


@lru_cache(maxsize=1)
def industry_keywords() -> tuple[str, ...]:
    return tuple(load_scoring_config()["industry_keywords"])


def _boundary_count(haystack: str, needle: str) -> int:
    """Occurrences of needle with a non-word char (or string edge) around it."""
    if not needle:
        return 0
    start, count = 0, 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            break
        left = haystack[idx - 1] if idx > 0 else " "
        right_idx = idx + len(needle)
        right = haystack[right_idx] if right_idx < len(haystack) else " "
        # BOTH sides must be non-word chars ('python3' must not match 'python')
        if not left.isalnum() and not right.isalnum():
            count += 1
        start = idx + len(needle)
    return count


def discover_demands(jd_text: str, kb_keys: frozenset[str],
                     demand_keys: frozenset[str], cap: int) -> dict:
    """Demanded skills found in the JD text: claimable (KB) vs demanded-but-unclaimable.

    KB skills/aliases are matched with word boundaries; demand_tools with hard
    boundaries. The two lists are kept disjoint (a KB skill never counts as a
    demand_tool). Long demand_tools also count inside German compounds
    ("Linuxkenntnisse", "MATLAB-Erfahrung") via explicit suffixes. Returns
    {claimable: [...], unclaimable: [...], truncated: bool}.
    """
    hay = " " + " ".join(jd_text.lower().split()) + " "
    claimable: list[str] = []
    unclaimable: list[str] = []
    truncated = False

    for key in sorted(kb_keys, key=len, reverse=True):
        if _boundary_count(hay, key):
            claimable.append(key)

    compound_suffixes = ("kenntnisse", "erfahrung", "experience", "skills")
    for key in sorted(demand_keys, key=len, reverse=True):
        if _boundary_count(hay, key):
            unclaimable.append(key)
        elif len(key) >= 6:
            # German/English compounds glue the tool to a suffix word
            if any((key + suffix) in hay.replace(" ", "") or
                   (key + "-" + suffix) in hay for suffix in compound_suffixes):
                unclaimable.append(key)

    total = len(claimable) + len(unclaimable)
    if total > cap:
        truncated = True
        keep_claim = claimable[: max(1, cap // 2)]
        keep_unclaim = unclaimable[: cap - len(keep_claim)]
        claimable, unclaimable = keep_claim, keep_unclaim

    return {"claimable": claimable, "unclaimable": unclaimable, "truncated": truncated}


def _degree_signal(jd_text: str) -> tuple[list[str], list[str]]:
    """(matched_fields, demanded_fields) for degree-field requirements."""
    hay = " " + " ".join(jd_text.lower().split()) + " "
    demanded: list[str] = []
    for field, names in _DEGREE_FIELDS.items():
        if any(_boundary_count(hay, name) for name in names):
            demanded.append(field)
    matched = [f for f in demanded if f in _CANDIDATE_DEGREE_FIELDS]
    return matched, demanded


def _industry_bonus(jd_text: str, company: str = "") -> tuple[float, list[str]]:
    """Bounded bonus for tech-adjacent employer/sector signals (JD + company)."""
    hay = " " + " ".join((jd_text + " " + company).lower().split()) + " "
    hits: list[str] = []
    for kw in industry_keywords():
        if _boundary_count(hay, kw):
            hits.append(kw)
    cfg = load_scoring_config()
    weight, cap = cfg["industry_weight"], cfg["industry_cap"]
    bonus = min(len(hits) * weight, cap) if weight > 0 else 0.0
    return bonus, hits


def score_job(job: dict, kb_keys: frozenset[str] | None = None,
              demand_keys: frozenset[str] | None = None,
              scoring_cfg: dict | None = None) -> dict:
    """Score one job's skill alignment against the candidate KB.

    Returns {alignment_ratio, claimable, unclaimable, demanded_count,
    degree_fields, degree_matched, industry_hits, industry_bonus}.
    """
    cfg = scoring_cfg or load_scoring_config()
    kb_keys = kb_keys if kb_keys is not None else candidate_skill_keys()
    demand_keys = demand_keys if demand_keys is not None else demand_tool_keys()

    jd_text = " ".join(str(job.get(col) or "") for col in JD_TEXT_COLUMNS)
    company = str(job.get("company") or "")
    demands = discover_demands(jd_text, kb_keys, demand_keys, cfg["jd_demand_cap"])

    degree_matched, degree_demanded = _degree_signal(jd_text)
    bonus, industry_hits = _industry_bonus(jd_text, company)

    matched = len(demands["claimable"])
    if degree_demanded and degree_matched:
        matched += 1  # a degree field the candidate actually has counts once
    denominator = len(demands["claimable"]) + len(demands["unclaimable"]) + (
        1 if degree_demanded else 0)

    if denominator == 0:
        ratio = 0.0  # no detectable tech demands: zero alignment
    elif denominator < cfg["min_denominator"]:
        # too few demands for a meaningful ratio: any claimable demand keeps the
        # job; NONE means even the visible signals point away from us -> out
        ratio = 1.0 if matched > 0 else 0.0
    else:
        ratio = min(1.0, matched / denominator + bonus)

    return {
        "alignment_ratio": round(ratio, 4),
        "claimable": demands["claimable"],
        "unclaimable": demands["unclaimable"],
        "demanded_truncated": demands["truncated"],
        "demanded_count": denominator,
        "degree_fields": degree_demanded,
        "degree_matched": degree_matched,
        "industry_hits": industry_hits,
        "industry_bonus": round(bonus, 2),
    }


def classify_scored(job: dict, scoring_cfg: dict | None = None) -> dict:
    """Scored-stage decision record for one family-less job.

    Kept at alignment >= min_skill_alignment (default 0.60); below that the job
    is eliminated ("way outside our domain: skill alignment below threshold").
    """
    cfg = scoring_cfg or load_scoring_config()
    score = score_job(job, scoring_cfg=cfg)
    threshold = cfg["min_skill_alignment"]
    keep = score["alignment_ratio"] >= threshold
    return {
        "decision": "keep" if keep else "eliminate",
        "reason": (f"skill alignment {score['alignment_ratio']:.0%} >= {threshold:.0%}"
                   if keep else
                   f"skill alignment {score['alignment_ratio']:.0%} < {threshold:.0%} "
                   f"(way outside domain)"),
        "score": score,
    }
