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
  3. DESCRIPTIONS     at most 2 evidence-licensed focus sentences appended
                      ("Key working areas: X and Y.") using ONLY that entry's
                      pool skills that match required terms.
  4. AREA LABELS      per-job labels derived from the area's own skills that
                      match required terms (<= 4 words total).
  5. OBJECTIVE        mirrorable JD tools are added as familiarity targets —
                      objective ONLY, never claimed as owned skills, and only if
                      they appear in the required/preferred lists (generator rule
                      1; putting them in rows is v1's fabrication mechanism).

Every output stays inside the claimable set, adds no digits, and must still pass
the G2/G3 pre-build gates — the caller re-gates and reverts on any finding.
The pass is idempotent: tailoring already-tailored text is a no-op.
"""
from __future__ import annotations

import copy
import re

from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.claimable_set import ClaimableSet
from resume_content_improve_research.generation.normalize import _norm

MAX_ROW_ITEMS = 8
MAX_MIRROR_TARGETS = 2      # generator rule: "at most two MIRRORABLE tools as targets"
MAX_DESC_INSERTIONS = 2     # focus sentences per resume
MAX_OBJECTIVE_WORDS_AFTER = 75
MAX_DESC_WORDS_BEFORE_INSERT = 55
MAX_LABEL_WORDS = 4

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


def _mirror_targets(cset: ClaimableSet, analysis: dict, norm_objective: str) -> list[str]:
    """Mirrorable tools listed in required/preferred and not already in the objective.

    Returns the analyst's VERBATIM tool spelling where available (cset.jd_tools is
    normalized/lowercase; the JD's own casing is what the ATS looks for).
    """
    required, preferred = _jd_terms(analysis)
    listed = required + preferred
    display: dict[str, str] = {}
    for raw in analysis.get("tools") or []:
        display.setdefault(_norm(str(raw)), str(raw).strip())
    targets: list[str] = []
    for tool in cset.jd_tools:
        if _norm(tool) in norm_objective:
            continue
        if any(_matches(t, tool) for t in listed):
            targets.append(display.get(_norm(tool), tool))
        if len(targets) >= MAX_MIRROR_TARGETS:
            break
    return targets


def _mirror_sentence(targets: list[str]) -> str:
    """Verbatim JD tool names (the analyst copied them from the posting)."""
    shown = [str(t) for t in targets[:MAX_MIRROR_TARGETS]]
    if len(shown) == 1:
        return f" Working toward hands-on {shown[0]} experience."
    return f" Working toward hands-on {shown[0]} and {shown[1]} experience."


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


def tailor_components(components: dict, analysis: dict, cset: ClaimableSet, kb: dict) -> tuple[dict, dict]:
    """Apply the full tailoring pass to a components dict; returns (tailored, report)."""
    kb_index = _kb_skill_index(kb)
    tailored = copy.deepcopy(components)
    tailored["experiences"] = [dict(e) for e in (tailored.get("experiences") or [])]
    tailored["projects"] = [dict(p) for p in (tailored.get("projects") or [])]
    report: dict = {
        "applied": True, "mirror_targets": [], "dormant_added": {},
        "desc_insertions": [], "area_labels": {}, "project_repick": [], "gate_findings": [],
        "rows_reordered": 0, "skills_recased": 0,
    }

    experiences = tailored.get("experiences") or []
    projects = tailored.get("projects") or []
    skills_section = tailored.get("skills_section") or {}
    areas = skills_section.get("areas") or []

    # 1. project re-pick (before dormancy so pools/text align with the final set)
    projects, repicked = _repick_projects({**tailored, "projects": projects}, analysis, cset, kb)
    tailored["projects"] = projects
    report["project_repick"] = repicked

    # 2. dormant licensed skills: ownable, absent from the draft, AND asked for by
    #    the JD (required/preferred). Weave ALL of them (row caps of 8 bound the
    #    volume naturally) — a per-pass count cap would break the fixed point: each
    #    pass would surface 6 MORE not-yet-present skills. JD-matching-only selection
    #    is also the tailoring point: no stuffing with skills the posting never names.
    required, preferred = _jd_terms(analysis)
    present = _norm(_intent_text(tailored))
    # display forms come from the pools themselves (original casing), NOT from
    # ownable() — that set is lowercased for membership tests and would leak
    # 'crud'/'api integration'-style strings into the resume.
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

    # Placement scans EVERY candidate row once per skill (targets that rejected a
    # skill keep the chance to reject it again on a later pass -> idempotent; the
    # old placed/break ladder spilled overflow into fresh targets per pass).
    added: dict[str, list[str]] = {}
    targets_scan: list[tuple[str, int, dict, set[str] | None]] = []
    for i, entry in enumerate(experiences):
        pool = {_norm(s) for s in cset.per_experience.get(str(entry.get("id") or ""), [])}
        targets_scan.append(("experience", i, entry, pool))
    for i, project in enumerate(projects):
        pool = {_norm(s) for s in cset.per_project.get(str(project.get("id") or ""), [])}
        targets_scan.append(("project", i, project, pool))
    for i, area in enumerate(areas):
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
    # order (stable sort). Real ATS emphasis, still zero fabrication.
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
    for entry in experiences + projects + areas:
        row = entry.get("skills") or []
        if not row:
            continue
        new_row = sorted(row, key=_rank)
        if new_row != row:
            entry["skills"] = new_row
            reordered += 1
    report["rows_reordered"] = reordered

    # 2c. display-casing sweep: rows may carry generator-normalized lowercase
    # ('django') — canonicalize every row skill through the KB/display forms.
    recased = 0
    for entry in experiences + projects + areas:
        row = entry.get("skills") or []
        fixed = [_short_display(str(s), kb_index) for s in row]
        if fixed != row:
            recased += sum(1 for a, b in zip(row, fixed) if a != b)
            entry["skills"] = fixed
    report["skills_recased"] = recased

    # 3. description focus sentences: surface the entry's OWN pool-licensed,
    #    JD-matched skills that its description doesn't yet mention (required
    #    terms first). Marks make the pass idempotent; caps keep it discreet.
    def _focus_candidates(entry, pool: set[str]) -> list[str]:
        desc = str(entry.get("description") or "")
        if len(desc.split()) > MAX_DESC_WORDS_BEFORE_INSERT:
            return []
        norm_desc = _norm(desc)
        row_norms = {_norm(str(s)) for s in (entry.get("skills") or [])}
        cands = [disp for disp in pool_display.values()
                 if _norm(disp) in row_norms and _norm(disp) in pool
                 and not (len(_norm(disp)) >= 4 and _norm(disp) in norm_desc)
                 and any(_matches(t, disp) for t in required + preferred)]
        cands.sort(key=_rank)
        return [_short_display(s, kb_index) for s in cands[:2]]

    def _has_focus_mark(entry) -> bool:
        low = str(entry.get("description") or "").lower()
        return "key working areas" in low or "implementation focus" in low

    # Global deterministic top-k across ALL entries (rank -> kind -> index), where
    # entries already carrying a focus sentence occupy window slots with priority.
    # That is the fixed-point condition: a later pass can never promote fresh
    # entries into a window already claimed by the first run (the naive "next N
    # unmarked" slides the window forever).
    qualifying: list[tuple[tuple, dict, str, list[str]]] = []
    for i, entry in enumerate(experiences):
        pool = {_norm(s) for s in cset.per_experience.get(str(entry.get("id") or ""), [])}
        cands = _focus_candidates(entry, pool)
        marked = _has_focus_mark(entry)
        if cands or marked:
            rank = -1 if marked else _rank(cands[0])
            qualifying.append(((rank, 0, i), entry, "experience", cands))
    for i, project in enumerate(projects):
        if str(project.get("id") or "") in (repicked or []):
            continue  # evidence-derived description; do not stack a second template
        pool = {_norm(s) for s in cset.per_project.get(str(project.get("id") or ""), [])}
        cands = _focus_candidates(project, pool)
        marked = _has_focus_mark(project)
        if cands or marked:
            rank = -1 if marked else _rank(cands[0])
            qualifying.append(((rank, 1, i), project, "project", cands))
    qualifying.sort(key=lambda t: t[0])
    for _, entry, kind, cands in qualifying[:MAX_DESC_INSERTIONS]:
        if _has_focus_mark(entry) or not cands:
            continue  # already tailored (occupies its slot) or nothing new to say
        phrase = " and ".join(cands)
        if kind == "experience":
            entry["description"] = str(entry.get("description") or "").rstrip() + \
                f" Key working areas: {phrase}."
        else:
            entry["description"] = str(entry.get("description") or "").rstrip() + \
                f" Implementation focus: {phrase}."
        report["desc_insertions"].append(f"{kind}:{phrase}")

    # 4. per-job area labels from the area's own skills that match required terms
    for i, area in enumerate(areas):
        fallback = str(area.get("label") or "Technical Skills")
        hits: list[str] = []
        for skill in area.get("skills") or []:
            if skill in hits:
                continue
            if any(_matches(t, skill) for t in required):
                hits.append(skill)
        picked: list[str] = []
        words = 0
        for hit in hits:
            shown = _short_display(hit, kb_index)
            if words + len(shown.split()) <= MAX_LABEL_WORDS:
                picked.append(shown)
                words += len(shown.split())
            if len(picked) == 2:
                break
        label = " & ".join(picked) if picked else fallback
        if label != fallback:
            area["label"] = label
            report["area_labels"][f"area_{i + 1}"] = f"{fallback} -> {label}"

    # 5. mirrorable JD tools as objective familiarity targets (objective ONLY)
    objective = str(tailored.get("objective") or "")
    targets = _mirror_targets(cset, analysis, _norm(objective))
    if targets:
        sentence = _mirror_sentence(targets)
        if len(objective.split()) + len(sentence.split()) <= MAX_OBJECTIVE_WORDS_AFTER:
            tailored["objective"] = objective.rstrip() + sentence
            report["mirror_targets"] = targets

    flat_added = sum(len(v) for v in added.values())
    report["summary"] = (
        f"mirror={len(report['mirror_targets'])} dormant_added={flat_added} "
        f"desc_insertions={len(report['desc_insertions'])} "
        f"labels={len(report['area_labels'])} reorder={report['rows_reordered']} "
        f"recased={report['skills_recased']} repicked={bool(repicked)}"
    )
    return tailored, report


def tailor_generated(gc, analysis_dict: dict, cset: ClaimableSet, kb: dict) -> dict:
    """Adapter for GeneratedComponents: tailor in place, return the report."""
    components = {
        "objective": gc.objective,
        "skills_section": gc.skills_section,
        "experiences": gc.experiences,
        "projects": gc.projects,
    }
    tailored, report = tailor_components(components, analysis_dict, cset, kb)
    gc.objective = tailored["objective"]
    gc.skills_section = tailored["skills_section"]
    gc.experiences = tailored["experiences"]
    gc.projects = tailored["projects"]
    return report
