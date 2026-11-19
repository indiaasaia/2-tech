"""Interview prep output (plan v3 §7): what to learn and what to say, per job.

Every resume carries 100% of its job keywords; some of them are not backed by the
candidate's KB yet. Step 5 writes, for each verified job,
  output/applications/prep/<Company>_<Role>.md
    - keywords to learn before the interview (printed for the ATS, not in the KB)
    - keywords to talk about, each with the real KB entries that support it
    - the ad's tasks, plus eligibility / language / education points to check
and across all jobs
  output/applications/prep/learning_priorities.{json,md}
    - prep terms ranked by how many jobs ask for them: the best use of learning
      time (each one learned and added to the KB becomes a real, backed skill).
Deterministic, zero LLM calls.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from engine import config
from engine.generation import kb_loader
from engine.generation.evidence_vocab import _keys_for, allowed_keys
from engine.generation.keywords import _norm_key, plan_for_record

def _entry_label(entry: dict, kind: str) -> str:
    if kind == "experience":
        title = (entry.get("titles_allowed") or [entry.get("role", "")])[0]
        return f"{title} at {entry.get('company', '')}"
    if kind == "research":
        return f"Research: {entry.get('title', '')}"
    return f"Project: {entry.get('title', '')}"


def evidence_for(term: str, canonical: str, kb: dict) -> list[str]:
    """KB entries whose evidence supports `term` (for 'talk about it' notes)."""
    keys = set(_keys_for(term)) | ({_norm_key(canonical)} if canonical else set())
    keys.discard("")
    sources: list[str] = []
    for kind, entries in (("experience", kb_loader.experiences(kb)),
                          ("project", kb_loader.main_projects(kb)),
                          ("research", kb_loader.research(kb))):
        for entry in entries:
            if keys & allowed_keys(entry, kb):
                sources.append(_entry_label(entry, kind))
    return sources


def _tasks_excerpt(posting: dict, limit: int = 900) -> str:
    tasks = str(posting.get("your_tasks") or "").strip()
    description = str(posting.get("job_description") or "").strip()
    text = tasks if tasks and tasks != description else description
    return " ".join(text.split())[:limit]


def prep_markdown(result: dict, record: dict, kb: dict) -> str:
    """The per-job prep sheet (markdown)."""
    plan = record.get("keywords") or plan_for_record(record).to_dict()
    posting = (record.get("letter_input") or {}).get("posting") or record
    gate = result.get("keyword_gate") or {}
    share = result.get("kb_backed_share")
    prep_terms = list(result.get("prep_terms") or [])
    prep_keys = {_norm_key(t) for t in prep_terms}

    lines = [f"# Interview prep: {result.get('title', '')} @ {result.get('company', '')}", ""]
    if result.get("job_url"):
        lines.append(f"- Posting: {result['job_url']}")
    if share is not None:
        lines.append(f"- Fit: {share:.0%} of the job's technical keywords are backed by your KB")
    if result.get("pdf"):
        lines.append(f"- Resume: {Path(str(result['pdf'])).name}")
    lines += ["", "## Learn before the interview",
              "On your resume for the ATS, not yet in your knowledge base. Expect questions on these.", ""]
    lines += [f"- [ ] {term}" for term in prep_terms] or ["- (nothing - every technical keyword is backed)"]

    lines += ["", "## Talk about these with real examples", ""]
    talk = 0
    for keyword in plan.get("keywords") or []:
        if keyword.get("category") in ("soft_skills", "education_field", "domain"):
            continue
        if _norm_key(keyword["term"]) in prep_keys:
            continue
        sources = evidence_for(str(keyword["term"]), str(keyword.get("canonical") or ""), kb)
        lines.append(f"- **{keyword['term']}**: " + ("; ".join(sources) if sources else "listed KB skill"))
        talk += 1
    if not talk:
        lines.append("- (none)")

    tasks = _tasks_excerpt(posting)
    if tasks:
        lines += ["", "## What the job asks you to do (from the ad)", "", f"> {tasks}"]

    checks: list[str] = []
    if gate.get("eligibility"):
        checks.append("Eligibility: " + "; ".join(gate["eligibility"]))
    if gate.get("languages_required"):
        checks.append("Languages required: " + "; ".join(gate["languages_required"]))
    if gate.get("education_gaps"):
        checks.append("Education asked for but not on your resume: " + "; ".join(gate["education_gaps"]))
    if checks:
        lines += ["", "## Check before applying", ""] + [f"- {c}" for c in checks]
    return "\n".join(lines) + "\n"


def learning_priorities(results: list[dict]) -> list[dict]:
    """Prep terms across verified jobs, most-requested first."""
    tally: dict[str, dict] = {}
    for result in results:
        if result.get("status") != "verified":
            continue
        for term in result.get("prep_terms") or []:
            key = _norm_key(term)
            entry = tally.setdefault(key, {"term": term, "jobs": 0, "companies": []})
            if not any(ch in entry["term"] for ch in "/.+#-") and any(ch in term for ch in "/.+#-"):
                entry["term"] = term          # the ad's spelling ("CI/CD") beats a paraphrase ("CI CD")
            entry["jobs"] += 1
            company = str(result.get("company") or "")
            if company and company not in entry["companies"]:
                entry["companies"].append(company)
    # distinct companies first: one employer posting four near-identical roles (Amazon x4
    # on the 10-14 run) must not outrank a skill that four different companies ask for
    return sorted(tally.values(), key=lambda e: (-len(e["companies"]), -e["jobs"], e["term"].lower()))


def write_prep_files(results: list[dict], records: list[dict], kb: dict, out_dir: Path | None = None) -> dict:
    """Write per-job prep sheets + learning priorities; sets result['prep_file']."""
    from engine.templates.build import archive_stale, cut_stem, safe_name

    target = out_dir or (config.OUTPUT_DIR / "prep")
    target.mkdir(parents=True, exist_ok=True)
    by_url = {str(r.get("job_url") or ""): r for r in records}
    used: dict[str, int] = {}
    written = 0
    for result in results:
        record = by_url.get(str(result.get("job_url") or ""))
        if result.get("status") != "verified" or record is None:
            continue
        stem = f"{cut_stem(safe_name(str(result.get('company') or '')), 30)}_{cut_stem(safe_name(str(result.get('title') or '')), 50)}"
        used[stem] = used.get(stem, 0) + 1
        if used[stem] > 1:
            stem = f"{stem}-{used[stem]}"
        path = target / f"{stem}.md"
        path.write_text(prep_markdown(result, record, kb), encoding="utf-8")
        result["prep_file"] = str(path)
        written += 1

    keep = {Path(str(r["prep_file"])).stem for r in results if r.get("prep_file")} | {"learning_priorities"}
    if out_dir is None:      # sheets of jobs no longer in the report, old file names
        archive_stale([target], keep, config.OUTPUT_DIR / "stale")

    priorities = learning_priorities(results)
    payload = {"generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "verified_jobs": sum(1 for r in results if r.get("status") == "verified"),
               "priorities": priorities}
    (target / "learning_priorities.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
    md = ["# Learning priorities", "",
          "Skills printed on your resumes for the ATS but not yet in your knowledge base, ranked by how "
          "many different companies (then jobs) ask for them. Learn the top ones first, then add them to "
          "candidate_kb.json with real evidence (a small project) so they become backed skills.", "",
          "| Skill | Companies | Jobs | Who asks |", "|---|---|---|---|"]
    md += [f"| {p['term']} | {len(p['companies'])} | {p['jobs']} | "
           f"{', '.join(c.replace('|', '-') for c in p['companies'][:6])} |"   # 'proceedit | AI ...' broke the table
           for p in priorities]
    (target / "learning_priorities.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return {"prep_files": written, "priorities": priorities}
