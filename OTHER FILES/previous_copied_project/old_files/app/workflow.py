"""Sequential end-to-end workflow for finalized jobs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.core import config
from app.core import activity
from app.phase2 import resume_generator
from app.phase3 import application_generator


def run_sequential(input_csv: Path | None = None, limit: int | None = None, use_llm: bool = True, compile_pdfs: bool = True) -> list[dict[str, Any]]:
    source = input_csv or config.COMBINED_CSV
    if not source.exists():
        raise FileNotFoundError(f"Finalized jobs CSV not found: {source}")
    jobs = pd.read_csv(source, keep_default_na=False)
    if limit is not None:
        jobs = jobs.head(limit)
    profile = resume_generator.load_profile()
    results: list[dict[str, Any]] = []
    for index, (_, row) in enumerate(jobs.iterrows(), 1):
        # Each job is completed fully before the next job begins.
        components, resume_method = resume_generator.build_components(row, profile, use_llm=use_llm)
        stem = resume_generator._safe_stem(row, index)
        component_path = config.COMPONENTS_DIR / f"{stem}.json"
        tex_path = config.TEX_DIR / f"{stem}.tex"
        pdf_path = config.PDF_DIR / f"{stem}.pdf"
        component_path.parent.mkdir(parents=True, exist_ok=True)
        tex_path.parent.mkdir(parents=True, exist_ok=True)
        component_path.write_text(json.dumps(components, indent=2, ensure_ascii=False), encoding="utf-8")
        tex_path.write_text(resume_generator.render_resume(row, components, profile), encoding="utf-8")
        resume_pdf_ok, resume_message = resume_generator._compile(tex_path, pdf_path) if compile_pdfs else (False, "skipped")

        letter_payload, letter_method = application_generator.generate_cover_letter(row, profile, components, use_llm=use_llm)
        letter_dir = config.PHASE3_DIR / "cover_letters"
        md_path, letter_tex, letter_pdf = letter_dir / f"{stem}.md", letter_dir / "tex" / f"{stem}.tex", letter_dir / "pdf" / f"{stem}.pdf"
        for directory in (letter_dir, letter_tex.parent, letter_pdf.parent):
            directory.mkdir(parents=True, exist_ok=True)
        md_path.write_text(application_generator.render_markdown(letter_payload), encoding="utf-8")
        letter_tex.write_text(application_generator.render_tex(letter_payload, profile), encoding="utf-8")
        letter_pdf_ok, letter_message = application_generator.compile_pdf(letter_tex, letter_pdf) if compile_pdfs else (False, "skipped")

        result = {
            "index": index, "job_url": str(row.get("job_url", "")), "title": str(row.get("title", "")), "company": str(row.get("company", "")),
            "resume_method": resume_method, "resume_components": str(component_path), "resume_tex": str(tex_path),
            "resume_pdf": str(pdf_path) if resume_pdf_ok else "", "resume_pdf_ok": resume_pdf_ok, "resume_message": resume_message,
            "cover_method": letter_method, "cover_letter_md": str(md_path), "cover_letter_tex": str(letter_tex),
            "cover_letter_pdf": str(letter_pdf) if letter_pdf_ok else "", "cover_letter_pdf_ok": letter_pdf_ok, "cover_message": letter_message,
            "application_status": "ready_for_review" if resume_pdf_ok and letter_pdf_ok else "needs_attention",
        }
        results.append(result)
        print(f"[WORKFLOW {index}/{len(jobs)}] {result['company']} | resume={'OK' if resume_pdf_ok else 'FAIL'} | cover={'OK' if letter_pdf_ok else 'FAIL'}")
        activity.log_event("workflow", "job_done", f"{result['application_status']}: {result['company']} | resume={result['resume_method']} | cover={result['cover_method']}", index=index, company=result["company"], title=result["title"], status=result["application_status"])

    config.APPLICATIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).to_csv(config.APPLICATIONS_CSV, index=False, encoding="utf-8")
    config.PHASE3_REPORT.write_text(json.dumps({"workflow": "sequential", "jobs_processed": len(results), "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    return results
