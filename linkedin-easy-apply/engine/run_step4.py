"""Step 4: domain gate -> analyst -> claimable set -> constrained generation -> gates.

The engine of the pipeline: consumes the filtered jobs CSV from steps 1-2 and
produces KB-grounded, gate-verified RESUME components per job. Serial
(free tier = 1 request at a time). Per job:
  0. domain gate: two-stage filter (family keywords, then 60% skill-alignment
     scoring for family-less jobs) — out-of-domain jobs never cost an LLM call
  1. analyst call (+ repair) -> JDAnalysis
  2. deterministic post-check (language sweep, tiers, dedupe)
  3. keyword plan (every job-ad keyword) + claimable set (KB ∪ JD tools ∪ keywords)
  4. constrained generation (up to 3 calls) + keyword-placing tailoring pass
  5. pre-build gates G2/G3 on the intent; on failure regenerate with the
     violations listed verbatim (<= 2 iterations), else park the job.

The COVER LETTER is intentionally NOT created here: step 6 (run_step6.py)
generates every letter AFTER all resume work has completed, into its own
separate files (letters_report.json, application_bundles.json). Step 4 only
stores a deterministic `letter_input` payload (posting fields + generated
analysis) so step 6 can rebuild the letter context without any LLM call or
CSV re-read.

Progress is saved after every job; a parked job records its reason visibly.

Run:  python engine/run_step4.py [--limit N] [--jobs url1,url2]
      (or via the end-to-end entrypoint: python main.py)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# direct-run bootstrap: make the project root importable (python .../run_step4.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from engine import config
from engine.generation import kb_loader
from engine.generation.analyst import LLMAnalysisError, analyze_job
from engine.generation.domain_filter import load_filter_config, run_filter, write_report
from engine.generation.analyst_postcheck import analysis_to_dict, postcheck
from engine.generation.claimable_set import build_claimable_set, claimable_summary
from engine.generation.generator import generate_components
from engine.generation.keywords import analysis_text, build_keyword_plan
from engine.generation.llm import LLMError, load_first_key
from engine.generation.tailoring import tailor_generated
from engine.verification.gates import run_prebuild_gates

config.ensure_utf8_stdout()

COMPONENTS_KEY = "components_v2"
MAX_REGEN_ITERATIONS = config.MAX_REGENERATION_ITERATIONS


def load_jobs() -> list[dict]:
    """Filtered jobs CSV from v1 steps 1-2 (same input, new engine).

    Resume support: jobs already gated_ok in components_v2.json are kept in the
    store untouched (no LLM cost); the default target set is everything else
    (gated_ok jobs are re-run only with --force or --jobs).
    """
    import pandas as pd

    if not config.FILTERED_JOBS_CSV.exists():
        raise RuntimeError(f"input not found: {config.FILTERED_JOBS_CSV} — run main.py steps 1-2 first")
    frame = pd.read_csv(config.FILTERED_JOBS_CSV, keep_default_na=False)
    if frame.empty:
        raise RuntimeError("no jobs to process")
    return frame.to_dict("records")


def load_previous_records() -> dict[str, dict]:
    """Previous run's records keyed by job_url (for resume/keep-good support)."""
    path = config.OUTPUT_DIR / "components_v2.json"
    if not path.exists():
        return {}
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(r.get("job_url") or ""): r for r in records}


def save_output(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


def _clean_meta(letter_dict: dict, meta: dict) -> tuple[dict, dict]:
    """Drop the private working keys before the meta goes into the report."""
    for key in ("_claim_sentences", "_hard_findings"):
        meta.pop(key, None)
    return letter_dict, meta


def vocabulary_findings(components, kb: dict, plan: dict | None) -> list[str]:
    """Bullets that print a tool/keyword the entry's KB evidence does not support."""
    from engine.generation.evidence_vocab import find_entry, vocabulary_violations

    out: list[str] = []
    entries = list(getattr(components, "experiences", None) or []) + list(getattr(components, "projects", None) or [])
    for entry in entries:
        source = find_entry(kb, str(entry.get("id") or ""))
        for bullet in entry.get("bullets") or []:
            for term in vocabulary_violations(str(bullet), source, kb, plan):
                out.append(f"vocabulary: {term!r} is not evidenced for {source.get('id')} "
                           f"(bullet: {str(bullet)[:70]!r})")
    return out


def intent_text_for(components) -> str:
    """The full claim text the G2/G3 gates inspect (dataclass or plain dict)."""
    if isinstance(components, dict):
        get = lambda name, default: components.get(name, default)  # noqa: E731
    else:
        get = lambda name, default: getattr(components, name, default)  # noqa: E731
    skills = get("skills_section", {}) or {}
    parts = [str(get("objective", "") or "")]
    for entry in get("experiences", []) or []:
        parts += [entry["description"], ", ".join(entry["skills"]), entry["role"]]
    for project in get("projects", []) or []:
        parts += [project["description"], ", ".join(project["skills"]), project["title"]]
    for area in skills["areas"]:
        parts.append(", ".join(area["skills"]))
    parts += [", ".join(skills["languages"]), ", ".join(skills["specialized_areas"])]
    return " | ".join(parts)


def build_letter_input(job: dict, analysis_dict: dict) -> dict:
    """Deterministic step-6 input for one job: minimal posting + analysis.

    Stored on the gated_ok record so step 6 can create the letter AFTER all
    resume work without re-reading the CSV or re-running the analyst (zero
    extra LLM cost). Only fields cover_letter.py actually consumes.
    """
    return {
        "posting": {col: str(job.get(col) or "") for col in config.LETTER_POSTING_COLS},
        "analysis": analysis_dict,
    }


def process_letter_input(letter_input: dict, kb: dict, token: str,
                         analysis_dict: dict | None = None,
                         candidate_facts: str | None = None) -> tuple[dict, dict]:
    """Create + gate one letter from a stored letter_input (used by step 6).

    `analysis_dict` overrides the stored analysis (the retailor may have
    refreshed record["analysis"] after step 4): creation and gating must use
    the SAME claim surface or the gate would judge a different license than
    the letter was written against.

    Letter v3 (2026-10-17): the LLM writes opening/fit/motivation from the ad's
    tasks and the candidate's real evidence; the closing is the deterministic
    logistics paragraph (enrolment, hours, permit). Every attempt goes through
    L1-L4 (incl. the biography check that once made the LLM path unsafe); a
    failing LLM letter gets ONE repair round with its findings, then the
    deterministic KB-grounded letter is the fallback. The job's top keywords
    are guaranteed in the body (cover_letter.ensure_letter_keywords).

    Returns (letter_dict, meta); raises RuntimeError on unfixed L1-L4 findings
    (step 6 parks that LETTER, never the resume).
    """
    from engine.generation import cover_letter as cl
    from engine.generation.keywords import build_keyword_plan
    from engine.verification.cl_gates import run_letter_gates

    job = letter_input["posting"]
    analysis_dict = analysis_dict or letter_input["analysis"]
    cset = cl.build_letter_claimable_set(analysis_dict, kb, job)
    plan = build_keyword_plan(job, analysis_dict).to_dict()
    licensed = kb_loader.licensed_digits(kb)
    title = str(job.get("title") or "")
    meta: dict = {"calls": 0, "attempts": [], "letter_source": "",
                  "letter_optional": cl.letter_optional(job),
                  "top_keywords": cl.top_letter_keywords(plan)}

    def finish_and_gate(letter) -> list[str]:
        from engine.generation.claim_check import claim_sentences, claim_violations
        from engine.generation.text_norm import plain_typography

        letter.opening, letter.fit, letter.motivation = (
            plain_typography(letter.opening), plain_typography(letter.fit), plain_typography(letter.motivation))
        name_fixes: list[str] = []
        for attr in ("opening", "fit", "motivation"):
            fixed, found = cl.fix_entity_names(getattr(letter, attr), kb)
            setattr(letter, attr, fixed)
            name_fixes += found
        if name_fixes:
            meta.setdefault("name_fixes", []).extend(name_fixes)
        letter.closing = cl.logistics_paragraph(kb, letter.language, title)
        meta["keywords_inserted"] = cl.ensure_letter_keywords(letter, plan)
        meta["postcheck_fixes"] = cl.postcheck_letter(letter, job, cset)
        cl.probe_date_line(letter)
        results = run_letter_gates(letter, cset, licensed)
        meta["letter_gates"] = {r.gate: {"passed": r.passed, "findings": r.findings} for r in results}
        # Unbacked keywords stated as done work (policy v3; generation/claim_check.py).
        from engine.generation.keywords import clean_headline

        titles = (title, clean_headline(title), re.sub(r"\s*\([^)]*\)", "", title), letter.subject)
        claims = claim_violations(" ".join([letter.opening, letter.fit]), kb, plan, exclude=titles)
        claims += claim_violations(letter.motivation, kb, plan, exclude=titles, first_person_only=True)
        meta["_claim_sentences"] = (
            [s for s, _ in claim_sentences(" ".join([letter.opening, letter.fit]), kb, plan, exclude=titles)]
            + [s for s, _ in claim_sentences(letter.motivation, kb, plan, exclude=titles, first_person_only=True)])
        meta["_hard_findings"] = [f for r in results for f in r.findings]
        meta["letter_gates"]["claims"] = {"passed": not claims, "findings": claims}
        return [f for r in results for f in r.findings] + claims

    findings: list[str] = []
    letter = None
    for attempt in range(2):          # write, then one repair with the gate findings
        letter = cl.build_skeleton(job, analysis_dict, kb)
        try:
            letter, gen_meta = cl.generate_letter(
                letter, job, plan, kb, token, temperature=0.25 if attempt == 0 else 0.0,
                candidate_facts=candidate_facts, findings=findings)
        except (RuntimeError, LLMError) as exc:
            meta["attempts"].append(f"llm unavailable/invalid: {exc}")
            break
        meta["calls"] += gen_meta["calls"]
        findings = finish_and_gate(letter)
        if not findings:
            # deterministic checks passed: one LLM fact check for invented activities
            unsupported, verify_meta = cl.verify_letter_facts(
                letter, candidate_facts or cl._candidate_facts_block(kb), token)
            meta["calls"] += verify_meta["calls"]
            meta.setdefault("fact_checks", []).append(
                {"unsupported": unsupported, "error": verify_meta["error"]})
            meta["_claim_sentences"] = verify_meta.get("sentences", [])
            findings = unsupported
        if not findings:
            meta["letter_source"] = "llm"
            return _clean_meta(cl.letter_to_dict(letter), meta)
        meta["attempts"].append(findings[:6])

    # Trim instead of discard: when the last LLM letter failed ONLY on flagged
    # sentences (claims / unsupported facts, no structural or truth-gate finding),
    # drop exactly those sentences and re-run every deterministic gate.
    if findings and letter is not None and not meta.get("_hard_findings") and meta.get("_claim_sentences"):
        from engine.generation.claim_check import drop_sentences

        from engine.generation.claim_check import SKILLS_LIST_RE, sentences

        bad = list(meta["_claim_sentences"])
        trimmed = [drop_sentences(getattr(letter, a), bad) for a in ("opening", "fit", "motivation")]
        # a trimmed letter must keep its substance (live SIXT letter, 2026-10-17: the
        # trim left a one-sentence opening and a fit paragraph that was only the toolkit list)
        evidence = [s for s in sentences(trimmed[1]) if not SKILLS_LIST_RE.match(s)]
        if len(sentences(trimmed[0])) >= 2 and len(evidence) >= 2 and sentences(trimmed[2]):
            letter.opening, letter.fit, letter.motivation = trimmed
            if not finish_and_gate(letter):
                unsupported, verify_meta = cl.verify_letter_facts(
                    letter, candidate_facts or cl._candidate_facts_block(kb), token)
                meta["calls"] += verify_meta["calls"]
                meta.setdefault("fact_checks", []).append(
                    {"unsupported": unsupported, "error": verify_meta["error"], "after_trim": True})
                if not unsupported:
                    meta["letter_source"] = "llm"
                    meta["trimmed_sentences"] = bad
                    return _clean_meta(cl.letter_to_dict(letter), meta)

    # fallback: the deterministic, KB-evidenced letter (zero LLM calls)
    letter = cl.build_skeleton(job, analysis_dict, kb)
    letter, grounded_meta = cl.generate_grounded_letter(letter, cset, job, analysis_dict, kb)
    meta.update({k: v for k, v in grounded_meta.items() if k != "calls"})
    findings = finish_and_gate(letter)
    if findings:
        raise RuntimeError("letter gates failed: " + "; ".join(findings[:6]))
    meta["letter_source"] = "fallback"
    return _clean_meta(cl.letter_to_dict(letter), meta)


def process_job(job: dict, token: str, kb: dict, tailor: bool = True) -> dict:
    """Full v2 pipeline for one job; never raises — failures park the job."""
    record = {
        "job_url": str(job.get("job_url") or ""),
        "title": str(job.get("title") or ""),
        "company": str(job.get("company") or ""),
        "status": "pending",
        "analysis": None,
        "components": None,
        "generation_meta": None,
        "postcheck_fixes": [],
        "gate_findings": [],
        "error": "",
    }
    try:
        # The analyst gets the WHOLE ad: for 17/36 jobs the requirements live in a
        # separate scraped column that job_description alone never contained.
        analysis, meta = analyze_job(str(job.get("title") or ""), analysis_text(job), token)
        fixes = postcheck(analysis, " ".join(str(job.get(col) or "") for col in (
            "job_description", "requirements", "your_tasks", "applicant_profile", "what_they_offer")))
        record["analysis"] = analysis_to_dict(analysis)
        record["generation_meta"] = meta
        record["postcheck_fixes"] = fixes
        record["keywords"] = build_keyword_plan(job, record["analysis"]).to_dict()
        print(f"    keywords: {len(record['keywords']['targets'])} targets "
              f"({', '.join(f'{c} {len(t)}' for c, t in record['keywords']['by_category'].items())})")

        plan = record["keywords"]
        cset = build_claimable_set(record["analysis"], kb, keywords=plan["targets"])
        licensed_digits = kb_loader.licensed_digits(kb)
        print(f"    {claimable_summary(cset)}")

        components, gen_meta = generate_components(cset, kb, analysis.title_core, token, plan=plan)
        record["generation_meta"].update(gen_meta)
        if tailor:
            record["tailoring"] = tailor_generated(components, analysis_to_dict(analysis), cset, kb, plan=plan)

        # gate -> regenerate loop (V7: mandatory, violations fed back verbatim).
        # Gating runs on the TAILORED intent: the pass only adds claimable-set
        # material, so any finding is a real violation, not a false alarm.
        for iteration in range(1, MAX_REGEN_ITERATIONS + 2):
            intent = intent_text_for(components)
            results = run_prebuild_gates(intent, components.experiences, cset, licensed_digits)
            hard = [f for r in results for f in r.findings]
            soft = vocabulary_findings(components, kb, plan)
            findings = hard + soft
            record["vocabulary_findings"] = soft
            if not findings:
                record["status"] = "gated_ok"
                record["gate_findings"] = []
                break
            record["gate_findings"] = findings
            if iteration > MAX_REGEN_ITERATIONS:
                if not hard:
                    # Only per-entry vocabulary left: step-5 grounding drops exactly
                    # those bullets, so the job still ships (findings kept on record).
                    record["status"] = "gated_ok"
                    record["gate_findings"] = []
                break
            print(f"    gates found {len(findings)} violation(s) -> regenerating (iteration {iteration})")
            for finding in findings[:10]:
                print(f"      - {finding}")
            components, gen_meta = generate_components(
                cset, kb, analysis.title_core, token, temperature=0.0, plan=plan, findings=findings)
            record["generation_meta"].update(gen_meta)
            if tailor:
                record["tailoring"] = tailor_generated(
                    components, analysis_to_dict(analysis), cset, kb, plan=plan)
        else:
            record["status"] = "gated_failed"

        if record["status"] == "gated_ok":
            record["components"] = {
                "objective": components.objective,
                "skills_section": components.skills_section,
                "experiences": components.experiences,
                "projects": components.projects,
                "profile": components.raw.get("profile", {}),
            }
            # The letter is created by STEP 6, after ALL resume work — this
            # payload carries the deterministic inputs step 6 needs.
            record["letter_input"] = build_letter_input(job, record["analysis"])
        else:
            record["status"] = "parked"
            record["error"] = "gates failed after regeneration: " + "; ".join(record["gate_findings"][:6])
    except LLMAnalysisError as exc:
        record["status"] = "parked"
        record["error"] = f"analyst failed: {exc}"
    except LLMError as exc:
        record["status"] = "parked"
        record["error"] = f"LLM unavailable: {exc}"
    except Exception as exc:  # noqa: BLE001 - one job failure never stops the run
        record["status"] = "parked"
        record["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    return record


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: parse args and run the pipeline (main.py calls run_pipeline)."""
    parser = argparse.ArgumentParser(description="resume component generation (step 4)")
    parser.add_argument("--limit", type=int, default=None, help="process only the first N jobs")
    parser.add_argument("--jobs", type=str, default=None, help="comma-separated job_url substrings to filter")
    parser.add_argument("--force", action="store_true",
                        help="re-run gated_ok jobs too (default: keep their results, retry parked only)")
    parser.add_argument("--no-tailor", action="store_true",
                        help="disable the per-job tailoring pass (raw generator output; A/B testing)")
    parser.add_argument("--no-domain-filter", action="store_true",
                        help="skip the domain gate entirely (process all scraped jobs)")
    parser.add_argument("--loose-filter", action="store_true",
                        help="keyword-only domain gate (skip the 60%% skill-alignment scoring "
                             "for family-less jobs)")
    args = parser.parse_args(argv)

    token = load_first_key()
    if not token:
        print("[V2] no usable Ollama key — run step 3 first")
        return 1

    kb = kb_loader.load_kb()  # raises if not APPROVED
    jobs = load_jobs()
    if not args.no_domain_filter:
        scored = not args.loose_filter
        buckets = load_filter_config()
        kept, eliminated, filter_records = run_filter(jobs, buckets, scored=scored)
        write_report(filter_records)
        kept_urls = {r["job_url"] for r in filter_records if r["decision"] == "keep"}
        jobs = [j for j in jobs if str(j.get("job_url") or "") in kept_urls]
        mode = "keyword+scored" if scored else "keyword-only (--loose-filter)"
        print(f"[V2] domain filter ({mode}): {len(kept)} kept, {len(eliminated)} eliminated "
              f"(use --no-domain-filter to disable, --loose-filter for keyword-only; "
              f"details: output/applications/domain_filter_report.json)")
        for rec in filter_records:
            if rec["decision"] == "eliminate":
                score = rec.get("score")
                extra = f" [{score['alignment_ratio']:.0%}]" if score else ""
                print(f"    CUT  {str(rec['title'])[:50]:50}{extra} {rec['reason'][:60]}")
    previous = load_previous_records()
    if args.jobs:
        keys = [k.strip().lower() for k in args.jobs.split(",") if k.strip()]
        jobs = [j for j in jobs if any(k in str(j.get("job_url", "")).lower() for k in keys)]

    # Resume semantics: keep previous gated_ok results, (re)process everything else.
    # Letters are step 6's job entirely: records from before the letter_input
    # era are kept too (their letters come from step 6's legacy migration, no
    # LLM cost) — a missing letter_input must never trigger a costly re-run.
    # Records NOT being reprocessed are carried over from the previous store
    # verbatim — a --jobs-scoped run must never wipe the rest of the store.
    keep: dict[str, dict] = {}
    todo: list[dict] = []
    for job in jobs:
        url = str(job.get("job_url") or "")
        prior = previous.get(url)
        if prior and prior.get("status") == "gated_ok" \
                and (prior.get("components") or {}) and not args.force:
            keep[url] = prior
        else:
            todo.append(job)
    if args.limit:
        todo = todo[: args.limit]

    print(f"[V2] step 4: {len(todo)} job(s) to run, {len(keep)} kept gated_ok, "
          f"model {config.OLLAMA_MODEL}, output {config.OUTPUT_DIR}")
    todo_urls = {str(j.get("job_url") or "") for j in todo}
    records: list[dict] = [prior for url, prior in previous.items()
                           if url not in todo_urls]
    for index, job in enumerate(todo, 1):
        label = str(job.get("title") or "?")[:60]
        print(f"[V2] [{index}/{len(todo)}] {label}")
        record = process_job(job, token, kb, tailor=not args.no_tailor)
        print(f"    -> {record['status']}" + (f" ({record['error'][:90]})" if record["error"] else ""))
        records.append(record)
        save_output(records, config.OUTPUT_DIR / "components_v2.json")

    ok = sum(1 for r in records if r["status"] == "gated_ok")
    parked = sum(1 for r in records if r["status"] == "parked")
    calls = sum((r.get("generation_meta") or {}).get("calls", 0) for r in records)
    print(f"\n[V2] summary: {ok} gated_ok, {parked} parked | LLM calls this run: {calls}")
    print(f"[V2] saved -> {config.OUTPUT_DIR / 'components_v2.json'}")
    print("[V2] letters are created by step 6 (run_step6.py) after all resume work")
    return 0 if parked == 0 else 1


def run_pipeline(**overrides) -> int:
    """Library entrypoint for main.py: run step 4 with keyword-flag overrides.

    Accepted overrides mirror the CLI flags (limit, jobs, force, no_tailor,
    no_domain_filter, loose_filter); unspecified options keep their defaults.
    """
    prefix = "--"
    argv: list[str] = []
    for key, value in overrides.items():
        if value is None or value is False:
            continue
        flag = prefix + key.replace("_", "-")
        if value is True:
            argv.append(flag)
        else:
            argv.extend((flag, str(value)))
    return main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
