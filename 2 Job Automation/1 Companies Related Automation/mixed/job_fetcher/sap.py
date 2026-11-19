"""SAP job fetcher & language filter module."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .base import BaseJobFetcher, NormalizedJob
from .language_filter import classify_text
from .registry import register_fetcher


@register_fetcher("sap")
class SAPJobFetcher(BaseJobFetcher):
    company_id = "sap"
    display_name = "SAP SE"
    portal_type = "SuccessFactors"

    def fetch_jobs(self, force: bool = False, limit: int | None = None) -> list[NormalizedJob]:
        csv_path = self.workspace_root / "SAP FETCHER" / "sap_results.csv"
        
        if force or not csv_path.exists() or csv_path.stat().st_size == 0:
            print(f"[sap] Running live fetch via 1_sap_job_fetcher.py...")
            import subprocess
            import sys
            fetcher_script = self.workspace_root / "SAP FETCHER" / "1_sap_job_fetcher.py"
            subprocess.run([sys.executable, str(fetcher_script)], cwd=str(fetcher_script.parent), check=True)

        if not csv_path.exists():
            raise FileNotFoundError(f"SAP results file not found: {csv_path}")

        jobs: list[NormalizedJob] = []
        with csv_path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            for r in reader:
                link = str(r.get("Link") or r.get("job_url") or "").strip()
                title = str(r.get("Job Title") or r.get("title") or "").strip()
                desc = str(r.get("Description") or r.get("job_description") or "").strip()
                if not link or not title or not desc:
                    continue

                lang, evidence = classify_text(desc)

                location = str(r.get("Location") or "Walldorf, Germany").strip()
                job = NormalizedJob(
                    job_url=link,
                    title=title,
                    company="SAP SE",
                    job_description=desc,
                    detail_company_name="SAP SE",
                    source="SuccessFactors",
                    source_job_id=str(r.get("Job ID") or r.get("job_id") or ""),
                    location=location,
                    detail_location=location,
                    posting_date=str(r.get("Date") or ""),
                    apply_url=link,
                    language_filter=lang,
                    filter_evidence=evidence,
                    extra=r,
                )
                jobs.append(job)
                if limit and len(jobs) >= limit:
                    break

        print(f"[sap] Loaded {len(jobs)} jobs (English OK: {sum(1 for j in jobs if j.language_filter == 'ENGLISH_OK')})")
        return jobs


if __name__ == "__main__":
    fetcher = SAPJobFetcher()
    results = fetcher.fetch_jobs(limit=5)
    for j in results:
        print(f"- {j.title} [{j.language_filter}]: {j.job_url}")
