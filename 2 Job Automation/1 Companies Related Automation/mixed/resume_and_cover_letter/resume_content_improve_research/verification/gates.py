"""Deterministic gates G1-G3 (FINAL_MODEL 3.2) — fail = never ship.

G1 parse sanity: word count 200-800, name/contact/sections extractable.
G2 hallucination: every tech token in the claimable set; every digit (incl.
   spelled-out) KB-licensed; titles within titles_allowed.
G3 artifact integrity: no leftover tokens, no legacy placeholder prefixes,
   dates use four-digit years, no corrupted section titles, ligature-free.

Measured justification: V3 (scshape/date corruption), V4 (21/21 collision bug),
V5 (154-word segmentation collapse), V6 (201 G2 findings, "thirty percent" evasion).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SPELL_NUMBERS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20",
    "twenty-five": "25", "thirty": "30", "forty": "40", "fifty": "50",
    "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
    "hundred": "100",
}

# Small counts that carry no metric meaning (e.g. "three languages", "two stints",
# "four skill rows"). The digit rule targets METRIC-shaped numbers (measurements,
# percentages, sizes); single digits in prose are not a fabrication vector — the
# KB's licensed metrics are all two-digit (40+ stars, 24+ forks, 70 accuracy).
# Two-digit numbers stay fully gated (V6's "thirty percent" evasion must never pass).
SMALL_COUNT_LIMIT = 9

TECH_TOKEN_RE = re.compile(
    r"\b(python|java|javascript|typescript|c\+\+|c#|sql|mysql|postgres(?:ql)?|mongodb|redis|"
    r"docker|kubernetes|k8s|aws|azure|gcp|git|jenkins|react|angular|vue|node\.?js|next\.?js|spring|"
    r"fastapi|django|flask|streamlit|tensorflow|pytorch|sklearn|scikit-learn|pandas|numpy|spark|hadoop|"
    r"kafka|airflow|tableau|power\s?bi|excel|sap|salesforce|hubspot|jira|confluence|linux|bash|"
    r"etl|erp|crm|hris|rexx|rest|graphql|api|apis|nlp|nlp s|llm|llms|transformers|hugging\s?face|"
    r"agile|scrum|kanban|ci|cd|latex|matlab|vba|flutter|react-native|css|html|tailwind|"
    r"tensorflow|mxnet|xgboost|lightgbm|selenium|playwright|cypress|terraform|ansible)\b",
    re.IGNORECASE,
)

SECTION_KEYWORDS = [
    "career objective", "experience", "education", "main projects", "research", "achievements",
    "skills", "certifications", "languages", "declaration", "publications", "additional projects",
]

CORRUPT_TITLE_MARKERS = ("AREER BJECTIVE", "E XPERIENCE", "E DUCATION", "KILLS", "M AIN", "ESEARCH")


@dataclass
class GateResult:
    gate: str
    passed: bool
    findings: list[str] = field(default_factory=list)


def _numbers_in_text(text: str) -> list[str]:
    """All digit strings + spelled-out numbers used with percent/count/plus framing."""
    found = [m.group(0) for m in re.finditer(r"\d+(?:\.\d+)?", text)]
    for word in SPELL_NUMBERS:
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            found.append(SPELL_NUMBERS[word])
    return found


def _number_occurrences(text: str):
    """Return numeric values with spans so exemptions apply to the right occurrence."""
    for match in re.finditer(r"\d+(?:\.\d+)?", text):
        yield match.group(0), match.start(), match.end()
    for word, number in SPELL_NUMBERS.items():
        for match in re.finditer(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            yield number, match.start(), match.end()


def _is_product_version(text: str, number: str, start: int) -> bool:
    """Known product suffixes are identifiers, not candidate performance metrics."""
    if number != "365":
        return False
    prefix = text[max(0, start - 24):start]
    return re.search(r"\b(?:microsoft|ms|office|dynamics)\s*$", prefix, re.IGNORECASE) is not None


def _is_work_schedule(text: str, number: str, end: int) -> bool:
    """A small hours-per-week contract figure is not a candidate achievement."""
    try:
        if float(number) > 40:
            return False
    except ValueError:
        return False
    return re.match(r"\s*(?:hours?|hrs?|stunden|h\b)", text[end:end + 15], re.IGNORECASE) is not None


def check_g2_claims(text: str, cset, licensed_digits: set[str]) -> list[str]:
    """G2 on the generated INTENT text (claims) — tech tokens + digit rule + titles."""
    from resume_content_improve_research.generation.normalize import normalize_skill

    findings: list[str] = []
    mentionable = cset.mentionable()
    normalized_mentionable = {normalize_skill(item).lower() for item in mentionable}

    for match in TECH_TOKEN_RE.finditer(text):
        token = match.group(0).lower().replace(" ", "")
        # normalize composite spellings and plurals before the set check
        token = {
            "node.js": "nodejs", "nodejs": "nodejs", "next.js": "nextjs",
            "scikit-learn": "scikit-learn", "k8s": "kubernetes",
            "llms": "llm", "apis": "api", "nlp s": "nlp",
        }.get(token, token)
        candidates = {token}
        singular = token[:-1] if token.endswith("s") and len(token) > 3 else token
        candidates.add(singular)
        canonical = normalize_skill(match.group(0)).lower()
        candidates.add(canonical)
        if candidates & mentionable or candidates & normalized_mentionable:
            continue
        # containment fallback for multi-word entries (e.g. 'api' ⊂ 'api integration');
        # only for tokens long enough to avoid nonsense hits like 'ci' ⊂ 'circular'
        if len(token) >= 4 and any(token in item or item in token for item in mentionable):
            continue
        findings.append(f"G2: tech token {match.group(0)!r} is not in the claimable set")

    for number, start, end in _number_occurrences(text):
        normalized = number.lstrip("0") or "0"
        if _is_product_version(text, normalized, start):
            continue  # e.g. Microsoft 365 / Office365 is a JD tool name, not a metric
        if normalized not in licensed_digits and not re.match(r"^(19|20)\d{2}$", normalized):
            try:
                if float(normalized) <= SMALL_COUNT_LIMIT:
                    continue  # prose counts ("three languages") are not metrics
            except ValueError:
                pass
            # Working-hour schedules (e.g. "20 hours per week") are JD contract
            # facts, not candidate performance metrics. Use this occurrence's
            # span (including spelled-out values) instead of searching the text
            # for its first matching digits, which could be inside a year.
            if _is_work_schedule(text, number, end):
                continue
            findings.append(f"G2: number {number!r} is not KB-licensed")

    for match in re.finditer(r"\b([a-z ]+)\s+percent\b", text, re.IGNORECASE):
        findings.append(f"G2: spelled-out percent phrase {match.group(0)!r} (percentages are never claimable)")
    for match in re.finditer(r"\b\d+(?:\.\d+)?\s*%", text):
        findings.append(f"G2: percentage {match.group(0)!r} not claimable (V4: 35 fabricated metrics)")
    return findings


def check_g2_titles(experiences: list[dict]) -> list[str]:
    """Titles must be within the KB's titles_allowed for that entry."""
    findings: list[str] = []
    for entry in experiences:
        exp_id = str(entry.get("id", ""))
        role = str(entry.get("role", "")).lower()
        kb_exp = next((e for e in _kb_experience_list() if e.get("id") == exp_id), None)
        if kb_exp is None:
            findings.append(f"G2: experience id {exp_id!r} is not in the KB")
            continue
        allowed = [t.lower() for t in kb_exp.get("titles_allowed", [])]
        if role not in allowed:
            findings.append(f"G2: title {entry.get('role')!r} not in titles_allowed {allowed}")
        for pattern in kb_exp.get("titles_forbidden_patterns", []):
            if re.search(pattern, role):
                findings.append(f"G2: title {entry.get('role')!r} matches forbidden pattern {pattern!r}")
    return findings


_KB_CACHE: dict | None = None


def _kb_experience_list() -> list[dict]:
    global _KB_CACHE
    if _KB_CACHE is None:
        from resume_content_improve_research import config as cfg
        from resume_content_improve_research.generation import kb_loader
        _KB_CACHE = kb_loader.load_kb()
    return _KB_CACHE.get("experience", [])


def check_g3_text(text: str) -> list[str]:
    """G3 on the FILLED TEMPLATE text (artifact integrity, pre-compile)."""
    findings: list[str] = []
    if "@@" in text:
        findings.append("G3: leftover @@ tokens in filled template")
    # V4's one-line killer assert, verbatim: the replacement-order collision shipped
    # a literal PROJECT- prefix into 21/21 PDFs and no digit is required to detect it.
    if "PROJECT-" in text:
        findings.append("G3: literal 'PROJECT-' in text (replacement-order collision class)")
    if re.search(r"\b(SKILLS|DESCRIPTION|ROLE|CAREER)-\d", text):
        findings.append("G3: legacy placeholder prefix leaked (V4 collision class)")
    if "SKILLS AREA" in text:
        findings.append("G3: unfilled SKILLS AREA label")
    if re.search(r"[A-Z][a-z]{2}[’']\d{2}\b", text):
        findings.append("G3: apostrophe-year date present (Dec'23 style; parser-invisible)")
    for marker in CORRUPT_TITLE_MARKERS:
        if marker in text:
            findings.append(f"G3: corrupted section title marker {marker!r}")
    ligatures = sum(text.count(c) for c in ("\ufb00", "\ufb01", "\ufb02", "\ufb03", "\ufb04"))
    if ligatures:
        findings.append(f"G3: {ligatures} ligature glyphs present")
    return findings


def check_g1(pdf_text: str, word_count: int) -> list[str]:
    """G1 on the PARSED-BACK artifact (post-compile)."""
    findings: list[str] = []
    if word_count < 200 or word_count > 800:
        findings.append(f"G1: word count {word_count} outside 200-800 (segmentation/corruption?)")
    if "RAVAL" not in pdf_text:
        findings.append("G1: name not extractable")
    if not re.search(r"\S+@\S+\.\S+", pdf_text):
        findings.append("G1: email not extractable")
    if not re.search(r"\+?\d[\d\s\-/()]{6,}\d", pdf_text):
        findings.append("G1: phone not extractable (EU regex)")
    found_sections = [kw for kw in SECTION_KEYWORDS if kw in pdf_text.lower()]
    if len(found_sections) < 6:
        findings.append(f"G1: only {len(found_sections)} sections detectable")
    return findings


def run_prebuild_gates(intent_text: str, experiences: list[dict], cset, licensed_digits: set[str]) -> list[GateResult]:
    """G2 (claims + titles) and G3 (filled text) before compilation."""
    g2 = GateResult("G2", True, [])
    findings = check_g2_claims(intent_text, cset, licensed_digits)
    findings += check_g2_titles(experiences)
    g2.passed = not findings
    g2.findings = findings
    g3 = GateResult("G3", True, check_g3_text(intent_text))
    return [g2, g3]


def run_postbuild_gates(pdf_text: str, word_count: int, filled_text: str) -> list[GateResult]:
    """G1 on the parsed-back PDF plus the artifact-side of G3."""
    g1 = GateResult("G1", True, check_g1(pdf_text, word_count))
    g3 = GateResult("G3", True, check_g3_text(filled_text))
    return [g1, g3]
