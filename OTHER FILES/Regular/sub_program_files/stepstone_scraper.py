"""Fetch Stepstone jobs as a DataFrame. Import and call ``fetch_stepstone_jobs``."""
from __future__ import annotations

import pandas as pd

from app.phase1 import stepstone_fetcher


def fetch_stepstone_jobs(
    keywords: list[str] | None = None,
    pages: int | None = None,
    details: bool = True,
    headless: bool = True,
    max_age_days: float | None = None,
) -> pd.DataFrame:
    """Fetch Stepstone jobs (listings + full details) and return them as a DataFrame."""
    return stepstone_fetcher.fetch(
        max_pages=pages,
        fetch_details=details,
        headless=headless,
        max_posting_age_days=max_age_days,
    )


def get_stepstone_jobs(
    keywords: list[str] | None = None,
    pages: int | None = None,
    details: bool = True,
    headless: bool = True,
    max_age_days: float | None = None,
) -> list[dict]:
    """Fetch Stepstone jobs and return them as a list of job dicts."""
    frame = fetch_stepstone_jobs(
        keywords=keywords,
        pages=pages,
        details=details,
        headless=headless,
        max_age_days=max_age_days,
    )
    return frame.to_dict("records") if frame is not None else []