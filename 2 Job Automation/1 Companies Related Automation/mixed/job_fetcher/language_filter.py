"""Rule-based language classifier for job postings across all companies.

Classifies postings into:
    ENGLISH_OK      - English required/welcome, or German only "a plus"/basic/or-choice,
                      or German mentioned without requirement strength
    GERMAN_REQUIRED - hard German requirement: a strength/level/requirement word near
                      a German mention (fluent, fließend, sehr gute, B2/C1, required, "is a must")
    UNSURE          - no language signals found

Key design principles:
    - Never judge by the language the description is written in (often in German, but English is accepted)
    - Proximity-based, negation-aware, either/or-aware
    - Stores the exact evidence sentence for auditability
"""
from __future__ import annotations

import re
from typing import Tuple

GERMAN_MENTION = re.compile(r"\b(?:german|deutsch\w*)\b", re.I)
ENGLISH_MENTION = re.compile(r"\b(?:english|englisch\w*)\b", re.I)

OR_PATTERN = re.compile(
    r"\b(?:german|deutsch\w*)\s+(?:or|oder)\s+(?:english|englisch\w*)\b"
    r"|\b(?:english|englisch\w*)\s+(?:or|oder)\s+(?:german|deutsch\w*)\b",
    re.I,
)

STRENGTH_RE = [
    re.compile(p, re.I)
    for p in [
        r"fluen\w*",
        r"flie[sß]+end\w*",
        r"excellent",
        r"advanced",
        r"proficient",
        r"sehr\s+gut\w*",
        r"very\s+good",
        r"\bgood\b",
        r"\bgut\w*",
        r"verhandlungssicher",
        r"business[- ]?fluent",
        r"muttersprachl\w*",
        r"\bnative\b",
        r"\bstrong\b",
        r"\bstark\w*\b",
    ]
]

REQ_AFTER_RE = re.compile(
    r"\b(?:required|erforderlich\w*|vorausgesetzt|voraussetzung|gesetzt|must)\b",
    re.I,
)
LEVEL_AFTER_RE = re.compile(r"\b(?:c[12]|b[2-9])\b", re.I)

SOFTENER_RE = [
    re.compile(p, re.I)
    for p in [
        r"keine?",
        r"nicht\s+(?:erforderlich|zwingend|vorausgesetzt)",
        r"no\s+(?:german|fluency|language)\b",
        r"not\s+(?:required|necessary|mandatory)",
        r"(?:a|an)\s+(?:plus|asset|advantage|bonus)",
        r"von\s+vorteil",
        r"willkommen",
        r"willing\s+to\s+learn",
        r"gerne\w*",
        r"nice\s+to\s+have",
        r"desired\b",
        r"helpful\b",
        r"beneficial\b",
        r"erwünscht",
        r"(?:basic|beginner)\s+(?:german|deutsch\w*)",
        r"(?:german|deutsch\w*)\s+basic",
        r"grundkenntnisse\w*",
        r"\ba1\b|\ba2\b",
    ]
]

PRE_WINDOW = 80
POST_WINDOW = 60


def _split_into_sentences(text: str) -> list[str]:
    clean = re.sub(r"[\r\n\t]+", " ", text)
    clean = re.sub(r"&nbsp;|&#160;", " ", clean)
    parts = re.split(r"(?<=[.!?•\-])\s+(?=[A-ZÄÖÜa-zäöü])", clean)
    return [p.strip() for p in parts if p.strip()]


def _classify_sentence(sentence: str) -> Tuple[str, str] | None:
    for de_match in GERMAN_MENTION.finditer(sentence):
        start, end = de_match.span()
        pre = sentence[max(0, start - PRE_WINDOW):start]
        post = sentence[end:min(len(sentence), end + POST_WINDOW)]
        window = pre + sentence[start:end] + post

        if OR_PATTERN.search(window):
            return "ENGLISH_OK", sentence

        if any(p.search(window) for p in SOFTENER_RE):
            return "ENGLISH_OK", sentence

        has_strength_pre = any(p.search(pre) for p in STRENGTH_RE)
        has_strength_post = any(p.search(post) for p in STRENGTH_RE)
        has_req_post = bool(REQ_AFTER_RE.search(post))
        has_level_post = bool(LEVEL_AFTER_RE.search(post))

        if has_strength_pre or has_strength_post or has_req_post or has_level_post:
            return "GERMAN_REQUIRED", sentence

        if ENGLISH_MENTION.search(sentence):
            return "ENGLISH_OK", sentence

        return "ENGLISH_OK", sentence

    return None


def classify_text(text: str) -> Tuple[str, str]:
    if not text or not text.strip():
        return "UNSURE", ""

    sentences = _split_into_sentences(text)
    candidate_en_ok: Tuple[str, str] | None = None

    for sentence in sentences:
        if not GERMAN_MENTION.search(sentence) and not ENGLISH_MENTION.search(sentence):
            continue

        result = _classify_sentence(sentence)
        if result is None:
            if ENGLISH_MENTION.search(sentence):
                candidate_en_ok = ("ENGLISH_OK", sentence)
            continue

        label, evidence = result
        if label == "GERMAN_REQUIRED":
            return "GERMAN_REQUIRED", evidence
        if candidate_en_ok is None:
            candidate_en_ok = (label, evidence)

    if candidate_en_ok is not None:
        return candidate_en_ok

    if ENGLISH_MENTION.search(text):
        for s in sentences:
            if ENGLISH_MENTION.search(s):
                return "ENGLISH_OK", s
        return "ENGLISH_OK", "English mentioned in posting"

    return "UNSURE", ""
