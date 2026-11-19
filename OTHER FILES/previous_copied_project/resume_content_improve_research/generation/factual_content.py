"""KB-grounded resume text assembly for the final build stage.

The LLM is useful for discovering a role's terminology, but its generated prose
can still invent adjacent experience even when a token gate passes. This module
keeps the role-specific skill/project selection from the component store while
rebuilding biographical claims and descriptions exclusively from the approved
candidate KB.
"""
from __future__ import annotations

import re
from copy import deepcopy

from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.claimable_set import build_claimable_set
from resume_content_improve_research.generation.normalize import normalize_skill
from resume_content_improve_research.generation.tailoring import _display_case


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9+#]+", " ", str(value or "").casefold()).strip()


def _display_skill(value: str, canonical: dict[str, str]) -> str:
    normalized = normalize_skill(str(value)).casefold()
    return canonical.get(_key(normalized), _display_case(normalized))


def _matched_skills(analysis: dict, skill_names: list[str]) -> list[str]:
    """Return candidate-owned skills that exactly resolve from this JD's terms."""
    vocabulary = set(skill_names)
    by_key = {_key(name): name for name in skill_names}
    selected: list[str] = []
    for term in (analysis.get("required") or []) + (analysis.get("preferred") or []):
        resolved = normalize_skill(str(term), vocabulary=vocabulary)
        name = by_key.get(_key(resolved))
        if name and name not in selected:
            selected.append(name)
        if len(selected) == 4:
            break
    return selected


def _date_label(value: str) -> str:
    year, month = str(value).split("-")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return year if month == "00" else f"{months[int(month) - 1]} {year}"


def _experience_description(exp_id: str) -> str:
    """Short paraphrase containing only the selected KB experience's evidence."""
    if exp_id == "soham":
        return (
            "Developed multiple functions and quant models achieving high level of profitability in "
            "financial decision-making. Designed and built backend components and real-time algorithms "
            "to support trading operations, leveraging quant and AI algorithms. Focused on black-box "
            "and gray-box models to surpass overall benchmark marks."
        )
    if exp_id == "pantechelearning":
        return (
            "Implemented machine learning models for projects including text-to-speech applications "
            "and high functional visual-activity analysis. Worked on data extraction and preprocessing "
            "tasks, ensuring accuracy for model training and evaluation."
        )
    return ""


def _project_description(project_id: str) -> str:
    """Evidence-backed project summary; omits the HFT metric to avoid exaggeration."""
    if project_id == "hft":
        return (
            "Developed an end-to-end system including real-time data scraping, analysis, and filtering. "
            "Combined quantitative and AI models to take actions in real-time markets and manage "
            "unexpected actions."
        )
    if project_id == "resume_gen":
        return (
            "Developed a complete system using structured datasets for AI, backend, and data job "
            "categories. The datasets describe how project, skills, and role-highlight sections should "
            "be framed for each role type using an open-source LLM."
        )
    if project_id == "vehicle_sharing":
        return (
            "Developed a full-stack application for vehicle sharing in a specific city. Used the "
            "Dijkstra algorithm for route selection and managed real-time CRUD actions with simple UI features."
        )
    return ""


def _latex_item(text: str) -> str:
    from resume_content_improve_research.templates.fill import escape_latex

    return r"\item " + escape_latex(text)


def static_section_values(kb: dict, languages_per_line: int = 4) -> dict[str, str]:
    """Build escaped TeX fragments for all static sections from the approved KB."""
    from resume_content_improve_research import config
    from resume_content_improve_research.templates.fill import escape_latex

    values = {
        config.TOKENS["education"]: "",
        config.TOKENS["research"]: "",
        config.TOKENS["achievements"]: "",
        config.TOKENS["certifications"]: "",
        config.TOKENS["additional_projects"]: "",
        config.TOKENS["spoken_languages"]: "",
    }
    education_lines = [
        r"\textbf{" + escape_latex("MSc Artificial Intelligence") + "} — "
        + escape_latex("Brandenburgische Technische Universität Cottbus-Senftenberg, Germany")
        + r" \hfill " + escape_latex("April 2025 — Present"),
        r"\textbf{" + escape_latex("BE Computer Engineering") + "} — "
        + escape_latex("Gujarat Technological University, Gujarat, India")
        + r" \hfill " + escape_latex("June 2020 — May 2024"),
    ]
    values[config.TOKENS["education"]] = "\n".join(education_lines)

    research_items: list[str] = []
    for item in kb_loader.research(kb):
        title = escape_latex(str(item.get("title") or ""))
        evidence = " ".join(str(text) for text in item.get("evidence", []))
        research_items.append(r"\item \textbf{" + title + "}. " + escape_latex(evidence))
    values[config.TOKENS["research"]] = "\n".join(research_items)

    values[config.TOKENS["achievements"]] = "\n".join(
        _latex_item(f"{item.get('name', '')} — {item.get('result', '')}")
        for item in kb_loader.achievements(kb)
    )
    values[config.TOKENS["certifications"]] = "\n".join(
        _latex_item(str(item.get("name") or "")) for item in kb_loader.certifications(kb)
    )

    additional_items: list[str] = []
    for project in kb_loader.projects(kb, tier="additional"):
        title = str(project.get("title") or "")
        evidence = "; ".join(str(text) for text in project.get("evidence", []))
        url = str(project.get("url") or "")
        if url:
            line = r"\item \textbf{" + escape_latex(title) + "} — " + escape_latex(evidence)
            line += r" \href{" + url + "}{Project link}"
        else:
            line = r"\item \textbf{" + escape_latex(title) + "} — " + escape_latex(evidence)
        additional_items.append(line)
    if additional_items:
        additional_items[-1] = additional_items[-1].replace(r"\item ", r"\item ", 1)
    values[config.TOKENS["additional_projects"]] = "\n".join(additional_items)

    spoken = kb_loader.languages_spoken(kb)
    language_lines = [
        ", ".join(f"{item.get('lang', '')} ({item.get('level', '')})" for item in spoken[i:i + languages_per_line])
        for i in range(0, len(spoken), languages_per_line)
    ]
    values[config.TOKENS["spoken_languages"]] = "\n".join(_latex_item(line) for line in language_lines)
    return values


def resume_static_sections(kb: dict) -> dict:
    """Return static candidate facts for the editable DOCX mirror."""
    additional_projects: list[dict] = []
    for project in kb_loader.projects(kb, tier="additional"):
        evidence = "; ".join(str(item) for item in project.get("evidence", []))
        additional_projects.append({
            "title": str(project.get("title") or ""),
            "evidence": evidence,
            "url": str(project.get("url") or ""),
        })
    return {
        "research": [
            {"title": str(item.get("title") or ""),
             "evidence": "; ".join(str(e) for e in item.get("evidence", []))}
            for item in kb_loader.research(kb)
        ],
        "achievements": [
            {"name": str(item.get("name") or ""), "result": str(item.get("result") or "")}
            for item in kb_loader.achievements(kb)
        ],
        "certifications": [
            {"name": str(item.get("name") or ""), "url": str(item.get("url") or "")}
            for item in kb_loader.certifications(kb)
        ],
        "additional_projects": additional_projects,
        "languages": [
            {"lang": str(item.get("lang") or ""), "level": str(item.get("level") or "")}
            for item in kb_loader.languages_spoken(kb)
        ],
    }


def ground_components(components: dict, analysis: dict, kb: dict) -> dict:
    """Return build-ready components whose biographical claims come from `kb`.

    The LLM-selected project IDs and owned skill matches are retained when
    valid, preserving job tailoring. Text, identity fields, dates, and employer
    details are reconstructed from candidate-approved entries.
    """
    grounded = deepcopy(components)
    skills = kb_loader.global_skill_names(kb)
    skill_keys = {_key(skill) for skill in skills}
    canonical: dict[str, str] = {}
    for skill in skills:
        canonical[_key(skill)] = skill
    for entry in kb_loader.global_skills(kb):
        name = str(entry.get("name") or "")
        for alias in entry.get("aliases", []):
            canonical[_key(str(alias))] = name

    relevant = _matched_skills(analysis, skills)
    if not relevant:
        relevant = [name for name in ("Python", "Machine Learning", "Data Analytics") if name in skills]
    relevant_text = ", ".join(relevant[:4])
    grounded["objective"] = (
        "MSc candidate in Artificial Intelligence and BE graduate in Computer Engineering with "
        "experience as a Software Engineer and Machine Learning Intern. Seeking to apply "
        f"{relevant_text} in a role aligned with this technical background."
    )

    cset = build_claimable_set(analysis, kb)
    current_experiences = {
        str(entry.get("id") or ""): entry
        for entry in (grounded.get("experiences") or [])
        if isinstance(entry, dict)
    }
    grounded_experiences: list[dict] = []
    for source in kb_loader.experiences(kb):
        exp_id = str(source.get("id") or "")
        current = current_experiences.get(exp_id, {})
        pool = list(cset.per_experience.get(exp_id, []))
        allowed = {_key(skill) for skill in pool}
        selected: list[str] = []
        for value in current.get("skills", []):
            display = _display_skill(value, canonical)
            if _key(normalize_skill(display)) in allowed and display not in selected:
                selected.append(display)
        for value in pool:
            display = _display_skill(value, canonical)
            if _key(normalize_skill(display)) in allowed and display not in selected:
                selected.append(display)
            if len(selected) >= 7:
                break
        end = str(source.get("end") or "")
        grounded_experiences.append({
            "id": exp_id,
            "role": (source.get("titles_allowed") or [source.get("role", "")])[0],
            "company": str(source.get("company") or ""),
            "location": str(source.get("location") or ""),
            "dates": f"{_date_label(str(source.get('start') or ''))} - "
                     f"{'Current' if end == 'present' else _date_label(end)}",
            "description": _experience_description(exp_id),
            "skills": selected[:8],
        })
    grounded["experiences"] = grounded_experiences

    main_projects = {str(project["id"]): project for project in kb_loader.main_projects(kb)}
    current_projects = [p for p in (grounded.get("projects") or []) if isinstance(p, dict)]
    project_ids: list[str] = []
    for project in current_projects:
        project_id = str(project.get("id") or "")
        if project_id in main_projects and project_id not in project_ids:
            project_ids.append(project_id)
        if len(project_ids) == 2:
            break
    for project_id in ("hft", "resume_gen", "vehicle_sharing"):
        if project_id not in project_ids and len(project_ids) < 2:
            project_ids.append(project_id)

    grounded_projects: list[dict] = []
    current_project_by_id = {str(p.get("id") or ""): p for p in current_projects}
    for project_id in project_ids:
        source = main_projects[project_id]
        pool = list(cset.per_project.get(project_id, []))
        allowed = {_key(skill) for skill in pool}
        selected: list[str] = []
        for value in current_project_by_id.get(project_id, {}).get("skills", []):
            display = _display_skill(value, canonical)
            if _key(normalize_skill(display)) in allowed and display not in selected:
                selected.append(display)
        for value in pool:
            display = _display_skill(value, canonical)
            if _key(normalize_skill(display)) in allowed and display not in selected:
                selected.append(display)
            if len(selected) >= 6:
                break
        grounded_projects.append({
            "id": project_id,
            "title": str(source.get("title") or ""),
            "description": _project_description(project_id),
            "skills": selected[:8],
        })
    grounded["projects"] = grounded_projects

    original_skills = grounded.get("skills_section") or {}

    def owned_row(values, fallback, limit=7):
        result: list[str] = []
        for value in values or []:
            display = _display_skill(str(value), canonical)
            if _key(normalize_skill(display)) in skill_keys and display not in result:
                result.append(display)
            if len(result) == limit:
                break
        for value in fallback:
            display = _display_skill(str(value), canonical)
            if _key(normalize_skill(display)) in skill_keys and display not in result:
                result.append(display)
            if len(result) == limit:
                break
        return result

    programming = [s for s in ("Python", "C++", "JavaScript", "SQL") if s in skills]
    specialized = [s for s in (
        "Machine Learning", "Deep Learning", "Natural Language Processing",
        "Computer Vision", "Reinforcement Learning",
    ) if s in skills]
    existing_areas = original_skills.get("areas") or []
    area_1 = existing_areas[0].get("skills", []) if len(existing_areas) > 0 else []
    area_2 = existing_areas[1].get("skills", []) if len(existing_areas) > 1 else []
    backend_fallback = [s for s in ("Python", "Django", "FastAPI", "SQL", "NodeJS", "MongoDB") if s in skills]
    modeling_fallback = [s for s in (
        "Machine Learning", "Deep Learning", "Reinforcement Learning", "Transformers",
        "Quantitative Modeling", "Data Analytics",
    ) if s in skills]
    grounded["skills_section"] = {
        "languages": owned_row(original_skills.get("languages"), programming, limit=5),
        "specialized_areas": owned_row(original_skills.get("specialized_areas"), specialized, limit=5),
        "areas": [
            {"label": "Technical Skills", "skills": owned_row(area_1, backend_fallback)},
            {"label": "AI & Modeling", "skills": owned_row(area_2, modeling_fallback)},
        ],
    }

    profile = kb.get("profile", {})
    contact = profile.get("contact", {})
    grounded["profile"] = {
        "full_name": str(profile.get("name") or ""),
        "contact_line": " | ".join(filter(None, (
            str(contact.get("email") or ""),
            str(contact.get("phone_de") or ""),
            str(contact.get("linkedin") or "").removeprefix("https://www.linkedin.com/in/"),
            str(contact.get("github") or "").removeprefix("https://github.com/"),
        ))),
    }
    return grounded
