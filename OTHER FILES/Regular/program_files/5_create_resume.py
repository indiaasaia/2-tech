"""Step 5: build the per-job resume files (PDF + DOCX) from the generated components.

Reads the four component stores written by step 4
  program_files/output/career_objective.json
  program_files/output/experience.json
  program_files/output/projects.json
  program_files/output/skills.json
plus the master job list program_files/output/todays_overall_jobs.csv and the template
sub_program_files/resume_content/core_resume_template.tex.

For every job that has ALL four components (matched by job_url) it:
  1. LaTeX-escapes every generated value and fills the template placeholders
  2. saves the filled tex to program_files/output/resume/tex/<safe_name>.tex
  3. compiles it to output/resume/pdf/<safe_name>.pdf (tectonic or pdflatex)
  4. builds output/resume/docx/<safe_name>.docx with python-docx

safe_name is derived from the job title (posting suffixes like (m/f/d) stripped).
One job failure never stops the loop. Exits 0 only when every resume succeeded.

Run directly: python program_files/5_create_resume.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output"
TEX_DIR = OUTPUT_DIR / "resume" / "tex"
PDF_DIR = OUTPUT_DIR / "resume" / "pdf"
DOCX_DIR = OUTPUT_DIR / "resume" / "docx"
TEMPLATE_TEX = PROJECT_ROOT / "sub_program_files" / "resume_content" / "core_resume_template.tex"
TECTONIC_CANDIDATES = (
    PROJECT_ROOT / "tools" / "tectonic.exe",
)

COMPONENT_FILES = (
    ("career_objective.json", "objectives", "objective_error"),
    ("experience.json", "experiences", "experience_error"),
    ("projects.json", "projects", "projects_error"),
    ("skills.json", "skills", "skills_error"),
)

SOHAM_INFOTECH = "Soham Infotech"


def load_components() -> dict[str, dict]:
    """Load the four component stores keyed by job_url.

    Returns {job_url: {"objective": {...}, "experience": {...}, "projects": {...}, "skills": {...}}}.
    Jobs missing a store, flagged with an error, or missing from it are reported.
    """
    stores: dict[str, dict] = {}
    for file_name, records_key, error_field in COMPONENT_FILES:
        path = OUTPUT_DIR / file_name
        if not path.exists():
            raise RuntimeError(f"component store not found: {path} — run step 4 first")
        payload = json.loads(path.read_text(encoding="utf-8"))
        valid: dict[str, dict] = {}
        for record in payload.get(records_key, []):
            if record.get(error_field):
                continue  # flagged records never reach resume assembly
            valid[str(record.get("job_url") or "")] = record
        stores[file_name] = valid
        print(f"[RESUME] {file_name}: {len(valid)} usable record(s)")

    all_urls = set(stores["career_objective.json"]) \
        & set(stores["experience.json"]) & set(stores["projects.json"]) & set(stores["skills.json"])
    counts = {name: len(store) for name, store in stores.items()}
    print(f"[RESUME] jobs with all four components: {len(all_urls)} (store sizes: {counts})")
    return {url: {
        "objective": stores["career_objective.json"][url],
        "experience": stores["experience.json"][url],
        "projects": stores["projects.json"][url],
        "skills": stores["skills.json"][url],
    } for url in all_urls}


def load_master_jobs() -> dict[str, dict]:
    """Load todays_overall_jobs.csv keyed by job_url (title/company metadata source)."""
    path = OUTPUT_DIR / "todays_overall_jobs.csv"
    if not path.exists():
        raise RuntimeError(f"master job list not found: {path} — run steps 1 and 2 first")
    frame = pd.read_csv(path, keep_default_na=False)
    return {str(row.get("job_url") or ""): row for _, row in frame.iterrows() if str(row.get("job_url") or "")}


def safe_name(title: str) -> str:
    """Turn a posting title into a filesystem-safe resume file stem."""
    name = re.sub(r"\((m/f/d|x|/|m/w/d|w/m/d|f/m|d|m|w)+\)", " ", title, flags=re.IGNORECASE)
    name = re.sub(r"\((m/f/d|x|/|m/w/d|w/m/d|f/m|d|m|w)+\)", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    name = re.sub(r"[\s_]+", "-", name.strip()).strip("-")
    return name[:80] or "resume"


def escape_latex(text: str) -> str:
    """Escape every LaTeX-special character in a generated value."""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    result = str(text)
    for character, token in replacements.items():
        result = result.replace(character, token)
    return result


def fill_template(template: str, components: dict, job: dict) -> str:
    """Fill all placeholders of the template with the job's escaped component values."""
    objective = components["objective"]["career_objective"]
    experience_1 = components["experience"]["experience_1"]
    experience_2 = components["experience"]["experience_2"]
    project_1 = components["projects"]["project_1"]
    project_2 = components["projects"]["project_2"]
    skills = components["skills"]["skills_section"]

    def join_items(items: list[str]) -> str:
        return ", ".join(escape_latex(item) for item in items)

    text = template

    # Projects replaced before experience to prevent SKILLS-1 from eating PROJECT-SKILLS-1.
    text = text.replace("PROJECT-DESCRIPTION-1", escape_latex(project_1["description"]))
    text = text.replace("PROJECT-SKILLS-1", join_items(project_1["skills"]))
    text = text.replace("PROJECT-1", escape_latex(project_1["project"]))
    text = text.replace("PROJECT-DESCRIPTION-2", escape_latex(project_2["description"]))
    text = text.replace("PROJECT-SKILLS-2", join_items(project_2["skills"]))
    text = text.replace("PROJECT-2", escape_latex(project_2["project"]))

    # Experience entry 1: the whole fixed block (company slot currently says Software Engineer).
    role_1 = f"{escape_latex(experience_1['role'])} - {SOHAM_INFOTECH}"
    text = text.replace(r"\textbf{ROLE-1 - Software Engineer}", rf"\textbf{{{role_1}}}")
    text = text.replace("DESCRIPTION-1", escape_latex(experience_1["description"]))
    text = text.replace("SKILLS-1", join_items(experience_1["skills"]))

    # Experience entry 2: role token only; the - Pantechelearning part is fixed in the template.
    text = text.replace("ROLE-2", escape_latex(experience_2["role"]))
    text = text.replace("DESCRIPTION-2", escape_latex(experience_2["description"]))
    text = text.replace("SKILLS-2", join_items(experience_2["skills"]))

    # Career objective.
    text = text.replace("CAREER-OBJECTIVE", escape_latex(objective))

    # Skills rows. Both SKILLS AREA placeholders are identical, so replace them by occurrence:
    # the first becomes skill area 1, the second skill area 2.
    text = text.replace("LANGUAGES", join_items(skills["languages"]))
    text = text.replace("SPECIALIZED-AREAS", join_items(skills["specialized_areas"]))
    text = text.replace("SKILLS AREA", escape_latex(skills["skills_area_1"]["label"]), 1)
    text = text.replace("SKILLS AREA", escape_latex(skills["skills_area_2"]["label"]), 1)
    text = text.replace("{SKILLS}", join_items(skills["skills_area_1"]["skills"]), 1)
    text = text.replace("{SKILLS}", join_items(skills["skills_area_2"]["skills"]), 1)

    # Sanity: no generation placeholder may survive.
    leftover = re.findall(r"(?:ROLE-2|DESCRIPTION-\d|SKILLS-\d|PROJECT-\d|PROJECT-DESCRIPTION-\d|PROJECT-SKILLS-\d|CAREER-OBJECTIVE|LANGUAGES|SPECIALIZED-AREAS|\{SKILLS\}|PROJECT-)", text)
    if leftover:
        raise RuntimeError(f"unfilled placeholders remain: {sorted(set(leftover))}")
    unused = re.findall(r"SKILLS AREA", text)
    if unused:
        raise RuntimeError(f"{len(unused)} SKILLS AREA labels were not replaced")
    return text


def find_latex_engine() -> str | None:
    """Return the command to compile tex, preferring the bundled tectonic."""
    for candidate in TECTONIC_CANDIDATES:
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
    # tectonic and pdflatex both write the pdf next to the tex file.
    if not (produced.exists() and produced.stat().st_size > 0):
        return False, f"compiler exit {process.returncode}: {process.stderr[-400:] or process.stdout[-400:]}"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(produced), str(pdf_path))
    return True, f"compiled with {Path(engine).name}"


def build_docx(docx_path: Path, job: dict, components: dict) -> None:
    """Write a structured DOCX mirror of the resume content (no LaTeX involved)."""
    from docx import Document
    from docx.shared import Pt

    document = Document()
    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10.5)

    def heading(text: str) -> None:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(text)
        run.bold = True
        run.font.size = Pt(12)
        paragraph.paragraph_format.space_before = Pt(8)
        paragraph.paragraph_format.space_after = Pt(2)

    def item(text: str, bold_prefix: str = "") -> None:
        paragraph = document.add_paragraph(style="List Bullet")
        if bold_prefix:
            run = paragraph.add_run(bold_prefix)
            run.bold = True
        paragraph.add_run(text)

    name = "RAVAL MEETKUMAR RITESHKUMAR"
    contact = "ravalmeett@gmail.com | +49 15565 468731 | linkedin.com/in/meetraval | github.com/ravalmeet"
    title = document.add_paragraph()
    run = title.add_run(name)
    run.bold = True
    run.font.size = Pt(16)
    meta = document.add_paragraph(contact)
    meta.alignment = 1

    heading("Career Objective")
    document.add_paragraph(components["objective"]["career_objective"])

    heading("Experience")
    for entry, company in ((components["experience"]["experience_1"], SOHAM_INFOTECH),
                           (components["experience"]["experience_2"], "Pantechelearning")):
        item(entry["description"], bold_prefix=f"{entry['role']} - {company}: ")
        item(", ".join(entry["skills"]), bold_prefix="Skills: ")

    heading("Main Projects")
    for project in (components["projects"]["project_1"], components["projects"]["project_2"]):
        item(project["description"], bold_prefix=f"{project['project']}: ")
        item(", ".join(project["skills"]), bold_prefix="Skills: ")

    skills = components["skills"]["skills_section"]
    heading("Skills")
    item(", ".join(skills["languages"]), bold_prefix="Programming Languages: ")
    item(", ".join(skills["specialized_areas"]), bold_prefix="Specialized Area: ")
    item(", ".join(skills["skills_area_1"]["skills"]), bold_prefix=f"{skills['skills_area_1']['label']}: ")
    item(", ".join(skills["skills_area_2"]["skills"]), bold_prefix=f"{skills['skills_area_2']['label']}: ")

    heading("Education")
    document.add_paragraph("MSc Artificial Intelligence - BTU Cottbus-Senftenberg, Germany (April 2025 - Current)")
    document.add_paragraph("BE Computer Engineering - Gujarat Technological University, India (June 2020 - May 2024)")

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(docx_path))


def main() -> int:
    """Assemble, compile and save one resume per job; returns the exit code."""
    components_by_url = load_components()
    master_jobs = load_master_jobs()
    engine = find_latex_engine()
    print(f"[RESUME] LaTeX engine: {engine or 'NONE (PDFs will fail)'}")

    TEX_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    DOCX_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    total = len(components_by_url)
    seen_names: dict[str, int] = {}
    for index, (url, components) in enumerate(sorted(components_by_url.items()), 1):
        job = master_jobs.get(url, {})
        title = str(job.get("title") or components["objective"].get("title") or url)
        name = safe_name(title)
        # Different titles can sanitize to the same stem (e.g. "Working Student" and
        # "Working Student (m/f/d)"); add a counter suffix so one never overwrites the other.
        if name in seen_names:
            seen_names[name] += 1
            name = f"{name}-{seen_names[name]}"
        else:
            seen_names[name] = 1
        record = {"job_url": url, "title": title, "tex": "", "pdf": "", "docx": "", "error": ""}
        print(f"[RESUME] [{index}/{total}] {title[:60]} -> {name}")

        try:
            template = TEMPLATE_TEX.read_text(encoding="utf-8")
            filled = fill_template(template, components, job)
            tex_path = TEX_DIR / f"{name}.tex"
            tex_path.write_text(filled, encoding="utf-8")
            record["tex"] = str(tex_path)

            pdf_ok, message = compile_pdf(tex_path, PDF_DIR / f"{name}.pdf", engine)
            if pdf_ok:
                record["pdf"] = str(PDF_DIR / f"{name}.pdf")
            else:
                record["error"] = f"pdf: {message}"

            try:
                docx_path = DOCX_DIR / f"{name}.docx"
                build_docx(docx_path, job, components)
                record["docx"] = str(docx_path)
            except Exception as exc:  # noqa: BLE001 - docx failure should not kill the pdf result
                record["error"] = (record["error"] + f" | docx: {type(exc).__name__}: {exc}").strip(" |")
        except Exception as exc:  # noqa: BLE001 - one job failure never stops the loop
            record["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

        status = "OK" if (record["pdf"] and record["docx"] and not record["error"]) else "FAILED"
        print(f"[RESUME] [{index}/{total}] {status}: {name} (pdf={bool(record['pdf'])}, docx={bool(record['docx'])})")
        if record["error"]:
            print(f"         {record['error']}")
        results.append(record)

    report_path = OUTPUT_DIR / "resume_report.json"
    report_path.write_text(json.dumps({"total_jobs": total, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = sum(1 for record in results if record["pdf"] and record["docx"] and not record["error"])
    print(f"\n[RESUME] summary: {ok}/{total} resumes complete (pdf + docx)")
    print(f"[RESUME] report -> {report_path}")
    print(f"[RESUME] tex -> {TEX_DIR}")
    print(f"[RESUME] pdf -> {PDF_DIR}")
    print(f"[RESUME] docx -> {DOCX_DIR}")
    return 0 if ok == total and total > 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
