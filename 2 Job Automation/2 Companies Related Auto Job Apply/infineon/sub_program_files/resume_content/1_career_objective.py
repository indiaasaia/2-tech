"""Stage 1 of the resume sections: generate a career objective for every job.

Reads the filtered jobs CSV written by steps 1 and 2 (program_files/output/2_filted_jobs.csv),
fills career_objective_prompt.md for each job, asks the Ollama model via
ollama_request_response.send_prompt, and saves every job with its objective to
program_files/output/career_objective.json.

Jobs with an empty job_description are skipped (recorded with a reason). One failed
request never stops the loop; its error is recorded on that job's record. Exits 0
when every request succeeded (skips are warnings), 1 when any request failed.

Run directly: python sub_program_files/resume_content/1_career_objective.py
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ollama_request_response import MODEL, load_first_key, send_prompt

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_CANDIDATES = (
    PROJECT_ROOT / "INFINEON_jobs_detailed.csv",
    PROJECT_ROOT / "program_files" / "output" / "2_filted_jobs.csv",
    PROJECT_ROOT.parent / "resume_creation" / "program_files" / "output_v2" / "state" / "2_filted_jobs_sap.csv",
)
INPUT_CSV = next((p for p in INPUT_CANDIDATES if p.exists() and p.stat().st_size > 0), INPUT_CANDIDATES[0])
OUTPUT_JSON = PROJECT_ROOT / "sub_program_files" / "output" / "career_objective.json"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompt" / "career_objective_prompt.md"

DESCRIPTION_LIMIT = 6000   # characters of job_description sent to the model
REQUIREMENTS_LIMIT = 4000  # characters of merged requirements/tasks sent to the model

# Job fields copied into the output JSON next to the objective.
JOB_COLUMNS = ("source", "title", "company", "location", "posted_time", "job_url", "job_description")

# TEST ONLY: process at most this many jobs. Set to None for the full run.
# Full-run mode: process every filtered job. Set to a number for test runs.
TEST_JOB_LIMIT = None


def load_jobs(input_csv: Path) -> list[dict]:
    """Read the filtered jobs CSV and return its rows as a list of dicts."""
    if not input_csv.exists():
        raise RuntimeError(f"input not found: {input_csv} — run steps 1 and 2 (main.py) first")
    try:
        frame = pd.read_csv(input_csv, keep_default_na=False)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise RuntimeError(f"could not read {input_csv}: {exc}") from exc
    if frame.empty:
        raise RuntimeError(f"input has no jobs: {input_csv}")

    # Standardize column names across SAP FETCHER schemas
    col_map = {
        "title": "title",
        "link": "job_url",
        "apply_url": "job_url",
        "description_text": "job_description",
        "locations": "location",
        "standardized_locations": "location",
        "posted_date": "posted_time",
        "department": "company",
    }
    for old_col, new_col in col_map.items():
        if old_col in frame.columns and new_col not in frame.columns:
            frame[new_col] = frame[old_col]

    if "company" not in frame.columns or not frame["company"].iloc[0]:
        frame["company"] = "Infineon Technologies"
    if "source" not in frame.columns:
        frame["source"] = "Eightfold"

    # Only process ENGLISH_OK jobs if language filter is applied
    if "Language_Filter" in frame.columns:
        english_frame = frame[frame["Language_Filter"] == "ENGLISH_OK"]
        if not english_frame.empty:
            frame = english_frame

    return frame.to_dict("records")


def load_template() -> str:
    """Return the sendable prompt text (everything below the '## PROMPT' marker)."""
    text = PROMPT_FILE.read_text(encoding="utf-8")
    if "## PROMPT" not in text:
        raise RuntimeError(f"prompt marker '## PROMPT' missing in {PROMPT_FILE}")
    return text.split("## PROMPT", 1)[1].split("\n", 1)[1].strip()


def build_prompt(template: str, job: dict) -> str | None:
    """Fill the prompt template for one job; None when the job has no description."""
    description = str(job.get("job_description") or "").strip()
    if not description:
        return None
    requirements = " ".join(
        str(job.get(column) or "").strip()
        for column in ("requirements", "your_tasks")
        if str(job.get(column) or "").strip()
    )
    return (
        template
        .replace("{{JOB_TITLE}}", str(job.get("title") or "").strip())
        .replace("{{JOB_DESCRIPTION}}", description[:DESCRIPTION_LIMIT])
        .replace("{{KEY_REQUIREMENTS}}", requirements[:REQUIREMENTS_LIMIT])
    )


# Unicode characters the model sometimes emits that break LaTeX or CSV handling.
_UNICODE_FIXES = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
}


def clean_response(text: object) -> str:
    """Reduce the model reply to one clean plain-text paragraph (ASCII punctuation)."""
    flattened = " ".join(str(text).split())  # collapse newlines and repeated spaces
    for character, fix in _UNICODE_FIXES.items():
        flattened = flattened.replace(character, fix)
    return flattened.strip().strip('"').strip("'").strip()


def save_output(records: list[dict], total_jobs: int, output_json: Path) -> None:
    """Write all records processed so far, so progress survives a crash."""
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL,
        "total_jobs": total_jobs,
        "objectives": records,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_objectives(jobs: list[dict], template: str, token: str, output_json: Path) -> list[dict]:
    """Generate one objective per job, saving progress after every job."""
    records: list[dict] = []
    for index, job in enumerate(jobs, 1):
        label = str(job.get("title") or "?")[:60]
        record = {column: str(job.get(column) or "") for column in JOB_COLUMNS}
        record["career_objective"] = ""
        record["objective_error"] = ""

        prompt = build_prompt(template, job)
        if prompt is None:
            record["objective_error"] = "skipped: empty job_description"
            print(f"[OBJECTIVE] [{index}/{len(jobs)}] skipped (no description): {label}")
        else:
            try:
                record["career_objective"] = clean_response(send_prompt(prompt, token))
                print(f"[OBJECTIVE] [{index}/{len(jobs)}] OK: {label}")
            except Exception as exc:  # noqa: BLE001 - one failure must not stop the rest
                record["objective_error"] = f"{type(exc).__name__}: {exc}"
                print(f"[OBJECTIVE] [{index}/{len(jobs)}] FAILED: {label}")
                traceback.print_exc()

        records.append(record)
        save_output(records, len(jobs), output_json)
    return records


def main(input_csv: Path = INPUT_CSV, output_json: Path = OUTPUT_JSON) -> int:
    """Generate career objectives for the jobs and save them; returns the exit code."""
    token = load_first_key()
    if not token:
        print("[OBJECTIVE] no usable API key — run step 3 (3_test_ollama_keys.py) first")
        return 1

    jobs = load_jobs(input_csv)
    print(f"[OBJECTIVE] loaded {len(jobs)} job(s) from {input_csv}")

    if TEST_JOB_LIMIT is not None:
        jobs = jobs[0:TEST_JOB_LIMIT]  # TEST ONLY cap; set TEST_JOB_LIMIT = None for full runs

    template = load_template()
    records = generate_objectives(jobs, template, token, output_json)

    generated = sum(1 for r in records if r["career_objective"])
    skipped = sum(1 for r in records if r["objective_error"].startswith("skipped"))
    failed = sum(1 for r in records if r["objective_error"] and not r["objective_error"].startswith("skipped"))
    print(f"\n[OBJECTIVE] summary: {generated} generated, {skipped} skipped, {failed} failed")
    print(f"[OBJECTIVE] saved -> {output_json}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[OBJECTIVE] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
