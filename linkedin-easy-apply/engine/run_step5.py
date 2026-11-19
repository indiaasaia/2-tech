"""Step 5: build pdf/docx -> parse back -> gates -> scorecard -> triage -> report.

Builds a resume for every gated_ok job from step 4. Per job:
  1. fill the @@TOKEN@@ template (collision-proof) and write the .tex
  2. compile with tectonic, build the DOCX mirror
  3. parse the PDF back (parser simulation) — verification runs on THIS text
  4. post-build gates G1 + G3-artifact; fail -> the resume is NOT shipped
     (moved to output/applications/failed/ with the reason)
  5. coverage over the extracted text -> scorecard -> gap report
Writes output/applications/resume_report.json (v2 schema, verification page source).

Cover letters are intentionally NOT built here: step 6 (run_step6.py) creates
every letter AFTER all resume work has completed, into its own separate files
(letters_report.json + application_bundles.json). This keeps the resume phase
and the letter phase independently re-runnable and debuggable.

Run:  python engine/run_step5.py [--help]
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

from engine import config
from engine.generation import kb_loader

from engine.templates.build import (
    build_docx,
    compile_pdf,
    cv_file_stem,
    find_latex_engine,
)
from engine.templates.fill import fill_template
from engine.templates.render import latex_fill_values, resume_document

from engine.verification.coverage import score_coverage
from engine.verification.gates import run_postbuild_gates
from engine.verification.keyword_gate import check_artifacts, ensure_keywords, kb_backing
from engine.verification.prep import write_prep_files
from engine.verification.parse_sim import parse_pdf
from engine.verification.scorecard import build_scorecard
from engine.verification.triage import write_shortlist

config.ensure_utf8_stdout()


def _quarantine(out: dict, findings: list[str]) -> dict:
    """Fail = never ship: move the built artifacts to failed/ and record why."""
    failed_dir = config.RUNS_FAILED_DIR
    failed_dir.mkdir(parents=True, exist_ok=True)
    for key in ("pdf", "docx", "tex"):
        if out.get(key):
            shutil.move(out[key], failed_dir / Path(out[key]).name)
            out[key] = ""
    out["build_error"] = (out["build_error"] + " | gated: " + "; ".join(findings[:5])).strip(" |")
    out["gates"]["G3"] = out["gates"].get("G3", True) and not any(f.startswith("G") for f in findings)
    return out


def _docx_text(path: str) -> str:
    """All paragraph text of a built DOCX (what a DOCX-parsing ATS reads)."""
    from docx import Document

    return "\n".join(p.text for p in Document(path).paragraphs)


def resume_file_stem(record: dict, kb: dict) -> str:
    """'Meetkumar_Raval_CV_<Company>_<Role>' — the name recruiters see in the portal."""
    profile = kb_loader.profile(kb)
    names = str(profile.get("name") or "").split()
    first = str(profile.get("first_name") or (names[0] if names else ""))
    last = str(profile.get("last_name") or (names[-1] if names else ""))
    return cv_file_stem(first, last, str(record.get("company") or ""), str(record.get("title") or ""))


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

    from engine.generation.factual_content import ground_components

    kb = kb_loader.load_kb()
    analysis = record.get("analysis") or {}
    from engine.generation.keywords import plan_for_record

    # Always rebuild the plan from the posting (deterministic, zero LLM calls): step 6
    # does the same, so resume and letter share one plan and keyword-plan fixes apply
    # without a step-4 re-run. The stored plan is only the fallback.
    try:
        plan = plan_for_record(record).to_dict()
    except Exception:  # noqa: BLE001 - malformed legacy record
        plan = record.get("keywords") or {}
    components = ground_components(record["components"], analysis, kb, plan=plan)
    out["grounding_findings"] = components.get("grounding_findings", [])
    out["grounded_components"] = {            # what is printed, for audits + dashboard
        "objective": components.get("objective", ""),
        "experiences": [{"id": e.get("id"), "bullets": e.get("bullets", [])} for e in components.get("experiences", [])],
        "projects": [{"id": e.get("id"), "bullets": e.get("bullets", [])} for e in components.get("projects", [])],
    }
    out["keyword_targets"] = len(plan.get("targets") or [])
    from engine.generation.claimable_set import build_claimable_set
    from engine.run_step4 import intent_text_for
    from engine.verification.gates import run_prebuild_gates

    cset = build_claimable_set(analysis, kb, keywords=plan.get("targets"))
    prebuild = run_prebuild_gates(
        intent_text_for(components), components["experiences"], cset, kb_loader.licensed_digits(kb))
    out["gates"]["G2"] = all(result.passed for result in prebuild)
    out["gate_findings_prebuild"] = [finding for result in prebuild for finding in result.findings]
    if not out["gates"]["G2"]:
        out["status"] = "gated_failed"
        out["build_error"] = "grounded content failed pre-build gates: " + "; ".join(
            out["gate_findings_prebuild"][:6])
        return out

    # ONE document model feeds both the PDF and the DOCX (templates/render.py)
    doc = resume_document(components, kb, plan)
    # 100% keyword gate, pre-build half: any target still missing is placed now
    out["keywords_inserted"] = ensure_keywords(doc, plan)

    # The deduped stem from main() wins when provided; two postings may sanitize to
    # the same stem and must not overwrite each other's PDF on disk.
    name = name or resume_file_stem(record, kb)
    try:
        template = config.TEMPLATE_TEX.read_text(encoding="utf-8")
        filled = fill_template(template, latex_fill_values(doc))
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
            build_docx(docx_path, doc)
            out["docx"] = str(docx_path)
        except Exception as exc:  # noqa: BLE001 - docx failure must not kill the pdf
            out["build_error"] = f"docx: {type(exc).__name__}: {exc}"

        # ---- verification on the parsed-back artifact
        parsed = parse_pdf(config.PDF_DIR / f"{name}.pdf")
        results = run_postbuild_gates(parsed.text, parsed.word_count, filled)
        # Page count is a hard deliverable criterion: at most config.MAX_PAGES
        # (plan v3: page 2 is allowed rather than dropping keywords).
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
        pages_ok = 1 <= page_count <= config.MAX_PAGES
        if not pages_ok:
            out["gates"]["G1"] = False
            out["gate_findings_postbuild"].append(
                f"G1: expected at most {config.MAX_PAGES} pages, found {page_count}")

        if not (by_gate["G1"].passed and by_gate["G3"].passed and pages_ok):
            return _quarantine(out, out["gate_findings_postbuild"])

        # ---- 100% keyword gate, post-build half: every target in the parsed PDF
        #      AND the DOCX (a keyword lost in rendering never ships)
        docx_text = _docx_text(out["docx"]) if out.get("docx") else None
        gate = check_artifacts(plan, parsed.text, docx_text)
        out["keyword_gate"] = gate
        out["keyword_coverage"] = gate["coverage"]
        if not gate["passed"]:
            out["gates"]["KW"] = False
            return _quarantine(out, [
                f"KW: keyword missing from {fmt}: {terms[:6]}"
                for fmt, terms in (("pdf", gate["missing_pdf"]), ("docx", gate["missing_docx"])) if terms])
        out["gates"]["KW"] = True
        backing = kb_backing(plan, kb)
        out["kb_backed_share"] = backing["kb_backed_share"]
        out["prep_terms"] = backing["prep_terms"]

        # ---- coverage + scorecard over the extracted text
        cset = build_claimable_set(analysis, kb, keywords=plan.get("targets"))
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
        out["gap_report"] = {
            **card.gaps,
            # policy v3: skill keywords are all printed; what remains are facts a
            # resume line cannot make true, plus the terms to learn before interviews
            "education_gaps": gate["education_gaps"],
            "eligibility": gate["eligibility"],
            "prep_terms": backing["prep_terms"],
        }
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


def _previous_results() -> dict[str, dict]:
    """Step-5 results of the last run, keyed by job_url ({} when there is none)."""
    if not config.REPORT_PATH.exists():
        return {}
    try:
        report = json.loads(config.REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(r.get("job_url") or ""): r for r in report.get("results", [])}


def main(only_urls: set[str] | None = None) -> int:
    """Build + verify resumes. `only_urls` (run.py: the jobs of this run) builds just
    those; every other stored job keeps its previous result, so a daily run does
    not rebuild weeks of old resumes."""
    token_note = "(pdf builds need the bundled tectonic)" if find_latex_engine() is None else ""
    engine = find_latex_engine()
    print(f"[V2] step 5: LaTeX engine {engine or 'NONE'} {token_note}")

    records = load_components()
    kb = kb_loader.load_kb()
    previous = _previous_results() if only_urls is not None else {}
    results: list[dict] = []
    total = len(records)
    seen_names: dict[str, int] = {}
    for index, record in enumerate(records, 1):
        title = record.get("title") or "resume"
        name = resume_file_stem(record, kb)
        if name in seen_names:
            seen_names[name] += 1
            name = f"{name}-{seen_names[name]}"
        else:
            seen_names[name] = 1
        url = str(record.get("job_url") or "")
        if only_urls is not None and url not in only_urls and url in previous:
            results.append(previous[url])          # built in an earlier run, unchanged
            continue
        print(f"[V2] [{index}/{total}] {title[:60]}")
        result = build_record(record, engine, name=name)
        result["file_stem"] = name
        print(f"    -> {result['status']}" + (
            f" score={result['score']}" if result.get("score") is not None else "") + (
            f" keywords={result['keyword_coverage']:.0%}" if result.get("keyword_coverage") is not None else "") + (
            f" kb_backed={result['kb_backed_share']:.0%}" if result.get("kb_backed_share") is not None else "") + (
            f" ({result['build_error'][:80]})" if result.get("build_error") else ""))
        results.append(result)

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Interview prep: per-job sheets + cross-job learning priorities (sets prep_file)
    prep = write_prep_files(results, records, kb)
    top = ", ".join(f"{p['term']} ({p['jobs']})" for p in prep["priorities"][:8])
    print(f"[V2] interview prep: {prep['prep_files']} sheet(s) -> {config.OUTPUT_DIR / 'prep'}"
          + (f" | learn first: {top}" if top else ""))
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "v2",
        "total_jobs": total,
        "results": results,
    }
    config.REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    from engine.templates.build import archive_stale

    keep = {Path(str(r.get(k))).stem for r in results for k in ("tex", "pdf", "docx") if r.get(k)}
    stale = archive_stale((config.TEX_DIR, config.PDF_DIR, config.DOCX_DIR), keep, config.OUTPUT_DIR / "stale")
    if stale:
        print(f"[V2] moved {len(stale)} stale resume file(s) -> {config.OUTPUT_DIR / 'stale'}")

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
