"""Stage 3 of the resume sections: generate the two project entries for every job.

Reads the filtered jobs CSV (program_files/output/2_filted_jobs.csv), fills
projects_1_prompt.md and projects_2_prompt.md for each job, asks the Ollama model via
ollama_request_response.send_prompt (two calls per job — one per resume slot), and saves
every job with both project entries to program_files/output/projects.json.

The candidate has exactly two real projects; each call picks and tailors one for its
resume slot (slot 1 = strongest match, slot 2 = the other project). Project names must
be one of the two fixed names. One failed request never stops the loop. Exits 0 when
every request succeeded, 1 when any job needs review.

Run directly: python sub_program_files/resume_content/3_projects.py
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ollama_request_response import MODEL, load_first_key, send_prompt

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_CANDIDATES = (
    PROJECT_ROOT / "sap_results.csv",
    PROJECT_ROOT / "program_files" / "output" / "2_filted_jobs.csv",
    PROJECT_ROOT.parent / "resume_creation" / "program_files" / "output_v2" / "state" / "2_filted_jobs_sap.csv",
)
INPUT_CSV = next((p for p in INPUT_CANDIDATES if p.exists() and p.stat().st_size > 0), INPUT_CANDIDATES[0])
OUTPUT_JSON = PROJECT_ROOT / "sub_program_files" / "output" / "projects.json"
PROMPT_1 = Path(__file__).resolve().parent.parent / "prompt" / "projects_1_prompt.md"
PROMPT_2 = Path(__file__).resolve().parent.parent / "prompt" / "projects_2_prompt.md"

DESCRIPTION_LIMIT = 6000   # characters of job_description sent to the model
REQUIREMENTS_LIMIT = 4000  # characters of merged requirements/tasks sent to the model

DESCRIPTION_WORDS_MAX = 50
SKILLS_MIN, SKILLS_MAX = 4, 10
PROJECT_TITLE_WORDS_MIN, PROJECT_TITLE_WORDS_MAX = 2, 8

# Job fields copied into the output JSON next to the project entries.
JOB_COLUMNS = ("source", "title", "company", "location", "posted_time", "job_url", "job_description")

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
        "Job Title": "title",
        "Link": "job_url",
        "Description": "job_description",
        "Location": "location",
        "Posted Date": "posted_time",
        "Department": "company",
    }
    for old_col, new_col in col_map.items():
        if old_col in frame.columns and new_col not in frame.columns:
            frame[new_col] = frame[old_col]

    if "company" not in frame.columns or not frame["company"].iloc[0]:
        frame["company"] = "SAP SE"
    if "source" not in frame.columns:
        frame["source"] = "SuccessFactors"

    # Only process ENGLISH_OK jobs if language filter is applied
    if "Language_Filter" in frame.columns:
        english_frame = frame[frame["Language_Filter"] == "ENGLISH_OK"]
        if not english_frame.empty:
            frame = english_frame

    return frame.to_dict("records")


def load_template(prompt_file: Path) -> str:
    """Return the sendable prompt text.

    When the file contains a '## PROMPT' marker, only the text below it is sent;
    otherwise (plain prompt files) the whole file is sent.
    """
    text = prompt_file.read_text(encoding="utf-8")
    if "## PROMPT" in text:
        return text.split("## PROMPT", 1)[1].split("\n", 1)[1].strip()
    return text.strip()


def build_prompt(template: str, job: dict) -> str | None:
    """Fill a prompt template for one job; None when the job has no description."""
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


def strip_fences(text: str) -> str:
    """Remove markdown code fences and bold markers, normalize Unicode punctuation."""
    text = re.sub(r"```[a-zA-Z]*\n?|```", "", text)
    text = text.replace("**", "")
    for character, fix in _UNICODE_FIXES.items():
        text = text.replace(character, fix)
    return text


def parse_entry(text: object) -> tuple[dict, str]:
    """Parse a PROJECT/DESCRIPTION/SKILLS reply into a validated entry.

    Returns (entry, error). error is '' when everything passed validation.
    """
    entry = {"project": "", "description": "", "skills": []}
    flattened = " ".join(strip_fences(str(text)).split())
    project_match = re.search(r"PROJECT:\s*(.+?)(?=\s+DESCRIPTION:|$)", flattened, re.IGNORECASE)
    description_match = re.search(r"DESCRIPTION:\s*(.+?)(?=\s+SKILLS:|$)", flattened, re.IGNORECASE)
    skills_match = re.search(r"SKILLS:\s*(.+)$", flattened, re.IGNORECASE)
    if not (project_match and description_match and skills_match):
        return entry, f"unparseable response: {str(text)[:200]}"
    entry["project"] = project_match.group(1).strip().strip('"').strip(".")
    # Auto-trim an overlong title: drop a trailing "for ..." clause, then truncate if needed.
    title_words = len(entry["project"].split())
    corrections: list[str] = []
    if title_words > PROJECT_TITLE_WORDS_MAX:
        trimmed = re.sub(r"\s+for\s+[^,]+$", "", entry["project"]).strip()
        if trimmed and len(trimmed.split()) < title_words:
            corrections.append(f"trimmed project title {entry['project']!r} -> {trimmed!r}")
            entry["project"] = trimmed
    if len(entry["project"].split()) > PROJECT_TITLE_WORDS_MAX:
        shortened = " ".join(entry["project"].split()[:PROJECT_TITLE_WORDS_MAX])
        corrections.append(f"truncated project title to {shortened!r}")
        entry["project"] = shortened
    entry["description"] = description_match.group(1).strip().strip('"').strip(".")
    entry["skills"] = [skill.strip() for skill in skills_match.group(1).split(",") if skill.strip()]

    title_words = len(entry["project"].split())
    if not PROJECT_TITLE_WORDS_MIN <= title_words <= PROJECT_TITLE_WORDS_MAX:
        return entry, f"project title has {title_words} words (allowed {PROJECT_TITLE_WORDS_MIN}-{PROJECT_TITLE_WORDS_MAX}): {entry['project']!r}"
    if corrections:
        entry["auto_corrections"] = corrections
    description_words = len(entry["description"].split())
    if description_words > DESCRIPTION_WORDS_MAX:
        return entry, f"description has {description_words} words (max {DESCRIPTION_WORDS_MAX})"
    if not SKILLS_MIN <= len(entry["skills"]) <= SKILLS_MAX:
        return entry, f"{len(entry['skills'])} skills (allowed {SKILLS_MIN}-{SKILLS_MAX})"
    return entry, ""


def generate_entry(template: str, job: dict, token: str, attempts: int = 3) -> tuple[dict, str]:
    """Fill the prompt, call the model, parse and validate; returns (entry, error).

    Transient request failures are retried up to `attempts` times with a short pause.
    """
    prompt = build_prompt(template, job)
    if prompt is None:
        return {"project": "", "description": "", "skills": []}, "skipped: empty job_description"
    error = ""
    for attempt in range(1, attempts + 1):
        try:
            reply = send_prompt(prompt, token)
        except Exception as exc:  # noqa: BLE001 - transient network errors are retried
            error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(3 * attempt)
                continue
            return {"project": "", "description": "", "skills": []}, error
        return parse_entry(reply)
    return {"project": "", "description": "", "skills": []}, error


def save_output(records: list[dict], total_jobs: int, output_json: Path) -> None:
    """Write all records processed so far, so progress survives a crash."""
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL,
        "total_jobs": total_jobs,
        "projects": records,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_projects(jobs: list[dict], templates: tuple[str, str], token: str, output_json: Path) -> list[dict]:
    """Generate both project entries per job, saving progress after every job."""
    records: list[dict] = []
    for index, job in enumerate(jobs, 1):
        label = str(job.get("title") or "?")[:60]
        record = {column: str(job.get(column) or "") for column in JOB_COLUMNS}
        record["project_1"] = {"project": "", "description": "", "skills": []}
        record["project_2"] = {"project": "", "description": "", "skills": []}
        record["projects_error"] = ""

        entry_1, error_1 = generate_entry(templates[0], job, token)
        # Slot 2's prompt is told what slot 1 chose, so it always shows the OTHER project.
        slot2_template = templates[1].replace("{{SLOT1_PROJECT}}", entry_1["project"] or "(unavailable)")
        entry_2, error_2 = generate_entry(slot2_template, job, token)

        # Safety net: retry once if the model still repeated slot 1's choice.
        if (
            not error_1
            and not error_2
            and entry_1["project"]
            and entry_2["project"] == entry_1["project"]
        ):
            print(f"           both slots chose {entry_1['project']} — retrying slot 2")
            entry_2, error_2 = generate_entry(slot2_template, job, token, attempts=2)

        record["project_1"], record["project_2"] = entry_1, entry_2

        errors = [error for error in (error_1, error_2) if error]
        if (
            not errors
            and entry_1["project"]
            and entry_2["project"]
            and entry_1["project"] == entry_2["project"]
        ):
            errors.append("both slots chose the same project — review for slot differentiation")
        record["projects_error"] = " | ".join(errors)

        status = "OK" if not record["projects_error"] else "REVIEW"
        print(f"[PROJECTS] [{index}/{len(jobs)}] {status}: {label} -> {entry_1['project'] or '?'} / {entry_2['project'] or '?'}")
        if record["projects_error"]:
            print(f"           {record['projects_error']}")

        records.append(record)
        save_output(records, len(jobs), output_json)
    return records


def main(input_csv: Path = INPUT_CSV, output_json: Path = OUTPUT_JSON) -> int:
    """Generate project entries for the jobs and save them; returns the exit code."""
    token = load_first_key()
    if not token:
        print("[PROJECTS] no usable API key — run step 3 (3_test_ollama_keys.py) first")
        return 1

    jobs = load_jobs(input_csv)
    print(f"[PROJECTS] loaded {len(jobs)} job(s) from {input_csv}")

    if TEST_JOB_LIMIT is not None:
        jobs = jobs[0:TEST_JOB_LIMIT]  # TEST ONLY: first 10 jobs — set TEST_JOB_LIMIT = None for full runs

    templates = (load_template(PROMPT_1), load_template(PROMPT_2))
    records = generate_projects(jobs, templates, token, output_json)

    ok = sum(1 for r in records if not r["projects_error"])
    review = len(records) - ok
    print(f"\n[PROJECTS] summary: {ok} clean, {review} need review")
    print(f"[PROJECTS] saved -> {output_json}")
    return 0 if review == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[PROJECTS] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
