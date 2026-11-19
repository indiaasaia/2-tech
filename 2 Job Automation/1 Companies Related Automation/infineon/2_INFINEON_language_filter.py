"""
Language Differentiator for Infineon job postings
-------------------------------------------------
Classifies each Infineon Werkstudent/Working Student job by whether a
non-German-speaking (English-only) applicant can realistically apply.

Method (rule-based, free, deterministic, auditable):
    ENGLISH_OK      - English wanted, or German only "a plus"/basic/or-choice,
                      or German mentioned without any requirement strength
    GERMAN_REQUIRED - hard German requirement: a strength/level/requirement
                      word near a German mention (fluent, fließend, sehr gute,
                      B2/C1, erforderlich, "is a must", ...) incl. bilingual
                      requirements
    UNSURE          - no language signals at all

Key design points:
    * Never judges by the language the description is WRITTEN in - only by
      requirement STATEMENTS inside the text (German or English).
    * Proximity-based, not exact-phrase: catches "Fluent written and verbal
      German", "German and English, both fluent", "Excellent knowledge in
      German", "German (min. C1)", "German at level B2", ...
    * Negation-aware: "keine Deutschkenntnisse erforderlich" / "German is a
      plus" / "basic German" contain "German" but mean NO hard requirement.
    * Either/or aware: "Fluent in German or English" = English alone suffices.
    * Every decision stores the exact evidence sentence in the output.

Use (from 2_MERCEDES_create_resumes.py):
    importlib.import_module("2_MERCEDES_language_filter").classify_rows(records)

Or run directly on the detailed CSV:
    python 2_MERCEDES_language_filter.py
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

INPUT_CSV = Path(__file__).resolve().parent / "INFINEON_jobs_detailed.csv"

# ---------------------------------------------------------------- keywords ---

# German / English mentions
GERMAN_MENTION = re.compile(r"\b(?:german|deutsch\w*)\b", re.I)
ENGLISH_MENTION = re.compile(r"\b(?:english|englisch\w*)\b", re.I)

# Either/or requirement: "Fluent in German or English" = English suffices
OR_PATTERN = re.compile(
    r"\b(?:german|deutsch\w*)\s+(?:or|oder)\s+(?:english|englisch\w*)\b"
    r"|\b(?:english|englisch\w*)\s+(?:or|oder)\s+(?:german|deutsch\w*)\b", re.I)

# Strength words: fluency/quality claims that make a language a REQUIREMENT
STRENGTH_RE = [re.compile(p, re.I) for p in [
    r"fluen\w*",                       # fluent, fluency
    r"flie[sß]+end\w*",
    r"excellent", r"advanced", r"proficient",
    r"sehr\s+gut\w*", r"very\s+good", r"\bgood\b", r"\bgut\w*\b",
    r"verhandlungssicher", r"business[- ]?fluent",
    r"muttersprachl\w*", r"\bnative\b",
    r"\bstrong\b", r"\bstark\w*\b",
]]

# Requirement words expected AFTER a German mention
REQ_AFTER_RE = re.compile(
    r"\b(?:required|erforderlich\w*|vorausgesetzt|voraussetzung|gesetzt|must)\b", re.I)

# CEFR level expected shortly AFTER a German mention ("German (min. C1)")
LEVEL_AFTER_RE = re.compile(r"\b(?:c[12]|b[2-9])\b", re.I)

# Softeners: the mention is NOT a hard requirement
SOFTENER_RE = [re.compile(p, re.I) for p in [
    r"keine?", r"nicht\s+(?:erforderlich|zwingend|vorausgesetzt)",
    r"no\s+(?:german|fluency|language)\b", r"not\s+(?:required|necessary|mandatory)",
    r"(?:a|an)\s+(?:plus|asset|advantage|bonus)", r"von\s+vorteil", r"willkommen",
    r"willing\s+to\s+learn", r"gerne\w*", r"nice\s+to\s+have", r"desired\b",
    r"helpful\b", r"beneficial\b", r"erw\u00fcnscht",
    r"(?:basic|beginner)\s+(?:german|deutsch\w*)",      # basic German
    r"(?:german|deutsch\w*)\s+basic",                   # German basic knowledge
    r"grundkenntnisse\w*",                              # Grundkenntnisse
    r"\ba1\b|\ba2\b",
    r"von\s+Vorteil",                                   # "von Vorteil" (an advantage)
]]

# Proximity windows (chars) around a German mention
PRE_WINDOW = 80   # strength word shortly BEFORE the mention
POST_WINDOW = 40  # strength/requirement word shortly AFTER the mention
LEVEL_WINDOW = 15  # CEFR level right after the mention

SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n")

# Abbreviations whose period must NOT end a sentence ("min. C1" etc.)
_ABBREVIATIONS = ["min.", "max.", "ca.", "e.g.", "i.e.", "etc.", "z.B.",
                  "z. B.", "bzw.", "ggf.", "u.a.", "evtl.", "Nr."]


def _sentences(text: str) -> list[str]:
    """Split text into sentences; abbreviation periods do not end sentences."""
    for abbr in _ABBREVIATIONS:
        text = text.replace(abbr, abbr.replace(".", "\x00"))
    parts = SENTENCE_SPLIT.split(text)
    return [p.replace("\x00", ".").strip() for p in parts if p.strip()]


def _is_softened(sentence: str) -> bool:
    return any(rx.search(sentence) for rx in SOFTENER_RE)


def _is_hard_german(sentence: str) -> bool:
    """True if a German mention in this sentence carries requirement strength."""
    for m in GERMAN_MENTION.finditer(sentence):
        pre = sentence[max(0, m.start() - PRE_WINDOW):m.start()]
        post = sentence[m.end():m.end() + POST_WINDOW]
        if any(rx.search(pre) for rx in STRENGTH_RE):
            return True
        if any(rx.search(post) for rx in STRENGTH_RE):
            return True
        if REQ_AFTER_RE.search(post):
            return True
        if LEVEL_AFTER_RE.search(sentence[m.end():m.end() + LEVEL_WINDOW]):
            return True
    return False


def classify_description(description: str) -> tuple[str, str]:
    """Classify one description.

    Returns:
        (bucket, evidence) where bucket is ENGLISH_OK / GERMAN_REQUIRED /
        UNSURE and evidence is the decisive sentence ("" if none).
    """
    german_lines, english_lines, or_lines = [], [], []

    for sentence in _sentences(description):
        if OR_PATTERN.search(sentence):
            or_lines.append(sentence)
            continue
        if GERMAN_MENTION.search(sentence):
            german_lines.append(sentence)
        if ENGLISH_MENTION.search(sentence):
            english_lines.append(sentence)

    # --- 1) explicit hard German requirements decide first ------------------
    # (softeners win within a sentence: "No German required" / "keine ... erforderlich"
    #  contain requirement words but negate them)
    hard, softened = [], []
    for s in german_lines:
        if _is_softened(s):
            softened.append(s)
        elif _is_hard_german(s):
            hard.append(s)
    if hard:
        return "GERMAN_REQUIRED", hard[0]

    # --- 2) either/or language choice -> English alone suffices -------------
    if or_lines:
        return "ENGLISH_OK", or_lines[0]

    # --- 3) English statements without any hard German ----------------------
    if english_lines:
        return "ENGLISH_OK", english_lines[0]

    # --- 4) German only as a "plus" / basic / softened -> English-friendly ---
    if softened:
        return "ENGLISH_OK", softened[0]

    # --- 5) nothing said about languages at all ------------------------------
    if not german_lines:
        return "UNSURE", ""

    # --- 6) German mentioned but never with requirement strength -------------
    return "ENGLISH_OK", german_lines[0]


def classify_row(row: dict, text: str | None = None) -> dict:
    """Add Language_Filter + Filter_Evidence to one row dict.

    `text` overrides the row's own description field (the pipeline passes the
    merged title+description text here).
    """
    if text is None:
        text = str(row.get("_lang_text") or row.get("Description")
                   or row.get("job_description") or "")
    bucket, evidence = classify_description(text)

    # Title hint is a strong override: "(DE)" / "Deutsch" programs want German
    title = str(row.get("title") or row.get("Title") or row.get("Job Title") or "")
    if bucket != "GERMAN_REQUIRED" and re.search(r"\(DE\)|\bDE\b|deutsch", title, re.I):
        bucket, evidence = "GERMAN_REQUIRED", f"title hint: {title}"

    row["Language_Filter"] = bucket
    row["Filter_Evidence"] = evidence.replace("\n", " ")[:300]
    return row


def classify_rows(rows: list[dict]) -> list[dict]:
    """Classify every row dict (in place) and return the list."""
    return [classify_row(row) for row in rows]


def _cli() -> int:
    """Classify the detailed CSV in place and print bucket counts."""
    from collections import Counter

    if not INPUT_CSV.exists():
        print(f"[LANG] input not found: {INPUT_CSV}")
        return 1
    with open(INPUT_CSV, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])

    for extra in ("Language_Filter", "Filter_Evidence"):
        if extra not in fieldnames:
            fieldnames.append(extra)

    for row in rows:
        text = f"{row.get('title', '')}\n{row.get('description_text', '')}"
        classify_row(row, text)

    with open(INPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r["Language_Filter"] for r in rows)
    print(f"[LANG] classified {len(rows)} jobs -> {INPUT_CSV}")
    for bucket in ("ENGLISH_OK", "GERMAN_REQUIRED", "UNSURE"):
        print(f"  {bucket}: {counts[bucket]}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(_cli())
