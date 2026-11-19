#!/usr/bin/env python3
"""
Phase 3 — cold-outreach email sender.

Sends personalised English outreach emails (Werkstudent / internship /
SDE / AI / software / data opportunities) to the contacts discovered in
Phase 2, from a Gmail account using an App Password.

Input is `contacts_to_send.csv`, generated from the pipeline by
`build_email_list.py` (one row per company-email pair, with per-row
personalization columns: contact_name, technical_focus, why_target,
relevant_roles, current_hiring_evidence, website). The legacy 2-column
format (`Company,"email1, email2"`) is also accepted.

Two modes:
  test  -> send exactly ONE email to TEST_RECIPIENT (your own extra address)
           so you can check the inbox and the spam folder first.
  all   -> send to every address in the CSV (filtered, deduplicated,
           rate-limited).

Usage:
  python3 build_email_list.py                     # build contacts_to_send.csv
  python3 send_emails.py --mode test --dry-run    # preview without sending
  python3 send_emails.py --mode test              # send the test email
  python3 send_emails.py --mode all --limit 5     # first real batch (small)
  python3 send_emails.py --mode all               # full run (uses daily cap)

Configuration lives in `.env` (see `.env.example`). Never commit `.env`.
"""

import argparse
import csv
import json
import os
import random
import re
import socket
import smtplib
import sys
import time
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
from smtplib import SMTPDataError, SMTPRecipientsRefused, SMTPServerDisconnected

import email_text

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --------------------------------------------------------------------------
# Defaults (overridden by .env)
# --------------------------------------------------------------------------
DEFAULTS = {
    "SENDER_EMAIL": "ravalmeetkumar0@gmail.com",
    "SENDER_NAME": "Meetkumar Riteshkumar Raval",
    "GMAIL_APP_PASSWORD": "",
    "CONTACT_EMAIL": "ravalmeett.de@gmail.com",
    "TEST_RECIPIENT": "ravalmeett@gmail.com",
    "SEND_MODE": "test",
    "CSV_PATH": "contacts_to_send.csv",
    "RESUME_PATH": "",
    "DEGREE": "M.Sc. Artificial Intelligence (in progress)",
    "UNIVERSITY": "BTU Cottbus-Senftenberg",
    "SKILLS": "Python: 3y, PyTorch: 1y, SQL, FastAPI, Docker",
    "AVAILABILITY": "immediately",
    "GERMAN_LEVEL": "B1",
    "PHONE": "+49 155 67018163",
    # --- personalization (PERSONALIZATION_PLAN.md layers 3/4/6) ---
    "SENDER_ROLES": "AI Engineering Working Student, Backend Working Student, Data Intern",
    "SENDER_LOCATION": "Berlin",
    "EDUCATION_EXTRA": "",
    "LINKEDIN": "",
    "GITHUB": "",
    "PORTFOLIO": "",
    # Auto-picked-up when data/email_hooks.csv exists (generate_hooks.py).
    "EMAIL_HOOKS_CSV": "data/email_hooks.csv",
    # Send plain text only (no HTML alternative): personal-looking cold
    # outreach is less likely to be tabbed as Promotions by Gmail.
    "PLAIN_TEXT_ONLY": "false",
    # --- sending speed / safety ---
    "DELAY_SECONDS": "45",
    "JITTER_SECONDS": "15",
    "MAX_PER_COMPANY": "6",
    "MAX_PER_DOMAIN": "2",
    "MAX_PER_DAY": "120",
    "LOCAL_KEYWORDS": "",
    "CHECK_BUSINESS_HOURS": "false",
    # --- progress tracking ---
    "STATE_FILE": "state.json",
    "LOG_FILE": "send_log.txt",
    "HISTORY_FILE": "sent_history.csv",
}

# Addresses that must NOT receive job applications: compliance / legal /
# officers' inboxes. Mailing these can trigger complaints and hurt delivery.
# Keep in sync with build_email_list.BLOCKED_KEYWORDS.
BLOCKED_KEYWORDS = (
    "datenschutz", "impressum", "abuse", "arbeitssicherheit",
    "gleichstellung", "strahlenschutz", "hinweise",
    "noreply", "no-reply", "donotreply", "bounce", "security",
    "compliance", "dpo", "privacy", "legal", "investor", "ir",
    "billing", "invoice", "accounting", "payment", "sales", "press",
    "media", "marketing", "newsletter", "alert", "notification",
    "kundenservice", "support", "help", "admin", "webmaster", "postmaster",
)

APP_KEYWORDS = (
    # German application inboxes
    "bewerbung", "bewerben", "job", "karriere", "arbeit", "willkommen",
    # English application inboxes (English-first startups from Phase 2)
    "jobs", "careers", "hiring", "talent", "recruiting", "hr", "people",
    "dev", "engineering", "tech", "join",
)
GENERAL_KEYWORDS = (
    "info", "kontakt", "mail", "office", "empfang", "zentrale",
    "avjs", "buero", "gf", "hello",
)


def is_in_business_hours() -> tuple[bool, str]:
    """Check if current time is within optimal German business hours:
    Monday-Thursday: 08:30-11:30, 13:30-16:30 CET
    Friday: 08:30-12:00 CET
    Avoid sending on Friday afternoons, weekends, or late nights where
    emails get buried under backlogs.
    """
    now = datetime.now()
    weekday = now.weekday()  # 0 = Monday, 4 = Friday, 5 = Saturday, 6 = Sunday
    hour_minute = now.hour + now.minute / 60.0

    if weekday in (5, 6):
        return False, f"Weekend ({now:%A})"
    if weekday == 4:
        if hour_minute > 12.0:
            return False, f"Friday afternoon ({now:%H:%M})"
        if hour_minute < 8.5:
            return False, f"Before Friday morning window ({now:%H:%M})"
        return True, f"Optimal Friday morning window ({now:%H:%M})"
    # Monday - Thursday: optimal morning and afternoon windows
    if 8.5 <= hour_minute <= 11.5 or 13.5 <= hour_minute <= 16.5:
        return True, f"Optimal window ({now:%A %H:%M})"
    if hour_minute < 8.5:
        return False, f"Before morning business hours ({now:%H:%M})"
    if 11.5 < hour_minute < 13.5:
        return False, f"Lunch break lull ({now:%H:%M})"
    return False, f"Outside optimal business hours ({now:%H:%M})"


def log(msg, log_file=None):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_env(path=".env"):
    """Tiny .env loader (KEY=VALUE, # comments, optional quotes)."""
    cfg = dict(DEFAULTS)
    if not os.path.exists(path):
        alt = os.path.join(os.path.dirname(__file__), path)
        if os.path.exists(alt):
            path = alt
        else:
            return cfg

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            cfg[key.strip()] = value

    env_dir = os.path.dirname(os.path.abspath(path))
    for path_key in ("CSV_PATH", "EMAIL_HOOKS_CSV", "STATE_FILE", "LOG_FILE", "HISTORY_FILE", "RESUME_PATH"):
        val = cfg.get(path_key, "")
        if val and not os.path.isabs(val):
            if not os.path.exists(val):
                candidate = os.path.normpath(os.path.join(env_dir, val))
                if os.path.exists(candidate) or path_key in ("STATE_FILE", "LOG_FILE", "HISTORY_FILE"):
                    cfg[path_key] = candidate
            else:
                cfg[path_key] = os.path.abspath(val)

    return cfg


def load_state(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("sent", {}), data.get("daily_counts", {})
        except (json.JSONDecodeError, OSError):
            log(f"WARNING: could not read {path}, starting fresh")
    return {}, {}


def save_state(path, sent, daily_counts):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"sent": sent, "daily_counts": daily_counts}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def read_recipients(csv_path):
    """Return a list of row dicts — one per (company, email).

    New schema (header: company_name,email,contact_name,technical_focus,...)
    is the output of build_email_list.py; the legacy 2-column format
    (Company,"email1, email2", no header) is also accepted so old files
    keep working.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"Recipient CSV not found: {csv_path}. Run `python3 build_email_list.py` "
            "to generate it (or point CSV_PATH at an existing file in .env)."
        )
    rows = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        first_line = f.readline()
        f.seek(0)
        first_cell = first_line.split(",", 1)[0].strip().lower()

        if first_cell in ("company_name", "company name", "company"):
            for raw in csv.DictReader(f):
                email = (raw.get("email") or raw.get("contact_email") or "").strip()
                if not email:
                    continue
                row = {k.strip(): (v or "").strip() for k, v in raw.items()}
                row["company_name"] = row.get("company_name") or row.get("company") or ""
                row["email"] = email
                if row["company_name"]:
                    rows.append(row)
        else:
            # Legacy: one row per company, emails comma-separated in one cell.
            f.seek(0)
            for line in f:
                parts = next(csv.reader([line]))
                if len(parts) != 2:
                    continue
                name = parts[0].strip()
                for e in parts[1].split(","):
                    e = e.strip()
                    if name and e:
                        rows.append({"company_name": name, "email": e})
    return rows


def is_valid_email(addr):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", addr))


def is_blocked(addr):
    low = addr.lower()
    return any(k in low for k in BLOCKED_KEYWORDS)


def is_personal_contact(row_or_addr) -> bool:
    """True if row represents a named individual decision-maker rather than a generic or role inbox."""
    if isinstance(row_or_addr, dict):
        contact_name = (row_or_addr.get("contact_name") or "").strip()
        if contact_name:
            clean_name = re.sub(r"\(.*?\)", "", contact_name).strip()
            if clean_name and not email_text._is_role_inbox(clean_name):
                return True
        email_addr = (row_or_addr.get("email") or "").lower()
    else:
        email_addr = str(row_or_addr).lower()

    local_part = email_addr.split("@")[0] if "@" in email_addr else email_addr
    if any(k in local_part for k in APP_KEYWORDS) or any(k in local_part for k in GENERAL_KEYWORDS) or any(k in local_part for k in BLOCKED_KEYWORDS):
        return False
    # If it's a direct firstname.lastname@ or similar personal pattern
    if "." in local_part and not any(k in local_part for k in ("info", "kontakt", "career", "job", "dev", "tech", "team")):
        return True
    return False


def priority(row_or_addr, local_keywords=()):
    """Lower number = send first.
    0: direct personal contacts / decision-makers (CTO, VP Eng, Founder, Tech Lead, etc.)
    1: application / engineering-specific inboxes (APP_KEYWORDS: jobs@, bewerbung@, dev@, tech@, ...)
    2: local branches (from LOCAL_KEYWORDS)
    3: generic inboxes (GENERAL_KEYWORDS: info@, kontakt@, hello@, etc.)
    4: anything else
    """
    if is_personal_contact(row_or_addr):
        return 0

    if isinstance(row_or_addr, dict):
        low = (row_or_addr.get("email") or "").lower()
    else:
        low = str(row_or_addr).lower()
    local_part = low.split("@")[0] if "@" in low else low

    if any(k in local_part for k in APP_KEYWORDS):
        return 1
    if any(k in local_part for k in local_keywords):
        return 2
    if any(k in local_part for k in GENERAL_KEYWORDS):
        return 3
    return 4


def build_recipient_plan(cfg, rows, mode, sent=None):
    """
    Return the ordered list of recipient row dicts to send.

    test mode: one row to TEST_RECIPIENT (personalised with the first
               matching company name).
    all mode:  each company -> filtered, deduplicated, human-prioritized,
               capped rows with domain-level rate throttling.
    """
    local_keywords = tuple(
        k.strip().lower() for k in cfg.get("LOCAL_KEYWORDS", "").split(",") if k.strip()
    )
    plan = []
    if mode == "test":
        base = rows[0] if rows else {}
        test_row = dict(base)
        test_row["company_name"] = base.get("company_name", "Testfirma")
        test_row["email"] = cfg["TEST_RECIPIENT"]
        plan.append(test_row)
        return plan

    max_per_company = int(cfg.get("MAX_PER_COMPANY", 6))
    max_per_domain = int(cfg.get("MAX_PER_DOMAIN", 2))

    # Pre-populate domain counts from emails already sent today
    domain_counts = {}
    if sent is None and cfg.get("STATE_FILE"):
        sent, _ = load_state(cfg["STATE_FILE"])
    if sent:
        today_prefix = str(date.today())
        for key, ts in sent.items():
            if str(ts).startswith(today_prefix) and "@" in key:
                email_part = key.split("::")[-1].strip()
                if "@" in email_part:
                    d = email_part.split("@")[-1].lower()
                    domain_counts[d] = domain_counts.get(d, 0) + 1

    by_company = {}
    for row in rows:
        by_company.setdefault(row["company_name"], []).append(row)

    for company, group in by_company.items():
        seen = set()
        kept = []
        for row in group:
            e = row["email"].lower()
            if not is_valid_email(e) or is_blocked(e) or e in seen:
                continue
            seen.add(e)
            kept.append(row)

        # Human decision-maker prioritization: if a direct personal contact
        # exists (Rank 0), automatically suppress low-priority generic inboxes (Rank 3)
        has_personal = any(priority(r, local_keywords) == 0 for r in kept)
        if has_personal:
            kept = [r for r in kept if priority(r, local_keywords) < 3]

        kept.sort(key=lambda r: priority(r, local_keywords))

        company_added = 0
        for row in kept:
            if company_added >= max_per_company:
                break
            domain = row["email"].split("@")[-1].lower()
            if domain_counts.get(domain, 0) >= max_per_domain:
                continue
            plan.append(row)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            company_added += 1

    return plan


def load_hooks(cfg):
    """Optional per-company pre-written hooks (Layer 7); empty dict if none.

    EMAIL_HOOKS_CSV points at a CSV with columns: company_name, hook.
    """
    path = cfg.get("EMAIL_HOOKS_CSV", "")
    hooks = {}
    if not path or not os.path.exists(path):
        return hooks
    with open(path, encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            company = (raw.get("company_name") or raw.get("company") or "").strip()
            hook = (raw.get("hook") or "").strip()
            # "NO_HOOK" (generator's fallback marker) and empty cells mean
            # "use the Layer 2 hook" — never inject the marker itself.
            if company and hook and hook.upper() != "NO_HOOK":
                hooks[company.lower()] = hook
    return hooks


def make_facts(cfg, row):
    """Single source of truth for the facts used in the email body.

    Sender facts come from `.env`; per-recipient facts come from the row
    (contact_name, technical_focus, why_target, ...). Missing per-row values
    fall back to written fallback sentences inside email_text.py.
    """
    hooks = cfg.get("_HOOKS", {})
    company = row.get("company_name", "")
    facts = {
        "company": company,
        "contact_name": row.get("contact_name", ""),
        "technical_focus": row.get("technical_focus", ""),
        "why_target": row.get("why_target", ""),
        "relevant_roles": row.get("relevant_roles", ""),
        "current_hiring_evidence": row.get("current_hiring_evidence", ""),
        "website": row.get("website", ""),
        "sender_name": cfg["SENDER_NAME"],
        "sender_email": cfg["SENDER_EMAIL"],
        "contact_email": cfg["CONTACT_EMAIL"] or cfg["SENDER_EMAIL"],
        "phone": cfg["PHONE"],
        "degree": cfg.get("DEGREE", ""),
        "university": cfg.get("UNIVERSITY", ""),
        "skills": cfg.get("SKILLS", ""),
        "availability": cfg.get("AVAILABILITY", ""),
        "german_level": cfg["GERMAN_LEVEL"],
        "sender_location": cfg.get("SENDER_LOCATION", "Berlin"),
        "sender_roles": cfg.get("SENDER_ROLES", ""),
        "education_extra": cfg.get("EDUCATION_EXTRA", ""),
        "linkedin": cfg.get("LINKEDIN", ""),
        "github": cfg.get("GITHUB", ""),
        "portfolio": cfg.get("PORTFOLIO", ""),
        "has_resume": bool(
            cfg.get("RESUME_PATH") and os.path.exists(cfg.get("RESUME_PATH", ""))
        ),
    }
    hook = hooks.get(company.lower())
    # Defense in depth: load_hooks already filters this marker; never let it
    # through even if a caller builds _HOOKS by hand.
    if hook and hook.upper() != "NO_HOOK":
        facts["company_hook"] = hook
    return facts


def build_message(cfg, facts, recipient):
    msg = EmailMessage()
    msg["From"] = formataddr((facts["sender_name"], facts["sender_email"]))
    msg["To"] = recipient
    msg["Subject"] = email_text.subject(facts)
    msg["Reply-To"] = facts["contact_email"]

    msg.set_content(email_text.plain_body(facts))
    if cfg.get("PLAIN_TEXT_ONLY", "false").lower() not in ("1", "true", "yes"):
        msg.add_alternative(email_text.html_body(facts), subtype="html")

    resume_path = cfg.get("RESUME_PATH", "")
    if resume_path:
        if not os.path.exists(resume_path):
            log(f"WARNING: resume not found at {resume_path} — sending without attachment.")
        else:
            with open(resume_path, "rb") as f:
                pdf = f.read()
            msg.add_attachment(
                pdf,
                maintype="application",
                subtype="pdf",
                filename=os.path.basename(resume_path),
            )
    return msg


HISTORY_COLUMNS = [
    "timestamp", "from_name", "from_email", "reply_to", "to",
    "company", "subject", "status", "error", "body",
]


def record_send(cfg, facts, recipient, status, error=""):
    """Append one row to the sent-history CSV (what/who/when/from)."""
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "from_name": facts["sender_name"],
        "from_email": facts["sender_email"],
        "reply_to": facts["contact_email"],
        "to": recipient,
        "company": facts["company"],
        "subject": email_text.subject(facts),
        "status": status,
        "error": error,
        "body": email_text.plain_body(facts),
    }
    path = cfg["HISTORY_FILE"]
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def connect_smtp(cfg):
    server = smtplib.SMTP("smtp.gmail.com", 587, timeout=60)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(cfg["SENDER_EMAIL"], cfg["GMAIL_APP_PASSWORD"])
    return server


def send_one(server, cfg, facts, recipient, sent, log_file):
    msg = build_message(cfg, facts, recipient)
    # Set a per-send socket timeout so a silent Gmail drop can't hang forever.
    server.sock.settimeout(120)
    server.send_message(msg)
    sent[f"{facts['company']}::{recipient}"] = datetime.now().isoformat(timespec="seconds")
    record_send(cfg, facts, recipient, "sent")
    log(f"SENT -> {recipient}  (company: {facts['company']})", log_file)


def main():
    ap = argparse.ArgumentParser(description="Send job application emails from the CSV.")
    ap.add_argument("--mode", choices=["test", "all"], help="override SEND_MODE from .env")
    ap.add_argument("--dry-run", action="store_true", help="plan and preview only, do not connect or send")
    ap.add_argument("--limit", type=int, default=None, help="max emails to send in this run")
    ap.add_argument("--company", help="only process companies whose name contains this (substring)")
    ap.add_argument("--to", help="send the test email to this address instead of TEST_RECIPIENT (implies test mode)")
    ap.add_argument("--ignore-schedule", action="store_true", help="bypass German business hours check")
    args = ap.parse_args()

    cfg = load_env()
    if args.to:
        cfg["TEST_RECIPIENT"] = args.to.strip()
    mode = args.mode or ("test" if args.to else cfg["SEND_MODE"])
    if mode not in ("test", "all"):
        log("SEND_MODE must be 'test' or 'all'.")
        sys.exit(1)

    if not cfg["GMAIL_APP_PASSWORD"] and not args.dry_run:
        log("ERROR: GMAIL_APP_PASSWORD is not set in .env.")
        log("Create a Gmail App Password (Google Account -> Security -> 2-Step")
        log("Verification -> App passwords) and put it in .env, then retry.")
        sys.exit(1)

    if not cfg["PHONE"]:
        log("WARNING: PHONE is empty in .env — the email will be sent without a phone number.")

    cfg["_HOOKS"] = load_hooks(cfg)

    rows = read_recipients(cfg["CSV_PATH"])
    if args.company:
        rows = [r for r in rows if args.company.lower() in r["company_name"].lower()]
    if not rows:
        log("No companies matched.")
        sys.exit(1)

    sent, daily_counts = load_state(cfg["STATE_FILE"])
    today = str(date.today())
    already_today = daily_counts.get(today, 0)
    max_per_day = int(cfg["MAX_PER_DAY"])

    plan = build_recipient_plan(cfg, rows, mode, sent=sent)

    # Deduplicate BEFORE applying --limit so that re-running with a limit
    # continues with the next unsent targets instead of re-processing sent ones.
    # (Test mode sends to TEST_RECIPIENT and is never suppressed by prior test runs).
    if mode != "test":
        plan = [
            row for row in plan
            if f"{row['company_name']}::{row['email']}" not in sent
        ]

    if already_today >= max_per_day:
        log(f"Daily cap reached ({already_today}/{max_per_day}). Try again tomorrow.")
        sys.exit(0)

    room_today = max_per_day - already_today
    plan = plan[:room_today]

    if args.limit is not None:
        plan = plan[: args.limit]

    if not plan:
        log("Nothing to send - all targets already emailed.")
        return

    # Check business hours in live mode
    if mode == "all" and not args.dry_run and not args.ignore_schedule:
        check_hours = cfg.get("CHECK_BUSINESS_HOURS", "false").lower() in ("true", "1", "yes")
        if check_hours:
            in_window, reason = is_in_business_hours()
            if not in_window:
                log(f"Schedule check: Outside German business hours ({reason}). Email dispatch paused.")
                log("To send anyway, pass --ignore-schedule or set CHECK_BUSINESS_HOURS=false in .env.")
                return

    log(f"Mode: {mode} | recipient rows in CSV: {len(read_recipients(cfg['CSV_PATH']))} | "
        f"planned emails: {len(plan)} | already sent today: {already_today}")

    if args.dry_run:
        for i, row in enumerate(plan):
            facts = make_facts(cfg, row)
            print(f"\n--- preview {i + 1}/{len(plan)} ---")
            print(f"To:      {row['email']}")
            print(f"Contact: {facts['contact_name'] or '-'}")
            print(f"Subject: {email_text.subject(facts)}")
            print("Body (plain):")
            print(email_text.plain_body(facts))
        log("Dry run finished - nothing was sent.")
        return

    log(f"Connecting to smtp.gmail.com as {cfg['SENDER_EMAIL']} ...")
    server = connect_smtp(cfg)
    delay = float(cfg["DELAY_SECONDS"])
    jitter = float(cfg["JITTER_SECONDS"])
    ok_count = 0
    try:
        for i, row in enumerate(plan):
            if i > 0:
                time.sleep(delay + random.uniform(0, jitter))
            facts = make_facts(cfg, row)
            try:
                send_one(server, cfg, facts, row["email"], sent, cfg["LOG_FILE"])
                ok_count += 1
                daily_counts[today] = already_today + ok_count
                save_state(cfg["STATE_FILE"], sent, daily_counts)
            except (SMTPServerDisconnected, socket.timeout, socket.error, OSError) as e:
                # Gmail dropped the connection — reconnect and retry this email.
                log(f"SMTP error ({type(e).__name__}) — reconnecting...", cfg["LOG_FILE"])
                time.sleep(5)
                try:
                    server.quit()
                except Exception:
                    pass
                try:
                    server = connect_smtp(cfg)
                except Exception as re:
                    log(f"Reconnect FAILED: {re}", cfg["LOG_FILE"])
                    time.sleep(30)
                    server = connect_smtp(cfg)
                try:
                    send_one(server, cfg, facts, row["email"], sent, cfg["LOG_FILE"])
                    ok_count += 1
                    daily_counts[today] = already_today + ok_count
                    save_state(cfg["STATE_FILE"], sent, daily_counts)
                except (SMTPRecipientsRefused, SMTPDataError, SMTPServerDisconnected, socket.timeout, socket.error, OSError) as e2:
                    record_send(cfg, facts, row["email"], "failed", str(e2))
                    log(f"FAILED after reconnect -> {row['email']}: {e2}", cfg["LOG_FILE"])
            except (SMTPRecipientsRefused, SMTPDataError) as e:
                # Skip this one recipient and keep going - don't lose the run.
                record_send(cfg, facts, row["email"], "failed", str(e))
                log(f"FAILED -> {row['email']}: {e}", cfg["LOG_FILE"])
    finally:
        try:
            server.quit()
        except Exception:
            pass

    log(f"Done. Sent {ok_count}/{len(plan)} email(s) this run. Total sent today: {daily_counts.get(today, 0)}")


if __name__ == "__main__":
    main()
