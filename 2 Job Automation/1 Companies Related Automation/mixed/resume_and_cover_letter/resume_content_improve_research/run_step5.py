"""Step 5: build pdf/docx -> parse back -> gates -> scorecard -> triage -> report.

Builds a resume for every gated_ok job from step 4. Per job:
  1. fill the @@TOKEN@@ template (collision-proof) and write the .tex
  2. compile with tectonic, build the DOCX mirror
  3. parse the PDF back (parser simulation) — verification runs on THIS text
  4. post-build gates G1 + G3-artifact; fail -> the resume is NOT shipped
     (moved to output_v2/failed/ with the reason)
  5. coverage over the extracted text -> scorecard -> gap report
Writes output_v2/resume_report.json (v2 schema, verification page source).

Cover letters are intentionally NOT built here: step 6 (run_step6.py) creates
every letter AFTER all resume work has completed, into its own separate files
(letters_report.json + application_bundles.json). This keeps the resume phase
and the letter phase independently re-runnable and debuggable.

Run:  python resume_content_improve_research/run_step5.py [--help]
      (or via the end-to-end entrypoint: python main.py)
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# direct-run bootstrap: make the project root importable (python .../run_step5.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from resume_content_improve_research import config
from resume_content_improve_research.generation import kb_loader

from resume_content_improve_research.templates.build import (
    build_docx,
    compile_pdf,
    find_latex_engine,
    safe_name,
)
from resume_content_improve_research.templates.fill import fill_template

from resume_content_improve_research.verification.coverage import score_coverage
from resume_content_improve_research.verification.gates import run_postbuild_gates
from resume_content_improve_research.verification.parse_sim import parse_pdf
from resume_content_improve_research.verification.scorecard import build_scorecard
from resume_content_improve_research.verification.triage import write_shortlist

config.ensure_utf8_stdout()

EDUCATION_LINES = [
    "MSc Artificial Intelligence - Brandenburgische Technische Universität Cottbus-Senftenberg, Germany (April 2025 - Current)",
    "BE Computer Engineering - Gujarat Technological University, India (June 2020 - May 2024)",
]


def load_components() -> list[dict]:
    path = config.OUTPUT_DIR / "components_v2.json"
    if not path.exists():
        raise RuntimeError(f"components file not found: {path} — run run_step4.py first")
    return json.loads(path.read_text(encoding="utf-8"))





def build_record(record: dict, engine: str | None, name: str | None = None) -> dict:
    """Build + verify one job; returns the enriched report record."""
    out = {
        "job_url": record.get("job_url", ""),
        "title": record.get("title", ""),
        "company": record.get("company", ""),
        "status": record.get("status", ""),
        "tex": "", "pdf": "", "docx": "",
        "build_error": "",
        "gates": {"G1": True, "G2": not record.get("gate_findings"), "G3": True},
        "gate_findings_prebuild": record.get("gate_findings", []),
        "gate_findings_postbuild": [],
        "score": None,
        "score_breakdown": None,
        "required_coverage": None,
        "preferred_coverage": None,
        "gap_report": None,
        "llm_calls": (record.get("generation_meta") or {}).get("calls"),
        "artifacts": {"resume_pdf": "", "resume_docx": ""},
    }
    if record.get("status") != "gated_ok" or not record.get("components"):
        out["build_error"] = record.get("error") or f"status {record.get('status')}"
        out["gates"]["G2"] = False
        return out

    from resume_content_improve_research.generation.factual_content import (
        ground_components,
        resume_static_sections,
        static_section_values,
    )

    kb = kb_loader.load_kb()
    analysis = record.get("analysis") or {}
    components = ground_components(record["components"], analysis, kb)
    from resume_content_improve_research.generation.claimable_set import build_claimable_set
    from resume_content_improve_research.run_step4 import intent_text_for
    from resume_content_improve_research.verification.gates import run_prebuild_gates

    cset = build_claimable_set(analysis, kb)
    prebuild = run_prebuild_gates(
        intent_text_for(components), components["experiences"], cset, kb_loader.licensed_digits(kb))
    out["gates"]["G2"] = all(result.passed for result in prebuild)
    out["gate_findings_prebuild"] = [finding for result in prebuild for finding in result.findings]
    if not out["gates"]["G2"]:
        out["status"] = "gated_failed"
        out["build_error"] = "grounded content failed pre-build gates: " + "; ".join(
            out["gate_findings_prebuild"][:6])
        return out

    profile = components.get("profile", {})
    doc_components = {
        "profile": {
            "full_name": profile.get("full_name", "RAVAL MEETKUMAR RITESHKUMAR"),
            "contact_line": profile.get("contact_line", ""),
        },
        "objective": components["objective"],
        "experience": components["experiences"],
        "projects": components["projects"],
        "skills_section": components["skills_section"],
        "education_lines": EDUCATION_LINES,
        "static_sections": resume_static_sections(kb),
    }

    from resume_content_improve_research.generation.generator import GeneratedComponents

    gen = GeneratedComponents(
        objective=components["objective"],
        skills_section=components["skills_section"],
        experiences=components["experiences"],
        projects=components["projects"],
        raw={},
    )
    gen.raw["profile"] = profile

    # The deduped stem from main() wins when provided; titles like "Working Student"
    # and "Working Student (m/f/d)" sanitize to the same stem and must not overwrite
    # each other's PDF on disk (measured: the second build silently replaced the first).
    name = name or safe_name(record.get("title") or "resume")
    try:
        template = config.TEMPLATE_TEX.read_text(encoding="utf-8")
        values = gen.to_fill_values()
        values.update(static_section_values(kb))
        filled = fill_template(template, values)
        tex_path = config.TEX_DIR / f"{name}.tex"
        config.TEX_DIR.mkdir(parents=True, exist_ok=True)
        tex_path.write_text(filled, encoding="utf-8")
        out["tex"] = str(tex_path)

        pdf_ok, message = compile_pdf(tex_path, config.PDF_DIR / f"{name}.pdf", engine)
        if pdf_ok:
            out["pdf"] = str(config.PDF_DIR / f"{name}.pdf")
        else:
            out["build_error"] = f"pdf: {message}"
            out["gates"]["G3"] = False
            return out

        docx_path = config.DOCX_DIR / f"{name}.docx"
        try:
            build_docx(docx_path, doc_components)
            out["docx"] = str(docx_path)
        except Exception as exc:  # noqa: BLE001 - docx failure must not kill the pdf
            out["build_error"] = f"docx: {type(exc).__name__}: {exc}"

        # ---- verification on the parsed-back artifact
        parsed = parse_pdf(config.PDF_DIR / f"{name}.pdf")
        results = run_postbuild_gates(parsed.text, parsed.word_count, filled)
        # Resume PDF page count is a hard deliverable criterion. The one-page
        # source template and all artifacts are checked below after compilation.
        by_gate = {r.gate: r for r in results}
        out["gates"]["G1"] = by_gate["G1"].passed
        out["gates"]["G3"] = by_gate["G3"].passed
        out["gate_findings_postbuild"] = [f for r in results for f in r.findings]
        out["parse"] = {
            "word_count": parsed.word_count,
            "name_extracted": parsed.name_extracted,
            "email_extracted": parsed.email_extracted,
            "phone_extracted": parsed.phone_extracted,
            "dates_found": parsed.dates_found,
            "apostrophe_dates": parsed.apostrophe_dates,
            "sections_found": parsed.sections_found,
            "ligature_count": parsed.ligature_count,
            "reading_order_ok": parsed.reading_order_ok,
        }
        import pdfplumber
        with pdfplumber.open(config.PDF_DIR / f"{name}.pdf") as built_pdf:
            page_count = len(built_pdf.pages)
        out["parse"]["page_count"] = page_count
        if page_count != 1:
            out["gates"]["G1"] = False
            out["gate_findings_postbuild"].append(
                f"G1: expected a one-page resume, found {page_count} pages")

        if not (by_gate["G1"].passed and by_gate["G3"].passed and page_count == 1):
            # fail = never ship: move the artifacts to failed/
            failed_dir = config.RUNS_FAILED_DIR
            failed_dir.mkdir(parents=True, exist_ok=True)
            for key in ("pdf", "docx", "tex"):
                if out.get(key):
                    shutil.move(out[key], failed_dir / Path(out[key]).name)
                    out[key] = ""
            out["build_error"] = (out["build_error"] + " | gated: " + "; ".join(
                out["gate_findings_postbuild"][:5])).strip(" |")
            out["gates"]["G3"] = False
            return out

        # ---- coverage + scorecard over the extracted text
        cset = build_claimable_set(analysis, kb)
        coverage = score_coverage(parsed.text, analysis)
        intent = " | ".join(filter(None, [
            components["objective"],
            ", ".join(components["skills_section"]["languages"]),
            ", ".join(components["skills_section"]["specialized_areas"]),
        ] + [", ".join(a["skills"]) for a in components["skills_section"]["areas"]] + [
            e["description"] for e in components["experiences"]
        ] + [", ".join(e["skills"]) for e in components["experiences"]] + [
            p["description"] for p in components["projects"]
        ] + [", ".join(p["skills"]) for p in components["projects"]]))
        card = build_scorecard(True, coverage, parsed, filled, intent, analysis, cset,
                               page_count=page_count)
        out["score"] = card.total
        out["score_breakdown"] = card.breakdown
        out["required_coverage"] = card.required_coverage
        out["preferred_coverage"] = card.preferred_coverage
        out["gap_report"] = card.gaps
        out["tailoring"] = record.get("tailoring") or {}
        out["status"] = "verified"

        # Resume artifact paths for the step-6 application manifest: step 6
        # joins on these to compute per-portal bundle completeness.
        out["artifacts"]["resume_pdf"] = out.get("pdf", "")
        out["artifacts"]["resume_docx"] = out.get("docx", "")
    except Exception as exc:  # noqa: BLE001 - one job failure never stops the run
        out["build_error"] = f"{type(exc).__name__}: {exc}"
        out["gates"]["G3"] = False
    return out


def main(limit: int | None = None, jobs: str | None = None) -> int:
    token_note = "(pdf builds need the bundled tectonic)" if find_latex_engine() is None else ""
    engine = find_latex_engine()
    print(f"[V2] step 5: LaTeX engine {engine or 'NONE'} {token_note}")

    records = load_components()
    if jobs:
        substrs = [j.strip() for j in str(jobs).split(",") if j.strip()]
        records = [r for r in records if any(s in str(r.get("job_url", "")) for s in substrs)]
    if limit:
        records = records[:limit]
    results: list[dict] = []
    total = len(records)
    seen_names: dict[str, int] = {}
    for index, record in enumerate(records, 1):
        title = record.get("title") or "resume"
        name = safe_name(title)
        if name in seen_names:
            seen_names[name] += 1
            name = f"{name}-{seen_names[name]}"
        else:
            seen_names[name] = 1
        print(f"[V2] [{index}/{total}] {title[:60]}")
        result = build_record(record, engine, name=name)
        result["file_stem"] = name
        print(f"    -> {result['status']}" + (
            f" score={result['score']}" if result.get("score") is not None else "") + (
            f" ({result['build_error'][:80]})" if result.get("build_error") else ""))
        results.append(result)

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "v2",
        "total_jobs": total,
        "results": results,
    }
    config.REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Application triage: rank verified resumes, persist shortlist.json.
    # (The letter bundles manifest is step 6's output — see run_step6.py.)
    shortlist = write_shortlist(results)

    verified = sum(1 for r in results if r["status"] == "verified")
    scores = [r["score"] for r in results if r.get("score") is not None]
    if scores:
        print(f"\n[V2] summary: {verified}/{total} verified | avg score {sum(scores)/len(scores):.1f}")
    else:
        print(f"\n[V2] summary: {verified}/{total} verified")
    counts = shortlist.get("counts", {})
    print(f"[V2] triage: {counts.get('strong', 0)} strong / {counts.get('good', 0)} good / "
          f"{counts.get('weak', 0)} weak / {counts.get('poor', 0)} poor")
    print(shortlist.get("recommendation", ""))
    print(f"[V2] report -> {config.REPORT_PATH}")
    print(f"[V2] shortlist -> {config.OUTPUT_DIR / 'shortlist.json'}")
    print(f"[V2] pdf -> {config.PDF_DIR}")
    print("[V2] letters + bundles are created by step 6 (run_step6.py)")
    return 0 if verified == total and total > 0 else 1


if __name__ == "__main__":
    import argparse

    # parse_args() gives -h/--help for free; the step itself takes no options.
    argparse.ArgumentParser(description="build + verify resumes (step 5)").parse_args()
    raise SystemExit(main())
