"""Siemens Energy job fetcher & language filter module."""
from __future__ import annotations

import json
from pathlib import Path

from .base import BaseJobFetcher, NormalizedJob
from .language_filter import classify_text
from .registry import register_fetcher


@register_fetcher("simense_energy", alias=True)
@register_fetcher("siemens_energy")
class SiemensEnergyJobFetcher(BaseJobFetcher):
    company_id = "siemens_energy"
    display_name = "Siemens Energy"
    portal_type = "Avature"

    def fetch_jobs(self, force: bool = False, limit: int | None = None) -> list[NormalizedJob]:
        json_path = self.workspace_root / "simense_energy" / "SIMENSE_ENERGY_jobs_full.json"
        
        if force or not json_path.exists() or json_path.stat().st_size == 0:
            print(f"[siemens_energy] Running live fetch via 1_SIMENSE_ENERGY_jobs_fetching.py...")
            import subprocess
            import sys
            fetcher_script = self.workspace_root / "simense_energy" / "1_SIMENSE_ENERGY_jobs_fetching.py"
            subprocess.run([sys.executable, str(fetcher_script)], cwd=str(fetcher_script.parent), check=True)

        if not json_path.exists():
            raise FileNotFoundError(f"Siemens Energy jobs file not found: {json_path}")

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
            desc_parts = [
                str(r.get("Description_Text") or "").strip(),
                str(r.get("Summary") or "").strip(),
            ]
            full_desc = "\n\n".join(p for p in desc_parts if p)
            if not link or not title or not full_desc:
                continue

            lang, evidence = classify_text(full_desc)

            loc = str(r.get("Location") or "Germany").strip()
            job = NormalizedJob(
                job_url=link,
                title=title,
                company="Siemens Energy",
                job_description=full_desc,
                detail_company_name=str(r.get("Company") or "Siemens Energy"),
                source="Avature",
                source_job_id=str(r.get("Job ID") or ""),
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

        print(f"[siemens_energy] Loaded {len(jobs)} jobs (English OK: {sum(1 for j in jobs if j.language_filter == 'ENGLISH_OK')})")
        return jobs


if __name__ == "__main__":
    fetcher = SiemensEnergyJobFetcher()
    results = fetcher.fetch_jobs(limit=5)
    for j in results:
        print(f"- {j.title} [{j.language_filter}]: {j.job_url}")
