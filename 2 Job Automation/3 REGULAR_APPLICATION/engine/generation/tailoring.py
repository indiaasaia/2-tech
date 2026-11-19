"""Per-job tailoring pass: weave JD vocabulary into components WITHOUT fabricating.

Why (measured, ab_test/tailoring.py over 21 jobs): v2's per-job variation
collapsed in the skills rows (95% mean pairwise similarity across jobs, 2%
JD-term density) and project descriptions (54% similarity, 1% density). v1
"tailored" those same sections by inventing content — 32 fabricated tech claims
(Flask x22, HubSpot, Salesforce, Power BI ...). This pass recovers honest
per-job tailoring, deterministic and LLM-free:

  1. PROJECT RE-PICK  2 of the 3 REAL main projects chosen by pool-vs-JD overlap
                      (replaces the LLM's job-blind default pair); a newly picked
                      project gets a verbatim KB-evidence description.
  2. DORMANT SKILLS   KB-licensed skills absent from the current draft are woven
                      into a row whose pool allows them (experience/project rows
                      stay pool-restricted; areas take any ownable skill).
  3. GAP PHRASES      "Working toward hands-on X" style sentences are removed from
                      the objective (policy v3: they advertised missing skills on
                      13/18 resumes of the 10-14 run).
  4. KEYWORDS         with a keyword plan (generation/keywords.py): every job-ad
                      keyword goes into the Skills rows, and keywords that truthfully
                      describe an entry lead that entry's row
                      (generation/keyword_injector.py, generation/evidence_vocab.py).

Removed in policy v3: the "Key working areas: X" / "Implementation focus: X"
description appendix (read as filler) and per-job area labels built from skill
names (produced labels like "Python: Python, HTML, C++").

Every output stays inside the claimable set, adds no digits, and must still pass
the G2/G3 pre-build gates — the caller re-gates and reverts on any finding.
The pass is idempotent: tailoring already-tailored text is a no-op.
"""
from __future__ import annotations

import copy
import re

from engine.generation import kb_loader
from engine.generation.claimable_set import ClaimableSet
from engine.generation.keyword_injector import (
    entry_row,
    is_printed,
    skill_rows,
    strip_gap_phrases,
)
from engine.generation.normalize import _norm

MAX_ROW_ITEMS = 8

_ACRONYMS = {"api", "css", "ui", "llm", "nlp", "crud", "qa", "sql", "html",
             "json", "etl", "kpi", "seo", "crm", "erp", "bi", "ai", "ml", "ci", "cd"}
_SMALL = {"to", "and", "of", "for", "with", "in", "on", "vs"}


def _display_case(text: str) -> str:
    """'api integration' -> 'API Integration'; keeps 'text-to-speech' natural."""
    out: list[str] = []
    for word in str(text).split():
        low = word.lower()
        if low in _ACRONYMS:
            out.append(low.upper())
            continue
        parts = re.split(r"(-)", word)
        fixed = [pl if j > 0 and pl.lower() in _SMALL else (pl[:1].upper() + pl[1:] if pl else pl)
                 for j, pl in enumerate(parts)]
        out.append("".join(fixed))
    return " ".join(out)


def _kb_skill_index(kb: dict) -> dict[str, dict]:
    """normalized skill name -> {name, aliases} (for display + presence checks)."""
    index: dict[str, dict] = {}
    for skill in kb.get("skills", []):
        name = str(skill.get("name") or "")
        if name:
            index[_norm(name)] = {"name": name, "aliases": [str(a) for a in skill.get("aliases", [])]}
    return index


def _short_display(skill: str, kb_index: dict) -> str:
    """Canonical KB display form (FastAPI, NodeJS, C++); pool-only skills get
    display casing (API Integration, Text-to-Speech) — never raw lowercase."""
    entry = kb_index.get(_norm(skill))
    return entry["name"] if entry else _display_case(str(skill))


def _matches(term: str, skill: str) -> bool:
    """Containment match in both directions on normalized forms (len>=3 skill)."""
    t, s = _norm(str(term)), _norm(str(skill))
    return bool(t) and bool(s) and len(s) >= 3 and (t == s or t in s or s in t)


def _skill_present(skill: str, norm_text: str, kb_index: dict) -> bool:
    keys = {_norm(skill)}
    entry = kb_index.get(_norm(skill))
    if entry:
        keys |= {_norm(a) for a in entry["aliases"]}
    return any(k and k in norm_text for k in keys)


def _intent_text(components: dict) -> str:
    """Dict-shaped mirror of run_step4.intent_text_for (same claim surface)."""
    skills = components.get("skills_section") or {}
    parts = [str(components.get("objective") or "")]
    for entry in components.get("experiences") or []:
        parts += [str(entry.get("description") or ""), ", ".join(entry.get("skills") or []),
                  str(entry.get("role") or "")]
    for project in components.get("projects") or []:
        parts += [str(project.get("description") or ""), ", ".join(project.get("skills") or []),
                  str(project.get("title") or "")]
    for area in skills.get("areas") or []:
        parts.append(", ".join(area.get("skills") or []))
    parts += [", ".join(skills.get("languages") or []), ", ".join(skills.get("specialized_areas") or [])]
    return " | ".join(parts)


def _jd_terms(analysis: dict) -> tuple[list[str], list[str]]:
    required = [str(t) for t in (analysis.get("required") or [])]
    preferred = [str(t) for t in (analysis.get("preferred") or [])]
    return required, preferred


def _evidence_description(proj: dict) -> str:
    """Deterministic honest description: first digit-free evidence line, <= 45 words."""
    lines = [str(e).strip() for e in (proj.get("evidence") or []) if str(e).strip()]
    for line in lines:
        if not re.search(r"\d", line):
            return " ".join(line.split()[:45])
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:percent|%)\b", "", lines[0]) if lines else ""
    return re.sub(r"\s{2,}", " ", text).strip(" .,;")


def _pool_row_skills(pid: str, cset: ClaimableSet, analysis: dict, kb_index: dict, cap: int = 6) -> list[str]:
    """Skill row for a newly picked project: pool skills, JD-required first."""
    pool = list(cset.per_project.get(pid, []))
    required, _ = _jd_terms(analysis)

    def key(skill: str) -> tuple:
        for i, term in enumerate(required):
            if _matches(term, skill):
                return (0, i)
        return (1, 0)

    ordered = sorted(pool, key=lambda s: (key(s), s.lower()))
    return [_short_display(s, kb_index) for s in ordered[:cap]]


def _repick_projects(components: dict, analysis: dict, cset: ClaimableSet, kb: dict) -> tuple[list[dict], list[str]]:
    """Pick the 2 main projects whose pools overlap the JD most; keep honest fallbacks."""
    current = components.get("projects") or []
    current_ids = [str(p.get("id") or "") for p in current]
    mains = kb_loader.main_projects(kb)
    main_by_id = {p["id"]: p for p in mains}
    if len(current) != 2 or any(pid not in main_by_id for pid in current_ids):
        return current, []
    required, preferred = _jd_terms(analysis)
    listed = required + preferred + [str(t) for t in (analysis.get("tools") or [])]

    def score(pid: str) -> int:
        pool = cset.per_project.get(pid, [])
        return sum(1 for t in listed if any(_matches(t, s) for s in pool))

    kb_order = [p["id"] for p in mains]
    ranked = sorted(mains, key=lambda p: (-score(p["id"]), kb_order.index(p["id"])))
    best_ids = [ranked[0]["id"], ranked[1]["id"]]
    if set(best_ids) == set(current_ids):
        return current, []
    if score(best_ids[0]) + score(best_ids[1]) <= score(current_ids[0]) + score(current_ids[1]):
        return current, []
    kb_index = _kb_skill_index(kb)
    out: list[dict] = []
    for pid in best_ids:
        keep = next((p for p in current if str(p.get("id")) == pid), None)
        if keep is not None:
            out.append(keep)
        else:
            kbproj = main_by_id[pid]
            out.append({
                "id": pid,
                "title": str(kbproj.get("title") or ""),
                "description": _evidence_description(kbproj),
                "skills": _pool_row_skills(pid, cset, analysis, kb_index),
            })
    return out, best_ids


def tailor_components(components: dict, analysis: dict, cset: ClaimableSet, kb: dict,
                      plan: dict | None = None) -> tuple[dict, dict]:
    """Apply the full tailoring pass to a components dict; returns (tailored, report).

    `plan` is the job's keyword plan (KeywordPlan.to_dict()). Without it the pass
    re-picks projects, weaves dormant KB skills, reorders, recases and strips gap
    phrases; with it, every job-ad keyword is also placed (step 4).
    """
    from engine.generation.evidence_vocab import find_entry

    kb_index = _kb_skill_index(kb)
    tailored = copy.deepcopy(components)
    tailored["experiences"] = [dict(e) for e in (tailored.get("experiences") or [])]
    tailored["projects"] = [dict(p) for p in (tailored.get("projects") or [])]
    report: dict = {
        "applied": True, "dormant_added": {}, "project_repick": [], "gate_findings": [],
        "rows_reordered": 0, "skills_recased": 0, "gap_phrases_removed": 0,
        "keywords_in_skills": 0, "entry_keywords_added": {},
    }

    experiences = tailored.get("experiences") or []
    skills_section = tailored.get("skills_section") or {}
    areas = skills_section.get("areas") or []
    # With a keyword plan the injector owns the Skills section; the row passes below
    # then touch only experience/project rows (keeps the pass idempotent), and job-ad
    # spellings are never recased ("pandas" must not become "Pandas").
    section_rows = [] if plan else areas
    plan_keys = {_norm(str(k.get("term") or "")) for k in (plan or {}).get("keywords") or []}

    # 1. project re-pick (before dormancy so pools/text align with the final set)
    projects, repicked = _repick_projects({**tailored, "projects": tailored["projects"]}, analysis, cset, kb)
    tailored["projects"] = projects
    report["project_repick"] = repicked

    # 2. dormant licensed skills: ownable, absent from the draft, AND asked for by
    #    the JD (required/preferred). Row caps of 8 bound the volume naturally.
    required, preferred = _jd_terms(analysis)
    present = _norm(_intent_text(tailored))
    # display forms come from the pools themselves (original casing), NOT from
    # ownable() — that set is lowercased for membership tests.
    pool_display: dict[str, str] = {}
    for skills in list(cset.per_experience.values()) + list(cset.per_project.values()):
        for s in skills:
            pool_display.setdefault(_norm(s), s)
    for s in cset.kb_skills:
        pool_display.setdefault(_norm(s), s)
    dormant = [disp for disp in pool_display.values()
               if not _skill_present(disp, present, kb_index)
               and any(_matches(t, disp) for t in required + preferred)]

    def _row_has(items: list[str], skill: str) -> bool:
        return any(_norm(str(x)) == _norm(skill) for x in items)

    added: dict[str, list[str]] = {}
    targets_scan: list[tuple[str, int, dict, set[str] | None]] = []
    for i, entry in enumerate(experiences):
        pool = {_norm(s) for s in cset.per_experience.get(str(entry.get("id") or ""), [])}
        targets_scan.append(("experience", i, entry, pool))
    for i, project in enumerate(projects):
        pool = {_norm(s) for s in cset.per_project.get(str(project.get("id") or ""), [])}
        targets_scan.append(("project", i, project, pool))
    for i, area in enumerate(section_rows):
        targets_scan.append(("skills_area", i, area, None))  # areas take any ownable skill

    for skill in dormant:
        key = _norm(skill)
        for kind, i, entry, pool in targets_scan:
            row = entry.setdefault("skills", [])
            if len(row) >= MAX_ROW_ITEMS or _row_has(row, skill):
                continue
            if pool is not None and key not in pool:
                continue
            row.append(_short_display(skill, kb_index))
            added.setdefault(f"{kind}_{i + 1}", []).append(skill)
            break
    report["dormant_added"] = added

    # 2b. JD-priority reordering: in every row, skills matching JD terms float to
    # the front (required first, then preferred); the rest keep their relative
    # order (stable sort).
    def _rank(skill: str) -> int:
        for i, term in enumerate(required):
            if _matches(term, skill):
                return i
        base = len(required)
        for i, term in enumerate(preferred):
            if _matches(term, skill):
                return base + i
        return base + len(preferred) + 1000

    reordered = 0
    for entry in experiences + projects + section_rows:
        row = entry.get("skills") or []
        if not row:
            continue
        new_row = sorted(row, key=_rank)
        if new_row != row:
            entry["skills"] = new_row
            reordered += 1
    report["rows_reordered"] = reordered

    # 2c. display-casing sweep for KB/pool skills (job-ad spellings are kept as-is)
    recased = 0
    for entry in experiences + projects + section_rows:
        row = entry.get("skills") or []
        fixed = [s if _norm(str(s)) in plan_keys else _short_display(str(s), kb_index) for s in row]
        if fixed != row:
            recased += sum(1 for a, b in zip(row, fixed) if a != b)
            entry["skills"] = fixed
    report["skills_recased"] = recased

    # 3. gap phrases: never tell the recruiter what is missing
    objective, removed = strip_gap_phrases(str(tailored.get("objective") or ""))
    if removed:
        tailored["objective"] = objective
        report["gap_phrases_removed"] = removed

    # 4. keywords: truthful ones lead entry rows; ALL go into the Skills rows
    if plan:
        for kind, entries in (("experience", experiences), ("project", projects)):
            for entry in entries:
                entry_id = str(entry.get("id") or "")
                row, new = entry_row(find_entry(kb, entry_id), entry.get("skills") or [], kb, plan)
                entry["skills"] = row
                if new:
                    report["entry_keywords_added"][f"{kind}:{entry_id}"] = new
        tailored["skills_section"] = skill_rows(plan, kb, skills_section)
        section = tailored["skills_section"]
        printed = [s for row in section.get("rows") or [] for s in row["skills"]]
        report["keywords_in_skills"] = sum(
            1 for k in plan.get("keywords") or []
            if k.get("category") != "education_field" and is_printed(str(k["term"]), printed))

    flat_added = sum(len(v) for v in added.values())
    report["summary"] = (
        f"dormant_added={flat_added} reorder={report['rows_reordered']} "
        f"recased={report['skills_recased']} repicked={bool(repicked)} "
        f"gap_removed={report['gap_phrases_removed']} keywords_in_skills={report['keywords_in_skills']} "
        f"entry_keywords={sum(len(v) for v in report['entry_keywords_added'].values())}"
    )
    return tailored, report


def tailor_generated(gc, analysis_dict: dict, cset: ClaimableSet, kb: dict, plan: dict | None = None) -> dict:
    """Adapter for GeneratedComponents: tailor in place, return the report."""
    components = {
        "objective": gc.objective,
        "skills_section": gc.skills_section,
        "experiences": gc.experiences,
        "projects": gc.projects,
    }
    tailored, report = tailor_components(components, analysis_dict, cset, kb, plan=plan)
    gc.objective = tailored["objective"]
    gc.skills_section = tailored["skills_section"]
    gc.experiences = tailored["experiences"]
    gc.projects = tailored["projects"]
    return report
