"""Standalone Phase 3: cover letters, application packages, and validation."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.core import config
from app.core import activity
from app.core import ollama_client
from app.phase2 import resume_generator as phase2


def _safe_stem(row: pd.Series, index: int) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{index:03d}_{row.get('company', 'company')}_{row.get('title', 'role')}").strip("._")
    return value[:120] or f"application_{index:03d}"


def _escape(value: Any) -> str:
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    text = str(value or "").replace("–", "-").replace("—", "-").replace("‑", "-").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace(" ", " ").replace(" ", " ")
    return "".join(replacements.get(ch, ch) for ch in text)


def _job_context(row: pd.Series) -> str:
    keys = ("title", "company", "location", "job_description", "requirements", "your_tasks", "what_they_offer")
    return "\n".join(f"{key}: {row.get(key, '')}" for key in keys if str(row.get(key, "")).strip())[:7000]


def _fallback(row: pd.Series, profile: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    title = str(row.get("title", "the role")).strip()
    company = str(row.get("company", "the company")).strip()
    name = str(profile.get("display_name") or profile.get("name") or "Candidate")
    skills: list[str] = []
    for values in (components.get("skills") or {}).values():
        skills.extend(str(x) for x in values)
    return {
        "subject": f"Application for {title} at {company}",
        "greeting": "Dear Hiring Team,",
        "opening": f"I am writing to apply for the {title} position at {company}. My background and practical experience make this opportunity a strong match for my goals.",
        "fit_summary": [
            f"Relevant strengths include {', '.join(skills[:5]) or 'software engineering and analytical problem solving'}.",
            str(components.get("objective", "")).strip()[:300],
            "I learn quickly, communicate clearly, and am motivated to contribute reliably to your team.",
        ],
        "closing": "Thank you for considering my application. I would welcome the opportunity to discuss how I can contribute to your team.",
        "signoff": "Sincerely,",
        "applicant_name": name,
    }


def _valid_payload(value: Any) -> bool:
    return isinstance(value, dict) and bool(str(value.get("opening", "")).strip()) and isinstance(value.get("fit_summary"), list) and bool(value.get("fit_summary"))


def generate_cover_letter(row: pd.Series, profile: dict[str, Any], components: dict[str, Any], use_llm: bool = True) -> tuple[dict[str, Any], str]:
    fallback = _fallback(row, profile, components)
    if not use_llm:
        return fallback, "template"
    prompt = (
        "Return ONLY valid JSON with keys subject, greeting, opening, fit_summary, closing, signoff, applicant_name. "
        "Write a truthful tailored cover letter using only the profile and resume components; never invent facts. "
        "fit_summary must contain 2-4 concise strings.\nJOB:\n" + _job_context(row) +
        "\nPROFILE:\n" + json.dumps(profile, ensure_ascii=False, default=str)[:9000] +
        "\nRESUME COMPONENTS:\n" + json.dumps(components, ensure_ascii=False, default=str)[:7000]
    )
    try:
        payload = ollama_client.call_json(prompt)
        return (payload, "ollama") if _valid_payload(payload) else (fallback, "template")
    except Exception as exc:
        print(f"[PHASE3] Ollama unavailable ({type(exc).__name__}); using truthful fallback")
        return fallback, "template"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [f"# {payload.get('applicant_name', '')}", f"**Subject:** {payload.get('subject', '')}", "", str(payload.get('greeting', 'Dear Hiring Team,')), "", str(payload.get('opening', '')), ""]
    lines.extend(f"- {item}" for item in payload.get("fit_summary", []))
    lines.extend(["", str(payload.get("closing", "")), "", str(payload.get("signoff", "")), str(payload.get("applicant_name", "")), ""])
    return "\n".join(lines)


def render_tex(payload: dict[str, Any], profile: dict[str, Any]) -> str:
    contact = " | ".join(_escape(profile.get(k, "")) for k in ("email", "phone", "address") if str(profile.get(k, "")).strip())
    lines = [r"\documentclass[a4paper,11pt]{article}", r"\usepackage[margin=2cm]{geometry}", r"\usepackage[T1]{fontenc}", r"\usepackage{enumitem}", r"\pagestyle{empty}", r"\begin{document}", rf"{{\Large\textbf{{{_escape(payload.get('applicant_name'))}}}}}", _escape(contact), "", datetime.now().strftime("%d %B %Y"), "", rf"\textbf{{Subject:}} {_escape(payload.get('subject'))}", "", _escape(payload.get("greeting")), "", _escape(payload.get("opening")), "", r"\begin{itemize}[leftmargin=1.2em]"]
    lines.extend(rf"\item {_escape(item)}" for item in payload.get("fit_summary", []))
    lines.extend([r"\end{itemize}", "", _escape(payload.get("closing")), "", _escape(payload.get("signoff")), "", _escape(payload.get("applicant_name")), r"\end{document}"])
    return "\n".join(lines) + "\n"


def compile_pdf(tex_path: Path, pdf_path: Path) -> tuple[bool, str]:
    compiler = config.find_latex_compiler()
    if not compiler:
        return False, "no LaTeX compiler found"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        outdir = pdf_path.parent
        if Path(compiler).stem.lower() == "tectonic":
            command = [compiler, str(tex_path), "--outdir", str(outdir)]
        else:
            command = [compiler, "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={outdir}", str(tex_path)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        built = outdir / f"{tex_path.stem}.pdf"
        if not built.exists():
            alternate = Path(str(outdir) + "\\" + f"{tex_path.stem}.pdf")
            if alternate.exists():
                built = alternate
        if result.returncode == 0 and built.exists():
            if built.resolve() != pdf_path.resolve():
                shutil.copy2(built, pdf_path)
            return True, "compiled"
        if built.exists():
            return True, "compiled with warnings"
        return False, (result.stderr or result.stdout)[-500:] or "compiler failed"
    except Exception as exc:
        return False, f"compile error: {type(exc).__name__}: {exc}"


def _load_components(row: pd.Series, index: int) -> dict[str, Any]:
    prefix = phase2._safe_stem(row, index)
    path = config.COMPONENTS_DIR / f"{prefix}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    components, _ = phase2.build_components(row, phase2.load_profile(), use_llm=False)
    return components


def run_phase3(input_csv: Path | None = None, limit: int | None = None, use_llm: bool = True, compile_pdfs: bool = True) -> list[dict[str, Any]]:
    source = input_csv or config.COMBINED_CSV
    if not source.exists():
        raise FileNotFoundError(f"jobs CSV not found: {source}")
    df = pd.read_csv(source, keep_default_na=False)
    if limit is not None:
        df = df.head(limit)
    profile = phase2.load_profile()
    letter_dir = config.PHASE3_DIR / "cover_letters"
    md_dir, tex_dir, pdf_dir = letter_dir, letter_dir / "tex", letter_dir / "pdf"
    for directory in (md_dir, tex_dir, pdf_dir):
        directory.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for index, (_, row) in enumerate(df.iterrows(), 1):
        components = _load_components(row, index)
        payload, method = generate_cover_letter(row, profile, components, use_llm=use_llm)
        stem = _safe_stem(row, index)
        md_path, tex_path, pdf_path = md_dir / f"{stem}.md", tex_dir / f"{stem}.tex", pdf_dir / f"{stem}.pdf"
        md_path.write_text(render_markdown(payload), encoding="utf-8")
        tex_path.write_text(render_tex(payload, profile), encoding="utf-8")
        pdf_ok, message = compile_pdf(tex_path, pdf_path) if compile_pdfs else (False, "skipped")
        results.append({"index": index, "job_url": str(row.get("job_url", "")), "title": str(row.get("title", "")), "company": str(row.get("company", "")), "method": method, "cover_letter_md": str(md_path), "cover_letter_tex": str(tex_path), "cover_letter_pdf": str(pdf_path) if pdf_ok else "", "pdf": pdf_ok, "application_status": "ready_for_review", "message": message})
        activity.log_event("phase3", "job_done", f"cover letter {index}/{len(df)} for {row.get('company', '')} | method={method} | pdf={'OK' if pdf_ok else message}", index=index, company=str(row.get("company", "")), title=str(row.get("title", "")), method=method, pdf=pdf_ok, status="ok" if pdf_ok else "warn")
    manifest = pd.DataFrame(results)
    config.APPLICATIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(config.APPLICATIONS_CSV, index=False, encoding="utf-8")
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "jobs_processed": len(results), "pdfs_created": sum(bool(x["pdf"]) for x in results), "output_csv": str(config.APPLICATIONS_CSV), "results": results}
    config.PHASE3_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return results
