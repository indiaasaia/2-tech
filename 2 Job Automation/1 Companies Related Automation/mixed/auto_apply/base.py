"""Base classes and interfaces for auto-apply modules."""
from __future__ import annotations

import csv
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ApplicationResult:
    company_id: str
    job_url: str
    status: str  # DRY_RUN, SUCCESS, FAILED, CAPTCHA_DETECTED, NEEDS_ATTENTION, BLOCKED, NO_APPLIER
    resume_path: str = ""
    letter_path: str = ""
    stages_reached: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_id": self.company_id,
            "job_url": self.job_url,
            "status": self.status,
            "resume_path": self.resume_path,
            "letter_path": self.letter_path,
            "stages_reached": self.stages_reached,
            "errors": self.errors,
            "screenshots": self.screenshots,
            "details": self.details,
        }


class BaseApplier(ABC):
    """Abstract base class for company auto-appliers."""

    company_id: str
    display_name: str
    portal_name: str

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root or Path(__file__).resolve().parents[2]
        self.mixed_root = Path(__file__).resolve().parents[1]
        self.results_dir = Path(__file__).resolve().parent / "results" / self.company_id
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def load_bundle_map(self) -> list[dict]:
        """Loads job bundle map created by resume_and_cover_letter hub."""
        map_path = (
            self.mixed_root
            / "resume_and_cover_letter"
            / "program_files"
            / "output_v2"
            / "state"
            / f"job_bundle_map_{self.company_id}.csv"
        )
        if not map_path.exists():
            return []
        with map_path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    @abstractmethod
    def apply_one(
        self,
        job_url: str,
        resume_path: str | Path,
        letter_path: str | Path | None = None,
        dry_run: bool = True,
        headless: bool = False,
        **kwargs,
    ) -> ApplicationResult:
        """Apply to one specific job posting."""
        pass

    def apply_batch(
        self,
        limit: int | None = None,
        dry_run: bool = True,
        headless: bool = False,
        jobs_filter: str | None = None,
        **kwargs,
    ) -> list[ApplicationResult]:
        """Apply to all verified jobs in the company bundle map."""
        targets = self.load_bundle_map()
        if not targets:
            print(f"[{self.company_id}] No verified bundles found in bundle map.")
            return []

        results: list[ApplicationResult] = []
        for row in targets:
            if row.get("status") != "OK":
                continue
            url = row.get("job_url", "")
            if jobs_filter and jobs_filter not in url:
                continue

            resume = row.get("resume_pdf", "")
            letter = row.get("letter_pdf") or None

            res = self.apply_one(
                job_url=url,
                resume_path=resume,
                letter_path=letter,
                dry_run=dry_run,
                headless=headless,
                **kwargs,
            )
            results.append(res)
            if limit and len(results) >= limit:
                break

        return results
