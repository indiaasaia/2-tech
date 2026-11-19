"""Constrained generator (FINAL_MODEL 3.1 step 5): 1-3 calls, strict JSON out.

Call groups (was 6 prompts in v1; V2 A6 / V7 budget):
  1. career objective + skills section
  2. both experience stints (descriptions + skill rows)
  3. both main projects (only the 3 REAL ones are offered, pick 2 per job)

Hard rules baked into every prompt: mention only claimable tools, real projects
only, no invented numbers, mirror-JD framing never claims ownership. V7 proved
prompting alone still leaks (~4x reduction only) — gates.py is the enforcement,
this module is the constraint.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from resume_content_improve_research.generation.claimable_set import ClaimableSet
from resume_content_improve_research.generation.llm import call_llm, extract_json
from resume_content_improve_research.generation.normalize import normalize_skill

MAX_OBJECTIVE_WORDS = 60
MAX_DESCRIPTION_WORDS = 45


@dataclass
class GeneratedComponents:
    objective: str
    skills_section: dict           # languages / specialized_areas / areas[2]
    experiences: list[dict]        # [{role, description, skills}]
    projects: list[dict]           # [{title, description, skills}]
    raw: dict

    def to_fill_values(self) -> dict[str, str]:
        """Flatten into token-keyed escaped-string values (fill.py contract:
        keys are the FULL @@NAME@@ token strings from config.TOKENS)."""
        from resume_content_improve_research import config
        from resume_content_improve_research.templates.fill import escape_latex, join_items

        tokens = config.TOKENS
        skills = self.skills_section
        areas = skills["areas"]
        exp1, exp2 = self.experiences[0], self.experiences[1]
        proj1, proj2 = self.projects[0], self.projects[1]
        return {
            tokens["career_objective"]: escape_latex(self.objective),
            tokens["role_1"]: escape_latex(exp1["role"]),
            tokens["company_1"]: escape_latex(exp1["company"]),
            tokens["location_1"]: escape_latex(exp1["location"]),
            tokens["dates_1"]: escape_latex(exp1["dates"]),
            tokens["description_1"]: escape_latex(exp1["description"]),
            tokens["skills_1"]: join_items(exp1["skills"]),
            tokens["role_2"]: escape_latex(exp2["role"]),
            tokens["company_2"]: escape_latex(exp2["company"]),
            tokens["location_2"]: escape_latex(exp2["location"]),
            tokens["dates_2"]: escape_latex(exp2["dates"]),
            tokens["description_2"]: escape_latex(exp2["description"]),
            tokens["skills_2"]: join_items(exp2["skills"]),
            tokens["project_1"]: escape_latex(proj1["title"]),
            tokens["project_desc_1"]: escape_latex(proj1["description"]),
            tokens["project_skills_1"]: join_items(proj1["skills"]),
            tokens["project_2"]: escape_latex(proj2["title"]),
            tokens["project_desc_2"]: escape_latex(proj2["description"]),
            tokens["project_skills_2"]: join_items(proj2["skills"]),
            tokens["languages"]: join_items(skills["languages"]),
            tokens["specialized_areas"]: join_items(skills["specialized_areas"]),
            tokens["skills_area_1_label"]: escape_latex(areas[0]["label"]),
            tokens["skills_area_1"]: join_items(areas[0]["skills"]),
            tokens["skills_area_2_label"]: escape_latex(areas[1]["label"]),
            tokens["skills_area_2"]: join_items(areas[1]["skills"]),
        }


def _rules_block(cset: ClaimableSet) -> str:
    tools = ", ".join(cset.jd_tools) if cset.jd_tools else "(none)"
    kb = ", ".join(cset.kb_skills)
    return (
        f"### THE ONLY TECHNOLOGIES/SKILLS YOU MAY MENTION ANYWHERE\n"
        f"OWNABLE (candidate's real skills, may be claimed as own): {kb}\n"
        f"MIRRORABLE (from the target job; may ONLY be mentioned as goals/targets/familiarity in the "
        f"objective, NEVER claimed as the candidate's own skill or project component): {tools}\n"
    )


def _objective_skills_prompt(cset: ClaimableSet, title_core: str) -> str:
    langs = ", ".join(
        f"{l['language']}" + (f" ({l.get('level')})" if l.get("level") else "")
        for l in cset.languages_required
    ) or "none stated"
    return f"""You write ATS resume content for ONE specific job. Use ONLY the licensed material below.
{_rules_block(cset)}
### JOB
Target role: {title_core}
Required keywords (weave the OWNABLE ones in naturally): {", ".join(cset.required) or "(none)"}
Preferred keywords: {", ".join(cset.preferred) or "(none)"}
Job language requirements: {langs}
Candidate languages: English C2 (native), German A2 (conversational), Hindi C2, Gujarati C2

### HARD RULES
1. NEVER claim a MIRRORABLE tool as the candidate's own skill. Allowed framing: "working toward",
   "familiar with", "targeting experience in" — ONLY if that tool appears in the required/preferred lists.
2. NEVER invent tools, employers, projects, metrics, percentages or numbers of any kind.
   NO percentages, shares, scores or counts anywhere (no "70%", no "70 percent", no "increased by X").
   Dates of the education entries (2018-2026 range) are the only numbers permitted, and only in the
   fixed education section, never in the objective, experience, project or skill text you generate.
3. Skill rows contain OWNABLE skills only.
4. Output ONLY valid JSON exactly:
{{"career_objective": "2-3 sentences, max {MAX_OBJECTIVE_WORDS} words, tailored to the target role; mention at most two MIRRORABLE tools as targets if they fit naturally",
 "skills_section": {{"languages": ["4-5 programming languages, OWNABLE only"],
  "specialized_areas": ["4-5 specialization areas, OWNABLE only"],
  "areas": [{{"label": "2-4 words", "skills": ["4-8 OWNABLE skills"]}},
            {{"label": "2-4 words", "skills": ["4-8 OWNABLE skills"]}}]}}}}"""


def _experience_prompt(cset: ClaimableSet, kb: dict, title_core: str) -> str:
    exp_lines = []
    for exp in kb["experience"]:
        evidence = " | ".join(exp["evidence"])
        allowed = ", ".join(cset.per_experience.get(exp["id"], exp.get("skills_allowed", [])))
        exp_lines.append(
            f"- id={exp['id']}: {exp.get('titles_allowed', [''])[0]} at {exp['company']}, "
            f"{exp['location']}, {exp['start']} to {exp['end']}\n"
            f"  Evidence (the ONLY facts you may use): {evidence}\n"
            f"  Skill row pool (use ONLY these): {allowed}"
        )
    return f"""You write the EXPERIENCE section of a resume for ONE job. Use ONLY the licensed material.
{_rules_block(cset)}
Target role: {title_core}
Experience entries (exactly these two, in this order):
{chr(10).join(exp_lines)}

### HARD RULES
1. Use the company names, locations, titles and dates EXACTLY as given above. The title must be one of titles_allowed.
2. Descriptions: 1-2 sentences, max {MAX_DESCRIPTION_WORDS} words each, built ONLY from the evidence lines,
   re-emphasized toward the target role. Never claim MIRRORABLE tools as used here.
3. Skill rows: 5-8 items, chosen ONLY from the skill row pool of that entry.
4. Dates format: "Dec 2023 - Jan 2025" (four-digit years, never apostrophe years).
5. Output ONLY valid JSON exactly:
{{"experiences": [{{"id": "soham", "role": "...", "company": "...", "location": "...", "dates": "Dec 2023 - Jan 2025", "description": "...", "skills": ["..."]}},
                 {{"id": "pantechelearning", "role": "...", "company": "...", "location": "...", "dates": "Dec 2021 - Feb 2022", "description": "...", "skills": ["..."]}}]}}"""


def _projects_prompt(cset: ClaimableSet, kb: dict, title_core: str) -> str:
    mains = kb_loader_mains(kb)
    lines = []
    for proj in mains:
        evidence = " | ".join(proj["evidence"])
        allowed = ", ".join(cset.per_project.get(proj["id"], proj.get("skills_allowed", [])))
        url = proj.get("url", "")
        lines.append(
            f"- id={proj['id']}: {proj['title']}{' (' + url + ')' if url else ''}\n"
            f"  Evidence (the ONLY facts you may use): {evidence}\n"
            f"  Skill pool (use ONLY these): {allowed}"
        )
    return f"""You write the MAIN PROJECTS section of a resume for ONE job. Use ONLY the licensed material.
{_rules_block(cset)}
Target role: {title_core}
REAL projects (choose the 2 that best match the target role; these are the only projects in existence):
{chr(10).join(lines)}

### HARD RULES
1. NEVER invent a project, tool, metric or number. The ONLY numbers you may print are the exact
   numeric tokens that appear verbatim inside the evidence lines above (e.g. a GitHub star count).
   NO percentages, shares or scores in any form, even if a number appears in the evidence with one.
2. Descriptions: 1-2 sentences, max {MAX_DESCRIPTION_WORDS} words, re-emphasized toward the target role.
3. Skill rows: 4-8 items chosen ONLY from that project's skill pool.
4. Output ONLY valid JSON exactly:
{{"projects": [{{"id": "<chosen id>", "title": "...", "description": "...", "skills": ["..."]}},
              {{"id": "<chosen id>", "title": "...", "description": "...", "skills": ["..."]}}]}}"""


def kb_loader_mains(kb: dict) -> list[dict]:
    from resume_content_improve_research.generation import kb_loader

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
) -> tuple[GeneratedComponents, dict]:
    """Run the 1-3 constrained generation calls; returns (components, meta)."""
    meta = {"calls": 0, "repair_retries": 0, "errors": []}

    profile = kb.get("profile", {})
    contact = profile.get("contact", {})
    full_name = profile.get("name", "")

    # ---- call 1: objective + skills
    raw = call_llm(_objective_skills_prompt(cset, title_core), token, temperature)
    meta["calls"] += 1
    data = _parse_or_fail(raw, ("career_objective", "skills_section"))

    # ---- call 2: experiences (with 1 repair retry on schema miss)
    try:
        raw = call_llm(_experience_prompt(cset, kb, title_core), token, temperature)
        meta["calls"] += 1
        exp_data = _parse_or_fail(raw, ("experiences",))
    except ValueError:
        meta["repair_retries"] += 1
        meta["calls"] += 1
        raw = call_llm(
            _experience_prompt(cset, kb, title_core)
            + "\n\nYour previous reply was invalid. Return ONLY the JSON object with key 'experiences'.",
            token, 0.0)
        exp_data = _parse_or_fail(raw, ("experiences",))

    # ---- call 3: projects (with 1 repair retry on schema miss)
    try:
        raw = call_llm(_projects_prompt(cset, kb, title_core), token, temperature)
        meta["calls"] += 1
        proj_data = _parse_or_fail(raw, ("projects",))
    except ValueError:
        meta["repair_retries"] += 1
        meta["calls"] += 1
        raw = call_llm(
            _projects_prompt(cset, kb, title_core)
            + "\n\nYour previous reply was invalid. Return ONLY the JSON object with key 'projects'.",
            token, 0.0)
        proj_data = _parse_or_fail(raw, ("projects",))

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


def _normalize_experiences(entries: list[dict], kb: dict) -> list[dict]:
    kb_by_id = {exp["id"]: exp for exp in kb["experience"]}
    out: list[dict] = []
    for entry in entries:
        exp = kb_by_id.get(str(entry.get("id", "")), {})
        role = str(entry.get("role") or (exp.get("titles_allowed") or ["Software Engineer"])[0])
        out.append({
            "id": entry.get("id", ""),
            "role": role,
            "company": str(entry.get("company") or exp.get("company", "")),
            "location": str(entry.get("location") or exp.get("location", "")),
            "dates": str(entry.get("dates") or _kb_dates(exp)),
            "description": str(entry.get("description") or ""),
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
        out.append({
            "id": entry.get("id", ""),
            "title": str(entry.get("title") or proj.get("title", "")),
            "description": str(entry.get("description") or ""),
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
