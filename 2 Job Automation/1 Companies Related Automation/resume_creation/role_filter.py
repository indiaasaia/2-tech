"""Strict role gate for the resume hub: prune out-of-domain jobs AFTER step 4.

Motivation (2026-09-20): the engine's pre-step domain gate matched short
keywords as raw substrings ("sem" inside "Semester", "erp" inside
"Erprobung", "bank" inside "Datenbank"), so business/engineering roles that
merely mention those strings got resumes. Two fixes:

  1. knowledge_base/domain_filters.json: the false-positive keywords were
     replaced with precise ones (config-only change, upstream-tunable).
  2. THIS module: a title-first strict gate that runs over a company's
     persisted components (post-step-4) and prunes jobs whose TITLE names an
     out-of-domain role. Title evidence is the strongest signal — a title
     says what the job IS, JD boilerplate only what it mentions.

Decision order per job (role_filter_config.json):
  1. drop_title pattern in the title  -> prune
  2. keep_title pattern in the title  -> keep
  3. fall back to the engine's own domain gate over the full JD text
     (classify_job from generation.domain_filter with the fixed config)

--dry-run prints the decision table and touches nothing. With --apply the
pruned jobs are removed from components_v2_<company>.json (backup first) and
the following step-5 rebuild + resume map only contains the kept jobs.

Library use:
    from role_filter import load_role_config, classify_role
    role_filter_prune("mercedes", dry_run=True)
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIG_PATH = ROOT / "role_filter_config.json"
STATE_DIR = ROOT / "program_files" / "output_v2" / "state"


def load_role_config(path: Path = CONFIG_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    drop = [str(k).lower() for k in data.get("drop_title", []) if str(k).strip()]
    keep = [str(k).lower() for k in data.get("keep_title", []) if str(k).strip()]
    return {"drop_title": drop, "keep_title": keep}


def _hits(title: str, patterns: list[str]) -> list[str]:
    norm = " ".join(title.lower().split())
    return sorted({p for p in patterns if p in norm})


def classify_role(job: dict, config: dict | None = None) -> dict:
    """Decide keep/prune for one job record (title-first, JD-gate fallback)."""
    cfg = config or load_role_config()
    title = str(job.get("title") or "")
    drop_hits = _hits(title, cfg["drop_title"])
    if drop_hits:
        return {"decision": "prune", "reason": f"title drop: {', '.join(drop_hits)}",
                "drop_hits": drop_hits, "keep_hits": []}
    keep_hits = _hits(title, cfg["keep_title"])
    if keep_hits:
        return {"decision": "keep", "reason": f"title keep: {', '.join(keep_hits)}",
                "drop_hits": [], "keep_hits": keep_hits}
    # Fallback: the engine's own domain gate over the full JD text, STRICT mode:
    # a family-signal job must ALSO clear the scored skill-alignment bar (60%),
    # so a stray keyword cannot carry a business/other-engineering role.
    from resume_content_improve_research.generation.domain_filter import (
        classify_job, load_filter_config)
    from resume_content_improve_research.generation.scored_filter import (
        classify_scored)
    jd_job = {
        "title": title,
        "company": job.get("company") or "",
        "job_url": job.get("job_url") or "",
        "job_description": job.get("job_description") or "",
    }
    verdict = classify_job(jd_job, load_filter_config(), scored=True)
    if verdict["decision"] != "keep":
        return {"decision": "prune", "reason": f"jd gate: {verdict['reason']}",
                "drop_hits": [], "keep_hits": []}
    if verdict.get("score") is not None:  # already scored (family-less path)
        return {"decision": "keep", "reason": f"jd gate: {verdict['reason']}",
                "drop_hits": [], "keep_hits": []}
    scored = classify_scored(jd_job)
    score = scored["score"]
    ratio, demands = score["alignment_ratio"], score["demanded_count"]
    # Strict: a real denominator is required — the engine's sparse-JD leniency
    # (fewer than min_denominator demands -> auto-keep at 100%) would let a
    # business role with one stray tech word through.
    from resume_content_improve_research.generation.scored_filter import (
        load_scoring_config)
    min_denominator = load_scoring_config()["min_denominator"]
    if scored["decision"] == "keep" and demands >= min_denominator:
        return {"decision": "keep", "reason": f"jd gate + alignment {ratio:.0%} ({demands} demands)",
                "drop_hits": [], "keep_hits": []}
    return {"decision": "prune", "reason": f"family signal but alignment {ratio:.0%} "
                                             f"on {demands} demand(s) — too sparse/below bar",
            "drop_hits": [], "keep_hits": []}


def role_filter_records(records: list[dict],
                        config: dict | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Classify persisted component records. Returns (kept, pruned, report_rows)."""
    cfg = config or load_role_config()
    kept: list[dict] = []
    pruned: list[dict] = []
    rows: list[dict] = []
    for record in records:
        verdict = classify_role(record, cfg)
        (kept if verdict["decision"] == "keep" else pruned).append(record)
        rows.append({
            "title": str(record.get("title") or "")[:70],
            "job_url": str(record.get("job_url") or ""),
            "decision": verdict["decision"],
            "status": str(record.get("status") or ""),
            "reason": verdict["reason"],
        })
    return kept, pruned, rows


def role_filter_prune(company: str, dry_run: bool = True,
                      config: dict | None = None) -> int:
    """Prune out-of-domain jobs from a company's persisted component state.

    dry_run: print the decision table, change nothing.
    apply:   back up the state file, then rewrite it with only the kept jobs.
    Returns the number of jobs that would be / were pruned.
    """
    state_path = STATE_DIR / f"components_v2_{company}.json"
    if not state_path.exists():
        print(f"[role-filter] {company}: no state file {state_path.name} — nothing to prune")
        return 0
    records = json.loads(state_path.read_text(encoding="utf-8"))
    kept, pruned, rows = role_filter_records(records, config)

    print(f"[role-filter] {company}: {len(records)} job(s) -> keep {len(kept)}, "
          f"prune {len(pruned)}")
    for row in rows:
        mark = "KEEP " if row["decision"] == "keep" else "PRUNE"
        print(f"  {mark} {row['title']:70} {row['reason'][:60]}")

    if dry_run:
        print("[role-filter] dry run — nothing changed (use --apply to prune)")
        return len(pruned)

    backup = state_path.with_suffix(".pre_rolefilter.json")
    shutil.copy2(state_path, backup)
    state_path.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[role-filter] {company}: pruned {len(pruned)} job(s); "
          f"{len(kept)} kept (backup: {backup.name})")
    return len(pruned)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="strict role gate over saved component state")
    parser.add_argument("company", help="e.g. mercedes")
    parser.add_argument("--apply", action="store_true", help="really prune (default: dry run)")
    args = parser.parse_args(argv)
    from resume_content_improve_research import config as engine_config
    engine_config.ensure_utf8_stdout()
    return 0 if role_filter_prune(args.company, dry_run=not args.apply) >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
