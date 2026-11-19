"""Truthful per-entry vocabulary: which job-ad keywords may describe a REAL entry.

Policy (plan v3 §3.2): every job-ad keyword goes into the Skills section, but a
keyword appears in an experience/project bullet or skill row ONLY when that
entry's KB evidence already describes the work. The allowed vocabulary of an
entry is:
  - its skills_allowed pool,
  - KB global skills whose evidence cites the entry,
  - truthful rewordings of those skills (knowledge_base/evidence_synonyms.json),
  - lexicon terms literally present in its evidence lines,
minus anything in its skills_forbidden list. Deterministic, zero LLM calls.
"""
from __future__ import annotations

import json
from functools import lru_cache

from engine import config
from engine.generation import kb_loader
from engine.generation.keywords import _norm_key, sweep

SYNONYMS_PATH = config.KB_DIR / "evidence_synonyms.json"

# Keyword categories that never describe a tool claim inside an entry.
_NON_CLAIM_CATEGORIES = {"soft_skills", "education_field", "domain"}


@lru_cache(maxsize=1)
def _synonyms() -> dict[str, tuple[str, ...]]:
    data = json.loads(SYNONYMS_PATH.read_text(encoding="utf-8"))
    return {_norm_key(k): tuple(v) for k, v in data.get("synonyms", {}).items()}


@lru_cache(maxsize=2048)
def _keys_for(term: str) -> frozenset[str]:
    """Normalized keys a term is known by: itself plus its lexicon canonical form."""
    keys = {_norm_key(term)}
    for hit in sweep(term):
        keys.add(_norm_key(hit["canonical"]))
        keys.add(_norm_key(hit["term"]))
    return frozenset(k for k in keys if k)


@lru_cache(maxsize=2048)
def _whole_keys(term: str) -> frozenset[str]:
    """Keys of the WHOLE term only: itself plus the canonical of a lexicon hit that
    spans the entire term ("AI assistants" must not pass because "AI" does)."""
    own = _norm_key(term)
    keys = {own}
    for hit in sweep(term):
        if _norm_key(hit["term"]) == own:
            keys.add(_norm_key(hit["canonical"]))
    return frozenset(k for k in keys if k)


def find_entry(kb: dict, entry_id: str) -> dict:
    """The experience/project/research entry with this id ({} when unknown)."""
    for entry in kb_loader.experiences(kb) + kb.get("projects", []) + kb_loader.research(kb):
        if str(entry.get("id") or "") == str(entry_id):
            return entry
    return {}


def allowed_keys(entry: dict, kb: dict) -> set[str]:
    """Normalized keys of every term that truthfully describes this entry."""
    entry_id = str(entry.get("id") or "")
    terms = [str(t) for t in entry.get("skills_allowed") or []]
    for skill in kb_loader.global_skills(kb):
        cited = {str(e).split()[0] for e in skill.get("evidence", []) if str(e).strip()}
        if entry_id and entry_id in cited:
            terms.append(str(skill.get("name") or ""))
    keys: set[str] = set()
    for term in terms:
        keys |= _keys_for(term)
        for synonym in _synonyms().get(_norm_key(term), ()):
            keys |= _keys_for(synonym)
    for line in entry.get("evidence") or []:
        for hit in sweep(str(line)):
            keys.add(_norm_key(hit["canonical"]))
            keys.add(_norm_key(hit["term"]))
    forbidden: set[str] = set()
    for term in entry.get("skills_forbidden") or []:
        forbidden |= _keys_for(str(term))
    return {k for k in keys if k} - forbidden


def entry_keywords(entry: dict, kb: dict, plan: dict | None) -> list[str]:
    """The job's target keywords that truthfully describe this entry (plan order)."""
    if not plan or not entry:
        return []
    allowed = allowed_keys(entry, kb)
    out: list[str] = []
    for keyword in plan.get("keywords") or []:
        if keyword.get("category") in _NON_CLAIM_CATEGORIES:
            continue
        keys = _whole_keys(str(keyword.get("term") or "")) | _whole_keys(str(keyword.get("canonical") or ""))
        if keys & allowed and keyword["term"] not in out:
            out.append(str(keyword["term"]))
    return out


def vocabulary_violations(text: str, entry: dict, kb: dict, plan: dict | None = None) -> list[str]:
    """Tool/method terms in `text` that this entry's evidence does not support.

    Checks lexicon terms AND, with a plan, every job keyword (free phrases such as
    "AI assistants" are not in the lexicon: measured 2026-10-17, the live LLM wrote
    "Implemented AI assistants by developing ML models for text-to-speech").
    """
    if not entry:
        return []
    allowed = allowed_keys(entry, kb)
    bad: list[str] = []
    for hit in sweep(text or ""):
        if hit["category"] in _NON_CLAIM_CATEGORIES:
            continue
        if _norm_key(hit["canonical"]) in allowed or _norm_key(hit["term"]) in allowed:
            continue
        if hit["term"] not in bad:
            bad.append(hit["term"])
    if plan:
        import re

        lowered = " ".join(str(text or "").lower().split())
        for keyword in plan.get("keywords") or []:
            if keyword.get("category") in ("soft_skills", "education_field"):
                continue
            term = str(keyword.get("term") or "")
            pattern = r"(?<![a-z0-9+#])" + re.escape(term.lower()) + r"(?![a-z0-9+#])"
            if not term or not re.search(pattern, lowered):
                continue
            keys = _whole_keys(term) | _whole_keys(str(keyword.get("canonical") or ""))
            if keys & allowed or term in bad:
                continue
            bad.append(term)
    return bad
