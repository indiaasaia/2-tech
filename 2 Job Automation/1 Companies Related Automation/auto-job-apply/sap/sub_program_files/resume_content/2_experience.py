"""Stage 2 of the resume sections: generate the experience entries for every job.

Reads the filtered jobs CSV (program_files/output/2_filted_jobs.csv), fills
experience_1_prompt.md and experience_2_prompt.md for each job, asks the Ollama model
via ollama_request_response.send_prompt (two calls per job — one per stint), and saves
every job with both experience entries to program_files/output/experience.json.

The company, location and dates of both stints are fixed in the resume template and are
never generated. One failed request never stops the loop; its error is recorded on that
job's record. Exits 0 when every request succeeded, 1 when any request failed.

Run directly: python sub_program_files/resume_content/2_experience.py
"""
from __future__ import annotations

import json
import re
import sys
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
OUTPUT_JSON = PROJECT_ROOT / "sub_program_files" / "output" / "experience.json"
PROMPT_1 = Path(__file__).resolve().parent.parent / "prompt" / "experience_1_prompt.md"
PROMPT_2 = Path(__file__).resolve().parent.parent / "prompt" / "experience_2_prompt.md"

DESCRIPTION_LIMIT = 6000   # characters of job_description sent to the model
REQUIREMENTS_LIMIT = 4000  # characters of merged requirements/tasks sent to the model

ROLE_WORDS_MIN, ROLE_WORDS_MAX = 1, 6
DESCRIPTION_WORDS_MAX = 35
SKILLS_MIN, SKILLS_MAX = 4, 10

# Job fields copied into the output JSON next to the experience entries.
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
    """Remove markdown code fences and bold markers the model may wrap around the lines."""
    text = re.sub(r"```[a-zA-Z]*\n?|```", "", text)
    text = text.replace("**", "")
    for character, fix in _UNICODE_FIXES.items():
        text = text.replace(character, fix)
    return text


def role_word_count(role: str) -> int:
    """Count meaningful words in a role; separator symbols like '&' or '-' do not count."""
    return len([token for token in role.split() if re.search(r"[A-Za-z]", token)])


def parse_entry(text: object) -> tuple[dict, str]:
    """Parse a ROLE/DESCRIPTION/SKILLS reply into a validated entry.

    Returns (entry, error). The entry is filled field by field as far as parsing
    succeeds; error is '' when everything passed validation.
    """
    entry = {"role": "", "description": "", "skills": []}
    flattened = " ".join(strip_fences(str(text)).split())
    role_match = re.search(r"ROLE:\s*(.+?)(?=\s+DESCRIPTION:|$)", flattened, re.IGNORECASE)
    description_match = re.search(r"DESCRIPTION:\s*(.+?)(?=\s+SKILLS:|$)", flattened, re.IGNORECASE)
    skills_match = re.search(r"SKILLS:\s*(.+)$", flattened, re.IGNORECASE)
    if not (role_match and description_match and skills_match):
        return entry, f"unparseable response: {str(text)[:200]}"
    entry["role"] = role_match.group(1).strip().strip('"').strip(".")
    # Auto-trim a trailing qualifier when the role exceeds the word limit,
    # e.g. "Software Development Intern - Backend" -> "Software Development Intern".
    if role_word_count(entry["role"]) > ROLE_WORDS_MAX:
        trimmed = re.sub(r"\s+[-\u2013]\s+[^-\u2013]+$", "", entry["role"]).strip()
        if trimmed and trimmed != entry["role"]:
            entry["role"] = trimmed
    entry["description"] = description_match.group(1).strip().strip('"').strip(".")
    entry["skills"] = [skill.strip() for skill in skills_match.group(1).split(",") if skill.strip()]

    role_words = role_word_count(entry["role"])
    if not ROLE_WORDS_MIN <= role_words <= ROLE_WORDS_MAX:
        return entry, f"role has {role_words} words (allowed {ROLE_WORDS_MIN}-{ROLE_WORDS_MAX}): {entry['role']}"
    description_words = len(entry["description"].split())
    if description_words > DESCRIPTION_WORDS_MAX:
        return entry, f"description has {description_words} words (max {DESCRIPTION_WORDS_MAX})"
    if not SKILLS_MIN <= len(entry["skills"]) <= SKILLS_MAX:
        return entry, f"{len(entry['skills'])} skills (allowed {SKILLS_MIN}-{SKILLS_MAX})"
    return entry, ""


def generate_entry(template: str, job: dict, token: str, label: str) -> tuple[dict, str]:
    """Fill the prompt, call the model once, parse and validate; returns (entry, error)."""
    prompt = build_prompt(template, job)
    if prompt is None:
        return {"role": "", "description": "", "skills": []}, "skipped: empty job_description"
    try:
        reply = send_prompt(prompt, token)
    except Exception as exc:  # noqa: BLE001 - caller records the failure per job
        return {"role": "", "description": "", "skills": []}, f"{type(exc).__name__}: {exc}"
    return parse_entry(reply)


def save_output(records: list[dict], total_jobs: int, output_json: Path) -> None:
    """Write all records processed so far, so progress survives a crash."""
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL,
        "total_jobs": total_jobs,
        "experiences": records,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_experiences(jobs: list[dict], templates: tuple[str, str], token: str, output_json: Path) -> list[dict]:
    """Generate both experience entries per job, saving progress after every job."""
    records: list[dict] = []
    for index, job in enumerate(jobs, 1):
        label = str(job.get("title") or "?")[:60]
        record = {column: str(job.get(column) or "") for column in JOB_COLUMNS}
        record["experience_1"] = {"role": "", "description": "", "skills": []}
        record["experience_2"] = {"role": "", "description": "", "skills": []}
        record["experience_error"] = ""

        entry_1, error_1 = generate_entry(templates[0], job, token, label)
        entry_2, error_2 = generate_entry(templates[1], job, token, label)
        record["experience_1"], record["experience_2"] = entry_1, entry_2

        errors = [error for error in (error_1, error_2) if error]
        if not errors and entry_1["role"].lower() == entry_2["role"].lower():
            errors.append("both stints generated the same role — review for differentiation")
        if not errors and set(entry_1["skills"]) == set(entry_2["skills"]):
            errors.append("both stints generated identical skill sets — review for authenticity")
        record["experience_error"] = " | ".join(errors)

        status = "OK" if not record["experience_error"] else "REVIEW"
        print(f"[EXPERIENCE] [{index}/{len(jobs)}] {status}: {label} -> {entry_1['role'] or '?'} / {entry_2['role'] or '?'}")
        if record["experience_error"]:
            print(f"             {record['experience_error']}")

        records.append(record)
        save_output(records, len(jobs), output_json)
    return records


def main(input_csv: Path = INPUT_CSV, output_json: Path = OUTPUT_JSON) -> int:
    """Generate experience entries for the jobs and save them; returns the exit code."""
    token = load_first_key()
    if not token:
        print("[EXPERIENCE] no usable API key — run step 3 (3_test_ollama_keys.py) first")
        return 1

    jobs = load_jobs(input_csv)
    print(f"[EXPERIENCE] loaded {len(jobs)} job(s) from {input_csv}")

    if TEST_JOB_LIMIT is not None:
        jobs = jobs[0:TEST_JOB_LIMIT]  # TEST ONLY: first 10 jobs — set TEST_JOB_LIMIT = None for full runs

    templates = (load_template(PROMPT_1), load_template(PROMPT_2))
    records = generate_experiences(jobs, templates, token, output_json)

    ok = sum(1 for r in records if not r["experience_error"])
    review = len(records) - ok
    print(f"\n[EXPERIENCE] summary: {ok} clean, {review} need review")
    print(f"[EXPERIENCE] saved -> {output_json}")
    return 0 if review == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[EXPERIENCE] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
