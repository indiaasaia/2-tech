"""Repair/regenerate skills.json for the Mercedes pipeline (merge-safe rewrite).

v1 bug (fixed here): 4_skills.generate_skills() saves ITS subset to the output
JSON on every call, so passing the real skills.json clobbered the file with only
the retried records. This version:

  1. loads the full expected job list from 2_filted_jobs.csv
  2. finds records that are missing from skills.json OR flagged (skills_error)
  3. regenerates ONLY those via the bundled 4_skills stage (relaxed validator),
     writing to a TEMP file so the real skills.json is never clobbered
  4. merges results back into the full record set and writes skills.json once
     per job (crash-safe), looping until every record is clean (max 3 rounds)

Run from the project root: python recover_flagged_skills.py
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = PROJECT_ROOT / "program_files" / "output_mercedes" / "skills.json"
ADAPTED_CSV = PROJECT_ROOT / "program_files" / "output_mercedes" / "2_filted_jobs.csv"
TEMP_JSON = PROJECT_ROOT / "program_files" / "output_mercedes" / "skills_regen_tmp.json"

sys.path.insert(0, str(PROJECT_ROOT / "sub_program_files"))
sys.path.insert(0, str(PROJECT_ROOT / "sub_program_files" / "resume_content"))

skills_stage = importlib.import_module("4_skills")

ERR = "skills_error"
MAX_ROUNDS = 3


def save_merged(records: list[dict]) -> None:
    """Write the FULL merged record set (never a subset) to skills.json."""
    payload = {
        "generated_at_utc": skills_stage.datetime.now(skills_stage.timezone.utc).isoformat(timespec="seconds"),
        "model": skills_stage.MODEL,
        "total_jobs": len(records),
        "skills": records,
    }
    OUTPUT_JSON.write_text(skills_stage.json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def regen(job: dict, template: str, token: str) -> tuple[dict, str]:
    """Generate one skills section and return (section, error)."""
    section, error = skills_stage.generate_section(template, job, token)
    return section, error


def main() -> int:
    frame = pd.read_csv(ADAPTED_CSV, keep_default_na=False)
    all_jobs = frame.to_dict("records")
    by_url_all = {str(j["job_url"]): j for j in all_jobs}

    payload = skills_stage.json.loads(OUTPUT_JSON.read_text(encoding="utf-8")) if OUTPUT_JSON.exists() else {"skills": []}
    records: list[dict] = list(payload.get("skills", []))
    have = {str(r.get("job_url") or ""): r for r in records}

    template = skills_stage.load_template(skills_stage.PROMPT_FILE)
    token = skills_stage.load_first_key()
    if not token:
        print("[RECOVER] no usable API key")
        return 1

    print(f"[RECOVER] expected jobs: {len(all_jobs)} | in skills.json: {len(records)} "
          f"(missing {len(all_jobs) - len(have)}, SKILLS_MIN={skills_stage.SKILLS_MIN})")

    for round_no in range(1, MAX_ROUNDS + 1):
        todo_urls = []
        for url, job in by_url_all.items():
            record = have.get(url)
            if record is None or record.get(ERR):
                todo_urls.append(url)
        if not todo_urls:
            break
        print(f"\n[RECOVER] round {round_no}: regenerating {len(todo_urls)} record(s)")
        for index, url in enumerate(todo_urls, 1):
            job = by_url_all[url]
            label = str(job.get("title") or "?")[:60]
            record = {column: str(job.get(column) or "") for column in skills_stage.JOB_COLUMNS}
            record["skills_section"] = {}
            record[ERR] = ""
            section, error = regen(job, template, token)
            record["skills_section"] = section
            record[ERR] = error
            have[url] = record
            status = "OK" if not error else ("SKIP" if error.startswith("skipped") else "REVIEW")
            print(f"  [{index}/{len(todo_urls)}] {status}: {label}" + ("" if not error else f" -> {error[:100]}"))
            # crash-safe: persist the FULL merged set after every job
            save_merged([have[u] for u in by_url_all if u in have])

    missing = [u for u in by_url_all if u not in have]
    flagged = [have[u] for u in by_url_all if u in have and have[u].get(ERR)]
    clean = len(by_url_all) - len(missing) - len(flagged)
    print(f"\n[RECOVER] skills.json: {clean}/{len(by_url_all)} clean "
          f"({len(flagged)} flagged, {len(missing)} missing)")
    TEMP_JSON.unlink(missing_ok=True)
    return 0 if not missing and not flagged else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI entry point
        print(f"[RECOVER] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
