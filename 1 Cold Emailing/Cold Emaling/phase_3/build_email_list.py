#!/usr/bin/env python3
"""
build_email_list.py — Phase 2 → Phase 3 pipeline link (Phase A of
PERSONALIZATION_PLAN.md).

Turns the Phase 2 contact list (one row per contact) plus the Phase 1
company research into the Phase 3 sender CSV (`contacts_to_send.csv`,
one row per company-email pair) carrying per-row personalization fields:

    company_name, email, contact_name,
    technical_focus, why_target, relevant_roles,
    current_hiring_evidence, website

Rules (mirror the sender-side rules so the file is clean up front):
  - blocked keywords (datenschutz@, abuse@, ...) are dropped;
  - invalid / empty emails are dropped;
  - (company, email) pairs are deduplicated;
  - `technical_focus` is normalized to "; "-separated terms;
  - company research that is missing falls back to empty cells — the
    template then uses its written fallback sentences.

Usage:
  python3 build_email_list.py                # write contacts_to_send.csv
  python3 build_email_list.py --dry-run      # per-company counts only, no write
  python3 build_email_list.py --phase2 <csv> --phase1 <csv> --output <csv>

Rerunnable: the file is regenerated from the Phase 1/2 CSVs every run.
"""

import argparse
import csv
import os
import re
import sys

# Paths relative to this file's directory (phase_3/).
DEFAULT_PHASE2 = os.path.join("..", "phase_2", "data", "contact_discovery_results.csv")
DEFAULT_PHASE1 = os.path.join("..", "phase_1", "data", "discovered_companies.csv")
DEFAULT_OUTPUT = "contacts_to_send.csv"

OUTPUT_COLUMNS = [
    "company_name", "email", "contact_name",
    "technical_focus", "why_target", "relevant_roles",
    "current_hiring_evidence", "website",
]

# Must match send_emails.BLOCKED_KEYWORDS — keep in sync.
# Expanded comprehensive blacklist: unmonitored / automated / legal / security / transactional
BLOCKED_KEYWORDS = (
    "datenschutz", "impressum", "abuse", "arbeitssicherheit",
    "gleichstellung", "strahlenschutz", "hinweise",
    "noreply", "no-reply", "donotreply", "bounce", "security",
    "compliance", "dpo", "privacy", "legal", "investor", "ir",
    "billing", "invoice", "accounting", "payment", "sales", "press",
    "media", "marketing", "newsletter", "alert", "notification",
    "kundenservice", "support", "help", "admin", "webmaster", "postmaster",
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MX_CACHE: dict[str, bool] = {}


def has_valid_mx(domain: str, timeout: float = 3.0) -> bool:
    """True if domain has valid MX records (or fallback A record), cached."""
    domain = (domain or "").strip().lower()
    if not domain:
        return False
    if domain in _MX_CACHE:
        return _MX_CACHE[domain]
    try:
        import dns.resolver
        resolver = dns.resolver.Resolver()
        resolver.timeout = timeout
        resolver.lifetime = timeout
        answers = resolver.resolve(domain, "MX")
        valid = len(answers) > 0
    except Exception:
        try:
            import socket
            socket.gethostbyname(domain)
            valid = True
        except Exception:
            valid = False
    _MX_CACHE[domain] = valid
    return valid


def read_phase1(path):
    """company_name (lowercased) -> research row dict."""
    companies = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            name = (raw.get("company_name") or "").strip()
            if not name:
                continue
            companies.setdefault(name.lower(), {
                "technical_focus": (raw.get("technical_focus") or "").strip(),
                "why_target": (raw.get("why_target") or "").strip(),
                "relevant_roles": (raw.get("relevant_roles") or "").strip(),
                "current_hiring_evidence": (raw.get("current_hiring_evidence") or "").strip(),
                "website": (raw.get("website") or "").strip(),
            })
    return companies


def read_phase2(path):
    """List of contact dicts from contact_discovery_results.csv."""
    contacts = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            company = (raw.get("company_name") or "").strip()
            email = (raw.get("contact_email") or "").strip()
            if not company or not email:
                continue
            contacts.append({
                "company_name": company,
                "email": email,
                "contact_name": (raw.get("contact_name") or "").strip(),
                "website": (raw.get("website") or "").strip(),
            })
    return contacts


def normalize_focus(raw):
    """'Conversational AI, Generative AI; NLP' -> 'Conversational AI; Generative AI; NLP'."""
    terms = [t.strip() for t in re.split(r"[;,]", raw or "") if t.strip()]
    return "; ".join(terms)


def build_rows(contacts, phase1, check_mx: bool = True):
    """Return output rows (dicts), filtered, MX-checked, and deduplicated."""
    seen = set()
    rows = []
    dropped_blocked = 0
    dropped_mx = 0
    for contact in contacts:
        email = contact["email"].lower()
        if not EMAIL_RE.match(email):
            continue
        if any(k in email for k in BLOCKED_KEYWORDS):
            dropped_blocked += 1
            continue
        domain = email.split("@", 1)[1].strip()
        if check_mx and not has_valid_mx(domain):
            dropped_mx += 1
            continue
        key = (contact["company_name"].lower(), email)
        if key in seen:
            continue
        seen.add(key)

        research = phase1.get(contact["company_name"].lower(), {})
        rows.append({
            "company_name": contact["company_name"],
            "email": email,
            "contact_name": contact["contact_name"],
            "technical_focus": normalize_focus(research.get("technical_focus")),
            "why_target": research.get("why_target", ""),
            "relevant_roles": research.get("relevant_roles", ""),
            "current_hiring_evidence": research.get("current_hiring_evidence", ""),
            "website": research.get("website") or contact["website"],
        })
    if dropped_blocked or dropped_mx:
        print(f"Filter stats: dropped {dropped_blocked} blocked inboxes, {dropped_mx} invalid MX domains.")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase2", default=DEFAULT_PHASE2, help="Phase 2 contact CSV")
    ap.add_argument("--phase1", default=DEFAULT_PHASE1, help="Phase 1 company research CSV")
    ap.add_argument("--output", default=DEFAULT_OUTPUT, help="output CSV path")
    ap.add_argument("--skip-mx", action="store_true", help="skip DNS MX record validation")
    ap.add_argument("--dry-run", action="store_true", help="print per-company counts, write nothing")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    phase2_path = args.phase2 if os.path.isabs(args.phase2) else os.path.join(here, args.phase2)
    phase1_path = args.phase1 if os.path.isabs(args.phase1) else os.path.join(here, args.phase1)
    output_path = args.output if os.path.isabs(args.output) else os.path.join(here, args.output)

    for label, path in (("Phase 2 contacts", phase2_path), ("Phase 1 research", phase1_path)):
        if not os.path.exists(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    phase1 = read_phase1(phase1_path)
    contacts = read_phase2(phase2_path)
    rows = build_rows(contacts, phase1, check_mx=not args.skip_mx)

    by_company = {}
    for row in rows:
        by_company.setdefault(row["company_name"], []).append(row)

    print(f"Contacts read:      {len(contacts)}")
    print(f"Kept (dedup, clean): {len(rows)}")
    print(f"Companies:          {len(by_company)}")
    print()
    for company in sorted(by_company):
        print(f"  {company:24s} {len(by_company[company])} recipient(s)")

    if args.dry_run:
        print("\nDry run - nothing written.")
        return

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {len(rows)} row(s) -> {output_path}")


if __name__ == "__main__":
    main()
