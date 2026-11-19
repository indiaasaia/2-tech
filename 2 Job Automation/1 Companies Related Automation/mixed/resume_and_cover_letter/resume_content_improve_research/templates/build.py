"""Document build: filled tex -> tectonic PDF, plus the python-docx DOCX mirror.

Kept from v1 (the plan's "kept unchanged" list) but pointed at the v2 template,
the @@TOKEN@@ filling, and the v2 output tree. The build itself is gated:
`assert no tokens remain` runs inside fill_template before any compile starts.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from resume_content_improve_research import config
from resume_content_improve_research.templates.fill import (  # noqa: F401 - latex_block/skills_line re-exported
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


def build_docx(docx_path: Path, components: dict) -> None:
    """Write a structured DOCX mirror of the v2 component JSON (no LaTeX involved)."""
    from docx import Document
    from docx.shared import Pt

    document = Document()
    for section in document.sections:
        section.top_margin = Pt(32)
        section.bottom_margin = Pt(32)
        section.left_margin = Pt(40)
        section.right_margin = Pt(40)

    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10)

    def heading(text: str) -> None:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(text)
        run.bold = True
        run.font.size = Pt(11.5)
        paragraph.paragraph_format.space_before = Pt(5)
        paragraph.paragraph_format.space_after = Pt(1)

    def item(text: str, bold_prefix: str = "") -> None:
        paragraph = document.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0.5)
        if bold_prefix:
            run = paragraph.add_run(bold_prefix)
            run.bold = True
        paragraph.add_run(text)

    profile = components["profile"]
    title = document.add_paragraph()
    run = title.add_run(profile.get("full_name", ""))
    run.bold = True
    run.font.size = Pt(16)
    meta = document.add_paragraph(profile.get("contact_line", ""))
    meta.alignment = 1

    heading("Career Objective")
    document.add_paragraph(components["objective"])

    heading("Experience")
    for entry in components["experience"]:
        item(entry["description"], bold_prefix=f"{entry['role']} - {entry['company']}: ")
        item(", ".join(entry["skills"]), bold_prefix="Skills: ")

    heading("Main Projects")
    for project in components["projects"]:
        item(project["description"], bold_prefix=f"{project['title']}: ")
        item(", ".join(project["skills"]), bold_prefix="Skills: ")

    static = components.get("static_sections") or {}
    if static.get("research"):
        heading("Research and Publications")
        for research in static["research"]:
            item(research.get("evidence", ""), bold_prefix=f"{research.get('title', '')}: ")
    if static.get("achievements"):
        heading("Achievements")
        for achievement in static["achievements"]:
            item(achievement.get("result", ""), bold_prefix=f"{achievement.get('name', '')}: ")
    if static.get("certifications"):
        heading("Certifications")
        for certification in static["certifications"]:
            item(certification.get("name", ""))
    if static.get("additional_projects"):
        heading("Additional Projects")
        for project in static["additional_projects"]:
            detail = project.get("evidence", "")
            if project.get("url"):
                detail = (detail + " | " if detail else "") + project["url"]
            item(detail, bold_prefix=f"{project.get('title', '')}: ")

    skills = components["skills_section"]
    heading("Skills")
    item(", ".join(skills["languages"]), bold_prefix="Programming Languages: ")
    item(", ".join(skills["specialized_areas"]), bold_prefix="Specialized Area: ")
    for area in skills["areas"]:
        item(", ".join(area["skills"]), bold_prefix=f"{area['label']}: ")
    if static.get("languages"):
        item(", ".join(
            f"{entry['lang']} ({entry['level']})" for entry in static["languages"]
            if entry.get("lang") and entry.get("level")
        ), bold_prefix="Languages: ")

    heading("Education")
    for line in components["education_lines"]:
        document.add_paragraph(line)

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
    return name[:80] or "resume"


def letter_file_names(title: str, company: str) -> tuple[str, str]:
    """Neutral per-role letter file names: Anschreiben_<Company> + <Role>.

    German recruiters expect neutral names (Anschreiben_Compugroup.pdf); the
    role keeps the portal-side uniqueness so two applications never collide.
    """
    company_part = safe_name(company or "Anschreiben")[:40]
    role_part = safe_name(title or "Rolle")[:40]
    return f"Anschreiben_{company_part}", f"{role_part}"
