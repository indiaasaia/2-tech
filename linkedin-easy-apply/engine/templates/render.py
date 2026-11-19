"""One resume document model -> PDF (LaTeX values) and DOCX (plan v3 §3.1, §1 D1-D4).

Before v3 the PDF and the DOCX were assembled separately and drifted apart (the
DOCX shipped without experience dates, locations or full links). Here a single
plain-text document model is built once from the grounded components, the KB
and the keyword plan; `latex_fill_values` renders it for the v3 template and
templates/build.build_docx renders the same model to Word.

Layout (single column, standard headers, Textkernel quality codes 151/302/433):
  Name / headline (job title | degree) / contact / availability
  Profile, Technical Skills, Work Experience, Projects, Education, Research,
  Achievements, Certifications, Additional Projects, Languages
"""
from __future__ import annotations

import re

from engine import config
from engine.generation import kb_loader
from engine.generation.keyword_injector import pair_acronyms
from engine.templates.fill import escape_latex, join_items

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DEFAULT_HEADLINE_TAIL = "MSc Artificial Intelligence"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _month_year(value: str) -> str:
    """'2025-04' -> 'Apr 2025' (four-digit years: parser-safe, V3)."""
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(value or "").strip())
    if not match:
        return str(value or "").strip()
    year, month = match.groups()
    return year if month == "00" else f"{_MONTHS[int(month) - 1]} {year}"


def _display_url(url: str) -> str:
    """'https://www.linkedin.com/in/meetraval/' -> 'linkedin.com/in/meetraval'."""
    text = re.sub(r"^https?://", "", str(url or "").strip())
    text = re.sub(r"^www\.", "", text)
    return text.rstrip("/")


def _full_url(url: str) -> str:
    url = str(url or "").strip()
    return url if not url or re.match(r"^https?://", url) else "https://" + url


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split()))
    return [p.strip() for p in parts if p.strip()]


def _with_stop(text: str) -> str:
    text = " ".join(str(text or "").split()).strip()
    return text if not text or text[-1] in ".!?" else text + "."


def _language_line(kb: dict) -> str:
    """'English - Fluent (C2) | German - Basic (A2), currently learning | Hindi - Native'."""
    parts: list[str] = []
    for item in kb_loader.languages_spoken(kb):
        language = str(item.get("lang") or "").strip()
        level = str(item.get("level") or "")
        cefr = (re.search(r"\b([ABC][12])\b", level) or [None, ""])[1]
        if not language:
            continue
        if language.lower() == "english" and cefr in ("C1", "C2"):
            shown = f"Fluent ({cefr})"
        elif "native" in level.lower():
            shown = "Native"
        elif cefr in ("A1", "A2"):
            shown = f"Basic ({cefr})" + (", currently learning" if language.lower() == "german" else "")
        elif cefr:
            shown = f"{'Fluent' if cefr in ('C1', 'C2') else 'Intermediate'} ({cefr})"
        else:
            shown = level.strip()
        parts.append(f"{language} - {shown}" if shown else language)
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# document model
# ---------------------------------------------------------------------------

def resume_document(components: dict, kb: dict, plan: dict | None = None) -> dict:
    """Plain-text resume model (unescaped). Same content feeds PDF and DOCX."""
    plan = plan or {}
    profile = kb_loader.profile(kb)
    contact = profile.get("contact", {})
    name = str(profile.get("name") or "").strip()

    headline_job = str(plan.get("headline") or "").strip()
    headline = f"{headline_job} | {DEFAULT_HEADLINE_TAIL}" if headline_job else \
        f"{DEFAULT_HEADLINE_TAIL} | Software Engineer"

    contact_items: list[tuple[str, str]] = []
    if profile.get("location"):
        contact_items.append((str(profile["location"]), ""))
    if contact.get("phone_de"):
        contact_items.append((str(contact["phone_de"]), ""))
    if contact.get("email"):
        contact_items.append((str(contact["email"]), "mailto:" + str(contact["email"])))
    for key in ("linkedin", "github", "portfolio"):
        if contact.get(key):
            contact_items.append((_display_url(contact[key]), _full_url(contact[key])))

    availability = profile.get("availability") or {}
    availability_parts = [str(availability.get("start") or ""), str(availability.get("hours") or "")]
    authorization = str(profile.get("work_authorization") or "")
    if authorization and not authorization.upper().startswith("NOTE"):
        availability_parts.append(authorization)
    availability_line = " | ".join(p for p in availability_parts if p.strip())

    section = components.get("skills_section") or {}
    if section.get("rows"):
        skill_rows = [(str(r["label"]), [str(s) for s in r["skills"]]) for r in section["rows"] if r.get("skills")]
    else:   # pre-v3 components: the legacy four rows
        skill_rows = [("Programming Languages", list(section.get("languages") or [])),
                      ("Specialized Areas", list(section.get("specialized_areas") or []))]
        skill_rows += [(str(a.get("label") or "Skills"), list(a.get("skills") or []))
                       for a in section.get("areas") or []]
        skill_rows = [(label, items) for label, items in skill_rows if items]

    experiences = []
    for entry in components.get("experiences") or []:
        bullets = [_with_stop(b) for b in entry.get("bullets") or [] if str(b).strip()] \
            or [_with_stop(s) for s in _sentences(entry.get("description", ""))]
        experiences.append({
            "title": str(entry.get("role") or ""),
            "company": str(entry.get("company") or ""),
            "location": str(entry.get("location") or ""),
            "dates": str(entry.get("dates") or ""),
            "bullets": bullets,
            "skills": pair_acronyms([str(s) for s in entry.get("skills") or []]),
        })

    kb_projects = {str(p.get("id")): p for p in kb.get("projects", [])}
    projects = []
    for entry in components.get("projects") or []:
        source = kb_projects.get(str(entry.get("id") or ""), {})
        bullets = [_with_stop(b) for b in entry.get("bullets") or [] if str(b).strip()] \
            or [_with_stop(s) for s in _sentences(entry.get("description", ""))]
        url = str(source.get("url") or "")
        projects.append({
            "title": str(entry.get("title") or source.get("title") or ""),
            "url_text": _display_url(url) if url else "",
            "url": _full_url(url) if url else "",
            "bullets": bullets,
            "skills": pair_acronyms([str(s) for s in entry.get("skills") or []]),
        })

    education = []
    for edu in kb.get("education", []):
        end = str(edu.get("end") or "")
        if end == "present" and edu.get("expected_end"):
            end_label = f"{_month_year(edu['expected_end'])} (expected)"
        elif end == "present":
            end_label = "Present"
        else:
            end_label = _month_year(end)
        lines: list[str] = []
        if edu.get("faculty"):
            lines.append(str(edu["faculty"]))
        if edu.get("focus_areas"):
            lines.append("Focus areas: " + ", ".join(str(f) for f in edu["focus_areas"]))
        education.append({
            "degree": str(edu.get("display_degree") or edu.get("degree") or ""),
            "school": str(edu.get("display_school") or edu.get("school") or ""),
            "location": str(edu.get("display_location") or ""),
            "dates": f"{_month_year(edu.get('start', ''))} - {end_label}",
            "lines": lines,
        })

    research = [{"title": str(r.get("title") or ""),
                 "summary": _with_stop((r.get("evidence") or [""])[0])}
                for r in kb_loader.research(kb)]
    achievements = [f"{a.get('name', '')}: {a.get('result', '')}".strip(": ")
                    for a in kb_loader.achievements(kb)]
    certifications = [str(c.get("name") or "") for c in kb_loader.certifications(kb) if c.get("name")]

    additional: list[tuple[str, str, str]] = []      # (text, url_text, url)
    freelance: list[str] = []
    for proj in kb_loader.projects(kb, tier="additional"):
        evidence = "; ".join(str(e) for e in proj.get("evidence", []))
        url = str(proj.get("url") or "")
        if evidence.lower().startswith("freelance work delivered"):
            label = str(proj.get("title") or "")
            freelance.append(f"{label} ({_display_url(url)})" if url else label)
            continue
        additional.append((f"{proj.get('title', '')}: {evidence}",
                           _display_url(url) if url else "", _full_url(url) if url else ""))
    if freelance:
        additional.append(("Freelance web projects delivered for clients: " + ", ".join(freelance), "", ""))

    return {
        "name": name,
        "pdf_title": f"{name} - CV",
        "headline": headline,
        "contact": contact_items,
        "availability": availability_line,
        "profile": str(components.get("objective") or "").strip(),
        "skill_rows": skill_rows,
        "experiences": experiences,
        "projects": projects,
        "education": education,
        "research": research,
        "achievements": achievements,
        "certifications": certifications,
        "additional_projects": additional,
        "languages": _language_line(kb),
    }


# ---------------------------------------------------------------------------
# LaTeX rendering (values for the v3 template; fill.py contract: pre-escaped)
# ---------------------------------------------------------------------------

def _href(url: str, text: str) -> str:
    safe_url = str(url).replace("\\", "").replace("%", r"\%").replace("#", r"\#")
    return r"\href{" + safe_url + "}{" + escape_latex(text) + "}"


def _items(lines: list[str]) -> str:
    """itemize body; an empty list still yields a valid (blank) item."""
    return "\n".join(lines) if lines else r"\item[] {}"


def latex_fill_values(doc: dict) -> dict[str, str]:
    """Token -> escaped LaTeX fragment for templates/core_resume_template_v3.tex."""
    t = config.TOKENS
    contact = " | ".join(_href(url, text) if url else escape_latex(text) for text, url in doc["contact"])

    skills = [r"\item \textbf{" + escape_latex(label) + r":} " + join_items(items)
              for label, items in doc["skill_rows"]]

    experience_blocks: list[str] = []
    for exp in doc["experiences"]:
        head = " | ".join(escape_latex(p) for p in (exp["company"], exp["location"]) if p)
        lines = [r"\textbf{" + escape_latex(exp["title"]) + "}" + (" | " + head if head else "")
                 + r" \hfill " + escape_latex(exp["dates"]) + r"\par",
                 r"\begin{itemize}"]
        lines += [r"\item " + escape_latex(b) for b in exp["bullets"]]
        if exp["skills"]:
            lines.append(r"\item \textbf{Key skills:} " + join_items(exp["skills"]))
        lines += [r"\end{itemize}", r"\vspace{3pt}"]
        experience_blocks.append("\n".join(lines))

    project_blocks: list[str] = []
    for proj in doc["projects"]:
        title = r"\textbf{" + escape_latex(proj["title"]) + "}"
        if proj["url"]:
            title += " | " + _href(proj["url"], proj["url_text"])
        lines = [title + r"\par", r"\begin{itemize}"]
        lines += [r"\item " + escape_latex(b) for b in proj["bullets"]]
        if proj["skills"]:
            lines.append(r"\item \textbf{Tech:} " + join_items(proj["skills"]))
        lines += [r"\end{itemize}", r"\vspace{3pt}"]
        project_blocks.append("\n".join(lines))

    education_blocks: list[str] = []
    for edu in doc["education"]:
        # two-line head: the long school name would push the dates onto a broken line
        school = " | ".join(escape_latex(p) for p in (edu["school"], edu["location"]) if p)
        lines = [r"\textbf{" + escape_latex(edu["degree"]) + r"} \hfill " + escape_latex(edu["dates"]) + r"\par"]
        if school:
            lines.append(school + r"\par")
        lines += [escape_latex(line) + r"\par" for line in edu["lines"]]
        lines.append(r"\vspace{3pt}")
        education_blocks.append("\n".join(lines))

    research = [r"\item \textbf{" + escape_latex(r["title"]) + r"}\\ " + escape_latex(r["summary"])
                for r in doc["research"]]
    achievements = [r"\item " + escape_latex(a) for a in doc["achievements"]]
    certifications = [r"\item " + escape_latex(c) for c in doc["certifications"]]
    additional = [r"\item " + escape_latex(text) + (" | " + _href(url, url_text) if url else "")
                  for text, url_text, url in doc["additional_projects"]]

    return {
        t["pdf_title"]: escape_latex(doc["pdf_title"]),
        t["name"]: escape_latex(doc["name"]),
        t["headline"]: escape_latex(doc["headline"]),
        t["contact_line"]: contact,
        t["availability"]: escape_latex(doc["availability"]),
        t["profile"]: escape_latex(doc["profile"]),
        t["skills_rows"]: _items(skills),
        t["experience"]: "\n".join(experience_blocks),
        t["projects"]: "\n".join(project_blocks),
        t["education"]: "\n".join(education_blocks),
        t["research"]: _items(research),
        t["achievements"]: _items(achievements),
        t["certifications"]: _items(certifications),
        t["additional_projects"]: _items(additional),
        t["spoken_languages"]: escape_latex(doc["languages"]),
    }
