"""Fetch workingstudentjobs.de jobs as a DataFrame. Import and call ``fetch_workingstudentjobs_jobs``."""
from __future__ import annotations

import pandas as pd

from app.phase1 import workingstudent_fetcher


def fetch_workingstudentjobs_jobs(
    pages: int | None = None,
    details: bool = True,
    max_age_days: float | None = None,
) -> pd.DataFrame:
    """Fetch workingstudentjobs.de jobs (listings + full details) and return them as a DataFrame."""
    return workingstudent_fetcher.fetch(
        max_pages=pages,
        fetch_details=details,
        max_posting_age_days=max_age_days,
    )


def get_workingstudent_jobs(
    pages: int | None = None,
    details: bool = True,
    max_age_days: float | None = None,
) -> list[dict]:
    """Fetch workingstudentjobs.de jobs and return them as a list of job dicts."""
    frame = fetch_workingstudentjobs_jobs(
        pages=pages,
        details=details,
        max_age_days=max_age_days,
    )
    return frame.to_dict("records") if frame is not None else []