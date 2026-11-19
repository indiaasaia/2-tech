"""Step 4: domain gate -> analyst -> claimable set -> constrained generation -> gates.

The engine of the pipeline: consumes the filtered jobs CSV from steps 1-2 and
produces KB-grounded, gate-verified resume components per job. Serial
(free tier = 1 request at a time). Per job:
  0. domain gate: two-stage filter (family keywords, then 60% skill-alignment
     scoring for family-less jobs) — out-of-domain jobs never cost an LLM call
  1. analyst call (+ repair) -> JDAnalysis
  2. deterministic post-check (language sweep, tiers, dedupe)
  3. claimable set (KB ∪ mirrorable JD tools)
  4. constrained generation (up to 3 calls)
  5. pre-build gates G2/G3 on the intent; on failure regenerate with the
     violations listed verbatim (<= 2 iterations), else park the job.
Progress is saved after every job; a parked job records its reason visibly.

Run:  python resume_content_improve_research/run_step4.py [--limit N] [--jobs url1,url2]
      (or via the end-to-end entrypoint: python main.py)
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# direct-run bootstrap: make the project root importable (python .../run_step4.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from resume_content_improve_research import config
from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.analyst import LLMAnalysisError, analyze_job
from resume_content_improve_research.generation.domain_filter import load_filter_config, run_filter, write_report
from resume_content_improve_research.generation.analyst_postcheck import analysis_to_dict, postcheck
from resume_content_improve_research.generation.claimable_set import build_claimable_set, claimable_summary
from resume_content_improve_research.generation.generator import generate_components
from resume_content_improve_research.generation.llm import LLMError, load_first_key
from resume_content_improve_research.generation.tailoring import tailor_generated
from resume_content_improve_research.verification.gates import run_prebuild_gates

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
        analysis, meta = analyze_job(str(job.get("title") or ""), str(job.get("job_description") or ""), token)
        fixes = postcheck(analysis, " ".join(str(job.get(col) or "") for col in (
            "job_description", "requirements", "your_tasks", "applicant_profile", "what_they_offer")))
        record["analysis"] = analysis_to_dict(analysis)
        record["generation_meta"] = meta
        record["postcheck_fixes"] = fixes

        cset = build_claimable_set(record["analysis"], kb)
        licensed_digits = kb_loader.licensed_digits(kb)
        print(f"    {claimable_summary(cset)}")

        components, gen_meta = generate_components(cset, kb, analysis.title_core, token)
        record["generation_meta"].update(gen_meta)
        if tailor:
            record["tailoring"] = tailor_generated(components, analysis_to_dict(analysis), cset, kb)

        # gate -> regenerate loop (V7: mandatory, violations fed back verbatim).
        # Gating runs on the TAILORED intent: the pass only adds claimable-set
        # material, so any finding is a real violation, not a false alarm.
        for iteration in range(1, MAX_REGEN_ITERATIONS + 2):
            intent = intent_text_for(components)
            results = run_prebuild_gates(intent, components.experiences, cset, licensed_digits)
            findings = [f for r in results for f in r.findings]
            if not findings:
                record["status"] = "gated_ok"
                record["gate_findings"] = []
                break
            record["gate_findings"] = findings
            if iteration > MAX_REGEN_ITERATIONS:
                break
            print(f"    gates found {len(findings)} violation(s) -> regenerating (iteration {iteration})")
            for finding in findings[:10]:
                print(f"      - {finding}")
            components, gen_meta = generate_components(
                cset, kb, analysis.title_core, token, temperature=0.0)
            record["generation_meta"].update(gen_meta)
            if tailor:
                record["tailoring"] = tailor_generated(components, analysis_to_dict(analysis), cset, kb)
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
              f"details: output_v2/domain_filter_report.json)")
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
    keep: dict[str, dict] = {}
    todo: list[dict] = []
    for job in jobs:
        url = str(job.get("job_url") or "")
        prior = previous.get(url)
        if prior and prior.get("status") == "gated_ok" and not args.force:
            keep[url] = prior
        else:
            todo.append(job)
    if args.limit:
        todo = todo[: args.limit]

    print(f"[V2] step 4: {len(todo)} job(s) to run, {len(keep)} kept gated_ok, "
          f"model {config.OLLAMA_MODEL}, output {config.OUTPUT_DIR}")
    records: list[dict] = list(keep.values())
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
