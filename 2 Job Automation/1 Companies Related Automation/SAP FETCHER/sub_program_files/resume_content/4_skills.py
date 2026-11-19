"""Stage 4 of the resume sections: generate the skills section for every job.

Reads the filtered jobs CSV (program_files/output/2_filted_jobs.csv), fills
skills_prompt.md for each job, asks the Ollama model via
ollama_request_response.send_prompt, and saves every job's skills section to
program_files/output/skills.json.

Output per job: two fixed rows (languages, specialized areas) plus two
model-named skill categories, validated for counts, duplicates, and LaTeX-safe
characters. One failed request never stops the loop. Exits 0 when every
request succeeded, 1 when any job needs review.

Run directly: python sub_program_files/resume_content/4_skills.py
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
OUTPUT_JSON = PROJECT_ROOT / "sub_program_files" / "output" / "skills.json"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompt" / "skills_prompt.md"

DESCRIPTION_LIMIT = 6000   # characters of job_description sent to the model
REQUIREMENTS_LIMIT = 4000  # characters of merged requirements/tasks sent to the model

LANGUAGES_MIN, LANGUAGES_MAX = 4, 8
AREAS_MIN, AREAS_MAX = 3, 6
SKILLS_MIN, SKILLS_MAX = 3, 10  # min relaxed 4 -> 3: design/comms-flavored postings cannot yield 4+ distinct skill-area entries
LABEL_WORDS_MAX = 6

# Known programming-language names used to clean junk out of the languages row.
KNOWN_LANGUAGES = {
    "python", "java", "javascript", "typescript", "c", "c++", "c#", "go", "golang", "rust",
    "kotlin", "swift", "ruby", "php", "sql", "pl/sql", "tsql", "matlab", "r", "scala", "perl",
    "dart", "html", "css", "bash", "shell", "powershell", "vba", "fortran", "haskell", "lua",
    "groovy", "objective-c", "f#", "vb.net", "assembly", "vhdl", "verilog", "simulink", "java,",
}

# Job fields copied into the output JSON next to the skills section.
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
    if frame.empty:
        raise RuntimeError(f"input has no jobs: {input_csv}")
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


def strip_fences(text: str) -> str:
    """Remove markdown code fences and bold markers, normalize Unicode punctuation."""
    text = re.sub(r"```[a-zA-Z]*\n?|```", "", text)
    text = text.replace("**", "")
    for character, fix in _UNICODE_FIXES.items():
        text = text.replace(character, fix)
    return text


def split_items(raw: str) -> list[str]:
    """Split a comma-separated list and clean each item."""
    return [item.strip().strip('"').strip("'").strip() for item in raw.split(",") if item.strip()]


def auto_correct(section: dict) -> list[str]:
    """Mechanically repair common model mistakes; returns a log of corrections.

    - drops later duplicates across the whole section (first occurrence wins)
    - trims lists back to their maximum sizes
    - drops multi-word non-language entries from the languages row
    """
    notes: list[str] = []

    languages = section["languages"]
    cleaned = [lang for lang in languages
               if lang.lower() in KNOWN_LANGUAGES or len(lang.split()) == 1]
    dropped = [lang for lang in languages if lang not in cleaned]
    if dropped:
        notes.append(f"removed non-language entries from LANGUAGES: {dropped}")
        section["languages"] = cleaned

    seen: dict[str, str] = {}
    for key in ("languages", "specialized_areas", "skills_area_1", "skills_area_2"):
        items = section[key] if isinstance(section[key], list) else section[key]["skills"]
        kept: list[str] = []
        for item in items:
            token = item.lower()
            if token in seen:
                notes.append(f"removed duplicate {item!r} from {key} (already in {seen[token]})")
            else:
                seen[token] = key
                kept.append(item)
        if isinstance(section[key], list):
            section[key] = kept
        else:
            section[key]["skills"] = kept

    limits = (("languages", LANGUAGES_MAX), ("specialized_areas", AREAS_MAX),
              ("skills_area_1", SKILLS_MAX), ("skills_area_2", SKILLS_MAX))
    for key, maximum in limits:
        items = section[key] if isinstance(section[key], list) else section[key]["skills"]
        if len(items) > maximum:
            removed = items[maximum:]
            notes.append(f"trimmed {key} to the first {maximum} (removed: {removed})")
            if isinstance(section[key], list):
                section[key] = items[:maximum]
            else:
                section[key]["skills"] = items[:maximum]
    return notes


def parse_section(text: object) -> tuple[dict, str]:
    """Parse a LANGUAGES/SPECIALIZED-AREAS/SKILLS-AREA-1/2 reply into a validated section.

    Returns (section, error). error is '' when everything passed validation.
    """
    section = {
        "languages": [],
        "specialized_areas": [],
        "skills_area_1": {"label": "", "skills": []},
        "skills_area_2": {"label": "", "skills": []},
        "auto_corrections": [],
    }
    flattened = " ".join(strip_fences(str(text)).split())
    languages_match = re.search(r"LANGUAGES:\s*(.+?)(?=\s+SPECIALIZED-AREAS:|$)", flattened, re.IGNORECASE)
    areas_match = re.search(r"SPECIALIZED-AREAS:\s*(.+?)(?=\s+SKILLS-AREA-1:|$)", flattened, re.IGNORECASE)
    area1_match = re.search(r"SKILLS-AREA-1:\s*(.+?)(?=\s+SKILLS-AREA-2:|$)", flattened, re.IGNORECASE)
    area2_match = re.search(r"SKILLS-AREA-2:\s*(.+)$", flattened, re.IGNORECASE)
    if not (languages_match and areas_match and area1_match and area2_match):
        return section, f"unparseable response: {str(text)[:200]}"

    section["languages"] = split_items(languages_match.group(1))
    section["specialized_areas"] = split_items(areas_match.group(1))

    for key, match in (("skills_area_1", area1_match), ("skills_area_2", area2_match)):
        body = match.group(1).strip()
        if "::" not in body:
            return section, f"{key}: missing 'label :: skills' separator"
        label, raw_skills = body.split("::", 1)
        section[key]["label"] = label.strip().strip('"')
        section[key]["skills"] = split_items(raw_skills)

    errors: list[str] = []
    for key in ("skills_area_1", "skills_area_2"):
        area = section[key]
        label_words = len(area["label"].split())
        if not area["label"] or label_words > LABEL_WORDS_MAX:
            errors.append(f"{key}: bad label {area['label']!r} (max {LABEL_WORDS_MAX} words)")
        if "::" in area["label"] or any("::" in skill for skill in area["skills"]):
            errors.append(f"{key}: stray separator inside label or skills")

    if section["skills_area_1"]["label"] and section["skills_area_1"]["label"].lower() == section["skills_area_2"]["label"].lower():
        errors.append("both skill areas use the same label")
    if not section["specialized_areas"]:
        errors.append("specialized areas row empty")

    # Mechanical repairs first (dedupe, language cleaning, trims), then final sanity checks.
    corrections = auto_correct(section)

    # Thin languages row: borrow the first meaningful technical name from skill area 1.
    if len(section["languages"]) < LANGUAGES_MIN:
        borrowed: list[str] = []
        area = section["skills_area_1"]
        while area["skills"] and len(section["languages"]) < LANGUAGES_MIN:
            candidate = area["skills"].pop(0)
            if candidate.lower() in {item.lower() for item in section["languages"]}:
                continue
            borrowed.append(candidate)
            section["languages"].append(candidate)
        if borrowed:
            corrections.append(f"moved {borrowed} from skills_area_1 to languages to meet the minimum")

    if not LANGUAGES_MIN <= len(section["languages"]) <= LANGUAGES_MAX:
        errors.append(f"{len(section['languages'])} languages after cleaning (min {LANGUAGES_MIN}, max {LANGUAGES_MAX})")
    if not AREAS_MIN <= len(section["specialized_areas"]) <= AREAS_MAX:
        errors.append(f"{len(section['specialized_areas'])} specialized areas (allowed {AREAS_MIN}-{AREAS_MAX})")
    for key in ("skills_area_1", "skills_area_2"):
        if len(section[key]["skills"]) < SKILLS_MIN:
            errors.append(f"{key}: {len(section[key]['skills'])} skills after borrowing (min {SKILLS_MIN})")

    if errors:
        return section, " | ".join(errors)
    if corrections:
        section["auto_corrections"] = corrections
    return section, ""


def generate_section(template: str, job: dict, token: str, attempts: int = 3) -> tuple[dict, str]:
    """Fill the prompt, call the model, parse and validate; returns (section, error).

    Transient request failures are retried up to `attempts` times with a short pause.
    """
    prompt = build_prompt(template, job)
    if prompt is None:
        return {
            "languages": [], "specialized_areas": [],
            "skills_area_1": {"label": "", "skills": []},
            "skills_area_2": {"label": "", "skills": []},
            "auto_corrections": [],
        }, "skipped: empty job_description"
    error = ""
    for attempt in range(1, attempts + 1):
        try:
            reply = send_prompt(prompt, token)
        except Exception as exc:  # noqa: BLE001 - transient network errors are retried
            error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(3 * attempt)
                continue
            break
        return parse_section(reply)
    return {
        "languages": [], "specialized_areas": [],
        "skills_area_1": {"label": "", "skills": []},
        "skills_area_2": {"label": "", "skills": []},
        "auto_corrections": [],
    }, error


def save_output(records: list[dict], total_jobs: int, output_json: Path) -> None:
    """Write all records processed so far, so progress survives a crash."""
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL,
        "total_jobs": total_jobs,
        "skills": records,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_skills(jobs: list[dict], template: str, token: str, output_json: Path) -> list[dict]:
    """Generate one skills section per job, saving progress after every job."""
    records: list[dict] = []
    for index, job in enumerate(jobs, 1):
        label = str(job.get("title") or "?")[:60]
        record = {column: str(job.get(column) or "") for column in JOB_COLUMNS}
        record["skills_section"] = {}
        record["skills_error"] = ""

        section, error = generate_section(template, job, token)
        record["skills_section"] = section
        record["skills_error"] = error

        status = "OK" if not error else ("SKIP" if error.startswith("skipped") else "REVIEW")
        print(f"[SKILLS] [{index}/{len(jobs)}] {status}: {label}")
        if error:
            print(f"         {error}")

        records.append(record)
        save_output(records, len(jobs), output_json)
    return records


def main(input_csv: Path = INPUT_CSV, output_json: Path = OUTPUT_JSON) -> int:
    """Generate skills sections for the jobs and save them; returns the exit code."""
    token = load_first_key()
    if not token:
        print("[SKILLS] no usable API key — run step 3 (3_test_ollama_keys.py) first")
        return 1

    jobs = load_jobs(input_csv)
    print(f"[SKILLS] loaded {len(jobs)} job(s) from {input_csv}")

    if TEST_JOB_LIMIT is not None:
        jobs = jobs[0:TEST_JOB_LIMIT]  # TEST ONLY: first 5 jobs — set TEST_JOB_LIMIT = None for full runs

    template = load_template(PROMPT_FILE)
    records = generate_skills(jobs, template, token, output_json)

    ok = sum(1 for r in records if not r["skills_error"])
    flagged = len(records) - ok
    print(f"\n[SKILLS] summary: {ok} clean, {flagged} need review")
    print(f"[SKILLS] saved -> {output_json}")
    return 0 if flagged == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI entry point: report and exit non-zero
        print(f"[SKILLS] FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        raise SystemExit(1) from exc
