"""Portal-aware delivery: plain-text rendering + per-portal application bundles.

Portal reality in Germany (what actually changes per portal):
  - StepStone: PDF upload in the "Anschreiben/Cover letter" document slot;
    the file name should be neutral (Anschreiben_<Company>.pdf).
  - workingstudentjobs / direct portals: PDF upload, sometimes DOCX too.
  - Many application forms (incl. XING/Indeed quick-apply): a TEXT FIELD for
    the letter ("Nachricht", "Message") — there the PDF alone is not enough.
  - Some scrapers cannot see the application form fields; the manifest is
    therefore best-effort guidance, not a parser of the form itself.

So the engine ships THREE artifacts per letter (pdf/txt/docx) plus a
per-portal manifest telling the user exactly what to upload where. The
letter CONTENT stays portal-agnostic on purpose: what varies is delivery.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from resume_content_improve_research import config

# Portal -> delivery requirements (letter artifact + notes for the user).
PORTAL_REQUIREMENTS: dict[str, dict] = {
    "stepstone": {
        "letter_artifact": "pdf",
        "pdf_upload_slot": "Anschreiben / Cover letter document slot",
        "text_field": False,
        "docx": False,
        "notes": "Upload the PDF in the Anschreiben slot during the online application.",
    },
    "workingstudentjobs": {
        "letter_artifact": "pdf",
        "pdf_upload_slot": "Cover letter / Anschreiben upload",
        "text_field": True,
        "docx": True,
        "notes": "PDF upload; if the form has a message field, paste the .txt version.",
    },
    "linkedin": {
        "letter_artifact": "pdf",
        "pdf_upload_slot": "Cover letter attachment (optional slot)",
        "text_field": True,
        "docx": False,
        "notes": "Attach the PDF; for Easy-Apply paste the .txt into the message field.",
    },
    "xing": {
        "letter_artifact": "pdf",
        "pdf_upload_slot": "Anschreiben document slot",
        "text_field": True,
        "docx": False,
        "notes": "Attach the PDF; paste the .txt into the message box when the form asks for a Nachricht.",
    },
    "indeed": {
        "letter_artifact": "pdf",
        "pdf_upload_slot": "Cover letter attachment",
        "text_field": True,
        "docx": False,
        "notes": "Attach the PDF; for Indeed-Apply paste the .txt into the cover-letter field.",
    },
    "unknown": {
        "letter_artifact": "pdf",
        "pdf_upload_slot": "application portal upload",
        "text_field": True,
        "docx": True,
        "notes": "Unknown portal: carry the PDF + the .txt (message-field fallback).",
    },
}


@dataclass
class PortalBundle:
    portal: str
    letter_pdf: str = ""
    letter_docx: str = ""
    letter_txt: str = ""
    resume_pdf: str = ""
    resume_docx: str = ""
    upload_slot: str = ""
    notes: str = ""
    text_field: bool = False
    requires_docx: bool = False
    artifacts_complete: bool = False
    missing: list[str] = field(default_factory=list)


def letter_plaintext(letter) -> str:
    """Render the letter as plain text (for portal message fields + .txt).

    Line-based layout mirrors the DIN 5008 print structure in text form:
    sender block, company block, date, subject, salutation, 4 paragraphs,
    sign-off, name.
    """
    lines: list[str] = []
    if letter.sender_name:
        lines += [letter.sender_name, letter.sender_address, letter.sender_contact, letter.sender_links]
    if letter.company_block:
        lines += [""]
        lines += [ln for ln in letter.company_block.splitlines() if ln.strip()]
    lines += ["", letter.date_line, "", letter.subject, "", letter.salutation, ""]
    lines += [str(getattr(letter, name) or "") for name in ("opening", "fit", "motivation", "closing")]
    lines += ["", letter.signoff, "", letter.name_print, ""]
    text = "\n".join(lines)
    # collapse triple+ blank lines produced by empty blocks
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def sanitize_header(text: str) -> str:
    """Windows-console-safe header string for the .txt version."""
    return str(text or "").encode("ascii", "replace").decode("ascii")


def bundle_for(job: dict, letter, artifacts: dict) -> PortalBundle:
    """Assemble the per-portal bundle for one job from the built artifact paths."""
    portal = letter.portal or detect_portal_fallback(job)
    req = PORTAL_REQUIREMENTS.get(portal, PORTAL_REQUIREMENTS["unknown"])
    bundle = PortalBundle(
        portal=portal,
        letter_pdf=str(artifacts.get("letter_pdf") or ""),
        letter_docx=str(artifacts.get("letter_docx") or ""),
        letter_txt=str(artifacts.get("letter_txt") or ""),
        resume_pdf=str(artifacts.get("resume_pdf") or ""),
        resume_docx=str(artifacts.get("resume_docx") or ""),
        upload_slot=req["pdf_upload_slot"],
        notes=req["notes"],
        text_field=req["text_field"],
        requires_docx=req["docx"],
    )
    missing: list[str] = []
    if not bundle.letter_pdf:
        missing.append(f"letter_pdf ({req['pdf_upload_slot']})")
    if req["text_field"] and not bundle.letter_txt:
        missing.append("letter_txt (message-field fallback)")
    if req["docx"] and not bundle.letter_docx:
        missing.append("letter_docx")
    if not bundle.resume_pdf:
        missing.append("resume_pdf")
    bundle.missing = missing
    bundle.artifacts_complete = not missing
    return bundle


def detect_portal_fallback(job: dict) -> str:
    from resume_content_improve_research.generation.cover_letter import detect_portal
    return detect_portal(job)


def bundles_report(records: list[dict], results: list[dict]) -> dict:
    """Build the application_bundles.json manifest from step-5 results.

    records: components_v2 records (carry the letter content + portal);
    results: step-5 build records (carry the artifact paths).
    """
    by_url = {str(r.get("job_url") or ""): r for r in results}
    out: list[dict] = []
    for record in records:
        url = str(record.get("job_url") or "")
        result = by_url.get(url) or {}
        letter = (record.get("components") or {}).get("cover_letter") or {}
        if not letter:
            continue
        bundle = {
            "job_url": url,
            "title": record.get("title", ""),
            "company": record.get("company", ""),
            "portal": letter.get("portal", "unknown"),
            "letter_language": letter.get("language", ""),
            "status": result.get("status", record.get("status", "")),
            "artifacts": result.get("artifacts", {}),
            "upload_slot": result.get("upload_slot", ""),
            "notes": result.get("notes", ""),
            "missing": result.get("bundle_missing", []),
            "artifacts_complete": result.get("artifacts_complete", False),
        }
        out.append(bundle)
    complete = sum(1 for b in out if b["artifacts_complete"])
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(out),
        "complete": complete,
        "bundles": out,
    }


def write_bundles(report: dict, path: Path | None = None) -> Path:
    path = path or config.BUNDLES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
