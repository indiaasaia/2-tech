"""Siemens job fetcher & language filter module."""
from __future__ import annotations

import json
from pathlib import Path

from .base import BaseJobFetcher, NormalizedJob
from .language_filter import classify_text
from .registry import register_fetcher


@register_fetcher("simense", alias=True)
@register_fetcher("siemens")
class SiemensJobFetcher(BaseJobFetcher):
    company_id = "siemens"
    display_name = "Siemens AG"
    portal_type = "Avature"

    def fetch_jobs(self, force: bool = False, limit: int | None = None) -> list[NormalizedJob]:
        json_path = self.workspace_root / "simense" / "SIMENSE_jobs_full.json"
        
        if force or not json_path.exists() or json_path.stat().st_size == 0:
            print(f"[siemens] Running live fetch via 1_SIMENSE_jobs_fetching.py...")
            import subprocess
            import sys
            fetcher_script = self.workspace_root / "simense" / "1_SIMENSE_jobs_fetching.py"
            subprocess.run([sys.executable, str(fetcher_script)], cwd=str(fetcher_script.parent), check=True)

        if not json_path.exists():
            raise FileNotFoundError(f"Siemens jobs file not found: {json_path}")

        raw_data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(raw_data, dict):
            for v in raw_data.values():
                if isinstance(v, list):
                    raw_data = v
                    break

        jobs: list[NormalizedJob] = []
        for r in raw_data:
            link = str(r.get("job_detail_url") or r.get("link") or "").strip()
            title = str(r.get("job_title") or r.get("title") or "").strip()
            desc = str(r.get("description_text") or "").strip()
            if not link or not title or not desc:
                continue

            lang, evidence = classify_text(desc)

            loc = str(r.get("location") or "Germany").strip()
            job = NormalizedJob(
                job_url=link,
                title=title,
                company="Siemens AG",
                job_description=desc,
                detail_company_name=str(r.get("company") or "Siemens AG"),
                source="Avature",
                source_job_id=str(r.get("job_id") or ""),
                location=loc,
                detail_location=loc,
                posting_date=str(r.get("posting_date") or ""),
                apply_url=link,
                language_filter=lang,
                filter_evidence=evidence,
                extra=r,
            )
            jobs.append(job)
            if limit and len(jobs) >= limit:
                break

        print(f"[siemens] Loaded {len(jobs)} jobs (English OK: {sum(1 for j in jobs if j.language_filter == 'ENGLISH_OK')})")
        return jobs


if __name__ == "__main__":
    fetcher = SiemensJobFetcher()
    results = fetcher.fetch_jobs(limit=5)
    for j in results:
        print(f"- {j.title} [{j.language_filter}]: {j.job_url}")
