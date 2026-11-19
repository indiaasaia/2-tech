"""Mercedes-Benz job fetcher & language filter module."""
from __future__ import annotations

import json
from pathlib import Path

from .base import BaseJobFetcher, NormalizedJob
from .language_filter import classify_text
from .registry import register_fetcher


@register_fetcher("mercedes")
class MercedesJobFetcher(BaseJobFetcher):
    company_id = "mercedes"
    display_name = "Mercedes-Benz"
    portal_type = "Workday / Taleo"

    def fetch_jobs(self, force: bool = False, limit: int | None = None) -> list[NormalizedJob]:
        json_path = self.workspace_root / "mercedes" / "MERCEDES_jobs_full.json"
        
        if force or not json_path.exists() or json_path.stat().st_size == 0:
            print(f"[mercedes] Running live fetch via 1_MERCEDES_Jobs_fetching.py...")
            import subprocess
            import sys
            fetcher_script = self.workspace_root / "mercedes" / "1_MERCEDES_Jobs_fetching.py"
            subprocess.run([sys.executable, str(fetcher_script)], cwd=str(fetcher_script.parent), check=True)

        if not json_path.exists():
            raise FileNotFoundError(f"Mercedes jobs file not found: {json_path}")

        raw_data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(raw_data, dict):
            for v in raw_data.values():
                if isinstance(v, list):
                    raw_data = v
                    break

        jobs: list[NormalizedJob] = []
        for r in raw_data:
            link = str(r.get("link") or r.get("job_url") or "").strip()
            title = str(r.get("title") or "").strip()
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

            # Resolve actual apply url (e.g. from custom_fields for Taleo)
            apply_url = link
            raw_cf = str(r.get("custom_fields") or "")
            if raw_cf:
                try:
                    cf = json.loads(raw_cf)
                    if cf.get("apply_url"):
                        apply_url = str(cf["apply_url"])
                except Exception:
                    pass

            job = NormalizedJob(
                job_url=link,
                title=title,
                company="Mercedes-Benz Group",
                job_description=full_desc,
                detail_company_name=str(r.get("company") or "Mercedes-Benz Tech Innovation GmbH"),
                source="Workday/Taleo",
                source_job_id=str(r.get("job_id") or ""),
                location=str(r.get("city") or ""),
                detail_location=f"{r.get('city', '')}, {r.get('country', 'Germany')}".strip(", "),
                posting_date=str(r.get("posting_date") or ""),
                apply_url=apply_url,
                language_filter=lang,
                filter_evidence=evidence,
                extra=r,
            )
            jobs.append(job)
            if limit and len(jobs) >= limit:
                break

        print(f"[mercedes] Loaded {len(jobs)} jobs (English OK: {sum(1 for j in jobs if j.language_filter == 'ENGLISH_OK')})")
        return jobs


if __name__ == "__main__":
    fetcher = MercedesJobFetcher()
    results = fetcher.fetch_jobs(limit=5)
    for j in results:
        print(f"- {j.title} [{j.language_filter}]: {j.job_url}")
