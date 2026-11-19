"""Skill normalization: alias map + ESCO labels -> canonical skill vocabulary.

Deterministic and free (V1 topic 3): no embeddings (killed by V5 measurement).
Resolution order (V6/V7): exact -> alias map -> ESCO preferred/alt labels ->
rapidfuzz token_set_ratio >= 92 against a combined candidate vocabulary.
"""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from resume_content_improve_research import config


def _norm(text: str) -> str:
    """Lowercase, strip punctuation to spaces, collapse whitespace."""
    text = re.sub(r"[^\w\s+.#-]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def load_alias_map() -> dict[str, str]:
    """Return {alias_lower -> canonical} from alias_map.json (build order matters)."""
    if not config.ALIAS_MAP_PATH.exists():
        return {}
    data = json.loads(config.ALIAS_MAP_PATH.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for canonical, aliases in data.get("aliases", {}).items():
        mapping[_norm(canonical)] = canonical
        for alias in aliases:
            mapping[_norm(alias)] = canonical
    return mapping


@lru_cache(maxsize=1)
def _esco_labels() -> dict[str, str]:
    """Return {normalized esco label or alt-label -> preferred label} from the local dump."""
    path = config.ESCO_DIR / "skills_en.csv"
    if not path.exists():
        return {}
    labels: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            preferred = (row.get("preferredLabel") or "").strip()
            if not preferred or len(preferred) > 40:
                continue  # long phrases are useless as skill tokens
            key = _norm(preferred)
            labels.setdefault(key, preferred)
            for alt in (row.get("altLabels") or "").splitlines():
                alt = alt.strip()
                if alt and len(alt) <= 40:
                    labels.setdefault(_norm(alt), preferred)
    return labels


@lru_cache(maxsize=1)
def esco_vocabulary() -> frozenset[str]:
    """The set of ESCO preferred labels (used as an advisory vocabulary)."""
    return frozenset(_esco_labels().values())


def _fuzzy_best(term: str, vocabulary: set[str]) -> str | None:
    """Return the closest vocabulary entry with token_set_ratio >= 92, else None."""
    best, best_score = None, 0
    for candidate in vocabulary:
        score = fuzz.token_set_ratio(term, candidate)
        if score > best_score:
            best, best_score = candidate, score
    return best if best_score >= config.COVERAGE_FUZZY_THRESHOLD else None


def normalize_skill(term: str, vocabulary: set[str] | None = None) -> str:
    """Canonicalize one skill term deterministically.

    Order: exact vocabulary hit -> alias map -> fuzzy >= 92 -> lowercase echo.
    """
    term = (term or "").strip()
    if not term:
        return ""
    key = _norm(term)
    if not key:
        return ""
    if vocabulary and key in {_norm(v) for v in vocabulary}:
        for v in vocabulary:
            if _norm(v) == key:
                return v
    alias = load_alias_map().get(key)
    if alias:
        return alias
    if vocabulary:
        fuzzy = _fuzzy_best(key, vocabulary)
        if fuzzy:
            return fuzzy
    return key


def normalize_all(terms: list[str], vocabulary: set[str] | None = None) -> list[str]:
    """Normalize a list, preserving order, dropping empties and duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        canonical = normalize_skill(term, vocabulary)
        if canonical and canonical.lower() not in seen:
            seen.add(canonical.lower())
            out.append(canonical)
    return out
