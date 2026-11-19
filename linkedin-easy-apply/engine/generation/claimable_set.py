"""The claimable set (FINAL_MODEL 3.1 step 4): what the generator may mention.

= KB-licensed skills (with evidence ids) ∪ JD tools ∪ the job's target keywords.
Policy v3 (2026-10-17): every keyword the job ad asks for may be printed; the
G2 tech-token gate still rejects technology the job never mentioned and the KB
does not license (real hallucinations). Which keywords may describe a specific
experience/project is decided per entry by generation/evidence_vocab.py.
Deterministic; normalized through the alias map + ESCO labels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from engine.generation import kb_loader
from engine.generation.normalize import normalize_all, normalize_skill


@dataclass
class ClaimableSet:
    kb_skills: list[str] = field(default_factory=list)          # ownable, evidence-backed
    jd_tools: list[str] = field(default_factory=list)           # mirrorable only, never ownable
    required: list[str] = field(default_factory=list)           # normalized JD requirements
    preferred: list[str] = field(default_factory=list)
    languages_required: list[dict] = field(default_factory=list)
    per_experience: dict[str, list[str]] = field(default_factory=dict)   # exp id -> allowed skills
    per_project: dict[str, list[str]] = field(default_factory=dict)      # project id -> allowed skills
    keywords: list[str] = field(default_factory=list)            # job-ad target keywords (printable)

    def ownable(self) -> set[str]:
        """Lowercased set of KB-licensed skills (the G2 'ownable' universe)."""
        keys = {s.lower() for s in self.kb_skills}
        for skills in self.per_experience.values():
            keys |= {s.lower() for s in skills}
        for skills in self.per_project.values():
            keys |= {s.lower() for s in skills}
        return keys

    def mirrorable(self) -> set[str]:
        return {t.lower() for t in self.jd_tools}

    def mentionable(self) -> set[str]:
        """Everything the generator may print as a technology token."""
        return self.ownable() | self.mirrorable() | {k.lower() for k in self.keywords}


def _clean_tools(tools: list[str]) -> list[str]:
    """Sanitize analyst tool names: strip punctuation, drop junk.

    Drops: pure numbers and percents ("70 %"), year-like tokens, units/currencies,
    and anything over 30 chars. Tools are MENTION-licensed only, so being strict
    here costs nothing and keeps the claimable set clean (V6 lesson).
    """
    drop_re = re.compile(r"^(\d+(?:[.,]\d+)?\s*%?|\d{4}|[\d\s+%.,/-]+|[€$£]|full time|part time)$", re.IGNORECASE)
    out: list[str] = []
    for tool in tools:
        tool = (tool or "").strip().strip(".,;:+*")
        if not tool or len(tool) > 30:
            continue
        if drop_re.match(tool):
            continue
        # must contain at least one letter (drops "2024", "70 %", "---")
        if not re.search(r"[a-zA-Z]", tool):
            continue
        out.append(tool)
    return out


def build_claimable_set(analysis_dict: dict, kb: dict, keywords: list[str] | None = None) -> ClaimableSet:
    """Assemble the per-job claimable set from the analyst JSON + the KB.

    `keywords` = the job's keyword-plan targets (generation/keywords.py); they join
    the printable universe so G2 never blocks a term the job ad asks for.
    """
    vocabulary = set(kb_loader.global_skill_names(kb))

    tools = normalize_all(_clean_tools(analysis_dict.get("tools", [])), vocabulary=None)
    # Drop tools that normalize into KB skills — they are ownable, not just mirrorable.
    kb_names = kb_loader.global_skill_names(kb)
    kb_keys = {s.lower() for s in kb_names}
    mirrorable_only: list[str] = []
    for tool in tools:
        if tool.lower() in kb_keys:
            continue
        mirrorable_only.append(tool)

    cset = ClaimableSet(
        kb_skills=kb_names,
        jd_tools=mirrorable_only,
        required=normalize_all(analysis_dict.get("required", []), vocabulary),
        preferred=normalize_all(analysis_dict.get("preferred", []), vocabulary),
        languages_required=analysis_dict.get("languages_required", []) or [],
        keywords=[str(k) for k in (keywords or []) if str(k).strip()],
    )

    for exp in kb_loader.experiences(kb):
        allowed = exp.get("skills_allowed", [])
        cset.per_experience[exp["id"]] = normalize_all(allowed, vocabulary)

    for proj in kb_loader.projects(kb):
        allowed = proj.get("skills_allowed", [])
        cset.per_project[proj["id"]] = normalize_all(allowed, vocabulary)

    return cset


def claimable_summary(cset: ClaimableSet) -> str:
    """Human-readable one-line summary for logs."""
    return (
        f"claimable: {len(cset.kb_skills)} KB skills, {len(cset.jd_tools)} JD tools, "
        f"{len(cset.keywords)} target keywords, "
        f"{len(cset.required)} required, {len(cset.preferred)} preferred, "
        f"languages: {[(l['language'], l.get('level')) for l in cset.languages_required]}"
    )


def normalize_skill_public(term: str) -> str:
    """Re-export for orchestrator convenience."""
    return normalize_skill(term)
