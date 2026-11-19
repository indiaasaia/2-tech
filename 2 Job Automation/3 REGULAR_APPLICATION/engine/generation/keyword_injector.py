"""Keyword injector (plan v3 §3.2): every job-ad keyword lands in the resume.

Placement rules:
  - Skills section: ALL target keywords, grouped by category, job-ad spelling,
    in plan order (required -> tools -> preferred -> swept); KB skills the
    generator chose follow while a row is still short.
  - Experience/project skill rows: only keywords that truthfully describe that
    entry (generation/evidence_vocab.py), placed first.
  - Profile/objective: gap-advertising sentences ("Working toward hands-on X")
    are removed — they told recruiters what the candidate lacks.

Education fields ("Computer Science") are not skills; they are rendered by the
education section (step 3). Deterministic and idempotent.
"""
from __future__ import annotations

import re

from engine.generation import kb_loader
from engine.generation.evidence_vocab import entry_keywords
from engine.generation.keywords import _norm_key, sweep

# The current template has four skill rows; categories map onto them.
# (row key, categories, label pieces per category)
ROWS = (
    ("languages", ("programming",)),
    ("specialized_areas", ("ml_ai", "data")),
    ("area_0", ("backend_cloud_devops", "security")),
    ("area_1", ("tools_methods", "soft_skills", "domain")),
)
_ROW_OF = {category: row for row, categories in ROWS for category in categories}
_DEFAULT_CATEGORY = "tools_methods"

ROW_EXTRA_CAP = 8           # KB-only skills are added while a row is shorter than this
ENTRY_ROW_CAP = 10

_GAP_SENTENCE_RE = re.compile(
    r"(?i)\b(?:working toward|working towards|eager to (?:deepen|gain|learn|build|develop|expand)|"
    r"looking to (?:gain|deepen|learn)|aspiring|seeking to (?:gain|learn)|"
    r"hope to (?:gain|learn)|targeting experience|actively expanding into|"
    r"gaining hands-on experience with)\b"
)


# Objective-style openers the profile must not use (records generated before
# policy v3 carry them; grounding swaps such text for the profile fallback).
_OBJECTIVE_STYLE_RE = re.compile(
    r"(?i)\b(?:seeking|looking for|eager|aspiring|passionate|hoping to|in search of|"
    r"to apply (?:my|his|her)?\s*\w*\s*(?:skills|expertise|knowledge))\b"
)


def is_objective_style(text: str) -> bool:
    """True for 'seeking a X role to apply ...' objective phrasing (not a profile)."""
    return bool(_OBJECTIVE_STYLE_RE.search(str(text or "")))


def category_of(term: str) -> str:
    """Lexicon category of a skill name (first hit), else tools_methods."""
    hits = sweep(str(term))
    return hits[0]["category"] if hits else _DEFAULT_CATEGORY


def strip_gap_phrases(text: str) -> tuple[str, int]:
    """Drop sentences that advertise a missing skill; returns (text, removed_count)."""
    sentences = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    kept = [s for s in sentences if s and not _GAP_SENTENCE_RE.search(s)]
    return " ".join(kept).strip(), len([s for s in sentences if s]) - len(kept)


def _area_label(row: str, categories_used: set[str]) -> str:
    if row == "area_0":
        if categories_used == {"security"}:
            return "Security"
        if "security" in categories_used:
            return "Software, Cloud & Security"
        return "Software & Cloud"
    if "soft_skills" in categories_used:
        return "Tools, Methods & Soft Skills"
    return "Tools & Methods"


# Category rows of the v3 template, in print order (empty rows are not printed).
CATEGORY_ROWS = (
    ("programming", "Programming Languages"),
    ("ml_ai", "AI & Machine Learning"),
    ("data", "Data & Analytics"),
    ("backend_cloud_devops", "Software, Cloud & DevOps"),
    ("security", "Security"),
    ("tools_methods", "Tools & Methods"),
    ("domain", "Domain Knowledge"),
    ("soft_skills", "Soft Skills"),
)
# Rows that fall back to KB skills when the job names nothing in them.
_FALLBACK_CATEGORIES = ("programming", "ml_ai", "data", "backend_cloud_devops")

# Acronym pairs printed as "Long Form (ACR)" so both search forms are present.
_ACRONYM_PAIRS = {
    "artificialintelligence": ("Artificial Intelligence", "AI"),
    "machinelearning": ("Machine Learning", "ML"),
    "naturallanguageprocessing": ("Natural Language Processing", "NLP"),
    "largelanguagemodels": ("Large Language Models", "LLMs"),
    "retrievalaugmentedgeneration": ("Retrieval-Augmented Generation", "RAG"),
    "exploratorydataanalysis": ("Exploratory Data Analysis", "EDA"),
    "künstlicheintelligenz": ("Künstliche Intelligenz", "KI"),
}
_ACRONYM_TO_LONG = {"ai": "artificialintelligence", "ml": "machinelearning", "nlp": "naturallanguageprocessing",
                    "llm": "largelanguagemodels", "llms": "largelanguagemodels",
                    "rag": "retrievalaugmentedgeneration", "eda": "exploratorydataanalysis",
                    "ki": "künstlicheintelligenz"}


_PAIRED_RE = re.compile(r"^(.+?)\s+\(([^()]+)\)$")


def _unpair(item: str) -> list[str]:
    """'Machine Learning (ML)' -> ['Machine Learning', 'ML']; other items unchanged."""
    match = _PAIRED_RE.match(item.strip())
    return [match.group(1), match.group(2)] if match else [item]


def is_printed(term: str, items: list[str]) -> bool:
    """True when `term` appears in a printed skills list, alone or inside a pair
    ('ML' in 'Machine Learning (ML)', 'Datenanalyse' in 'Datenanalyse (Data Analysis)')."""
    key = _norm_key(term)
    return any(key == _norm_key(part) for item in items for part in [item] + _unpair(item))


def pair_acronyms(items: list[str]) -> list[str]:
    """Merge/expand acronym pairs: ['ML', 'Machine Learning'] -> ['Machine Learning (ML)'].

    The job ad's acronym spelling wins ("LLM" vs "LLMs"); a lone long form gets the
    standard acronym, a lone acronym gets its long form.
    """
    out: list[str] = []
    position: dict[str, int] = {}
    for item in items:
        key = _norm_key(item)
        long_key = key if key in _ACRONYM_PAIRS else _ACRONYM_TO_LONG.get(key)
        if long_key is None:
            out.append(item)
            continue
        long_form, default_acronym = _ACRONYM_PAIRS[long_key]
        acronym = item if key != long_key else ""
        if long_key in position:
            if acronym:
                out[position[long_key]] = f"{long_form} ({acronym})"
            continue
        position[long_key] = len(out)
        out.append(f"{long_form} ({acronym or default_acronym})")
    return out


def skill_rows(plan: dict, kb: dict, existing: dict | None) -> dict:
    """Skills section for one job: category `rows` for the v3 template, plus the
    legacy four keys (languages / specialized_areas / areas) kept in sync for the
    intent-text, gate and scorecard code that still reads them."""
    existing = existing or {}
    by_category: dict[str, list[str]] = {category: [] for category, _ in CATEGORY_ROWS}
    seen: set[str] = set()

    def place(term: str, category: str, force: bool) -> None:
        key = _norm_key(term)
        if not key or key in seen:
            return
        category = category if category in by_category else _DEFAULT_CATEGORY
        if not force and len(by_category[category]) >= ROW_EXTRA_CAP:
            return
        seen.add(key)
        by_category[category].append(term)

    for keyword in plan.get("keywords") or []:
        if keyword.get("category") == "education_field":
            continue
        term = str(keyword["term"])
        english = str(keyword.get("english") or "")
        # German ad terms carry their English equivalent once: "Datenanalyse (Data Analysis)"
        if english and _norm_key(english) != _norm_key(term) and _norm_key(term) not in _ACRONYM_TO_LONG \
                and _norm_key(term) not in _ACRONYM_PAIRS:
            seen.add(_norm_key(english))
            term = f"{term} ({english})"
        place(term, str(keyword.get("category") or _DEFAULT_CATEGORY), force=True)
        seen.add(_norm_key(str(keyword["term"])))
        # a keyword's canonical spelling counts as present too (no "NodeJS" + "Node.js")
        if keyword.get("canonical"):
            seen.add(_norm_key(keyword["canonical"]))

    # extras from the draft must be real KB skills (an LLM-invented tool the job never
    # mentioned, or a pool phrase like "Backend Components", is not a Skills entry)
    kb_names: dict[str, str] = {}
    for skill in kb_loader.global_skills(kb):
        name = str(skill.get("name") or "")
        for alias in [name] + [str(a) for a in skill.get("aliases", [])]:
            kb_names.setdefault(_norm_key(alias), name)
    drafted = list(existing.get("languages") or []) + list(existing.get("specialized_areas") or [])
    for area in existing.get("areas") or []:
        drafted += list(area.get("skills") or [])
    for skill in drafted:
        # a row printed by an earlier pass holds "Machine Learning (ML)": look up both parts
        for part in _unpair(str(skill)):
            name = kb_names.get(_norm_key(part))
            if name:
                place(name, category_of(name), force=False)

    # core technical rows never stay empty: fall back to KB skills of that category
    for category in _FALLBACK_CATEGORIES:
        if by_category[category]:
            continue
        for skill in kb_loader.global_skill_names(kb):
            if category_of(skill) == category:
                place(skill, category, force=False)
            if len(by_category[category]) >= 4:
                break

    printed = {category: pair_acronyms(items) for category, items in by_category.items()}
    rows = [{"label": label, "skills": printed[category]}
            for category, label in CATEGORY_ROWS if printed[category]]

    legacy: dict[str, list[str]] = {row: [] for row, _ in ROWS}
    used: dict[str, set[str]] = {row: set() for row, _ in ROWS}
    for category, items in printed.items():
        if items:
            legacy[_ROW_OF[category]].extend(items)
            used[_ROW_OF[category]].add(category)
    areas = existing.get("areas") or [{}, {}]
    return {
        "rows": rows,
        "languages": legacy["languages"],
        "specialized_areas": legacy["specialized_areas"],
        "areas": [
            {"label": _area_label("area_0", used["area_0"]) if legacy["area_0"]
             else str((areas[0] or {}).get("label") or "Software & Cloud"),
             "skills": legacy["area_0"]},
            {"label": _area_label("area_1", used["area_1"]) if legacy["area_1"]
             else str((areas[1] if len(areas) > 1 else {}).get("label") or "Tools & Methods"),
             "skills": legacy["area_1"]},
        ],
    }


def entry_row(entry: dict, existing_row: list[str], kb: dict, plan: dict | None) -> tuple[list[str], list[str]]:
    """(row, added): truthful job keywords for this KB entry first, then the existing row."""
    truthful = entry_keywords(entry, kb, plan)
    row: list[str] = []
    seen: set[str] = set()
    for term in truthful + [str(s) for s in existing_row or []]:
        key = _norm_key(term)
        if key and key not in seen:
            seen.add(key)
            row.append(term)
    existing_keys = {_norm_key(s) for s in existing_row or []}
    added = [t for t in truthful if _norm_key(t) not in existing_keys]
    return row[:ENTRY_ROW_CAP], added
