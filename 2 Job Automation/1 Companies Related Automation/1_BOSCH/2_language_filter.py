"""
Language Differentiator for Bosch job postings (step 2 of the Bosch pipeline)
-----------------------------------------------------------------------------
Classifies each job in BOSCH_jobs_detailed.csv by whether a non-German-speaking
(English-only) applicant can realistically apply.

Same rule-based method as the SAP FETCHER pipeline (2_language_differntiate.py),
adapted to the Bosch CSV schema (title / description_text instead of
Job Title / Description):

    ENGLISH_OK      - English wanted, or German only "a plus"/basic/or-choice,
                      or German mentioned without any requirement strength
    GERMAN_REQUIRED - hard German requirement: a strength/level/requirement
                      word near a German mention (fluent, fließend, sehr gute,
                      B2/C1, required, "is a must", ...) incl. bilingual
                      requirements ("Fluent in German and English",
                      "Fließend in Deutsch und Englisch")
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
    * Every decision stores the exact evidence sentence in the CSV.

Use:
    python 2_language_differntiate.py
    (or) importlib.import_module("2_language_differntiate").classify_jobs()
"""

import csv
import re
from pathlib import Path

INPUT_CSV = Path(__file__).resolve().parent / "BOSCH_jobs_detailed.csv"  # next to this script, CWD-independent

# Bosch CSV column names (schema of 1_BOSCH_Jobs_fetching.py)
TITLE_COLUMN = "title"
DESCRIPTION_COLUMN = "description_text"

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
    r"fluen\w*",                       # fluent, fluency, fließend handled below
    r"flie[sß]+end\w*",
    r"excellent", r"advanced", r"proficient",
    r"sehr\s+gut\w*", r"very\s+good", r"\bgood\b", r"\bgut\w*",
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
]]

# Proximity windows (chars) around a German mention
PRE_WINDOW = 80   # strength word shortly BEFORE the mention
#                  (80 covers "Strong written and verbal communication skills in English and German")
POST_WINDOW = 40  # strength/requirement word shortly AFTER the mention
LEVEL_WINDOW = 15  # CEFR level right after the mention

SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n")

# Abbreviations whose period must NOT end a sentence ("min. C1" etc.)
_ABBREVIATIONS = ["min.", "max.", "ca.", "e.g.", "i.e.", "etc.", "z.B.",
                  "z. B.", "bzw.", "ggf.", "u.a.", "evtl.", "Nr."]


def _sentences(text: str) -> list[str]:
    # mask abbreviation periods so "German (min. C1)" stays one sentence
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


def classify_job(row: dict) -> dict:
    """Add Language_Filter + Filter_Evidence columns to one CSV row dict."""
    bucket, evidence = classify_description(row.get(DESCRIPTION_COLUMN, ""))

    # Title hint is a strong override: explicit "(DE)"/"German" programs want German
    if bucket != "GERMAN_REQUIRED" and re.search(r"\bGER\b|\(DE\)", row.get(TITLE_COLUMN, ""), re.I):
        bucket, evidence = "GERMAN_REQUIRED", f"title hint: {row.get(TITLE_COLUMN, '')}"

    row["Language_Filter"] = bucket
    row["Filter_Evidence"] = evidence.replace("\n", " ")[:300]
    return row


def classify_jobs(csv_path: str | Path = INPUT_CSV) -> list[dict]:
    """Classify every job in the CSV (in place on disk) and return the rows."""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    for extra in ("Language_Filter", "Filter_Evidence"):
        if extra not in fieldnames:
            fieldnames.append(extra)

    rows = [classify_job(r) for r in rows]

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    from collections import Counter

    result = classify_jobs()
    counts = Counter(r["Language_Filter"] for r in result)

    print(f"Classified {len(result)} jobs -> {INPUT_CSV}\n")
    for bucket in ("ENGLISH_OK", "GERMAN_REQUIRED", "UNSURE"):
        print(f"{bucket} ({counts[bucket]}):")
        for r in result:
            if r["Language_Filter"] == bucket:
                print(f"  - {r.get(TITLE_COLUMN, '')[:70]}")
        print()
