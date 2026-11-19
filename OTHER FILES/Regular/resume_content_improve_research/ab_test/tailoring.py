"""Tailoring audit: how much content does each engine actually customize per job?

The user's hypothesis: v1 optimizes every section per JD, v2 repeats the same
projects/descriptions/skills across jobs and only varies the objective.

Measured per engine, per section, over all 21 jobs:
- unique_ratio: distinct texts / 21 (1.0 = every job gets its own text)
- mean pairwise similarity (rapidfuzz token_set_ratio) between jobs' texts
- jd_term_density: share of that job's JD vocabulary present in the section text
No engine code is touched; both sides are read from their component stores.
"""
from __future__ import annotations

import json
import re
import sys
from itertools import combinations
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from rapidfuzz import fuzz  # noqa: E402

from resume_content_improve_research.verification.coverage import _norm  # noqa: E402

V1_DIR = PROJECT_ROOT / "program_files" / "output"
V2_DIR = PROJECT_ROOT / "program_files" / "output_v2"
OUT_PATH = Path(__file__).resolve().parent / "tailoring_results.json"

SECTIONS = [
    "career_objective",
    "experience_1_desc",
    "experience_2_desc",
    "project_1_desc",
    "project_2_desc",
    "skills_all",
    "skills_area_labels",
    "exp1_skills",
    "proj1_skills",
]


def load_v1() -> dict[str, dict[str, str]]:
    """v1 components keyed by job_url -> {section: text}."""
    out: dict[str, dict[str, str]] = {}
    stores = [
        ("career_objective.json", "objectives", None),
        ("experience.json", "experiences", None),
        ("projects.json", "projects", None),
        ("skills.json", "skills", None),
    ]
    joined: dict[str, dict] = {}
    for file_name, key, _ in stores:
        payload = json.loads((V1_DIR / file_name).read_text(encoding="utf-8"))
        for rec in payload[key]:
            url = str(rec.get("job_url") or "")
            if url:
                joined.setdefault(url, {})[file_name] = rec
    for url, recs in joined.items():
        try:
            out[url] = {
                "career_objective": str(recs["career_objective.json"].get("career_objective") or ""),
                "experience_1_desc": str((recs["experience.json"].get("experience_1") or {}).get("description") or ""),
                "experience_2_desc": str((recs["experience.json"].get("experience_2") or {}).get("description") or ""),
                "project_1_desc": str((recs["projects.json"].get("project_1") or {}).get("description") or ""),
                "project_2_desc": str((recs["projects.json"].get("project_2") or {}).get("description") or ""),
                "skills_all": json.dumps([
                    *recs["skills.json"]["skills_section"]["languages"],
                    *recs["skills.json"]["skills_section"]["specialized_areas"],
                    *recs["skills.json"]["skills_section"]["skills_area_1"]["skills"],
                    *recs["skills.json"]["skills_section"]["skills_area_2"]["skills"],
                    *recs["experience.json"]["experience_1"]["skills"],
                    *recs["experience.json"]["experience_2"]["skills"],
                    *recs["projects.json"]["project_1"]["skills"],
                    *recs["projects.json"]["project_2"]["skills"],
                ], ensure_ascii=False),
                "skills_area_labels": json.dumps([
                    recs["skills.json"]["skills_section"]["skills_area_1"]["label"],
                    recs["skills.json"]["skills_section"]["skills_area_2"]["label"],
                ], ensure_ascii=False),
                "exp1_skills": json.dumps(recs["experience.json"]["experience_1"]["skills"], ensure_ascii=False),
                "proj1_skills": json.dumps(recs["projects.json"]["project_1"]["skills"], ensure_ascii=False),
            }
        except KeyError:
            continue
    return out


def load_v2() -> dict[str, dict[str, str]]:
    """v2 components keyed by job_url -> {section: text}."""
    payload = json.loads((V2_DIR / "components_v2.json").read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for rec in payload:
        c = rec.get("components") or {}
        exps = c.get("experiences") or []
        projs = c.get("projects") or []
        sk = c.get("skills_section") or {}
        areas = sk.get("areas") or []
        out[str(rec.get("job_url") or "")] = {
            "career_objective": str(c.get("objective") or ""),
            "experience_1_desc": str((exps[0] if len(exps) > 0 else {}).get("description") or ""),
            "experience_2_desc": str((exps[1] if len(exps) > 1 else {}).get("description") or ""),
            "project_1_desc": str((projs[0] if len(projs) > 0 else {}).get("description") or ""),
            "project_2_desc": str((projs[1] if len(projs) > 1 else {}).get("description") or ""),
            "skills_all": json.dumps([
                *(sk.get("languages") or []),
                *(sk.get("specialized_areas") or []),
                *[s for a in areas for s in (a.get("skills") or [])],
                *[s for e in exps for s in (e.get("skills") or [])],
                *[s for p in projs for s in (p.get("skills") or [])],
            ], ensure_ascii=False),
            "skills_area_labels": json.dumps([a.get("label") for a in areas], ensure_ascii=False),
            "exp1_skills": json.dumps((exps[0] if exps else {}).get("skills") or [], ensure_ascii=False),
            "proj1_skills": json.dumps((projs[0] if projs else {}).get("skills") or [], ensure_ascii=False),
        }
    return out


def load_jd_terms() -> dict[str, set[str]]:
    """Each job's JD vocabulary (required+preferred+tools, normalized) from the v2 analyst."""
    payload = json.loads((V2_DIR / "components_v2.json").read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for rec in payload:
        a = rec.get("analysis") or {}
        terms: set[str] = set()
        for key in ("required", "preferred", "tools"):
            for term in a.get(key) or []:
                n = _norm(str(term))
                if n and len(n) >= 3:
                    terms.add(n)
        out[str(rec.get("job_url") or "")] = terms
    return out


def unique_ratio(texts: list[str]) -> float:
    clean = [re.sub(r"\s+", " ", t).strip().lower() for t in texts if t.strip()]
    return len(set(clean)) / len(clean) if clean else 0.0


def pairwise_similarity(texts: list[str]) -> float:
    clean = [re.sub(r"\s+", " ", t).strip().lower() for t in texts if t.strip()]
    if len(clean) < 2:
        return 0.0
    scores = [fuzz.token_set_ratio(a, b) for a, b in combinations(clean, 2)]
    return sum(scores) / len(scores)


def jd_density(texts_by_url: dict[str, str], jd_terms: dict[str, set[str]]) -> float:
    """Share of each job's JD terms present in that job's own section text."""
    ratios = []
    for url, terms in jd_terms.items():
        text = _norm(texts_by_url.get(url) or "")
        if not terms:
            continue
        hits = sum(1 for t in terms if t in text or all(w in text for w in t.split()))
        ratios.append(hits / len(terms))
    return sum(ratios) / len(ratios) if ratios else 0.0


def audit(name: str, data: dict[str, dict[str, str]], jd_terms: dict[str, set[str]]) -> dict:
    urls = [u for u in data if any(data[u].values())]
    print(f"\n=== {name} ({len(urls)} jobs)")
    report: dict = {}
    for section in SECTIONS:
        texts = {u: data[u].get(section, "") for u in urls}
        row = {
            "unique_ratio": round(unique_ratio(list(texts.values())), 3),
            "mean_pairwise_similarity": round(pairwise_similarity(list(texts.values())), 1),
            "jd_term_density": round(jd_density(texts, jd_terms), 3),
        }
        report[section] = row
        print(f"  {section:<20} unique={row['unique_ratio']:.2f}  pairwise_sim={row['mean_pairwise_similarity']:.0f}  jd_terms={row['jd_term_density']:.2f}")
    return report


def main() -> int:
    v1, v2 = load_v1(), load_v2()
    jd = load_jd_terms()
    report = {"v1": audit("v1 (old engine)", v1, jd), "v2": audit("v2 (current engine)", v2, jd)}
    OUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
