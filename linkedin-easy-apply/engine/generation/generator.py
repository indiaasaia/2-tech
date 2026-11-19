"""Constrained generator (FINAL_MODEL 3.1 step 5): 1-3 calls, strict JSON out.

Call groups (was 6 prompts in v1; V2 A6 / V7 budget):
  1. career objective + skills section
  2. both experience stints (descriptions + skill rows)
  3. both main projects (only the 3 REAL ones are offered, pick 2 per job)

Policy v3 (2026-10-17): every job-ad keyword (generation/keywords.py) is a
target. The profile and Skills rows carry them all; experience/project bullets
reword REAL evidence in job-ad vocabulary, using only the keywords that
generation/evidence_vocab.py licenses for that entry. Employers, titles, dates,
degrees and numbers stay KB-only. Prompting alone still leaks (V7) — gates.py
and the per-entry vocabulary check in factual_content.ground_components are the
enforcement, this module is the constraint.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from engine.generation.claimable_set import ClaimableSet
from engine.generation.llm import call_llm, extract_json
from engine.generation.normalize import normalize_skill

MAX_OBJECTIVE_WORDS = 60
MAX_DESCRIPTION_WORDS = 45
MAX_BULLETS_FIRST = 4       # Soham: one bullet per evidence line (4 lines)
MAX_BULLETS_OTHER = 2       # Pantechelearning: 2 evidence lines
MAX_BULLETS_PROJECT = 2
GENERATOR_MAX_TOKENS = 4000   # gpt-oss reasoning tokens count against max_tokens


@dataclass
class GeneratedComponents:
    objective: str
    skills_section: dict           # languages / specialized_areas / areas[2]
    experiences: list[dict]        # [{role, description, skills}]
    projects: list[dict]           # [{title, description, skills}]
    raw: dict


def _plan_terms(plan: dict | None, primary: bool) -> list[str]:
    """Target keywords: primary = from the analyst's required/tools, else the rest.

    Education fields ("Computer Science") are left out: the education section
    renders them, and listing them here invites relabelling the real degree.
    """
    out: list[str] = []
    for keyword in (plan or {}).get("keywords") or []:
        if keyword.get("category") == "education_field":
            continue
        first = (keyword.get("sources") or ["sweep"])[0]
        if (first in ("required", "tools")) == primary:
            out.append(str(keyword["term"]))
    return out


def _rules_block(cset: ClaimableSet, plan: dict | None = None) -> str:
    kb = ", ".join(cset.kb_skills)
    primary = _plan_terms(plan, True) or list(cset.required) + list(cset.jd_tools)
    other = _plan_terms(plan, False) or list(cset.preferred)
    return (
        f"### TARGET KEYWORDS FROM THE JOB AD (job-ad spelling; the resume must contain every one)\n"
        f"Most important (required + tools): {', '.join(primary) or '(none)'}\n"
        f"Also asked for: {', '.join(other) or '(none)'}\n"
        f"### THE CANDIDATE'S OWN SKILLS (knowledge base)\n{kb}\n"
    )


def _entry_keyword_line(entry: dict, kb: dict, plan: dict | None) -> str:
    from engine.generation.evidence_vocab import entry_keywords

    terms = entry_keywords(entry, kb, plan)
    return ", ".join(terms) if terms else "(none - describe the evidence in plain words)"


def _objective_skills_prompt(cset: ClaimableSet, kb: dict, title_core: str, plan: dict | None = None) -> str:
    langs = ", ".join(
        f"{l['language']}" + (f" ({l.get('level')})" if l.get("level") else "")
        for l in cset.languages_required
    ) or "none stated"
    exp_lines = [
        f"Experience: {e.get('titles_allowed', [e.get('role', '')])[0]} at {e['company']} ({e['start']} to {e['end']}): {' '.join(e['evidence'])}"
        for e in kb.get("experience", [])
    ]
    proj_lines = [
        f"Projects: {p['title']}—{' '.join(p['evidence'])}"
        for p in kb_loader_mains(kb)
    ]
    facts_block = "\n".join([
        "Education: MSc Artificial Intelligence at Brandenburgische Technische Universität Cottbus-Senftenberg (April 2025-present); BE Computer Engineering at Gujarat Technological University (June 2020-May 2024).",
    ] + exp_lines + proj_lines + [
        "Research: conducting research on NLP models for sarcasm across Indian regional dialects, focused on linguistic diversity and interpretation.",
    ])
    backing = ""
    if plan:
        from engine.verification.keyword_gate import kb_backing

        split = kb_backing(plan, kb)
        backing = ("Keywords the candidate's facts BACK (may be stated as work done): "
                   + (", ".join(split["kb_backed"]) or "(none)")
                   + "\nKeywords NOT backed (skills list only, never as work done or experience): "
                   + (", ".join(split["prep_terms"]) or "(none)") + "\n")
    return f"""You write ATS resume content for ONE specific job. Use ONLY the licensed material below.
{_rules_block(cset, plan)}
{backing}### JOB
Target role: {title_core}
Job language requirements: {langs}
Candidate languages: English C2 (native), German A2 (conversational), Hindi C2, Gujarati C2

### APPROVED CANDIDATE FACTS — THE ONLY BIOGRAPHY/EVIDENCE SOURCE
{facts_block}

### HARD RULES
1. Candidate facts MUST come only from the approved facts block. Do not infer candidate biography, degree/field, current study level, semester/year, location, availability, employer, project, activity or results from the target job or keyword list. In particular, the degrees are Artificial Intelligence (MSc) and Computer Engineering (BE); never relabel them Computer Science, Electrical Engineering, or another field. Do not say candidate is a current bachelor's student. Do not state a city.
2. "career_objective" is a PROFILE summary: 2-3 sentences, max {MAX_OBJECTIVE_WORDS} words, no "I", and none of
   "seeking", "looking for", "eager", "aspiring", "passionate", "working toward", "hoping to". Open with a noun phrase
   describing the CANDIDATE (e.g. "MSc Artificial Intelligence student and Software Engineer ..."), never with
   the job title itself; state the MSc Artificial Intelligence and the Software Engineer experience, and weave
   in 6-8 of the most important TARGET KEYWORDS in the job ad's exact spelling. A keyword the approved facts
   do not show the candidate using may appear only inside a plain skills list ("skills in X, Y and Z"),
   NEVER as work the candidate delivered, built, integrated, led or implemented.
3. NEVER invent employers, projects, metrics, percentages or numbers of any kind.
   NO percentages, shares, scores or counts anywhere (no "70%", no "70 percent", no "increased by X").
4. Skill rows: TARGET KEYWORDS first (job-ad spelling), then the candidate's own skills.
5. Output ONLY valid JSON exactly:
{{"career_objective": "2-3 sentence profile, max {MAX_OBJECTIVE_WORDS} words",
 "skills_section": {{"languages": ["programming languages: job-ad ones first"],
  "specialized_areas": ["AI / ML / data areas"],
  "areas": [{{"label": "2-4 words", "skills": ["4-10 skills"]}},
            {{"label": "2-4 words", "skills": ["4-10 skills"]}}]}}}}"""


def _experience_prompt(cset: ClaimableSet, kb: dict, title_core: str, plan: dict | None = None) -> str:
    exp_lines = []
    for exp in kb["experience"]:
        evidence = " | ".join(exp["evidence"])
        allowed = ", ".join(cset.per_experience.get(exp["id"], exp.get("skills_allowed", [])))
        exp_lines.append(
            f"- id={exp['id']}: {exp.get('titles_allowed', [''])[0]} at {exp['company']}, "
            f"{exp['location']}, {exp['start']} to {exp['end']}\n"
            f"  Evidence (the ONLY facts you may use): {evidence}\n"
            f"  Job-ad keywords that truthfully describe THIS entry: {_entry_keyword_line(exp, kb, plan)}\n"
            f"  Skill row pool: {allowed}"
        )
    return f"""You write the EXPERIENCE section of a resume for ONE job. Use ONLY the licensed material.
{_rules_block(cset, plan)}
Target role: {title_core}
Experience entries (exactly these two, in this order):
{chr(10).join(exp_lines)}

### HARD RULES
1. Use the company names, locations, titles and dates EXACTLY as given above. The title must be one of titles_allowed.
2. Bullets: {MAX_BULLETS_FIRST} for the first entry, {MAX_BULLETS_OTHER} for the second; each 10-25 words, starting with a
   past-tense action verb. Each bullet restates ONE evidence line, reworded in the job ad's vocabulary: use
   the entry's listed job-ad keywords (exact spelling) wherever that evidence describes that work.
3. A bullet may never add a tool, technology, outcome, domain, team size or metric the evidence does not
   state. Job-ad keywords NOT listed for an entry must not appear in that entry's bullets (they belong to
   the Skills section).
4. Skill rows: 5-10 items: the entry's listed job-ad keywords first, then the skill row pool.
5. Dates format: "Dec 2023 - Jan 2025" (four-digit years, never apostrophe years).
6. Output ONLY valid JSON exactly:
{{"experiences": [{{"id": "soham", "role": "...", "company": "...", "location": "...", "dates": "Dec 2023 - Jan 2025", "bullets": ["...", "..."], "skills": ["..."]}},
                 {{"id": "pantechelearning", "role": "...", "company": "...", "location": "...", "dates": "Dec 2021 - Feb 2022", "bullets": ["...", "..."], "skills": ["..."]}}]}}"""


def _projects_prompt(cset: ClaimableSet, kb: dict, title_core: str, plan: dict | None = None) -> str:
    mains = kb_loader_mains(kb)
    lines = []
    for proj in mains:
        evidence = " | ".join(proj["evidence"])
        allowed = ", ".join(cset.per_project.get(proj["id"], proj.get("skills_allowed", [])))
        url = proj.get("url", "")
        lines.append(
            f"- id={proj['id']}: {proj['title']}{' (' + url + ')' if url else ''}\n"
            f"  Evidence (the ONLY facts you may use): {evidence}\n"
            f"  Job-ad keywords that truthfully describe THIS project: {_entry_keyword_line(proj, kb, plan)}\n"
            f"  Skill pool: {allowed}"
        )
    return f"""You write the MAIN PROJECTS section of a resume for ONE job. Use ONLY the licensed material.
{_rules_block(cset, plan)}
Target role: {title_core}
REAL projects (choose the 2 with the most job-ad keywords listed; these are the only projects in existence):
{chr(10).join(lines)}

### HARD RULES
1. NEVER invent a project, tool, metric or number. The ONLY numbers you may print are the exact
   numeric tokens that appear verbatim inside the evidence lines above (e.g. a GitHub star count).
   NO percentages, shares or scores in any form, even if a number appears in the evidence with one.
2. Bullets: {MAX_BULLETS_PROJECT} per project, each 10-25 words, past-tense action verb first, each restating the selected
   project's evidence in the job ad's vocabulary (the project's listed job-ad keywords, exact spelling).
   Job-ad keywords NOT listed for a project must not appear in its bullets.
3. Skill rows: 4-10 items: the project's listed job-ad keywords first, then its skill pool.
4. Output ONLY valid JSON exactly:
{{"projects": [{{"id": "<chosen id>", "title": "...", "bullets": ["...", "..."], "skills": ["..."]}},
              {{"id": "<chosen id>", "title": "...", "bullets": ["...", "..."], "skills": ["..."]}}]}}"""


def kb_loader_mains(kb: dict) -> list[dict]:
    from engine.generation import kb_loader

    return kb_loader.main_projects(kb)


def _parse_or_fail(raw: str, expect_keys: tuple[str, ...]) -> dict:
    data = extract_json(raw)
    if data is None:
        raise ValueError("generator reply contained no JSON object")
    missing = [key for key in expect_keys if key not in data]
    if missing:
        raise ValueError(f"generator JSON missing keys: {missing}")
    return data


def generate_components(
    cset: ClaimableSet,
    kb: dict,
    title_core: str,
    token: str,
    temperature: float = 0.25,
    plan: dict | None = None,
    findings: list[str] | None = None,
) -> tuple[GeneratedComponents, dict]:
    """Run the 1-3 constrained generation calls; returns (components, meta).

    `plan` = the job's keyword plan (KeywordPlan.to_dict()); None keeps the
    analyst lists as the only keyword source. `findings` = gate findings of the
    previous attempt; they are fed back so the regeneration fixes them.
    """
    meta = {"calls": 0, "repair_retries": 0, "errors": []}
    feedback = ""
    if findings:
        listed = "\n".join(f"- {f}" for f in list(dict.fromkeys(findings))[:12])
        feedback = ("\n\n### PREVIOUS ATTEMPT FAILED THESE CHECKS - FIX THEM\n" + listed +
                    "\nA 'vocabulary' finding means that keyword must NOT appear in that entry's bullets.")

    profile = kb.get("profile", {})
    contact = profile.get("contact", {})
    full_name = profile.get("name", "")

    def json_call(prompt: str, keys: tuple[str, ...]) -> dict:
        """One call + one repair retry (temperature 0) on a missing/invalid JSON reply.

        Measured 2026-10-17 (live run): call 1 had no retry, and one empty reply
        parked the whole job; gpt-oss also spends part of max_tokens on internal
        reasoning, so the larger v3 prompts get a bigger budget.
        """
        prompt += feedback
        raw = call_llm(prompt, token, temperature, max_tokens=GENERATOR_MAX_TOKENS)
        meta["calls"] += 1
        try:
            return _parse_or_fail(raw, keys)
        except ValueError as exc:
            meta["repair_retries"] += 1
            meta["errors"].append(str(exc))
            raw = call_llm(
                prompt + f"\n\nYour previous reply was invalid ({exc}). Return ONLY the JSON object "
                         f"with key(s) {', '.join(repr(k) for k in keys)}. No other text.",
                token, 0.0, max_tokens=GENERATOR_MAX_TOKENS)
            meta["calls"] += 1
            return _parse_or_fail(raw, keys)

    # ---- call 1: profile (objective) + skills; call 2: experiences; call 3: projects
    data = json_call(_objective_skills_prompt(cset, kb, title_core, plan), ("career_objective", "skills_section"))
    exp_data = json_call(_experience_prompt(cset, kb, title_core, plan), ("experiences",))
    proj_data = json_call(_projects_prompt(cset, kb, title_core, plan), ("projects",))

    experiences = _normalize_experiences(exp_data["experiences"], kb)
    projects = _normalize_projects(proj_data["projects"], kb)
    skills_section = _normalize_skills(data["skills_section"], cset)

    components = GeneratedComponents(
        objective=str(data["career_objective"]).strip(),
        skills_section=skills_section,
        experiences=experiences,
        projects=projects,
        raw={"objective_skills": data, "experiences": exp_data, "projects": proj_data},
    )
    components.raw["profile"] = {
        "full_name": full_name,
        "contact_line": f"{contact.get('email', '')} | {contact.get('phone_de', '')} "
                        f"| linkedin.com/in/meetraval | github.com/ravalmeet",
    }
    return components, meta


def _clean_bullets(entry: dict, limit: int) -> list[str]:
    """Bullets from the reply (or a legacy 'description'), each ending with a full stop."""
    raw = entry.get("bullets")
    if not isinstance(raw, list) or not raw:
        raw = [entry.get("description") or ""]
    bullets: list[str] = []
    for bullet in raw:
        text = " ".join(str(bullet or "").split()).strip(" -•*")
        if text:
            bullets.append(text if text[-1] in ".!?" else text + ".")
    return bullets[:limit]


def _normalize_experiences(entries: list[dict], kb: dict) -> list[dict]:
    kb_by_id = {exp["id"]: exp for exp in kb["experience"]}
    out: list[dict] = []
    for index, entry in enumerate(entries):
        exp = kb_by_id.get(str(entry.get("id", "")), {})
        role = str(entry.get("role") or (exp.get("titles_allowed") or ["Software Engineer"])[0])
        bullets = _clean_bullets(entry, MAX_BULLETS_FIRST if index == 0 else MAX_BULLETS_OTHER)
        out.append({
            "id": entry.get("id", ""),
            "role": role,
            "company": str(entry.get("company") or exp.get("company", "")),
            "location": str(entry.get("location") or exp.get("location", "")),
            "dates": str(entry.get("dates") or _kb_dates(exp)),
            "bullets": bullets,
            # joined form for the current one-bullet template (step 3 renders bullets)
            "description": " ".join(bullets),
            "skills": [normalize_skill(s) for s in entry.get("skills", []) if s],
        })
    return out


def _kb_dates(exp: dict) -> str:
    def fmt(ym: str) -> str:
        year, month = ym.split("-")
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        if month == "00":
            return year
        return f"{months[int(month) - 1]} {year}"
    start = fmt(str(exp.get("start", "2023-12")))
    end = str(exp.get("end", ""))
    end_fmt = "Current" if end == "present" else fmt(end)
    return f"{start} - {end_fmt}"


def _normalize_projects(entries: list[dict], kb: dict) -> list[dict]:
    kb_by_id = {p["id"]: p for p in kb.get("projects", [])}
    out: list[dict] = []
    for entry in entries:
        proj = kb_by_id.get(str(entry.get("id", "")), {})
        bullets = _clean_bullets(entry, MAX_BULLETS_PROJECT)
        out.append({
            "id": entry.get("id", ""),
            "title": str(entry.get("title") or proj.get("title", "")),
            "bullets": bullets,
            "description": " ".join(bullets),
            "skills": [normalize_skill(s) for s in entry.get("skills", []) if s],
        })
    return out


def _normalize_skills(section: dict, cset: ClaimableSet) -> dict:
    areas = section.get("areas", [])
    if not isinstance(areas, list) or len(areas) < 2:
        areas = [{"label": "Technical Skills", "skills": []}, {"label": "Core Competencies", "skills": []}]
    return {
        "languages": [normalize_skill(s) for s in section.get("languages", []) if s],
        "specialized_areas": [normalize_skill(s) for s in section.get("specialized_areas", []) if s],
        "areas": [
            {
                "label": str(area.get("label") or "Technical Skills"),
                "skills": [normalize_skill(s) for s in area.get("skills", []) if s],
            }
            for area in areas[:2]
        ],
    }
