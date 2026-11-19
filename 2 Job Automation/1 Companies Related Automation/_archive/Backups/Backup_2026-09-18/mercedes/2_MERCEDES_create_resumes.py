"""Mercedes pipeline step 2: keep English-friendly jobs and generate resume components.

Two parts:
  A) Language filter: run 2_MERCEDES_language_filter.py over MERCEDES_results.csv
     (adds Language_Filter + Filter_Evidence columns in place) and keep only
     the ENGLISH_OK jobs that were posted within the recency window.
  B) Resume components: map the Mercedes CSV onto the column schema the resume
     generators expect (source/title/company/location/posted_time/job_url/
     job_description/requirements/your_tasks), write
     program_files/output_mercedes/2_filted_jobs.csv, and run the four generation
     stages from sub_program_files/resume_content (1_career_objective,
     2_experience, 3_projects, 4_skills) against that file. All outputs use the
     same file names as the original project but live in
     program_files/output_mercedes/ inside this folder.

This folder is fully self-contained (own copies of the resume stages, prompts,
LLM helper, keys and tectonic) -- no outside project needed.

Every stage runs via its main(input_csv=..., output_json=...) signature, so the
generation logic itself is 100% the existing code. One failed stage is reported
and does not stop the others. Exits 0 only when every stage succeeded.

Run directly (from anywhere): python 2_MERCEDES_create_resumes.py
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Self-contained: PROJECT_ROOT is this folder itself, which bundles
# program_files/, sub_program_files/ and tools/ (no outside project needed).
PROJECT_ROOT = Path(__file__).resolve().parent
# All Mercedes artifacts live in their own output directory, so nothing else
# is ever touched.
MERCEDES_OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output_mercedes"

MERCEDES_RESULTS_CSV = PROJECT_ROOT / "MERCEDES_results.csv"
ADAPTED_CSV = MERCEDES_OUTPUT_DIR / "2_filted_jobs.csv"
STAGE_INPUT_CSV = MERCEDES_OUTPUT_DIR / "stage_input.csv"  # per-run remaining jobs

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "sub_program_files"))
sys.path.insert(0, str(PROJECT_ROOT / "sub_program_files" / "resume_content"))

# (label, module name, output json inside output_mercedes, records key, error field)
STAGES = [
    ("1 career objective", "1_career_objective", "career_objective.json", "objectives", "objective_error"),
    ("2 experience", "2_experience", "experience.json", "experiences", "experience_error"),
    ("3 projects", "3_projects", "projects.json", "projects", "projects_error"),
    ("4 skills", "4_skills", "skills.json", "skills", "skills_error"),
]

DEFAULT_WINDOW_DAYS = 14  # keep jobs posted within this many days (0 = all)
DESCRIPTION_MIN_CHARS = 80  # shorter descriptions are useless for tailoring

COMPANY_VALUE = "Mercedes-Benz"


def _build_master_frame(window_days: int, limit: int | None,
                        unique_roles: int | None = None) -> pd.DataFrame:
    """Load the detailed Mercedes data, apply recency + description filters.

    Prefers MERCEDES_jobs_full.json (richer); falls back to the CSV when the
    JSON is missing. Raises RuntimeError when nothing usable remains.
    """
    full_json = PROJECT_ROOT / "MERCEDES_jobs_full.json"
    rows: list[dict] = []

    if full_json.exists():
        data = json.loads(full_json.read_text(encoding="utf-8"))
        for record in data.get("jobs", []):
            if "error" in record:
                continue
            sections = record.get("sections_raw") or {}
            tasks = str(sections.get("Tasks") or "").strip()
            qualifications = str(sections.get("Qualifications") or "").strip()
            description = str(record.get("description_text") or "").strip()
            if len(description) < DESCRIPTION_MIN_CHARS:
                continue
            if not tasks and not qualifications:
                tasks = description
            location = " ".join(
                part for part in (record.get("city"), record.get("region")) if part
            )
            custom = record.get("custom_fields") or ""
            apply_match = re.search(r'"apply_url": "([^"]+)"', custom)
            rows.append({
                "source": "mercedes",
                "title": str(record.get("title") or "").strip(),
                "company": str(record.get("company") or COMPANY_VALUE).strip(),
                "location": location,
                "posted_time": str(record.get("posting_date") or ""),
                "job_url": str(record.get("link") or "").strip(),
                "job_description": f"[Tasks] {tasks}\n\n[Qualifications] {qualifications}".strip(),
                "requirements": qualifications,
                "your_tasks": tasks,
                "apply_url": (apply_match.group(1) if apply_match else "").strip(),
                "_lang_text": f"{str(record.get('title') or '')}\n{description}",
            })
    else:
        # Fallback: the detailed CSV carries description_text/city/posting_date
        # (MERCEDES_results.csv is title+link only, useless for tailoring).
        detailed_csv = PROJECT_ROOT / "MERCEDES_jobs_detailed.csv"
        frame = pd.read_csv(detailed_csv, keep_default_na=False, encoding="utf-8-sig")
        for _, record in frame.iterrows():
            description = str(record.get("description_text") or "").strip()
            if len(description) < DESCRIPTION_MIN_CHARS:
                continue
            tasks, qualifications = description, ""
            if "[Qualifications]" in description:
                tasks, qualifications = description.split("[Qualifications]", 1)
                tasks = tasks.replace("[Tasks]", "").strip()
                qualifications = qualifications.strip()
            location = " ".join(
                part for part in (record.get("city"), record.get("region")) if part
            )
            rows.append({
                "source": "mercedes",
                "title": str(record.get("title") or "").strip(),
                "company": str(record.get("company") or COMPANY_VALUE).strip(),
                "location": location,
                "posted_time": str(record.get("posting_date") or "").strip(),
                "job_url": str(record.get("link") or "").strip(),
                "job_description": description,
                "requirements": qualifications,
                "your_tasks": tasks,
                "_lang_text": f"{record.get('title', '')}\n{description}",
            })

    if not rows:
        raise RuntimeError(
            "no usable Mercedes jobs found -- run 1_MERCEDES_Jobs_fetching.py first"
        )

    # Recency window (posting_date is ISO in the JSON; parse defensively).
    if window_days > 0:
        cutoff = datetime.now() - timedelta(days=window_days)
        kept: list[dict] = []
        for row in rows:
            try:
                posted = datetime.fromisoformat(row["posted_time"].strip())
            except ValueError:
                continue  # unparseable date cannot be proven fresh -> drop
            if posted >= cutoff:
                kept.append(row)
        print(f"[STEP2] recency filter: {len(kept)}/{len(rows)} job(s) posted "
              f"within {window_days} day(s)")
        rows = kept

    # Unique-role cap: keep the first N distinct titles (duplicate req-IDs of
    # the same role collapse onto their first posting).
    if unique_roles is not None:
        kept_rows, seen_titles = [], set()
        for row in rows:
            title_key = re.sub(r"\s+", " ", row["title"].strip().lower())
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            kept_rows.append(row)
            if len(kept_rows) >= unique_roles:
                break
        print(f"[STEP2] unique-role cap: {len(kept_rows)} distinct role(s) from {len(rows)} posting(s)")
        rows = kept_rows

    if limit is not None:
        rows = rows[:limit]  # TEST ONLY cap
    if not rows:
        raise RuntimeError(
            f"no jobs left after filtering (window={window_days}d) -- widen the window or re-run step 1"
        )
    return pd.DataFrame(rows)


def _title_text(row: dict) -> str:
    """Title of a row dict (tolerates pandas rows too)."""
    return str(row.get("title") or "")


def language_filter(frame: pd.DataFrame) -> pd.DataFrame:
    """Classify the frame via the rule-based filter and keep ENGLISH_OK jobs."""
    lang = importlib.import_module("2_MERCEDES_language_filter")
    rows = lang.classify_rows(frame.to_dict("records"))
    english = [row for row in rows if row.get("Language_Filter") == "ENGLISH_OK"]
    print(f"[STEP2] language filter: {len(english)}/{len(rows)} job(s) are ENGLISH_OK")
    if not english:
        raise RuntimeError("no ENGLISH_OK Mercedes jobs -- nothing to do")
    return pd.DataFrame(english)


def build_adapted_csv(frame: pd.DataFrame) -> int:
    """Map ENGLISH_OK Mercedes rows onto the resume-generator schema.

    Exact duplicate postings (Mercedes lists the same role under several req
    IDs) are de-duplicated, and every dropped URL is written to
    job_url_aliases.csv pointing at the kept URL, so the final resume map can
    give EACH posting its tailored-resume entry.

    Returns the number of unique jobs written.
    """
    columns = ["source", "title", "company", "location", "posted_time",
               "job_url", "job_description", "requirements", "your_tasks", "apply_url"]
    adapted = frame[columns].copy()
    seen: dict[str, str] = {}  # description -> kept job_url
    kept_rows: list[pd.Series] = []
    aliases: list[dict] = []
    for _, row in adapted.iterrows():
        kept_url = seen.get(row["job_description"])
        if kept_url is None:
            seen[row["job_description"]] = row["job_url"]
            kept_rows.append(row)
        elif kept_url != row["job_url"]:
            aliases.append({"dropped_job_url": row["job_url"], "kept_job_url": kept_url})
    adapted = pd.DataFrame(kept_rows).reset_index(drop=True)
    if adapted.empty:
        raise RuntimeError("no English-friendly jobs survived de-duplication")

    MERCEDES_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    adapted.to_csv(ADAPTED_CSV, index=False, encoding="utf-8")
    if aliases:
        pd.DataFrame(aliases, columns=["dropped_job_url", "kept_job_url"]).to_csv(
            MERCEDES_OUTPUT_DIR / "job_url_aliases.csv", index=False, encoding="utf-8")
        print(f"[STEP2] {len(aliases)} duplicate posting(s) aliased to their kept URL")
    print(f"[STEP2] wrote {len(adapted)} unique English-friendly Mercedes job(s) -> {ADAPTED_CSV}")
    return len(adapted)


def _load_stage_records(output_json: Path, records_key: str) -> dict[str, dict]:
    """Load one stage's existing records keyed by job_url (empty when absent)."""
    if not output_json.exists():
        return {}
    try:
        payload = json.loads(output_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(r.get("job_url") or ""): r for r in payload.get(records_key, [])}


def _stage_is_done(records: dict[str, dict], error_field: str) -> bool:
    """A job's record is done when it exists and carries no error flag."""
    def done(url: str) -> bool:
        record = records.get(url)
        return record is not None and not record.get(error_field)
    return done


def _write_stage_input(urls: list[str], source_csv: Path) -> pd.DataFrame:
    """Write the remaining-jobs CSV the stages consume this run."""
    frame = pd.read_csv(source_csv, keep_default_na=False)
    remaining = frame[frame["job_url"].isin(urls)].reset_index(drop=True)
    remaining.to_csv(STAGE_INPUT_CSV, index=False, encoding="utf-8")
    return remaining


def run_resumable_stages() -> list[tuple[str, bool]]:
    """Run every stage over ONLY its not-yet-clean jobs, then merge results.

    Resume behaviour: stage outputs persist between runs; each run feeds the
    stage a stage_input.csv containing only jobs whose record is missing or
    flagged, and afterwards merges the freshly generated records into the
    full store (one record per job_url, newest wins). This makes long batches
    resumable after crashes/network drops without re-paying for finished jobs.
    """
    frame = pd.read_csv(ADAPTED_CSV, keep_default_na=False)
    all_urls = [str(url) for url in frame["job_url"]]

    results: list[tuple[str, bool]] = []
    for label, module_name, output_json_name, records_key, error_field in STAGES:
        print(f"\n=== STEP 2 | {label} ===")
        output_json = MERCEDES_OUTPUT_DIR / output_json_name
        existing = _load_stage_records(output_json, records_key)
        done = _stage_is_done(existing, error_field)
        todo_urls = [url for url in all_urls if not done(url)]
        print(f"[STEP2] {label}: {len(all_urls) - len(todo_urls)}/{len(all_urls)} already done, "
              f"{len(todo_urls)} to generate")
        stage_ok = True
        if todo_urls:
            remaining = _write_stage_input(todo_urls, ADAPTED_CSV)
            try:
                module = importlib.import_module(module_name)
                module.main(input_csv=STAGE_INPUT_CSV, output_json=output_json)
            except SystemExit as exc:  # stage __main__-style exits
                if int(exc.code or 0) not in (0, 1):
                    print(f"[STEP2] {label} FAILED: abnormal exit {exc.code}")
                    stage_ok = False
            except Exception as exc:  # noqa: BLE001 - one stage must not stop the others
                print(f"[STEP2] {label} FAILED: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                stage_ok = False
            # Merge the stage's fresh subset into the full store (newest wins).
            fresh = _load_stage_records(output_json, records_key)
            merged = dict(existing)
            merged.update(fresh)  # fresh subset only contains todo jobs + their updates
            _save_stage_store(output_json, records_key, list(merged.values()))
        final = _load_stage_records(output_json, records_key)
        usable = sum(1 for url in all_urls
                     if final.get(url) is not None and not final[url].get(error_field))
        flagged = sum(1 for url in all_urls
                      if final.get(url) is not None and final[url].get(error_field))
        missing = len(all_urls) - usable - flagged
        if usable == 0 and missing == len(all_urls):
            print(f"[STEP2] {label} FAILED: no usable records")
            stage_ok = False
        print(f"[STEP2] {label}: {usable} usable, {flagged} flagged, {missing} missing "
              f"-> {'OK' if stage_ok and usable else 'FAIL'}")
        results.append((label, stage_ok and usable > 0))
    return results


def _save_stage_store(output_json: Path, records_key: str, records: list[dict]) -> None:
    """Persist one stage's FULL merged record set."""
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
        "total_jobs": len(records),
        records_key: records,
    }
    output_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_stage(label: str, module_name: str, output_json_name: str) -> bool:
    """Run one existing generation stage with Mercedes input/output paths.

    The stage exit code alone is too strict: e.g. 4_skills returns 1 when a
    job is merely flagged for review (thin section), while the record is still
    saved and the resume builder excludes flagged jobs anyway. So the stage
    counts as OK when it did not crash AND at least one usable record was saved.
    """
    print(f"\n=== STEP 2 | {label} ===")
    output_json = MERCEDES_OUTPUT_DIR / output_json_name
    try:
        module = importlib.import_module(module_name)
        module.main(input_csv=ADAPTED_CSV, output_json=MERCEDES_OUTPUT_DIR / output_json_name)
    except SystemExit as exc:  # stage __main__-style exits
        if int(exc.code or 0) not in (0, 1):
            print(f"[STEP2] {label} FAILED: abnormal exit {exc.code}")
            return False
    except Exception as exc:  # noqa: BLE001 - one stage must not stop the others
        print(f"[STEP2] {label} FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False

    try:
        usable, flagged = _usable_records(output_json)
    except Exception as exc:  # noqa: BLE001 - unreadable output = stage failure
        print(f"[STEP2] {label} FAILED: output unreadable: {exc}")
        return False
    if usable == 0:
        print(f"[STEP2] {label} FAILED: no usable records in {output_json.name}")
        return False
    print(f"[STEP2] {label}: {usable} usable, {flagged} flagged for review -> OK")
    return True


def run_pipeline(window_days: int = DEFAULT_WINDOW_DAYS, limit: int | None = None,
                 unique_roles: int | None = None) -> int:
    """Filter by language, adapt the schema, run all four stages (resumable)."""
    master_frame = _build_master_frame(window_days, limit, unique_roles)
    english_frame = language_filter(master_frame)
    job_count = build_adapted_csv(english_frame)

    results = run_resumable_stages()
    ok = all(success for _, success in results)

    print("\n=== STEP 2 | SUMMARY ===")
    for label, success in results:
        print(f"  [{'OK  ' if success else 'FAIL'}] {label}")
    print(f"  {job_count} job(s) processed in this run")
    print(f"step 2 (Mercedes) {'SUCCESS' if ok else 'HAD FAILURES'} (exit code {0 if ok else 1})")
    return 0 if ok else 1


def main() -> int:
    """CLI wrapper around run_pipeline."""
    parser = argparse.ArgumentParser(description="Mercedes resume components (step 2).")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"keep jobs posted within this many days (default {DEFAULT_WINDOW_DAYS}, 0 = all)")
    parser.add_argument("--limit", type=int, default=None,
                        help="TEST ONLY: process at most this many jobs")
    parser.add_argument("--unique-roles", type=int, default=None,
                        help="keep only the first N DISTINCT role titles before limiting")
    args = parser.parse_args()
    return run_pipeline(args.window_days, args.limit, args.unique_roles)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
