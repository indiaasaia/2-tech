"""Step 6: cover letters (Anschreiben) — created AFTER all resume work.

Runs strictly after step 5. By the time this starts, every resume is built,
verified and scored, so letter creation can never block or corrupt the resume
phase — and a parked letter never costs a resume. The two phases share no
writes: step 6 owns its own separate files.

Per gated_ok job (components_v2.json + the step-5 resume_report.json):
  1. letter_input (stored by step 4) -> deterministic skeleton -> ONE
     constrained LLM call -> post-checks -> gates L1-L4 (a failing letter
     parks here; the resume was already shipped by step 5)
  2. probe_date_line (build-day date) -> re-gate -> fill the @@CL_TOKEN@@
     template (de/en) -> L3 artifact check -> compile
  3. SEPARATE FILES per letter: Anschreiben_<Company>_<Role>.{tex,pdf,docx,txt}
  4. letters_report.json + application_bundles.json (per-portal upload guide)

Legacy migration: gated_ok records written by the pre-step-6 engine (letter
stored inside components.cover_letter, no letter_input) are re-gated and
rebuilt WITHOUT any LLM call, so an old run never needs a costly step-4
re-run just to get its letters.

Run:  python engine/run_step6.py [--jobs url1,url2] [--force]
      (or via the end-to-end entrypoint: python main.py)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# direct-run bootstrap: make the project root importable (python .../run_step6.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from engine import config
from engine.generation import kb_loader
from engine.generation.llm import load_first_key
from engine.generation.portal_delivery import (
    PORTAL_REQUIREMENTS,
    write_bundles,
)
from engine.templates.build import (
    build_letter_docx,
    compile_pdf,
    find_latex_engine,
)
from engine.templates.fill import fill_template

config.ensure_utf8_stdout()


def load_records() -> list[dict]:
    """The step-4 components store (gated_ok records carry letter_input)."""
    path = config.OUTPUT_DIR / "components_v2.json"
    if not path.exists():
        raise RuntimeError(f"components file not found: {path} — run run_step4.py first")
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise RuntimeError(f"no records in {path} — run run_step4.py first")
    return records


def load_resume_results() -> dict[str, dict]:
    """Step-5 report results keyed by job_url (resume status + artifact paths)."""
    if not config.REPORT_PATH.exists():
        return {}
    try:
        report = json.loads(config.REPORT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        str(r.get("job_url") or ""): r
        for r in report.get("results", [])
        if isinstance(r, dict)
    }


def letter_stem_for(title: str, company_name: str, language: str = "de") -> str:
    """Per-letter file stem the recruiter sees:
    'Meetkumar_Raval_Anschreiben_<Company>_<Role>' (German letters) or
    'Meetkumar_Raval_Cover_Letter_<Company>_<Role>' (English letters)."""
    from engine.templates.build import letter_file_names, safe_name

    profile = kb_loader.profile(kb_loader.load_kb())
    names = str(profile.get("name") or "").split()
    first = str(profile.get("first_name") or (names[0] if names else ""))
    last = str(profile.get("last_name") or (names[-1] if names else ""))
    person = "_".join(p for p in (safe_name(first), safe_name(last)) if p and p != "resume")
    company_part, role_part = letter_file_names(title, company_name)
    company_part = company_part.removeprefix("Anschreiben_")
    kind = "Anschreiben" if language == "de" else "Cover_Letter"
    return "_".join(p for p in (person, kind, company_part, role_part) if p)


def _build_artifacts(letter, stem: str, engine: str | None) -> tuple[dict[str, str], str]:
    """Fill -> L3 -> compile -> DOCX/TXT mirrors for an already-gated letter.

    Returns (artifacts, error); error is "" on full success. docx/txt
    failures are recorded but never kill the PDF.
    """
    from engine.generation.cover_letter import to_fill_values
    from engine.generation.portal_delivery import letter_plaintext
    from engine.verification.cl_gates import check_l3_artifact

    artifacts: dict[str, str] = {"letter_tex": "", "letter_pdf": "", "letter_docx": "", "letter_txt": ""}
    error = ""

    template_path = config.LETTER_TEMPLATE_DE if letter.language == "de" else config.LETTER_TEMPLATE_EN
    template = template_path.read_text(encoding="utf-8")
    filled = fill_template(template, to_fill_values(letter), tokens=config.CL_ALL_TOKENS)
    artifact_findings = check_l3_artifact(filled)
    if artifact_findings:
        return artifacts, "letter artifact checks failed: " + "; ".join(artifact_findings[:5])

    tex_path = config.LETTERS_TEX_DIR / f"{stem}.tex"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(filled, encoding="utf-8")
    artifacts["letter_tex"] = str(tex_path)

    pdf_ok, message = compile_pdf(tex_path, config.LETTERS_PDF_DIR / f"{stem}.pdf", engine)
    if not pdf_ok:
        return artifacts, f"letter pdf: {message}"
    artifacts["letter_pdf"] = str(config.LETTERS_PDF_DIR / f"{stem}.pdf")

    try:
        docx_path = config.LETTERS_DOCX_DIR / f"{stem}.docx"
        build_letter_docx(docx_path, letter)
        artifacts["letter_docx"] = str(docx_path)
    except Exception as exc:  # noqa: BLE001 - docx failure must not kill the pdf
        error = f"letter docx: {type(exc).__name__}: {exc}"

    try:
        txt_path = config.LETTERS_TXT_DIR / f"{stem}.txt"
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.write_text(letter_plaintext(letter), encoding="utf-8")
        artifacts["letter_txt"] = str(txt_path)
    except Exception as exc:  # noqa: BLE001 - txt failure must not kill the pdf
        error = (error + f"; txt: {exc}").strip("; ")

    return artifacts, error


def build_letter(record: dict, kb: dict, token: str, engine: str | None,
                 stem_override: str | None = None) -> dict:
    """Create + verify + build ONE letter (after all resume work). Never raises."""
    from engine import run_step4
    from engine.generation.cover_letter import (
        _candidate_facts_block,
        build_letter_claimable_set,
        letter_from_dict,
        letter_to_dict,
        probe_date_line,
    )
    from engine.verification.cl_gates import run_letter_gates

    out: dict = {
        "job_url": record.get("job_url", ""),
        "title": record.get("title", ""),
        "company": record.get("company", ""),
        "resume_status": record.get("status", ""),
        "letter": None,
        "letter_gates": None,
        "letter_gates_passed": False,
        "artifacts": {"letter_tex": "", "letter_pdf": "", "letter_docx": "", "letter_txt": "",
                      "resume_pdf": "", "resume_docx": ""},
        "upload_slot": "", "notes": "", "bundle_missing": [], "artifacts_complete": False,
        "letter_error": "",
        "llm_calls": 0,
    }

    try:
        if record.get("status") != "gated_ok":
            out["letter_error"] = f"resume not gated_ok ({record.get('status')}) — no letter attempted"
            return out

        letter_input = record.get("letter_input") or {}
        legacy_letter = (record.get("components") or {}).get("cover_letter") or {}
        analysis = record.get("analysis") or letter_input.get("analysis") or {}
        cset = build_letter_claimable_set(analysis, kb, letter_input.get("posting") or record)

        if letter_input:
            # ---- creation (the ONE LLM call), via the shared step-4 helper.
            # The record's CURRENT analysis wins over the stored one: the
            # retailor may have refreshed record["analysis"] after step 4, and
            # creation + gating must share one claim surface.
            letter_dict, meta = run_step4.process_letter_input(
                letter_input, kb, token, analysis_dict=analysis,
                candidate_facts=_candidate_facts_block(kb))
            letter = letter_from_dict(letter_dict)
            out["llm_calls"] = int(meta.get("calls", 0))
            out["letter_source"] = meta.get("letter_source", "")          # llm | fallback
            out["letter_optional"] = bool(meta.get("letter_optional"))
            out["letter_keywords_inserted"] = list(meta.get("keywords_inserted") or [])
            out["top_keywords"] = list(meta.get("top_keywords") or [])
            out["letter_attempts"] = meta.get("attempts", [])
            out["fact_checks"] = meta.get("fact_checks", [])
            out["trimmed_sentences"] = meta.get("trimmed_sentences", [])
            out["name_fixes"] = meta.get("name_fixes", [])
        elif legacy_letter:
            # ---- legacy migration: reuse the stored letter, no LLM cost
            letter = letter_from_dict(legacy_letter)
            letter.raw["legacy"] = True
        else:
            out["letter_error"] = "no letter_input on the record — re-run step 4"
            return out

        # ---- verification: the SAME L1-L4 gates, with the build-day date.
        # Creation-time gating already ran inside process_letter_input; this
        # re-gate catches stored/legacy letters drifted from their license.
        probe_date_line(letter)
        gate_results = run_letter_gates(letter, cset, kb_loader.licensed_digits(kb))
        findings = [f for r in gate_results for f in r.findings]
        out["letter_gates"] = {r.gate: {"passed": r.passed, "findings": r.findings} for r in gate_results}
        if findings:
            out["letter_error"] = "letter gates failed: " + "; ".join(findings[:6])
            return out
        out["letter_gates_passed"] = True

        # ---- SEPARATE FILES per letter:
        #      <First>_<Last>_{Anschreiben|Cover_Letter}_<Company>_<Role>.{tex,pdf,docx,txt}
        # stem_override: the caller pre-resolves stem collisions so the first
        # job's files can never be overwritten or moved after the fact.
        stem = stem_override or letter_stem_for(record.get("title") or "", letter.company_name, letter.language)
        artifacts, error = _build_artifacts(letter, stem, engine)
        out["artifacts"].update(artifacts)
        out["file_stem"] = stem
        if error and not artifacts.get("letter_pdf"):
            out["letter_error"] = error
            return out
        if error:
            out["letter_error"] = error  # docx/txt side failure; the PDF still shipped

        # ---- per-portal bundle, completed with the REAL step-5 resume paths
        resume_result = load_resume_results().get(str(record.get("job_url") or "")) or {}
        out["artifacts"]["resume_pdf"] = (resume_result.get("artifacts") or {}).get("resume_pdf") or resume_result.get("pdf", "")
        out["artifacts"]["resume_docx"] = (resume_result.get("artifacts") or {}).get("resume_docx") or resume_result.get("docx", "")

        portal = letter.portal or "unknown"
        req = PORTAL_REQUIREMENTS.get(portal, PORTAL_REQUIREMENTS["unknown"])
        out["upload_slot"] = req["pdf_upload_slot"]
        out["notes"] = req["notes"]
        if out.get("letter_optional"):
            out["notes"] += (" The posting says a cover letter is optional: upload it only where the "
                             "portal offers a slot.")

        bundle = bundle_for_job(record, letter, out["artifacts"])
        out["bundle_missing"] = bundle.missing
        out["requested_documents"] = bundle.requested_documents
        if bundle.notes.startswith(req["notes"]):          # attach-document hints from the bundle
            out["notes"] += bundle.notes[len(req["notes"]):]
        out["artifacts_complete"] = bundle.artifacts_complete

        out["letter"] = letter_to_dict(letter)
    except Exception as exc:  # noqa: BLE001 - one letter failure never stops the run
        out["letter_error"] = f"{type(exc).__name__}: {exc}"
    return out


def bundle_for_job(record: dict, letter, artifacts: dict):
    """The per-portal bundle for one job (posting fields + built artifacts)."""
    from engine.generation.portal_delivery import bundle_for

    posting = ((record.get("letter_input") or {}).get("posting")) or record
    return bundle_for(posting, letter, artifacts)


def previous_letters() -> dict[str, dict]:
    """The last letters_report.json, keyed by job_url (resume-mode)."""
    if not config.LETTERS_REPORT_PATH.exists():
        return {}
    try:
        report = json.loads(config.LETTERS_REPORT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        str(r.get("job_url") or ""): r
        for r in report.get("results", [])
        if isinstance(r, dict)
    }


def _collect_bundles(records: list[dict], results: list[dict]) -> dict:
    """Per-portal application manifest from the step-6 letters report."""
    out: list[dict] = []
    by_url = {str(r.get("job_url") or ""): r for r in results}
    for record in records:
        url = str(record.get("job_url") or "")
        result = by_url.get(url)
        if not result or not result.get("letter"):
            continue
        out.append({
            "job_url": url,
            "title": record.get("title", ""),
            "company": record.get("company", ""),
            "portal": (result.get("letter") or {}).get("portal", "unknown"),
            "letter_language": (result.get("letter") or {}).get("language", ""),
            "status": "letters_ok" if result.get("letter_gates_passed") else "letter_parked",
            "artifacts": result.get("artifacts", {}),
            "upload_slot": result.get("upload_slot", ""),
            "notes": result.get("notes", ""),
            "missing": result.get("bundle_missing", []),
            "requested_documents": result.get("requested_documents", []),
            "letter_source": result.get("letter_source", ""),
            "artifacts_complete": result.get("artifacts_complete", False),
        })
    complete = sum(1 for b in out if b["artifacts_complete"])
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(out),
        "complete": complete,
        "bundles": out,
    }


def main(argv: list[str] | None = None, only_urls: set[str] | None = None) -> int:
    """CLI entrypoint for the letter phase (main.py calls run_pipeline)."""
    parser = argparse.ArgumentParser(description="cover letter creation (step 6, after all resume work)")
    parser.add_argument("--jobs", type=str, default=None,
                        help="comma-separated job_url substrings to filter")
    parser.add_argument("--force", action="store_true",
                        help="recreate letters even for jobs that already have verified letters")
    args = parser.parse_args(argv)

    token = load_first_key()
    if not token:
        print("[V2] no usable Ollama key — run step 3 first")
        return 1

    kb = kb_loader.load_kb()  # raises if not APPROVED
    engine = find_latex_engine()
    print(f"[V2] step 6: letters after all resume work | LaTeX engine {engine or 'NONE'}")

    records = all_records = load_records()
    if only_urls is not None:          # run.py: exactly this run's jobs (URLs may contain commas)
        records = [r for r in records if str(r.get("job_url") or "") in only_urls]
    if args.jobs:
        keys = [k.strip().lower() for k in args.jobs.split(",") if k.strip()]
        records = [r for r in records if any(k in str(r.get("job_url", "")).lower() for k in keys)]

    previous = previous_letters()
    results: list[dict] = []
    total = len(records)
    seen_stems: dict[str, int] = {}
    created_now = 0
    calls_this_run = 0  # kept prior results carry HISTORICAL llm_calls; count only fresh builds
    for record in records:
        url = str(record.get("job_url") or "")
        label = str(record.get("title") or "?")[:60]
        prior = previous.get(url)
        has_verified_letter = bool(
            prior and prior.get("letter_gates_passed")
            and (prior.get("artifacts") or {}).get("letter_pdf")
            and Path(prior["artifacts"]["letter_pdf"]).exists()
        )
        if has_verified_letter and not args.force:
            print(f"[V2] [-/{total}] {label} -> letter kept (verified, no LLM call)")
            results.append(prior)
            continue

        print(f"[V2] [+/{total}] {label}")

        # stem dedupe BEFORE any build: two postings may sanitize to the same
        # Anschreiben stem, and a post-hoc rename would break the first job's
        # artifacts (the second build overwrote them, then moved them away).
        # build_letter receives the already-unique stem so every job's files
        # are written directly under their final names.
        probe = letter_stem_for(str(record.get("title") or ""), str(record.get("company") or ""),
                                str((record.get("analysis") or {}).get("language") or "de"))
        build_stem = probe
        if probe:
            if probe in seen_stems:
                seen_stems[probe] += 1
                build_stem = f"{probe}-{seen_stems[probe]}"
            else:
                seen_stems[probe] = 1
        if build_stem != probe:
            print(f"    -> stem collision: building as {build_stem}")

        result = build_letter(record, kb, token, engine, stem_override=build_stem or None)
        created_now += 1
        calls_this_run += int(result.get("llm_calls") or 0)

        if result.get("letter_error"):
            print(f"    -> letter parked: {result['letter_error'][:100]}")
        elif result.get("letter_gates_passed"):
            print(f"    -> letter verified -> {result.get('file_stem')}")
        results.append(result)

    if args.jobs or only_urls is not None:
        # A --jobs run rebuilds only the selected letters; every other job keeps its
        # previous result (a filtered run once wiped 14 of 18 entries from the report).
        fresh = {str(r.get("job_url") or ""): r for r in results}
        results = [fresh.get(url) or previous[url] for url in
                   (str(r.get("job_url") or "") for r in all_records) if url in fresh or url in previous]
        records = all_records
        total = len(records)

    letters_report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": "v2",
        "total_jobs": total,
        "results": results,
    }
    config.LETTERS_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.LETTERS_REPORT_PATH.write_text(
        json.dumps(letters_report, indent=2, ensure_ascii=False), encoding="utf-8")

    from engine.templates.build import archive_stale

    keep = set()
    for r in results:
        arts = r.get("artifacts") if isinstance(r.get("artifacts"), dict) else {}
        keep |= {Path(str(v)).stem for v in arts.values() if v}
    stale = archive_stale((config.LETTERS_TEX_DIR, config.LETTERS_PDF_DIR, config.LETTERS_DOCX_DIR,
                           config.LETTERS_TXT_DIR), keep, config.OUTPUT_DIR / "stale")
    if stale:
        print(f"[V2] moved {len(stale)} stale letter file(s) -> {config.OUTPUT_DIR / 'stale'}")

    bundles = _collect_bundles(records, results)
    write_bundles(bundles)

    created = sum(1 for r in results if r.get("letter_gates_passed"))
    print(f"\n[V2] letters: {created}/{total} verified | letters created this run: {created_now} | LLM calls this run: {calls_this_run}")
    print(f"[V2] bundles: {bundles.get('complete', 0)}/{bundles.get('total', 0)} application-complete")
    print(f"[V2] letters report -> {config.LETTERS_REPORT_PATH}")
    print(f"[V2] bundles -> {config.BUNDLES_PATH}")
    print(f"[V2] letters -> {config.LETTERS_PDF_DIR.parent}")
    return 0 if created == total and total > 0 else 1


def run_pipeline(**overrides) -> int:
    """Library entrypoint for main.py: run step 6 with keyword-flag overrides.

    Accepted overrides: jobs (str), force (bool), only_urls (set of exact job URLs).
    """
    argv: list[str] = []
    if overrides.get("jobs"):
        argv.extend(("--jobs", str(overrides["jobs"])))
    if overrides.get("force"):
        argv.append("--force")
    return main(argv, only_urls=overrides.get("only_urls"))


if __name__ == "__main__":
    raise SystemExit(main())
