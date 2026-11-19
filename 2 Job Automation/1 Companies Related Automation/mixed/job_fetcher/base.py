"""Base classes and types for job fetchers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class NormalizedJob:
    job_url: str
    title: str
    company: str
    job_description: str
    detail_company_name: str = ""
    source: str = ""
    source_job_id: str = ""
    location: str = ""
    detail_location: str = ""
    requirements: str = ""
    your_tasks: str = ""
    applicant_profile: str = ""
    about_us: str = ""
    what_they_offer: str = ""
    snippet: str = ""
    posting_date: str = ""
    apply_url: str = ""
    language_filter: str = "UNSURE"  # ENGLISH_OK, GERMAN_REQUIRED, UNSURE
    filter_evidence: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # flatten extra fields
        extra = d.pop("extra", {})
        for k, v in extra.items():
            if k not in d:
                d[k] = v
        return d


class BaseJobFetcher(ABC):
    """Abstract base class for all company job fetchers."""

    company_id: str
    display_name: str
    portal_type: str = ""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root or Path(__file__).resolve().parents[2]

    @abstractmethod
    def fetch_jobs(self, force: bool = False, limit: int | None = None) -> list[NormalizedJob]:
        """Fetch jobs, apply language filter, and return normalized jobs.

        Args:
            force: If True, bypass cached data and re-fetch from network.
            limit: Optional limit on the number of jobs returned.
        """
        pass
