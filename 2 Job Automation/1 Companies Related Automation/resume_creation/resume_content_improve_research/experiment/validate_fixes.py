"""Validate the V3 template fixes empirically: build original vs fixed tex, compile both
with tectonic, run parser-test heuristics on both PDFs, and compare results.

Run: python resume_content_improve_research/experiment/validate_fixes.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
EXP = Path(__file__).resolve().parent
TEX_SOURCE = ROOT / "program_files" / "output" / "resume" / "tex" / "Finance-Intern-Working-Student.tex"
TECTONIC = ROOT / "old_files" / "tools" / "tectonic.exe"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def make_fixed(src: str) -> str:
    text = src
    # FIX 1: section titles — \scshape -> \bfseries + uppercase after-title command
    text = re.sub(
        r"\\titleformat\{\\section\}\{([^}]*)\\scshape([^}]*)\}\{\}\{0em\}\{\}",
        lambda m: "\\titleformat{\\section}{" + m.group(1) + "\\bfseries" + m.group(2)
                  + "}{}{0em}{\\MakeUppercase}",
        text,
    )
    # FIX 2: dates Dec'yy -> Dec yyyy
    text = re.sub(r"([A-Z][a-z]{2})'(\d{2})", lambda m: f"{m.group(1)} 20{m.group(2)}", text)
    # FIX 3: disable common ligatures (XeTeX/tectonic route — glyphtounicode is pdfTeX-only)
    text = text.replace(
        "\\begin{document}",
        "\\usepackage{fontspec}\n"
        "\\setmainfont{texgyrepagella}[Ligatures=NoCommon, Extension=.otf,"
        " UprightFont=*-regular, BoldFont=*-bold, ItalicFont=*-italic, BoldItalicFont=*-bolditalic]\n"
        "\\begin{document}",
    )
    # FIX 4: full name in header
    text = text.replace("RAVAL MEETKUMAR }", "RAVAL MEETKUMAR RITESHKUMAR }")
    return text


def compile_tex(tex_path: Path) -> bool:
    if tex_path.with_suffix(".pdf").exists():
        tex_path.with_suffix(".pdf").unlink()
    result = subprocess.run(
        [str(TECTONIC), tex_path.name], cwd=tex_path.parent, capture_output=True, text=True, timeout=300
    )
    ok = tex_path.with_suffix(".pdf").exists()
    if not ok:
        print(result.stderr[-400:] or result.stdout[-400:])
    return ok


def analyze(pdf_path: Path) -> dict:
    import pypdf
    with pdfplumber.open(pdf_path) as pdf:
        plumber_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    pypdf_text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(str(pdf_path)).pages)

    def sections_upper(text: str) -> list[str]:
        out = []
        for line in text.splitlines():
            t = line.strip()
            if 3 < len(t) <= 40 and t.isupper() and t.split()[0].isalpha():
                out.append(t)
        return out

    import re as _re
    years = _re.findall(r"(?:19|20)\d{2}", plumber_text)
    apostrophe = _re.findall(r"[A-Z][a-z]{2}[’']\d{2}", plumber_text + pypdf_text)
    ligs = sum((plumber_text + pypdf_text).count(c) for c in ("\ufb01", "\ufb02", "\ufb00", "\ufb03"))
    return {
        "years_found": sorted(set(years)),
        "apostrophe_dates": apostrophe,
        "ligatures": ligs,
        "plumber_sections": sections_upper(plumber_text)[:14],
        "pypdf_name_ok": "RAVAL MEETKUMAR RITESHKUMAR" in pypdf_text.replace("  ", " "),
        "plumber_name_ok": "RAVAL MEETKUMAR RITESHKUMAR" in plumber_text.replace("  ", " "),
        "pypdf_title_corrupt": any(
            bad in pypdf_text for bad in ("AREER", "BJECTIVE", "ESEARCH AND UBLICATIONS", "KILLS")
        ),
        "plumber_title_corrupt": any(
            bad in plumber_text for bad in ("E XPERIENCE", "AREER", "M AIN P ROJECTS")
        ),
    }


def main() -> int:
    shutil.copy(TEX_SOURCE, EXP / "original.tex")
    fixed_src = make_fixed(TEX_SOURCE.read_text(encoding="utf-8"))
    (EXP / "fixed.tex").write_text(fixed_src, encoding="utf-8")

    for name in ("original", "fixed"):
        ok = compile_tex(EXP / f"{name}.tex")
        print(f"compile {name}: {'OK' if ok else 'FAILED'}")
        if not ok:
            return 1

    for name in ("original", "fixed"):
        res = analyze(EXP / f"{name}.pdf")
        print(f"\n=== {name} ===")
        for key, value in res.items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
