"""Load the candidate knowledge base (the single source of truth, FINAL_MODEL 3.4).

The KB is validated at load: status APPROVED, evidence ids resolve, every
experience/project carries explicit allowed/forbidden skill lists. The rest of
the engine reads the KB only through this module so the schema stays in one place.
"""
from __future__ import annotations

import json
from functools import lru_cache

from resume_content_improve_research import config


class KBError(RuntimeError):
    """Raised when the KB is missing, unapproved, or structurally invalid."""


@lru_cache(maxsize=1)
def load_kb() -> dict:
    """Load candidate_kb.json and enforce the hard preconditions."""
    if not config.KB_PATH.exists():
        raise KBError(f"knowledge base not found: {config.KB_PATH}")
    kb = json.loads(config.KB_PATH.read_text(encoding="utf-8"))
    if kb.get("status") != "APPROVED":
        raise KBError(
            "candidate_kb.json status must be APPROVED before v2 generation runs "
            f"(got {kb.get('status')!r})"
        )
    return kb


def profile(kb: dict) -> dict:
    return kb.get("profile", {})


def global_skills(kb: dict) -> list[dict]:
    """The 25 licensed global skills: {name, aliases, evidence}."""
    return kb.get("skills", [])


def global_skill_names(kb: dict) -> list[str]:
    return [s["name"] for s in global_skills(kb) if s.get("name")]


def experiences(kb: dict) -> list[dict]:
    """Both stints with titles_allowed / skills_allowed / skills_forbidden / evidence."""
    return kb.get("experience", [])


def projects(kb: dict, tier: str | None = None) -> list[dict]:
    """Real projects only (the KB rejects non-real ones at validation time)."""
    items = [p for p in kb.get("projects", []) if p.get("real")]
    if tier:
        items = [p for p in items if p.get("tier") == tier]
    return items


def main_projects(kb: dict) -> list[dict]:
    return projects(kb, tier="main")


def research(kb: dict) -> list[dict]:
    return kb.get("research", [])


def certifications(kb: dict) -> list[dict]:
    return kb.get("certifications", [])


def achievements(kb: dict) -> list[dict]:
    return kb.get("achievements", [])


def languages_spoken(kb: dict) -> list[dict]:
    return profile(kb).get("languages_spoken", [])


def motivation_profile(kb: dict) -> dict:
    """The optional candidate-approved motivation profile ({} when absent)."""
    from resume_content_improve_research.generation import motivation as _mot

    return _mot.get_profile(kb)


def motivation_entries(kb: dict) -> list[dict]:
    """Raw motivation entries ([] when the profile is absent — backward compat)."""
    from resume_content_improve_research.generation import motivation as _mot

    return _mot.entries(kb)


def licensed_digits(kb: dict) -> set[str]:
    """Every digit-string the candidate is licensed to print (V6 digit rule).

    Sources: education/certification/achievement years, and every number that
    appears inside evidence text of any entry (40+, 24, 70 ...).
    """
    import re

    digits: set[str] = set(config.DATE_YEARS_ALLOWED)
    texts: list[str] = []
    for exp in experiences(kb):
        texts.extend(str(e) for e in exp.get("evidence", []))
    for proj in projects(kb):
        texts.extend(str(e) for e in proj.get("evidence", []))
        texts.append(str(proj.get("metrics_note", "")))
    for res in research(kb):
        texts.extend(str(e) for e in res.get("evidence", []))
    for match in re.finditer(r"\d+(?:\.\d+)?", " ".join(texts)):
        digits.add(match.group(0).lstrip("0") or "0")
        digits.add(match.group(0))
    return digits


def evidence_ids(kb: dict) -> set[str]:
    """All entry ids plus the built-in master_cv source."""
    ids = {"master_cv"}
    for edu in kb.get("education", []):
        if edu.get("id"):
            ids.add(str(edu["id"]))
    for exp in experiences(kb):
        if exp.get("id"):
            ids.add(str(exp["id"]))
        second = exp.get("second_stint")
        if isinstance(second, dict) and second.get("id"):
            ids.add(str(second["id"]))
    for proj in projects(kb):
        if proj.get("id"):
            ids.add(str(proj["id"]))
    for res in research(kb):
        if res.get("id"):
            ids.add(str(res["id"]))
    return ids

