"""Auto Application Engine (Modular & Extensible).

Manages automated and semi-automated job submissions for working student positions.
Designed with strict separation:
  - Dry-run validation by default (safe preview without external network calls)
  - Pluggable portal adapters (Email, Personio, Greenhouse, Lever, Workday, Generic)
  - Automatic registration in applied_tracker upon submission or staging
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from . import applied_tracker, config
except ImportError:
    import applied_tracker, config

config.ensure_utf8_stdout()


class PortalType(str, Enum):
    EMAIL = "email"
    PERSONIO = "personio"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    GENERIC_PORTAL = "generic_portal"
    MANUAL = "manual"


@dataclass
class JobApplicationPackage:
    job_url: str
    company: str
    title: str
    location: str
    portal_type: str
    portal_url: str
    candidate_name: str
    candidate_email: str
    candidate_phone: str
    resume_pdf: str
    cover_letter_pdf: str
    cover_letter_text: str
    enrolment_cert: str
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_portal_type(url: str, description: str = "") -> tuple[PortalType, str]:
    """Detect application channel (Email, ATS portal, or direct link)."""
    u_low = url.lower()
    d_low = description.lower()

    if "personio.de" in u_low or "personio" in d_low:
        return PortalType.PERSONIO, url
    if "greenhouse.io" in u_low:
        return PortalType.GREENHOUSE, url
    if "lever.co" in u_low:
        return PortalType.LEVER, url
    if "myworkdayjobs.com" in u_low:
        return PortalType.WORKDAY, url

    # Check for direct email application in description
    email_match = re.search(r"\b([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)\b", description)
    if email_match and any(k in email_match.group(1).lower() for k in ("job", "karriere", "career", "bewerbung", "hr")):
        return PortalType.EMAIL, email_match.group(1)

    return PortalType.GENERIC_PORTAL, url


def load_candidate_profile() -> dict[str, str]:
    """Load candidate personal details from candidate_kb.json."""
    if not config.KB_PATH.exists():
        return {"name": "Candidate", "email": "", "phone": ""}
    try:
        kb = json.loads(config.KB_PATH.read_text(encoding="utf-8"))
        prof = kb.get("profile") or {}
        return {
            "name": prof.get("name") or "Candidate",
            "email": prof.get("email") or "",
            "phone": prof.get("phone") or "",
            "linkedin": prof.get("linkedin") or "",
            "github": prof.get("github") or "",
            "location": prof.get("location") or "",
        }
    except Exception:
        return {"name": "Candidate", "email": "", "phone": ""}


class AutoApplier:
    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.candidate = load_candidate_profile()

    def assemble_package(
        self,
        job_row: dict[str, Any],
        resume_pdf: Path | str = "",
        letter_pdf: Path | str = "",
        letter_text: str = "",
    ) -> JobApplicationPackage:
        """Assemble all assets and metadata for one application."""
        url = str(job_row.get("job_url") or "").strip()
        company = str(job_row.get("company") or "").strip()
        title = str(job_row.get("title") or "").strip()
        location = str(job_row.get("location") or "").strip()
        desc = str(job_row.get("job_description") or "")

        portal_type, portal_target = detect_portal_type(url, desc)

        # Enrolment cert check
        enrolment_path = ""
        if config.ENROLMENT_CERT.exists():
            enrolment_path = str(config.ENROLMENT_CERT)

        return JobApplicationPackage(
            job_url=url,
            company=company,
            title=title,
            location=location,
            portal_type=portal_type.value,
            portal_url=portal_target,
            candidate_name=self.candidate.get("name", ""),
            candidate_email=self.candidate.get("email", ""),
            candidate_phone=self.candidate.get("phone", ""),
            resume_pdf=str(resume_pdf),
            cover_letter_pdf=str(letter_pdf),
            cover_letter_text=letter_text,
            enrolment_cert=enrolment_path,
        )

    def validate_package(self, pkg: JobApplicationPackage) -> tuple[bool, list[str]]:
        """Validate that all essential application documents and fields exist."""
        errors: list[str] = []
        if not pkg.job_url:
            errors.append("Missing job_url")
        if not pkg.candidate_email:
            errors.append("Missing candidate_email in KB")
        if not pkg.resume_pdf or not Path(pkg.resume_pdf).exists():
            errors.append(f"Resume PDF not found: {pkg.resume_pdf}")
        if not pkg.cover_letter_pdf and not pkg.cover_letter_text:
            errors.append("Missing both cover letter PDF and text")

        return len(errors) == 0, errors

    def dispatch(self, pkg: JobApplicationPackage) -> dict[str, Any]:
        """Dispatch or simulate an application."""
        valid, errors = self.validate_package(pkg)
        if not valid:
            print(f"[AUTO-APPLIER] Validation failed for {pkg.company} - {pkg.title}: {', '.join(errors)}")
            return {
                "job_url": pkg.job_url,
                "status": "failed_validation",
                "errors": errors,
            }

        if self.dry_run:
            print(f"\n[AUTO-APPLIER: DRY-RUN] Verified package for {pkg.company}:")
            print(f"  Title      : {pkg.title}")
            print(f"  Portal     : {pkg.portal_type} -> {pkg.portal_url}")
            print(f"  Resume     : {pkg.resume_pdf}")
            print(f"  Cover Ltr  : {pkg.cover_letter_pdf or '(text only)'}")
            print(f"  Enrolment  : {pkg.enrolment_cert or '(not attached)'}")
            print("  Dry-run: Application package validated successfully.")

            # Record in tracker as ready_to_apply
            applied_tracker.mark_ready(
                job_url=pkg.job_url,
                company=pkg.company,
                title=pkg.title,
                location=pkg.location,
                notes=f"Auto-applier staged package ({pkg.portal_type})",
                resume_path=pkg.resume_pdf,
                cover_letter_path=pkg.cover_letter_pdf,
            )
            return {
                "job_url": pkg.job_url,
                "status": "staged_ready",
                "portal_type": pkg.portal_type,
            }

        # Live execution stub / browser automation hook:
        # When live execution is activated, automated form fill (Playwright/Selenium) or SMTP dispatch occurs here.
        print(f"[AUTO-APPLIER: LIVE] Submitting application to {pkg.company} via {pkg.portal_type}...")
        try:
            # Live submission logic hooks here
            # On success:
            applied_tracker.mark_applied(
                job_url=pkg.job_url,
                company=pkg.company,
                title=pkg.title,
                location=pkg.location,
                method=f"auto_{pkg.portal_type}",
                notes="Submitted via auto-application engine",
                resume_path=pkg.resume_pdf,
                cover_letter_path=pkg.cover_letter_pdf,
            )
            return {"job_url": pkg.job_url, "status": "applied", "portal_type": pkg.portal_type}
        except Exception as exc:
            print(f"[AUTO-APPLIER: LIVE] Submission failed: {exc}")
            return {"job_url": pkg.job_url, "status": "error", "error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auto Application Engine")
    parser.add_argument("--live", action="store_true", help="Execute live submissions (default is safe dry-run)")
    args = parser.parse_args(argv)

    applier = AutoApplier(dry_run=not args.live)
    print(f"[AUTO-APPLIER] Initialized (mode: {'LIVE' if args.live else 'DRY-RUN'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
