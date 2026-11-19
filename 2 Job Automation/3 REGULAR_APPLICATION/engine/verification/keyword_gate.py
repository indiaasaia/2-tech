"""100% keyword gate (plan v3 §4 step 3): every job-ad keyword must be in the artifact.

Two checks, both deterministic:
  1. pre-build  `ensure_keywords(doc, plan)` — any target missing from the resume
     document model is added to its category row in Technical Skills;
  2. post-build `check_artifacts(plan, pdf_text, docx_text)` — every target must be
     found in the PARSED PDF text AND the DOCX text. A keyword lost in rendering
     (the 2026-10-17 'Traf{}fic' escaping bug) fails the gate: never ship.

Not counted as misses (reported instead): education fields the candidate cannot
truthfully claim (e.g. "Business Informatics"), eligibility rules and language
requirements — a resume line cannot make them true.

`kb_backing` splits the job's technical keywords into KB-backed (a KB skill or a
term an entry's evidence supports) and prep terms (printed for the ATS, still to
learn before an interview); its share drives the shortlist ranking.
"""
from __future__ import annotations

import re

from engine.generation.keywords import _norm_key
from engine.templates.fill import clean_text

_TERM_CHAR = r"A-Za-z0-9_+#ÄÖÜäöüß"
_NON_TECH = ("soft_skills", "education_field", "domain")


def normalize_text(text: str) -> str:
    """Case-folded, whitespace-collapsed, unicode-punctuation-normalized text."""
    return re.sub(r"\s+", " ", clean_text(str(text or "")).lower()).strip()


def keyword_in_text(term: str, normalized_text: str) -> bool:
    """Whole-term, case-insensitive containment (tech-aware boundaries: 'C' never
    matches inside 'C++', 'Java' never inside 'JavaScript'). Pairs count:
    'ML' is found in 'Machine Learning (ML)'."""
    needle = normalize_text(term)
    if not needle:
        return True
    pattern = rf"(?<![{_TERM_CHAR}]){re.escape(needle)}(?![{_TERM_CHAR}])"
    return re.search(pattern, normalized_text) is not None


def _targets(plan: dict) -> tuple[list[dict], list[dict]]:
    """(skill-type keywords that must be printed, education fields)."""
    keywords = plan.get("keywords") or []
    return ([k for k in keywords if k.get("category") != "education_field"],
            [k for k in keywords if k.get("category") == "education_field"])


def document_text(doc: dict) -> str:
    """All text of the resume document model (templates/render.resume_document)."""
    parts = [doc.get("name", ""), doc.get("headline", ""), doc.get("availability", ""),
             doc.get("profile", ""), doc.get("languages", "")]
    parts += [text for text, _url in doc.get("contact", [])]
    for label, items in doc.get("skill_rows", []):
        parts += [label] + list(items)
    for entry in doc.get("experiences", []) + doc.get("projects", []):
        parts += [entry.get("title", ""), entry.get("company", ""), entry.get("location", "")]
        parts += list(entry.get("bullets", [])) + list(entry.get("skills", []))
    for edu in doc.get("education", []):
        parts += [edu.get("degree", ""), edu.get("school", ""), edu.get("location", "")] + list(edu.get("lines", []))
    for item in doc.get("research", []):
        parts += [item.get("title", ""), item.get("summary", "")]
    parts += list(doc.get("achievements", [])) + list(doc.get("certifications", []))
    parts += [text for text, _u, _url in doc.get("additional_projects", [])]
    return "\n".join(str(p) for p in parts if p)


def ensure_keywords(doc: dict, plan: dict) -> list[str]:
    """Add every target keyword missing from the document model to its category
    row (creating the row when needed). Returns the terms added."""
    from engine.generation.keyword_injector import CATEGORY_ROWS

    labels = dict(CATEGORY_ROWS)
    order = [label for _cat, label in CATEGORY_ROWS]
    text = normalize_text(document_text(doc))
    rows = [(label, list(items)) for label, items in doc.get("skill_rows", [])]
    added: list[str] = []
    skills, _education = _targets(plan)
    for keyword in skills:
        term = str(keyword.get("term") or "")
        if not term or keyword_in_text(term, text):
            continue
        label = labels.get(str(keyword.get("category") or ""), labels["tools_methods"])
        for index, (row_label, items) in enumerate(rows):
            if row_label == label:
                rows[index] = (row_label, items + [term])
                break
        else:
            rows.append((label, [term]))
        added.append(term)
        text += " " + normalize_text(term)
    rows.sort(key=lambda row: order.index(row[0]) if row[0] in order else len(order))
    doc["skill_rows"] = rows
    return added


def check_artifacts(plan: dict, pdf_text: str, docx_text: str | None) -> dict:
    """Gate result over the parsed artifacts (both formats must carry every keyword).

    `docx_text=None` means no DOCX was built (already a recorded build error);
    the gate then judges the PDF alone instead of failing every keyword.
    """
    pdf = normalize_text(pdf_text)
    skills, education = _targets(plan)
    terms = [str(k["term"]) for k in skills if str(k.get("term") or "").strip()]
    missing_pdf = [t for t in terms if not keyword_in_text(t, pdf)]
    if docx_text is None:
        missing_docx: list[str] = []
    else:
        docx = normalize_text(docx_text)
        missing_docx = [t for t in terms if not keyword_in_text(t, docx)]
    education_gaps = [str(k["term"]) for k in education if not keyword_in_text(str(k["term"]), pdf)]
    found = len(terms) - len(missing_pdf)
    return {
        "targets": len(terms),
        "found_pdf": found,
        "coverage": round(found / len(terms), 3) if terms else 1.0,
        "missing_pdf": missing_pdf,
        "missing_docx": missing_docx,
        "education_gaps": education_gaps,
        "eligibility": list(plan.get("eligibility") or []),
        "languages_required": list(plan.get("languages") or []),
        "passed": not missing_pdf and not missing_docx,
    }


def kb_backing(plan: dict, kb: dict) -> dict:
    """Which technical keywords the candidate's KB really supports vs. still to learn."""
    from engine.generation import kb_loader
    from engine.generation.evidence_vocab import _keys_for, _whole_keys, allowed_keys

    backed_keys: set[str] = set()
    for skill in kb_loader.global_skills(kb):
        for name in [str(skill.get("name") or "")] + [str(a) for a in skill.get("aliases", [])]:
            backed_keys |= set(_keys_for(name))
    for entry in kb_loader.experiences(kb) + kb_loader.projects(kb) + kb_loader.research(kb):
        backed_keys |= allowed_keys(entry, kb)

    backed: list[str] = []
    prep: list[str] = []
    for keyword in plan.get("keywords") or []:
        if keyword.get("category") in _NON_TECH:
            continue
        # whole-phrase keys only: "AI assistants" is not backed just because "AI" is
        keys = set(_whole_keys(str(keyword.get("term") or ""))) | set(_whole_keys(str(keyword.get("canonical") or "")))
        (backed if keys & backed_keys else prep).append(str(keyword["term"]))
    total = len(backed) + len(prep)
    return {
        "kb_backed": backed,
        "prep_terms": prep,
        "kb_backed_share": round(len(backed) / total, 3) if total else 0.0,
    }
