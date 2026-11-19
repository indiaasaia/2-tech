"""Empirical ATS-parser simulation test on the pipeline's real generated PDFs.

Applies parser heuristics modeled on published ATS parser behavior (OpenResume's
documented algorithm + common date regexes) to every PDF in
program_files/output/resume/pdf/ and reports concrete extraction failures.

Run: python resume_content_improve_research/empirical_parser_test.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = PROJECT_ROOT / "program_files" / "output" / "resume" / "pdf"
OUT = Path(__file__).resolve().parent / "empirical_parser_results.json"

# --- Parser heuristics (modeled on OpenResume's published algorithm) ---
EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
PHONE_EU_RE = re.compile(r"\+?\d[\d\s\-/()]{6,}\d")
# The core date regex used by ATS-style parsers (OpenResume core: (19|20)\d{2})
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
# Apostrophe-year format the current template emits: Dec'23, Jan'25
APOSTROPHE_YEAR_RE = re.compile(r"\b[A-Z][a-z]{2}'\d{2}\b")
SECTION_KEYWORDS = [
    "career objective", "objective", "experience", "education", "projects",
    "research", "achievements", "skills", "certifications", "languages",
    "declaration", "publications",
]

def extract_lines(page):
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

def analyze(pdf_path: Path) -> dict:
    report: dict = {"file": pdf_path.name, "issues": []}
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages
        text = "\n".join(p.extract_text() or "" for p in pages)
        words = [w for p in pages for w in p.extract_words(extra_attrs=["fontname", "size"])]
        lines = [ln for p in pages for ln in extract_lines(p)]

    report["extracts_text"] = len(text.strip()) > 100
    report["word_count"] = len(words)

    # 1. Name extraction (first bold+uppercase-ish line)
    name_found = "RAVAL" in text
    report["name_extracted"] = name_found
    if not name_found:
        report["issues"].append("name not found in extracted text")

    # 2. Contact extraction
    report["email_extracted"] = bool(EMAIL_RE.search(text))
    report["phone_extracted"] = bool(PHONE_EU_RE.search(text))
    if not report["email_extracted"]:
        report["issues"].append("email not extractable")

    # 3. Date extraction with the STANDARD year regex (19|20)\d{2}
    dates_std = YEAR_RE.findall(text)
    apostrophe_dates = APOSTROPHE_YEAR_RE.findall(text)
    report["dates_std_regex_count"] = len(set(dates_std))
    report["dates_apostrophe_only"] = apostrophe_dates[:6]
    # If experience dates use apostrophe years, standard parsers miss them
    exp_apostrophe = [d for d in apostrophe_dates if d not in text.replace("'", "")]
    if apostrophe_dates:
        report["issues"].append(
            f"{len(apostrophe_dates)} apostrophe-year dates (Dec'23 style) invisible to the standard "
            f"(19|20)\\d{{2}} year regex used by ATS parsers — found: {sorted(set(apostrophe_dates))}"
        )

    # 4. Section detection: bold+ALLCAPS primary heuristic vs keyword fallback
    primary_titles = [
        ln["text"] for ln in lines
        if ln["bold"] and ln["text"].strip().isupper() and len(ln["text"].split()) <= 6
        and len(ln["text"].strip()) > 3
    ]
    kw_titles = []
    for ln in lines:
        t = ln["text"].strip().lower()
        if any(t == k or (k in t and len(t) < len(k) + 15) for k in SECTION_KEYWORDS):
            kw_titles.append(ln["text"].strip())
    report["sections_primary_heuristic"] = primary_titles
    report["sections_keyword_fallback"] = kw_titles
    if len(kw_titles) < 6:
        report["issues"].append(f"only {len(kw_titles)} sections detectable via keyword fallback")
    if not primary_titles:
        report["issues"].append(
            "primary section heuristic (bold+ALLCAPS) matched nothing — parser relies on keyword fallback"
        )

    # 5. Skills findable in extracted text (sample of KB skills)
    kb_probe = ["python", "mysql", "django", "flask", "sql", "llm", "nlp", "kubernetes"]
    found = [s for s in kb_probe if re.search(rf"\b{re.escape(s)}\b", text, re.IGNORECASE)]
    report["kb_probe_found"] = found
    report["kb_probe_missing"] = [s for s in kb_probe if s not in found]

    # 6. Reading order sanity: does the name appear before the objective?
    idx_name = text.find("RAVAL")
    idx_obj = text.lower().find("career objective")
    report["reading_order_ok"] = 0 <= idx_name < idx_obj if idx_obj >= 0 else idx_name == 0
    if not report["reading_order_ok"]:
        report["issues"].append("reading-order problem: name not before first section")

    return report

def main() -> int:
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print("no PDFs found — run step 5 first")
        return 1
    results = [analyze(p) for p in pdfs]
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    n = len(results)
    agg = {
        "pdfs_tested": n,
        "name_ok": sum(1 for r in results if r["name_extracted"]),
        "email_ok": sum(1 for r in results if r["email_extracted"]),
        "phone_ok": sum(1 for r in results if r["phone_extracted"]),
        "reading_order_ok": sum(1 for r in results if r["reading_order_ok"]),
        "apostrophe_date_files": sum(1 for r in results if r["dates_apostrophe_only"]),
        "primary_section_heuristic_hits": sum(1 for r in results if r["sections_primary_heuristic"]),
    }
    print("=== EMPIRICAL PARSER SIMULATION (real generated PDFs) ===")
    for k, v in agg.items():
        print(f"  {k}: {v}/{n}")
    print("\n=== ISSUE FREQUENCY ===")
    issue_counts: dict[str, int] = {}
    for r in results:
        for issue in r["issues"]:
            key = issue.split(" — ")[0][:80]
            issue_counts[key] = issue_counts.get(key, 0) + 1
    for issue, count in sorted(issue_counts.items(), key=lambda kv: -kv[1]):
        print(f"  [{count}/{n}] {issue}")
    print(f"\nfull results -> {OUT}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
