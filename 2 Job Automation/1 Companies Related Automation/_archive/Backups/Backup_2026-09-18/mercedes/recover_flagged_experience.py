"""Repair/regenerate experience.json for the Mercedes pipeline (merge-safe).

Mirrors recover_flagged_skills.py: the experience stage saves ITS subset to the
output JSON, so re-running it wholesale would clobber records for other jobs.
This version:

  1. loads the full expected job list from 2_filted_jobs.csv
  2. finds records that are missing from experience.json OR flagged
     (experience_error - usually a role longer than the 4-word limit)
  3. regenerates ONLY those via the bundled 2_experience stage's per-entry
     generator, merging into the FULL record set (crash-safe, saved after
     every job), looping until every record is clean (max 3 rounds)

Run from the project root: python recover_flagged_experience.py
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = PROJECT_ROOT / "program_files" / "output_mercedes" / "experience.json"
ADAPTED_CSV = PROJECT_ROOT / "program_files" / "output_mercedes" / "2_filted_jobs.csv"

sys.path.insert(0, str(PROJECT_ROOT / "sub_program_files"))
sys.path.insert(0, str(PROJECT_ROOT / "sub_program_files" / "resume_content"))

experience_stage = importlib.import_module("2_experience")

ERR = "experience_error"
MAX_ROUNDS = 3


def save_merged(records: list[dict]) -> None:
    """Write the FULL merged record set (never a subset) to experience.json."""
    payload = {
        "generated_at_utc": experience_stage.datetime.now(experience_stage.timezone.utc).isoformat(timespec="seconds"),
        "model": experience_stage.MODEL,
        "total_jobs": len(records),
        "experiences": records,
    }
    OUTPUT_JSON.write_text(experience_stage.json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def regen(job: dict, templates: tuple[str, str], token: str) -> tuple[dict, dict, str]:
    """Generate both experience entries for one job; returns (entry_1, entry_2, error)."""
    entry_1, error_1 = experience_stage.generate_entry(templates[0], job, token, "recover")
    entry_2, error_2 = experience_stage.generate_entry(templates[1], job, token, "recover")
    errors = [error for error in (error_1, error_2) if error]
    if not errors and entry_1["role"].lower() == entry_2["role"].lower():
        errors.append("both stints generated the same role — review for differentiation")
    if not errors and set(entry_1["skills"]) == set(entry_2["skills"]):
        errors.append("both stints generated identical skill sets — review for authenticity")
    return entry_1, entry_2, " | ".join(errors)


def main() -> int:
    frame = pd.read_csv(ADAPTED_CSV, keep_default_na=False)
    all_jobs = frame.to_dict("records")
    by_url_all = {str(j["job_url"]): j for j in all_jobs}

    payload = experience_stage.json.loads(OUTPUT_JSON.read_text(encoding="utf-8")) if OUTPUT_JSON.exists() else {"experiences": []}
    records: list[dict] = list(payload.get("experiences", []))
    have = {str(r.get("job_url") or ""): r for r in records}

    templates = (experience_stage.load_template(experience_stage.PROMPT_1),
                 experience_stage.load_template(experience_stage.PROMPT_2))
    token = experience_stage.load_first_key()
    if not token:
        print("[RECOVER] no usable API key")
        return 1

    print(f"[RECOVER] expected jobs: {len(all_jobs)} | in experience.json: {len(records)} "
          f"(missing {len(all_jobs) - len(have)})")

    for round_no in range(1, MAX_ROUNDS + 1):
        todo_urls = [url for url in by_url_all
                     if have.get(url) is None or have[url].get(ERR)]
        if not todo_urls:
            break
        print(f"\n[RECOVER] round {round_no}: regenerating {len(todo_urls)} record(s)")
        for index, url in enumerate(todo_urls, 1):
            job = by_url_all[url]
            label = str(job.get("title") or "?")[:60]
            record = {column: str(job.get(column) or "") for column in experience_stage.JOB_COLUMNS}
            record["experience_1"] = {"role": "", "description": "", "skills": []}
            record["experience_2"] = {"role": "", "description": "", "skills": []}
            record[ERR] = ""
            entry_1, entry_2, error = regen(job, templates, token)
            record["experience_1"], record["experience_2"] = entry_1, entry_2
            record[ERR] = error
            have[url] = record
            status = "OK" if not error else "REVIEW"
            print(f"  [{index}/{len(todo_urls)}] {status}: {label}"
                  + ("" if not error else f" -> {error[:120]}"))
            # crash-safe: persist the FULL merged set after every job
            save_merged([have[u] for u in by_url_all if u in have])

    missing = [u for u in by_url_all if u not in have]
    flagged = [have[u] for u in by_url_all if u in have and have[u].get(ERR)]
    clean = len(by_url_all) - len(missing) - len(flagged)
    print(f"\n[RECOVER] experience.json: {clean}/{len(by_url_all)} clean "
          f"({len(flagged)} flagged, {len(missing)} missing)")
    return 0 if not missing and not flagged else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI entry point
        print(f"[RECOVER] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
