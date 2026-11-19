"""Stage 5: compile tailored LaTeX and PDF resumes from generated section JSONs.

Reads:
  sub_program_files/output/career_objective.json
  sub_program_files/output/experience.json
  sub_program_files/output/projects.json
  sub_program_files/output/skills.json
Template:
  sub_program_files/resume_content/core_resume_template.tex
Tectonic Compiler:
  ../resume_creation/tools/tectonic.exe

Emits:
  sub_program_files/output/resume/tex/<safe_name>.tex
  sub_program_files/output/resume/pdf/<safe_name>.pdf
  sub_program_files/output/job_resume_map_local.csv
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "sub_program_files" / "output"
TEX_DIR = OUTPUT_DIR / "resume" / "tex"
PDF_DIR = OUTPUT_DIR / "resume" / "pdf"
MAP_CSV = OUTPUT_DIR / "job_resume_map_local.csv"

TEMPLATE_TEX = Path(__file__).resolve().parent / "core_resume_template.tex"
TECTONIC_CANDIDATES = [
    PROJECT_ROOT.parent / "resume_creation" / "tools" / "tectonic.exe",
    PROJECT_ROOT.parent.parent / "resume_creation" / "tools" / "tectonic.exe",
    Path(r"E:\WorkSpace\2 Tech\2 Job Automation\Companies Related Automation\resume_creation\tools\tectonic.exe"),
]
TECTONIC_EXE = next((p for p in TECTONIC_CANDIDATES if p.exists() and p.is_file()), TECTONIC_CANDIDATES[0])

SOHAM_INFOTECH = "Soham Infotech"


def escape_latex(text: str) -> str:
    """Escape LaTeX-special characters."""
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
    result = str(text or "")
    for char, token in replacements.items():
        result = result.replace(char, token)
    return result


def safe_name(title: str) -> str:
    """Create a filesystem-safe file stem from job title."""
    name = re.sub(r"\((m/f/d|x|/|m/w/d|w/m/d|f/m|d|m|w|fmd)+\)", " ", title, flags=re.I)
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    name = re.sub(r"[\s_]+", "-", name.strip()).strip("-")
    return name[:70] or "resume"


def fill_template(template: str, components: dict) -> str:
    objective = components["objective"].get("career_objective", "")
    exp_1 = components["experience"].get("experience_1", {})
    exp_2 = components["experience"].get("experience_2", {})
    proj_1 = components["projects"].get("project_1", {})
    proj_2 = components["projects"].get("project_2", {})
    skills = components["skills"].get("skills_section", {})

    def join_items(items: list[str]) -> str:
        return ", ".join(escape_latex(item) for item in items)

    text = template

    # Projects (Must replace PROJECT-* before bare tokens)
    text = text.replace("PROJECT-DESCRIPTION-1", escape_latex(proj_1.get("description", "")))
    text = text.replace("PROJECT-DESCRIPTION-2", escape_latex(proj_2.get("description", "")))
    text = text.replace("PROJECT-SKILLS-1", join_items(proj_1.get("skills", [])))
    text = text.replace("PROJECT-SKILLS-2", join_items(proj_2.get("skills", [])))
    text = text.replace("PROJECT-1", escape_latex(proj_1.get("project", "Project 1")))
    text = text.replace("PROJECT-2", escape_latex(proj_2.get("project", "Project 2")))

    # Experience 1
    role_1 = f"{escape_latex(exp_1.get('role', 'Software Engineer'))} - {SOHAM_INFOTECH}"
    text = text.replace(r"\textbf{ROLE-1 - Software Engineer}", rf"\textbf{{{role_1}}}")
    text = text.replace("ROLE-1", escape_latex(exp_1.get("role", "Software Engineer")))
    text = text.replace("DESCRIPTION-1", escape_latex(exp_1.get("description", "")))
    text = text.replace("SKILLS-1", join_items(exp_1.get("skills", [])))

    # Experience 2
    text = text.replace("ROLE-2", escape_latex(exp_2.get("role", "Intern")))
    text = text.replace("DESCRIPTION-2", escape_latex(exp_2.get("description", "")))
    text = text.replace("SKILLS-2", join_items(exp_2.get("skills", [])))

    # Career objective
    text = text.replace("CAREER-OBJECTIVE", escape_latex(objective))

    # Skills rows
    text = text.replace("LANGUAGES", join_items(skills.get("languages", [])))
    text = text.replace("SPECIALIZED-AREAS", join_items(skills.get("specialized_areas", [])))
    
    area_1 = skills.get("skills_area_1", {})
    area_2 = skills.get("skills_area_2", {})
    text = text.replace("SKILLS AREA", escape_latex(area_1.get("label", "Technical Skills")), 1)
    text = text.replace("SKILLS AREA", escape_latex(area_2.get("label", "Applied Skills")), 1)
    text = text.replace("{SKILLS}", join_items(area_1.get("skills", [])), 1)
    text = text.replace("{SKILLS}", join_items(area_2.get("skills", [])), 1)

    return text


def load_all_components() -> dict[str, dict]:
    """Load matching components across all 4 JSON files."""
    files = {
        "objective": OUTPUT_DIR / "career_objective.json",
        "experience": OUTPUT_DIR / "experience.json",
        "projects": OUTPUT_DIR / "projects.json",
        "skills": OUTPUT_DIR / "skills.json",
    }
    for name, path in files.items():
        if not path.exists():
            raise RuntimeError(f"Required component file missing: {path}. Run steps 1-4 first.")

    obj_data = {r["job_url"]: r for r in json.loads(files["objective"].read_text(encoding="utf-8")).get("objectives", [])}
    exp_data = {r["job_url"]: r for r in json.loads(files["experience"].read_text(encoding="utf-8")).get("experiences", [])}
    proj_data = {r["job_url"]: r for r in json.loads(files["projects"].read_text(encoding="utf-8")).get("projects", [])}
    sk_data = {r["job_url"]: r for r in json.loads(files["skills"].read_text(encoding="utf-8")).get("skills", [])}

    common_urls = set(obj_data.keys()) & set(exp_data.keys()) & set(proj_data.keys()) & set(sk_data.keys())
    return {
        url: {
            "title": obj_data[url].get("title", ""),
            "objective": obj_data[url],
            "experience": exp_data[url],
            "projects": proj_data[url],
            "skills": sk_data[url],
        }
        for url in common_urls
    }


def main() -> int:
    TEX_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    if not TECTONIC_EXE.exists():
        print(f"[BUILD] ERROR: tectonic not found at {TECTONIC_EXE}")
        return 1

    template = TEMPLATE_TEX.read_text(encoding="utf-8")
    components_by_url = load_all_components()
    print(f"[BUILD] Loaded components for {len(components_by_url)} jobs.")

    map_rows = []
    built = 0

    for i, (url, data) in enumerate(components_by_url.items(), 1):
        stem = safe_name(data["title"])
        tex_path = TEX_DIR / f"{stem}.tex"
        pdf_path = PDF_DIR / f"{stem}.pdf"

        filled_tex = fill_template(template, data)
        tex_path.write_text(filled_tex, encoding="utf-8")

        # Compile with Tectonic
        cmd = [str(TECTONIC_EXE), "-o", str(PDF_DIR), str(tex_path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and pdf_path.exists():
            built += 1
            print(f"[BUILD] [{i}/{len(components_by_url)}] OK: {pdf_path.name}")
            map_rows.append({"job_url": url, "status": "OK", "resume_pdf": str(pdf_path), "title": data["title"]})
        else:
            print(f"[BUILD] [{i}/{len(components_by_url)}] FAILED: {pdf_path.name}\n{res.stderr[:200]}")
            map_rows.append({"job_url": url, "status": "FAILED", "resume_pdf": "", "title": data["title"]})

    # Save local map CSV
    with MAP_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["job_url", "status", "resume_pdf", "title"])
        writer.writeheader()
        writer.writerows(map_rows)

    print(f"\n[BUILD] Done! Built {built}/{len(components_by_url)} PDFs -> {PDF_DIR}")
    print(f"[BUILD] Local resume map -> {MAP_CSV}")
    return 0 if built == len(components_by_url) else 1


if __name__ == "__main__":
    sys.exit(main())
