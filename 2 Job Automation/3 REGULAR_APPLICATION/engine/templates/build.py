"""Document build: filled tex -> tectonic PDF, plus the python-docx DOCX mirror.

Kept from v1 (the plan's "kept unchanged" list) but pointed at the v2 template,
the @@TOKEN@@ filling, and the v2 output tree. The build itself is gated:
`assert no tokens remain` runs inside fill_template before any compile starts.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from engine import config
from engine.templates.fill import (  # noqa: F401 - latex_block/skills_line re-exported
    clean_text,
    escape_latex,
    join_items,
)


def latex_block(objective: str) -> str:
    """Escape the objective for the \textbf{...} slot."""
    return escape_latex(objective)


def skills_line(items: list[str]) -> str:
    """Escape a skill list for a template slot."""
    return join_items(items)


def find_latex_engine() -> str | None:
    """Return the compile command, preferring the bundled tectonic."""
    for candidate in config.TECTONIC_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    for command in ("tectonic", "pdflatex"):
        if shutil.which(command):
            return command
    return None


def compile_pdf(tex_path: Path, pdf_path: Path, engine: str | None) -> tuple[bool, str]:
    """Compile a tex file and place the pdf at pdf_path; returns (ok, message)."""
    if engine is None:
        return False, "no LaTeX engine found (tectonic.exe missing and nothing on PATH)"
    produced = tex_path.with_suffix(".pdf")
    produced.unlink(missing_ok=True)
    try:
        process = subprocess.run(
            [engine, str(tex_path)],
            cwd=str(tex_path.parent),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if not (produced.exists() and produced.stat().st_size > 0):
        detail = (process.stderr or process.stdout or "")[-400:]
        return False, f"compiler exit {process.returncode}: {detail}"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(produced), str(pdf_path))
    return True, f"compiled with {Path(engine).name}"


def build_docx(docx_path: Path, doc: dict) -> None:
    """Write the DOCX from the SAME document model as the PDF (templates/render.py).

    v3 fixes (measured on the 10-14 run): the old DOCX had no experience dates or
    locations (ATS computed 0 years of experience), truncated LinkedIn/GitHub to
    'meetraval/ | ravalmeet', used 'Normal' style for section titles and put
    Education last. Now: real Heading 1 titles, one 'Role | Company | Location |
    Dates' line per job, full links, identical section order and content.
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = Document()
    for section in document.sections:
        section.top_margin = Pt(34)
        section.bottom_margin = Pt(34)
        section.left_margin = Pt(42)
        section.right_margin = Pt(42)

    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10)
    heading_style = styles["Heading 1"]
    heading_style.font.name = "Calibri"
    heading_style.font.size = Pt(12)
    heading_style.font.bold = True

    def paragraph(text: str = "", bold_prefix: str = "", align=None, size: float | None = None,
                  bold: bool = False):
        para = document.add_paragraph()
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(1)
        if align is not None:
            para.alignment = align
        if bold_prefix:
            run = para.add_run(bold_prefix)
            run.bold = True
            if size:
                run.font.size = Pt(size)
        run = para.add_run(text)
        run.bold = bold
        if size:
            run.font.size = Pt(size)
        return para

    def heading(text: str) -> None:
        para = document.add_heading(text, level=1)
        para.paragraph_format.space_before = Pt(8)
        para.paragraph_format.space_after = Pt(2)

    def bullet(text: str, bold_prefix: str = "") -> None:
        para = document.add_paragraph(style="List Bullet")
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0.5)
        if bold_prefix:
            para.add_run(bold_prefix).bold = True
        para.add_run(text)

    center = WD_ALIGN_PARAGRAPH.CENTER
    paragraph(doc["name"], align=center, size=18, bold=True)
    paragraph(doc["headline"], align=center, size=12)
    # full URLs as visible text: a parser keeps them even without hyperlink support
    contact = " | ".join(url if url and not url.startswith("mailto:") else text
                         for text, url in doc["contact"])
    paragraph(contact, align=center, size=9)
    if doc["availability"]:
        paragraph(doc["availability"], align=center, size=9)

    heading("Profile")
    paragraph(doc["profile"])

    heading("Technical Skills")
    for label, items in doc["skill_rows"]:
        bullet(", ".join(items), bold_prefix=f"{label}: ")

    heading("Work Experience")
    for exp in doc["experiences"]:
        head = " | ".join(p for p in (exp["company"], exp["location"], exp["dates"]) if p)
        paragraph(head, bold_prefix=f"{exp['title']} | ")
        for text in exp["bullets"]:
            bullet(text)
        if exp["skills"]:
            bullet(", ".join(exp["skills"]), bold_prefix="Key skills: ")

    heading("Projects")
    for proj in doc["projects"]:
        paragraph(proj["url"] if proj["url"] else "", bold_prefix=proj["title"] + (" | " if proj["url"] else ""))
        for text in proj["bullets"]:
            bullet(text)
        if proj["skills"]:
            bullet(", ".join(proj["skills"]), bold_prefix="Tech: ")

    heading("Education")
    for edu in doc["education"]:
        paragraph(" | ".join(p for p in (edu["school"], edu["location"], edu["dates"]) if p),
                  bold_prefix=f"{edu['degree']} | ")
        for line in edu["lines"]:
            paragraph(line)

    if doc["research"]:
        heading("Research")
        for item in doc["research"]:
            bullet(item["summary"], bold_prefix=f"{item['title']}: ")
    if doc["achievements"]:
        heading("Achievements")
        for item in doc["achievements"]:
            bullet(item)
    if doc["certifications"]:
        heading("Certifications")
        for item in doc["certifications"]:
            bullet(item)
    if doc["additional_projects"]:
        heading("Additional Projects")
        for text, _url_text, url in doc["additional_projects"]:
            bullet(text + (f" | {url}" if url else ""))
    if doc["languages"]:
        heading("Languages")
        paragraph(doc["languages"])

    core = document.core_properties
    core.author = doc["name"]
    core.title = doc["pdf_title"]

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(docx_path))


def build_letter_docx(docx_path: Path, letter) -> None:
    """Write the DOCX mirror of the cover letter (portals that accept DOCX)."""
    from docx import Document
    from docx.shared import Pt

    document = Document()
    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(11)

    def right_block(lines: list[str], bold_first: bool = False) -> None:
        for i, line in enumerate(lines):
            if not line:
                continue
            paragraph = document.add_paragraph()
            paragraph.alignment = 2
            run = paragraph.add_run(line)
            run.bold = bold_first and i == 0
            run.font.size = Pt(10)

    right_block([letter.sender_name, letter.sender_address, letter.sender_contact, letter.sender_links],
                bold_first=True)
    document.add_paragraph()
    for line in (letter.company_block or "").splitlines():
        if line.strip():
            document.add_paragraph(line.strip())
    document.add_paragraph()
    date_paragraph = document.add_paragraph(letter.date_line)
    date_paragraph.alignment = 2
    document.add_paragraph()

    subject = document.add_paragraph()
    run = subject.add_run(letter.subject)
    run.bold = True
    document.add_paragraph()

    document.add_paragraph(letter.salutation)
    for name in ("opening", "fit", "motivation", "closing"):
        text = str(getattr(letter, name) or "").strip()
        if text:
            document.add_paragraph(text)
    document.add_paragraph()
    document.add_paragraph(letter.signoff)
    document.add_paragraph()
    document.add_paragraph(letter.name_print)

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(docx_path))


def safe_name(title: str) -> str:
    """Turn a posting title into a filesystem-safe resume file stem."""
    import re

    name = re.sub(r"\((m/f/d|x|/|m/w/d|w/m/d|f/m|d|m|w)+\)", " ", title, flags=re.IGNORECASE)
    name = re.sub(r"\((m/f/d|x|/|m/w/d|w/m/d|f/m|d|m|w)+\)", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    name = re.sub(r"[\s_]+", "-", name.strip()).strip("-")
    name = re.sub(r"-{2,}", "-", name)          # "Working Student - AI" -> one dash, not three
    return name[:80] or "resume"


def cut_stem(name: str, limit: int) -> str:
    """Shorten a dash-joined stem at a word boundary ("...-Intern-2027", never "...-Intern-20")."""
    if len(name) <= limit:
        return name.strip("-")
    head = name[:limit]
    return (head.rsplit("-", 1)[0] if "-" in head else head).strip("-")


def archive_stale(directories, keep: set, archive_root: Path) -> list[str]:
    """Move generated files whose stem is not in `keep` into archive_root/<dir name>/.

    Output folders kept old names next to new ones (44 resume PDFs for 18 jobs on
    2026-10-17), so a reader could upload a stale file. Files are moved, never deleted.
    """
    moved: list[str] = []
    for directory in directories:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.stem not in keep:
                target_dir = archive_root / directory.parent.name / directory.name
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target_dir / path.name))
                moved.append(path.name)
    return moved


def cv_file_stem(first_name: str, last_name: str, company: str, title: str) -> str:
    """'Meetkumar_Raval_CV_SIXT_Working-Student-Data-Science' (recruiters see the
    file name; Jobscan/VisualCV convention First_Last_CV, no spaces or specials)."""
    person = "_".join(p for p in (safe_name(first_name), safe_name(last_name)) if p and p != "resume")
    company_part = cut_stem(safe_name(company or ""), 30)
    role_part = cut_stem(safe_name(title or ""), 40)
    parts = [person or "CV", "CV"] if person else ["CV"]
    parts += [p for p in (company_part, role_part) if p and p != "resume"]
    return "_".join(parts)[:110]


def letter_file_names(title: str, company: str) -> tuple[str, str]:
    """Neutral per-role letter file names: Anschreiben_<Company> + <Role>.

    German recruiters expect neutral names (Anschreiben_Compugroup.pdf); the
    role keeps the portal-side uniqueness so two applications never collide.
    """
    company_part = cut_stem(safe_name(company or "Anschreiben"), 40)
    role_part = cut_stem(safe_name(title or "Rolle"), 40)
    return f"Anschreiben_{company_part}", f"{role_part}"
