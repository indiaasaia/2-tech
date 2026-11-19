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

from engine.generation import kb_loader
from engine.generation.claimable_set import build_claimable_set
from engine.generation.normalize import normalize_skill
from engine.generation.tailoring import _display_case
from engine.generation.text_norm import plain_typography


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


_PERCENT_RE = re.compile(r"(?i)\d+(?:\.\d+)?\s*(?:%|percent)|\bpercent\b")
# Appendix sentences the pre-v3 tailoring pass wrote into descriptions (read as filler).
_LEGACY_FILLER_RE = re.compile(r"(?i)\s*(?:Key working areas|Implementation focus):[^.]*\.?")


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split()))
    return [p.strip() for p in parts if p.strip()]


def _with_stop(text: str) -> str:
    text = " ".join(str(text).split()).strip(" -•*")
    return text if not text or text[-1] in ".!?" else text + "."


def _evidence_bullets(source: dict, limit: int) -> list[str]:
    """One bullet per KB evidence line (percentage lines are never printed)."""
    bullets = [_with_stop(line) for line in source.get("evidence") or []
               if str(line).strip() and not _PERCENT_RE.search(str(line))]
    return [b for b in bullets if b][:limit]


def bullet_findings(bullet: str, source: dict, kb: dict, cset, licensed_digits: set[str],
                    plan: dict | None = None) -> list[str]:
    """Why one generated bullet is not shippable for this KB entry ([] = clean)."""
    from engine.generation.evidence_vocab import vocabulary_violations
    from engine.verification.gates import check_g2_claims

    findings = [f"vocabulary: {term!r} is not evidenced for {source.get('id')}"
                for term in vocabulary_violations(bullet, source, kb, plan)]
    if _PERCENT_RE.search(bullet):
        # the KB's "70 percent accuracy" is a licensed digit, but percentages are never printed
        findings.append(f"percentage in bullet for {source.get('id')}: {bullet[:70]!r}")
    return findings + check_g2_claims(bullet, cset, licensed_digits)


def _grounded_bullets(current: dict, source: dict, kb: dict, cset, licensed_digits: set[str],
                      limit: int, plan: dict | None = None) -> tuple[list[str], list[str]]:
    """(bullets, findings): every generated bullet that stays inside this entry's
    truthful vocabulary and the digit rule; an offending bullet is dropped (not the
    whole entry). With no clean bullet left, the entry's evidence lines are used."""
    generated = [str(b) for b in current.get("bullets") or [] if str(b).strip()]
    if not generated:
        generated = _sentences(_LEGACY_FILLER_RE.sub("", str(current.get("description") or "")))
    generated = [_with_stop(_LEGACY_FILLER_RE.sub("", plain_typography(b))) for b in generated]
    generated = [b for b in generated if b]
    findings: list[str] = []
    clean: list[str] = []
    for bullet in generated:
        problems = bullet_findings(bullet, source, kb, cset, licensed_digits, plan)
        if problems:
            findings += problems
        else:
            clean.append(bullet)
    if clean:
        return clean[:limit], findings
    return _evidence_bullets(source, limit), findings


def ground_components(components: dict, analysis: dict, kb: dict, plan: dict | None = None) -> dict:
    """Return build-ready components whose biographical claims come from `kb`.

    The LLM-selected project IDs and owned skill matches are retained when
    valid, preserving job tailoring. Identity fields, dates, and employer
    details are reconstructed from candidate-approved entries. Generated
    bullets survive only inside each entry's truthful vocabulary
    (generation/evidence_vocab.py); otherwise the evidence lines are used.
    With a keyword plan, every job-ad keyword is placed in the Skills rows and
    truthful ones lead the entry rows (generation/keyword_injector.py).
    """
    from engine.generation.generator import (
        MAX_BULLETS_FIRST,
        MAX_BULLETS_OTHER,
        MAX_BULLETS_PROJECT,
    )
    from engine.generation.keyword_injector import (
        ENTRY_ROW_CAP,
        entry_row,
        is_objective_style,
        skill_rows,
        strip_gap_phrases,
    )

    grounded = deepcopy(components)
    grounded["grounding_findings"] = []
    skills = kb_loader.global_skill_names(kb)
    skill_keys = {_key(skill) for skill in skills}
    canonical: dict[str, str] = {}
    for skill in skills:
        canonical[_key(skill)] = skill
    for entry in kb_loader.global_skills(kb):
        name = str(entry.get("name") or "")
        for alias in entry.get("aliases", []):
            canonical[_key(str(alias))] = name

    cset = build_claimable_set(analysis, kb, keywords=(plan or {}).get("targets"))
    licensed_digits = kb_loader.licensed_digits(kb)
    from engine.verification.gates import check_g2_claims

    gen_obj, _ = strip_gap_phrases(plain_typography(str(components.get("objective") or "")).strip())
    if gen_obj and len(gen_obj.split()) <= 65 and not is_objective_style(gen_obj) \
            and not check_g2_claims(gen_obj, cset, licensed_digits):
        grounded["objective"] = gen_obj
    else:
        # profile-style fallback: facts + the job's top keywords, no "seeking".
        # Lead with up to two programming languages, then the ad's required/tool
        # keywords, then job keywords the KB really owns, then other lexicon terms.
        technical = [k for k in (plan or {}).get("keywords") or []
                     if k.get("category") not in ("soft_skills", "education_field", "domain")]
        owned_keys = {_key(name) for name in skills}
        ordered = [k["term"] for k in technical if k.get("category") == "programming"][:2]
        ordered += [k["term"] for k in technical if k.get("canonical")
                    and (k.get("sources") or ["sweep"])[0] in ("required", "tools")]
        ordered += [k["term"] for k in technical
                    if _key(k["term"]) in owned_keys or _key(k.get("canonical") or "") in owned_keys]
        ordered += [k["term"] for k in technical if k.get("canonical")]
        relevant = list(dict.fromkeys(ordered))[:6]
        if not relevant:
            relevant = _matched_skills(analysis, skills)
        if not relevant:
            relevant = [name for name in ("Python", "JavaScript", "Machine Learning", "Data Analytics") if name in skills]
        relevant_text = ", ".join(relevant[:6])
        grounded["objective"] = (
            "MSc Artificial Intelligence student and BE Computer Engineering graduate with experience as a "
            f"Software Engineer and Machine Learning Intern, working with {relevant_text}."
        )

    if plan:
        # Unbacked keywords only in skills-list framing (generation/claim_check.py).
        from engine.generation.claim_check import honest_profile

        grounded["objective"], profile_findings = honest_profile(grounded["objective"], kb, plan)
        grounded["grounding_findings"] += profile_findings

    current_experiences = {
        str(entry.get("id") or ""): entry
        for entry in (grounded.get("experiences") or [])
        if isinstance(entry, dict)
    }
    grounded_experiences: list[dict] = []
    for index, source in enumerate(kb_loader.experiences(kb)):
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
        if plan:
            selected, _ = entry_row(source, selected, kb, plan)
        limit = MAX_BULLETS_FIRST if index == 0 else MAX_BULLETS_OTHER
        bullets, findings = _grounded_bullets(current, source, kb, cset, licensed_digits, limit, plan)
        grounded["grounding_findings"] += findings
        end = str(source.get("end") or "")
        grounded_experiences.append({
            "id": exp_id,
            "role": (source.get("titles_allowed") or [source.get("role", "")])[0],
            "company": str(source.get("company") or ""),
            "location": str(source.get("location") or ""),
            "dates": f"{_date_label(str(source.get('start') or ''))} - "
                     f"{'Current' if end == 'present' else _date_label(end)}",
            "bullets": bullets,
            "description": " ".join(bullets),
            "skills": selected[:ENTRY_ROW_CAP if plan else 8],
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

    # Score candidate projects by overlap with JD analysis if needed
    req_terms = {_key(t) for t in (analysis.get("required") or []) + (analysis.get("tools") or [])}
    candidate_pids = [pid for pid in ("vehicle_sharing", "resume_gen", "hft") if pid not in project_ids]
    def _proj_score(pid: str) -> int:
        p_data = main_projects.get(pid, {})
        p_tokens = {_key(s) for s in p_data.get("skills_allowed", []) + p_data.get("evidence", [])}
        return sum(1 for r in req_terms if any(r in s or s in r for s in p_tokens) or _key(pid) in req_terms)
    candidate_pids.sort(key=_proj_score, reverse=True)
    for project_id in candidate_pids:
        if len(project_ids) < 2:
            project_ids.append(project_id)

    grounded_projects: list[dict] = []
    current_project_by_id = {str(p.get("id") or ""): p for p in current_projects}
    for project_id in project_ids:
        source = main_projects[project_id]
        pool = list(cset.per_project.get(project_id, []))
        allowed = {_key(skill) for skill in pool}
        selected: list[str] = []
        gen_p = current_project_by_id.get(project_id, {})
        for value in gen_p.get("skills", []):
            display = _display_skill(value, canonical)
            if _key(normalize_skill(display)) in allowed and display not in selected:
                selected.append(display)
        for value in pool:
            display = _display_skill(value, canonical)
            if _key(normalize_skill(display)) in allowed and display not in selected:
                selected.append(display)
            if len(selected) >= 6:
                break
        if plan:
            selected, _ = entry_row(source, selected, kb, plan)
        bullets, findings = _grounded_bullets(gen_p, source, kb, cset, licensed_digits, MAX_BULLETS_PROJECT, plan)
        grounded["grounding_findings"] += findings
        grounded_projects.append({
            "id": project_id,
            "title": str(source.get("title") or ""),
            "bullets": bullets,
            "description": " ".join(bullets),
            "skills": selected[:ENTRY_ROW_CAP if plan else 8],
        })
    grounded["projects"] = grounded_projects

    original_skills = grounded.get("skills_section") or {}

    def owned_row(values, fallback, limit=7, min_target=4):
        result: list[str] = []
        for value in values or []:
            display = _display_skill(str(value), canonical)
            if _key(normalize_skill(display)) in skill_keys and display not in result:
                result.append(display)
            if len(result) == limit:
                break
        if len(result) < min_target:
            for value in fallback:
                display = _display_skill(str(value), canonical)
                if _key(normalize_skill(display)) in skill_keys and display not in result:
                    result.append(display)
                if len(result) >= min_target:
                    break
        return result

    programming = [s for s in ("Python", "JavaScript", "TypeScript", "C++", "SQL") if s in skills]
    specialized = [s for s in (
        "Machine Learning", "Large Language Models", "Deep Learning", "Natural Language Processing",
        "Computer Vision", "Reinforcement Learning", "AI Agents",
    ) if s in skills]

    # Dynamically select domain defaults if areas or labels not provided
    req_blob = " ".join([str(t).lower() for t in (analysis.get("required") or []) + (analysis.get("tools") or []) + (analysis.get("preferred") or [])])
    is_frontend = any(k in req_blob for k in ("react", "javascript", "typescript", "html", "css", "frontend", "design system", "ui", "component"))
    is_ml_ai = any(k in req_blob for k in ("machine learning", "deep learning", "nlp", "computer vision", "llm", "large language", "neural", "model"))

    if is_frontend:
        default_label_1 = "Frontend Development"
        default_label_2 = "AI & Systems"
        fallback_1 = [s for s in ("React", "TypeScript", "JavaScript", "CSS", "HTML", "Design Systems", "Component Libraries") if s in skills]
        fallback_2 = [s for s in ("Python", "AI Agents", "Large Language Models", "FastAPI", "Django", "REST APIs", "Software Engineering Best Practices", "Git", "Agile Development") if s in skills]
    elif is_ml_ai:
        default_label_1 = "Machine Learning & AI"
        default_label_2 = "Software Engineering"
        fallback_1 = [s for s in ("Python", "Machine Learning", "Deep Learning", "Large Language Models", "Transformers", "Data Analytics") if s in skills]
        fallback_2 = [s for s in ("FastAPI", "Django", "REST APIs", "SQL", "Git", "Software Engineering Best Practices", "Agile Development") if s in skills]
    else:
        default_label_1 = "Software Engineering"
        default_label_2 = "AI & Modeling"
        fallback_1 = [s for s in ("Python", "FastAPI", "Django", "NodeJS", "REST APIs", "SQL", "Git", "Agile Development") if s in skills]
        fallback_2 = [s for s in ("Machine Learning", "Large Language Models", "AI Agents", "Data Analytics", "Quantitative Modeling") if s in skills]

    existing_areas = original_skills.get("areas") or []
    area_1 = existing_areas[0].get("skills", []) if len(existing_areas) > 0 else []
    area_2 = existing_areas[1].get("skills", []) if len(existing_areas) > 1 else []
    label_1 = existing_areas[0].get("label") if len(existing_areas) > 0 and existing_areas[0].get("label") else default_label_1
    label_2 = existing_areas[1].get("label") if len(existing_areas) > 1 and existing_areas[1].get("label") else default_label_2

    grounded["skills_section"] = {
        "languages": owned_row(original_skills.get("languages"), programming, limit=5, min_target=4),
        "specialized_areas": owned_row(original_skills.get("specialized_areas"), specialized, limit=5, min_target=4),
        "areas": [
            {"label": label_1, "skills": owned_row(area_1, fallback_1, limit=7, min_target=4)},
            {"label": label_2, "skills": owned_row(area_2, fallback_2, limit=7, min_target=4)},
        ],
    }
    if plan:
        # every job-ad keyword, grouped; the KB-owned rows above supply the extras
        grounded["skills_section"] = skill_rows(plan, kb, grounded["skills_section"])

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
