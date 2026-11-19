"""Prepares company jobs for the V2 resume + cover letter engine.

Maps normalized job objects into the engine's input CSV:
  mixed/resume_and_cover_letter/program_files/output/2_filted_jobs.csv
with all columns expected by Step 4 (analysis & components) and Step 6 (cover letters).
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
OUT_CSV = ROOT / "program_files" / "output" / "2_filted_jobs.csv"

# Complete columns combining Step 4 and Step 6 requirements
ENGINE_COLUMNS = [
    "job_url",
    "title",
    "company",
    "job_description",
    "detail_company_name",
    "source",
    "source_job_id",
    "location",
    "detail_location",
    "requirements",
    "your_tasks",
    "applicant_profile",
    "about_us",
    "what_they_offer",
    "snippet",
    "posting_date",
    "apply_url",
    "language_filter",
    "filter_evidence",
]


def prepare_jobs(jobs: Sequence[dict], force: bool = False) -> int:
    """Write normalized job dicts into 2_filted_jobs.csv."""
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    if OUT_CSV.exists() and force:
        backup = OUT_CSV.with_name("2_filted_jobs.prev.csv")
        shutil.move(str(OUT_CSV), str(backup))

    mapped: list[dict] = []
    seen_urls: set[str] = set()

    for job in jobs:
        url = str(job.get("job_url") or "").strip()
        desc = str(job.get("job_description") or "").strip()
        title = str(job.get("title") or "").strip()
        if not url or not desc or not title or url in seen_urls:
            continue

        seen_urls.add(url)
        row = {col: str(job.get(col) or "") for col in ENGINE_COLUMNS}
        # ensure defaults
        if not row["company"]:
            row["company"] = "Unknown"
        mapped.append(row)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ENGINE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(mapped)

    print(f"[prepare] Wrote {len(mapped)} jobs to {OUT_CSV.name}")
    return len(mapped)


def prepare_for_company(company_id: str, force: bool = False, limit: int | None = None) -> int:
    """Fetch/load jobs for company_id using job_fetcher and prepare 2_filted_jobs.csv."""
    # Add mixed directory to sys.path to import job_fetcher
    mixed_dir = ROOT.parent
    if str(mixed_dir) not in sys.path:
        sys.path.insert(0, str(mixed_dir))

    from job_fetcher.registry import get_fetcher
    fetcher = get_fetcher(company_id)
    jobs = fetcher.fetch_jobs(force=force, limit=limit)
    raw_dicts = [j.to_dict() for j in jobs]
    return prepare_jobs(raw_dicts, force=force)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        company = sys.argv[1]
        prepare_for_company(company)
    else:
        print("Usage: python prepare_jobs.py <company_id>")
