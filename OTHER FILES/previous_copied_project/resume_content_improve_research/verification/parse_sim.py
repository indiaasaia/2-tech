"""Parser simulation over the built PDF (FINAL_MODEL 3.1 step 8).

Port of the empirical_parser_test heuristics (OpenResume-style line grouping +
EU/German regexes). The coverage scorer and the G1 gate both run on THIS text —
never on the intent JSON (V5: intent and artifact can differ).

Section-title detection is strict: a title is a SHORT line that IS the keyword
(case/punctuation-insensitive). A sentence ending like "... skills and
experience." is prose, and "Tools: Airflow, Excel" is a value line — neither is
a section title (measured false positives on the 21-job run: "experience.",
"data-driven experience.", "skills and experience." were all detected as
titles and one resume even lost parse-fidelity points to it).

Contact checks are context-aware: an email/phone pattern must be found on a
HEADER line (the first few lines, where a resume prints it). A skill value like
"jdoe@tools.dev" inside a Tools section no longer counts as contact extraction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pdfplumber

EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
PHONE_EU_RE = re.compile(r"\+?\d[\d\s\-/()]{6,}\d")
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
APOSTROPHE_YEAR_RE = re.compile(r"\b[A-Z][a-z]{2}[’']\d{2}\b")
LIGATURE_RE = re.compile("[\ufb00-\ufb06]")

SECTION_KEYWORDS = [
    "career objective", "objective", "experience", "education", "projects",
    "main projects", "additional projects", "research", "achievements", "skills",
    "certifications", "languages", "declaration", "publications",
    "research and publications",
]

# Section titles live in the page header area of this one-page template; the
# first N lines (name + contact block) are never title candidates.
_HEADER_LINES = 4


def _is_section_title(line_text: str) -> bool:
    """True only when the line IS a section title (short, keyword-shaped).

    Accepts 'Experience', 'MAIN PROJECTS', 'Research and Publications';
    rejects sentences ('skills and experience.') and 'label: value' lines
    ('Tools: Airflow, Excel'). The trailing period on 'experience.' is prose
    punctuation — titles in this template carry none — so punctuation is kept
    in the normalized form and only spaces are collapsed.
    """
    stripped = line_text.strip()
    if not stripped or ":" in stripped:
        return False
    if len(stripped) > 40:
        return False
    if _count_words(stripped) > 4:
        return False
    normalized = re.sub(r"\s+", " ", stripped.lower()).strip()
    if not normalized:
        return False
    return normalized in SECTION_KEYWORDS


def _count_words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text) if w])


def _header_text(text: str) -> str:
    return "\n".join(text.splitlines()[:_HEADER_LINES])


@dataclass
class ParseResult:
    text: str
    word_count: int = 0
    lines: list[dict] = field(default_factory=list)
    name_extracted: bool = False
    email_extracted: bool = False
    phone_extracted: bool = False
    dates_found: list[str] = field(default_factory=list)
    apostrophe_dates: list[str] = field(default_factory=list)
    sections_found: list[str] = field(default_factory=list)
    ligature_count: int = 0
    reading_order_ok: bool = True


def extract_lines(page) -> list[dict]:
    """Group words into lines by y-position, like a text-order parser."""
    words = page.extract_words(extra_attrs=["fontname", "size"])
    lines: dict[float, list] = {}
    for w in words:
        key = round(w["top"] / 3.0)
        lines.setdefault(key, []).append(w)
    result = []
    for key in sorted(lines):
        ws = sorted(lines[key], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws)
        bold = any("bold" in (w.get("fontname") or "").lower() for w in ws)
        result.append({"text": text, "bold": bold})
    return result


def parse_pdf(pdf_path) -> ParseResult:
    """Extract everything the simulated ATS parser would see (dataclass above)."""
    result = ParseResult(text="")
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = pdf.pages
        result.text = "\n".join(p.extract_text() or "" for p in pages)
        words = [w for p in pages for w in p.extract_words(extra_attrs=["fontname", "size"])]
        result.word_count = len(words)
        result.lines = [ln for p in pages for ln in extract_lines(p)]
    text = result.text
    header = _header_text(text)
    result.name_extracted = "RAVAL" in text
    # Context-aware PII: only header-area matches count as contact extraction.
    result.email_extracted = bool(EMAIL_RE.search(header))
    result.phone_extracted = bool(PHONE_EU_RE.search(header))
    result.dates_found = sorted(set(YEAR_RE.findall(text)))
    result.apostrophe_dates = APOSTROPHE_YEAR_RE.findall(text)
    result.ligature_count = len(LIGATURE_RE.findall(text))

    for ln in result.lines:
        if _is_section_title(ln["text"]):
            result.sections_found.append(ln["text"].strip())

    idx_name = text.find("RAVAL")
    idx_obj = text.lower().find("career objective")
    result.reading_order_ok = (0 <= idx_name < idx_obj) if idx_obj >= 0 else idx_name == 0
    return result
