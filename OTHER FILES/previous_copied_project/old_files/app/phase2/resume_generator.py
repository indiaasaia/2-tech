"""Phase 2: generate a tailored resume for each selected job.

The implementation is standalone. It uses the Phase 1 jobs.csv and a copied
candidate profile stored inside JOB_AUTOMATION. LLM generation is optional;
when unavailable, deterministic truthful output is always produced.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pandas as pd

from app.core import config
from app.core import activity
from app.core import ollama_client

COMPONENTS = ("objective", "experience", "projects", "research", "skills")


def load_profile(path: Path | None = None) -> dict[str, Any]:
    target = path or config.PROFILE_JSON
    if not target.exists():
        return {"name": "Candidate", "objective": "Motivated student seeking a relevant role.", "experience": [], "education": [], "projects": [], "research": [], "achievements": [], "skill_groups": {}, "certificates": [], "languages": []}
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("candidate profile must be a JSON object")
    return value


def job_text(row: pd.Series) -> str:
    return "\n".join(f"{key}: {row.get(key, '')}" for key in ("title", "company", "location", "snippet", "job_description", "applicant_profile", "requirements", "your_tasks", "what_they_offer") if str(row.get(key, "")).strip())


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _keywords(text: str) -> list[str]:
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}", text)
    stop = {"the", "and", "for", "with", "your", "this", "that", "from", "are", "you", "our", "job", "role", "working", "student"}
    seen: set[str] = set()
    result = []
    for value in candidates:
        low = value.lower()
        if low not in stop and low not in seen:
            seen.add(low)
            result.append(value)
    return result[:30]


def _ordered(values: list[Any], text: str) -> list[str]:
    strings = [str(x).strip() for x in values if str(x).strip()]
    return [value for _, value in sorted(((int(_norm(value) in _norm(text)), value) for value in strings), key=lambda x: (-x[0], x[1].lower()))]


def _llm_prompt(row: pd.Series, profile: dict[str, Any]) -> str:
    return """Return ONLY valid JSON with keys objective, experience, projects, research, skills. Never invent facts; use only the candidate profile. Tailor wording to the job.\nJOB:\n%s\nPROFILE:\n%s""" % (job_text(row)[:7000], json.dumps(profile, ensure_ascii=False)[:10000])


def _merge_llm_components(value: Any, fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return fallback
    result = dict(fallback)
    for key in COMPONENTS:
        if key not in value:
            continue
        candidate = value[key]
        if key == "objective" and isinstance(candidate, str) and candidate.strip():
            result[key] = candidate.strip()
        elif key in {"experience", "projects", "research"} and isinstance(candidate, list):
            result[key] = candidate
        elif key == "skills" and isinstance(candidate, dict):
            result[key] = candidate
    return result


def build_components(row: pd.Series, profile: dict[str, Any], use_llm: bool = True) -> tuple[dict[str, Any], str]:
    text = job_text(row)
    title = str(row.get("title", "the role")).strip()
    company = str(row.get("company", "the company")).strip()
    objective = str(profile.get("objective", "")).strip()
    if objective:
        objective = f"{objective} Targeting the {title} position at {company}."
    else:
        objective = f"Motivated candidate targeting the {title} position at {company}."

    experience = []
    for item in profile.get("experience") or []:
        experience.append({
            "role": str(item.get("role", "")), "company": str(item.get("company", "")),
            "location": str(item.get("location", "")), "years": str(item.get("years", "")),
            "bullets": [str(x) for x in item.get("bullets", []) if str(x).strip()],
            "skills": _ordered(item.get("skills", []), text),
        })
    projects = []
    for item in profile.get("projects") or []:
        projects.append({"name": str(item.get("name", "")), "url": str(item.get("url", "")), "description": str(item.get("description", "")), "skills": _ordered(item.get("skills", []), text)})
    research = [{"title": str(x.get("title", "")), "description": str(x.get("description", ""))} for x in (profile.get("research") or [])]
    skills = {str(group): _ordered(values, text) for group, values in (profile.get("skill_groups") or {}).items()}
    fallback = {"objective": objective, "experience": experience, "projects": projects, "research": research, "skills": skills, "job_keywords": _keywords(text)}
    if use_llm:
        try:
            generated = ollama_client.call_json(_llm_prompt(row, profile))
            return _merge_llm_components(generated, fallback), "ollama"
        except Exception as exc:
            print(f"[PHASE2] Ollama unavailable for {row.get('title', '')}: {type(exc).__name__}; using truthful fallback")
    return fallback, "template"


def _latex_escape(value: Any) -> str:
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    text = str(value or "").replace("–", "-").replace("—", "-").replace("‑", "-").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace(" ", " ").replace(" ", " ")
    return "".join(replacements.get(ch, ch) for ch in text)


def _safe_stem(row: pd.Series, index: int) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{index:03d}_{row.get('company', 'company')}_{row.get('title', 'role')}").strip("._")
    return value[:120] or f"resume_{index:03d}"


def render_resume(row: pd.Series, components: dict[str, Any], profile: dict[str, Any]) -> str:
    lines = [r"\documentclass[a4paper,11pt]{article}", r"\usepackage[margin=1.5cm]{geometry}", r"\usepackage[T1]{fontenc}", r"\usepackage{enumitem}", r"\usepackage[hidelinks]{hyperref}", r"\setlist[itemize]{noitemsep,topsep=1pt}", r"\begin{document}", r"\begin{center}", rf"{{\Large\textbf{{{_latex_escape(profile.get('display_name') or profile.get('name', 'Candidate'))}}}}}", r"\end{center}"]
    contact = " | ".join(str(profile.get(k, "")).strip() for k in ("email", "phone", "address") if str(profile.get(k, "")).strip())
    if contact: lines.append(_latex_escape(contact))
    lines += [r"\section*{Career Objective}", _latex_escape(components["objective"])]
    lines += [r"\section*{Key Skills}", _latex_escape(", ".join(components.get("job_keywords", [])))]
    if components["experience"]:
        lines.append(r"\section*{Experience}")
        for item in components["experience"]:
            lines.append(rf"\textbf{{{_latex_escape(item.get('role', ''))} -- {_latex_escape(item.get('company', ''))}}}\\")
            lines.append(rf"{_latex_escape(item.get('location', ''))} | {_latex_escape(item.get('years', ''))}")
            lines.append(r"\begin{itemize}")
            for bullet in item.get("bullets", []): lines.append(rf"\item {_latex_escape(bullet)}")
            lines.append(rf"\item \textbf{{Skills:}} {_latex_escape(', '.join(item.get('skills', [])))}")
            lines.append(r"\end{itemize}")
    if components["projects"]:
        lines.append(r"\section*{Projects}")
        for item in components["projects"]:
            lines.append(rf"\textbf{{{_latex_escape(item.get('name', ''))}}}\\")
            lines.append(_latex_escape(item.get("description", "")))
            lines.append(rf"\\textit{{Skills:}} {_latex_escape(', '.join(item.get('skills', [])))}")
    if components["research"]:
        lines.append(r"\section*{Research}")
        for item in components["research"]: lines += [rf"\textbf{{{_latex_escape(item.get('title', ''))}}}\\", _latex_escape(item.get("description", ""))]
    if profile.get("education"):
        lines.append(r"\section*{Education}")
        for item in profile["education"]: lines.append(rf"\textbf{{{_latex_escape(item.get('degree'))}}} -- {_latex_escape(item.get('school'))} ({_latex_escape(item.get('years'))})\\")
    for section, key in (("Achievements", "achievements"), ("Certifications", "certificates"), ("Languages", "languages")):
        values = profile.get(key) or []
        if values:
            lines.append(rf"\section*{{{section}}}")
            lines.append(r"\begin{itemize}")
            for value in values:
                if isinstance(value, dict): value = f"{value.get('language', '')} ({value.get('level', '')})"
                lines.append(rf"\item {_latex_escape(value)}")
            lines.append(r"\end{itemize}")
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def _compile(tex_path: Path, pdf_path: Path) -> tuple[bool, str]:
    compiler = config.find_latex_compiler()
    if not compiler:
        return False, "no LaTeX compiler found"
    try:
        if "tectonic" in Path(compiler).name.lower():
            command = [compiler, str(tex_path), "--outdir", str(config.PDF_DIR)]
        else:
            command = [compiler, "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={config.PDF_DIR}", str(tex_path)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        built = config.PDF_DIR / f"{tex_path.stem}.pdf"
        if not built.exists():
            candidates = list(config.PDF_DIR.glob("*.pdf"))
            if candidates:
                built = max(candidates, key=lambda candidate: candidate.stat().st_mtime)
        if completed.returncode == 0:
            candidates = list(config.PDF_DIR.glob("*.pdf"))
            if candidates:
                newest = max(candidates, key=lambda candidate: candidate.stat().st_mtime)
                if newest.resolve() != pdf_path.resolve():
                    pdf_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(newest, pdf_path)
                return True, "compiled"
        if built.exists():
            return True, "compiled with warnings"
        return False, (completed.stderr or completed.stdout)[-300:] or "compiler failed"
    except Exception as exc:
        return False, f"compile error: {type(exc).__name__}: {exc}"


def run_phase2(input_csv: Path | None = None, limit: int | None = None, compile_pdf: bool = True, use_llm: bool = True) -> list[dict[str, Any]]:
    source = input_csv or config.COMBINED_CSV
    if not source.exists(): raise FileNotFoundError(f"Phase 1 CSV not found: {source}")
    df = pd.read_csv(source, keep_default_na=False)
    if limit is not None: df = df.head(limit)
    profile = load_profile()
    results = []
    for index, (_, row) in enumerate(df.iterrows(), 1):
        components, method = build_components(row, profile, use_llm=use_llm)
        for item in components.get("experience", []):
            if isinstance(item, dict):
                item.setdefault("role", "")
                item.setdefault("company", "")
                item.setdefault("location", "")
                item.setdefault("years", "")
                item.setdefault("bullets", [])
                item.setdefault("skills", [])
        stem = _safe_stem(row, index)
        json_path = config.COMPONENTS_DIR / f"{stem}.json"
        tex_path = config.TEX_DIR / f"{stem}.tex"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        tex_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(components, indent=2, ensure_ascii=False), encoding="utf-8")
        tex_path.write_text(render_resume(row, components, profile), encoding="utf-8")
        pdf_ok, pdf_message = _compile(tex_path, config.PDF_DIR) if compile_pdf else (False, "skipped")
        results.append({"index": index, "job_url": str(row.get("job_url", "")), "title": str(row.get("title", "")), "company": str(row.get("company", "")), "method": method, "components_json": str(json_path), "resume_tex": str(tex_path), "resume_pdf": str(config.PDF_DIR / f"{tex_path.stem}.pdf") if pdf_ok else "", "pdf": pdf_ok, "pdf_message": pdf_message})
        activity.log_event("phase2", "job_done", f"resume {index}/{len(df)} for {row.get('company', '')} | method={method} | pdf={'OK' if pdf_ok else pdf_message}", index=index, company=str(row.get("company", "")), title=str(row.get("title", "")), method=method, pdf=pdf_ok, status="ok" if pdf_ok else "warn")
    config.PHASE2_REPORT.parent.mkdir(parents=True, exist_ok=True)
    config.PHASE2_REPORT.write_text(json.dumps({"jobs_processed": len(results), "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    return results
