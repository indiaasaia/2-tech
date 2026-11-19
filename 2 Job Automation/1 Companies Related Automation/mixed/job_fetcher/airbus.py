"""Airbus job fetcher & language filter module."""
from __future__ import annotations

import json
from pathlib import Path

from .base import BaseJobFetcher, NormalizedJob
from .language_filter import classify_text
from .registry import register_fetcher


@register_fetcher("airbus")
class AirbusJobFetcher(BaseJobFetcher):
    company_id = "airbus"
    display_name = "Airbus"
    portal_type = "Workday CXS"

    def fetch_jobs(self, force: bool = False, limit: int | None = None) -> list[NormalizedJob]:
        json_path = self.workspace_root / "airbus" / "AIRBUS_jobs_full.json"
        
        if force or not json_path.exists() or json_path.stat().st_size == 0:
            print(f"[airbus] Running live fetch via 1_AIRBUS_jobs_fetching.py...")
            import subprocess
            import sys
            fetcher_script = self.workspace_root / "airbus" / "1_AIRBUS_jobs_fetching.py"
            subprocess.run([sys.executable, str(fetcher_script)], cwd=str(fetcher_script.parent), check=True)

        if not json_path.exists():
            raise FileNotFoundError(f"Airbus jobs file not found: {json_path}")

        raw_data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(raw_data, dict):
            for v in raw_data.values():
                if isinstance(v, list):
                    raw_data = v
                    break

        jobs: list[NormalizedJob] = []
        for r in raw_data:
            link = str(r.get("Apply_URL") or r.get("Link") or r.get("job_url") or "").strip()
            title = str(r.get("Detail_Title") or r.get("Title") or "").strip()
            desc = str(r.get("Description_Text") or "").strip()
            if not link or not title or not desc:
                continue

            lang, evidence = classify_text(desc)

            loc = str(r.get("Location") or "Germany").strip()
            job = NormalizedJob(
                job_url=link,
                title=title,
                company="Airbus",
                job_description=desc,
                detail_company_name="Airbus",
                source="Workday CXS",
                source_job_id=str(r.get("Job_ID") or ""),
                location=loc,
                detail_location=loc,
                posting_date=str(r.get("Date") or ""),
                apply_url=link,
                language_filter=lang,
                filter_evidence=evidence,
                extra=r,
            )
            jobs.append(job)
            if limit and len(jobs) >= limit:
                break

        print(f"[airbus] Loaded {len(jobs)} jobs (English OK: {sum(1 for j in jobs if j.language_filter == 'ENGLISH_OK')})")
        return jobs


if __name__ == "__main__":
    fetcher = AirbusJobFetcher()
    results = fetcher.fetch_jobs(limit=5)
    for j in results:
        print(f"- {j.title} [{j.language_filter}]: {j.job_url}")
