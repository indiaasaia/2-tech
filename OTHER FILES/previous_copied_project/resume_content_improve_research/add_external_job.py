"""Add an externally captured posting to the pipeline input CSV (2_filted_jobs.csv).

Used when a posting is discovered live on a company career site (not covered by
the stepstone/workingstudentjobs scrapers). Fills the columns the step-4 engine
and the letter builder actually consume; unknown columns stay empty.

Run:  python resume_content_improve_research/add_external_job.py
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from resume_content_improve_research import config

# Captured 2026-09-27 from https://www.brainlab.com/career/jobs/working-student-ux-ui-design-munich-by-de-744000148153599/
POSTING = {
    "source": "brainlab_career_site",
    "source_job_id": "744000148153599",
    "title": "Working Student UX & UI Design",
    "company": "Brainlab",
    "location": "Munich, BY, Germany",
    "posted_time": "2026-09-27",
    "job_url": "https://www.brainlab.com/career/jobs/working-student-ux-ui-design-munich-by-de-744000148153599/",
    "company_url": "https://www.brainlab.com",
    "snippet": "Working Student UX & UI Design - R&D Software - Associate - Munich, BY, Germany",
    "detail_company_name": "Brainlab",
    "detail_location": "Munich, BY, Germany",
    "detail_contract_type": "Working Student",
    "detail_work_type": "Part-time",
    "detail_online_date": "2026-09-27",
    "job_description": (
        "Join Brainlab's User Experience Design team and help shape the experience of medical "
        "software used by healthcare professionals around the world. As part of the Usability & "
        "Design department, you will work closely with UX Designers and GUI Engineers on the "
        "structure, interaction, and visual design of our products. You will contribute to our "
        "design system and support the team in making design work more consistent, scalable, and "
        "ready for new use cases. Practical experience working on design systems for complex "
        "medical software; close collaboration with experienced UX Designers and GUI Engineers; "
        "the opportunity to contribute to real product work and see how designs are implemented."
    ),
    "your_tasks": (
        "Contribute to the design, documentation, and maintenance of our design system; "
        "Help structure and prepare the design system for AI-assisted design workflows and new "
        "use cases; Create and maintain reusable wireframe components; Support UX/UI Designers "
        "with interface and visual design tasks in Figma; Explore new AI-supported approaches to "
        "design together with the team."
    ),
    "requirements": (
        "Currently enrolled in a degree program related to UX design, interaction design, "
        "human-computer interaction, interface design, media design, or a comparable field "
        "(Bachelor's from the 3rd semester onwards; Master's students welcome from the 1st "
        "semester); A strong interest in design systems and a willingness to learn how they are "
        "built and maintained; Fluent in English and comfortable communicating in German in a "
        "professional context; Initial experience with UI design, interaction design, or visual "
        "design and interest in both conceptual thinking and detailed interface design; "
        "A collaborative mindset and enthusiasm for working with cross-functional teams; "
        "Curiosity about AI-supported design workflows."
    ),
    "what_they_offer": (
        "Practical experience working on design systems for complex medical software; close "
        "collaboration with experienced UX Designers and GUI Engineers; flexible working hours; "
        "subsidized company restaurant; fitness program; regular student lunches and company "
        "events. Contact person: Sandra Lechner."
    ),
    "about_us": (
        "At the forefront of health technology for over 35 years, Munich-based Brainlab "
        "digitizes medical workflows, from diagnosis to therapy, to offer clinicians and "
        "patients better treatment possibilities. Our innovative digital ecosystem forms the "
        "basis for modern healthcare technology in 4000 hospitals in 120 countries."
    ),
}


def main() -> int:
    path = config.FILTERED_JOBS_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source", "source_job_id", "title", "company", "location", "posted_time", "job_url",
        "company_url", "snippet", "scraped_at_utc", "detail_company_name", "detail_location",
        "detail_contract_type", "detail_work_type", "detail_online_date", "job_description",
        "applicant_profile", "what_they_offer", "about_us", "your_tasks", "requirements",
        "we_offer", "predicted_salary", "details_fetched", "detail_error",
    ]
    posting = dict(POSTING)
    posting["scraped_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    posting["details_fetched"] = "True"

    existing: list[dict] = []
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as fh:
            existing = list(csv.DictReader(fh))
        if any(str(r.get("job_url") or "") == posting["job_url"] for r in existing):
            print(f"[EXTERNAL] already present: {posting['job_url']}")
            return 0

    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        if not existing:
            writer.writeheader()
        writer.writerow(posting)
    print(f"[EXTERNAL] appended: {posting['company']} — {posting['title']} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
