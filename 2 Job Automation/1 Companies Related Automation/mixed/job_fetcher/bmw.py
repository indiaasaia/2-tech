"""BMW Group job fetcher & language filter module."""
from __future__ import annotations

import json
from pathlib import Path

from .base import BaseJobFetcher, NormalizedJob
from .language_filter import classify_text
from .registry import register_fetcher


@register_fetcher("bmw")
class BMWJobFetcher(BaseJobFetcher):
    company_id = "bmw"
    display_name = "BMW Group"
    portal_type = "BMW Career Portal (Akamai)"

    def fetch_jobs(self, force: bool = False, limit: int | None = None) -> list[NormalizedJob]:
        json_path = self.workspace_root / "bmw" / "BMW_jobs_full.json"
        
        if force or not json_path.exists() or json_path.stat().st_size == 0:
            print(f"[bmw] Running live fetch via 1_BMW_jobs_fetching.py...")
            import subprocess
            import sys
            fetcher_script = self.workspace_root / "bmw" / "1_BMW_jobs_fetching.py"
            subprocess.run([sys.executable, str(fetcher_script)], cwd=str(fetcher_script.parent), check=True)

        if not json_path.exists():
            raise FileNotFoundError(f"BMW jobs file not found: {json_path}")

        raw_data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(raw_data, dict):
            for v in raw_data.values():
                if isinstance(v, list):
                    raw_data = v
                    break

        jobs: list[NormalizedJob] = []
        for r in raw_data:
            link = str(r.get("link") or r.get("job_url") or "").strip()
            title = str(r.get("title") or r.get("job_title") or "").strip()
            if not link or not title:
                continue

            desc_parts = [
                str(r.get("description_text") or "").strip(),
                str(r.get("start_info") or "").strip(),
            ]
            full_desc = "\n\n".join(p for p in desc_parts if p)
            if not full_desc:
                continue

            lang, evidence = classify_text(full_desc)

            job = NormalizedJob(
                job_url=link,
                title=title,
                company="BMW Group",
                job_description=full_desc,
                detail_company_name=str(r.get("company") or "BMW AG"),
                source="BMW Group",
                source_job_id=str(r.get("job_id") or ""),
                location=str(r.get("city") or "Munich"),
                detail_location=f"{r.get('city', '')}, {r.get('country', 'Germany')}".strip(", "),
                posting_date=str(r.get("posting_date") or ""),
                apply_url=link,
                language_filter=lang,
                filter_evidence=evidence,
                extra=r,
            )
            jobs.append(job)
            if limit and len(jobs) >= limit:
                break

        print(f"[bmw] Loaded {len(jobs)} jobs (English OK: {sum(1 for j in jobs if j.language_filter == 'ENGLISH_OK')})")
        return jobs


if __name__ == "__main__":
    fetcher = BMWJobFetcher()
    results = fetcher.fetch_jobs(limit=5)
    for j in results:
        print(f"- {j.title} [{j.language_filter}]: {j.job_url}")
