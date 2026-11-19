# Cold Outreach Email Sender — Phase 3

Sends personalised cold-outreach emails (English, for **Werkstudent /
internship / SDE / AI / software / data** opportunities) to the contacts
discovered in Phase 2, using Gmail SMTP with an App Password.

```
Phase 1 (Entity Discovery) → Phase 2 (Contact Discovery) → Phase 3 (Communication)
```

**Status:** pipeline link wired. `build_email_list.py` turns the Phase 2
contacts + Phase 1 research into `contacts_to_send.csv`, the sender reads
that file, and `audit_personalization.py` verifies the personalization
guarantees before anything is sent.

## How it works

1. **Build the recipient list** — `python3 build_email_list.py`
   joins `phase_2/data/contact_discovery_results.csv` (one row per contact)
   with the Phase 1 research (`technical_focus`, `why_target`,
   `relevant_roles`, `current_hiring_evidence`, `website`) and writes
   `contacts_to_send.csv` — one row per (company, email), deduplicated and
   cleaned of blocked compliance inboxes (`datenschutz@`, `abuse@`, ...).
   Rerunnable: it regenerates the whole file from the CSVs.2. **Audit** — `python3 audit_personalization.py` renders every planned email
   and asserts: no unresolved placeholders / TODOs, company name present,
   person-name contacts greeted by first name, and ≥90% of emails contain
   the company's focus terms.
2b. **(Optional) Gemini hooks** — `python3 generate_hooks.py` makes one
   Gemini call per company and writes a personalised 2-sentence opening to
   `data/email_hooks.csv` (Layer 7), picked up automatically via
   `EMAIL_HOOKS_CSV`. It uses **every** Gemini key it can find (env
   `GEMINI_API_KEYS` / `GEMINI_API_KEY` + `GEMINI_API_KEY_2`, then the
   enabled Gemini keys in `streamlit_app/settings.json`), rotating on
   failure; `NO_HOOK` results fall back to the Layer 2 hook.
3. **Send** — `send_emails.py` reads the CSV, filters/sorts/caps addresses
   (application inboxes first, then local keywords, then generic `info@`,
   then named individuals; `MAX_PER_COMPANY` cap), and sends **one recipient
   per message** with delay + jitter, a daily cap, and full state tracking so
   runs are resumable and nothing is ever sent twice.
4. **Personalization** — every email is unique per recipient
   (see `PERSONALIZATION_PLAN.md`): first-name greeting, a company hook built
   from its researched focus + why + hiring evidence, skills matching
   (`SKILLS` ∩ `technical_focus`), role matching (`SENDER_ROLES` ∩
   `relevant_roles`), a short subject, and a signature with at most one
   profile link. Every field has a written fallback — a missing value makes
   the email slightly less personal, never broken.
5. **Tracking** — every send is logged to `sent_history.csv` (time, from,
   reply-to, to, company, subject, full body, status).

## Test first (do NOT skip)

```bash
python3 build_email_list.py                 # build contacts_to_send.csv
python3 audit_personalization.py            # verify personalization (optional but recommended)
python3 send_emails.py --mode test --dry-run   # preview only, nothing sent
python3 send_emails.py --mode test             # ONE email to TEST_RECIPIENT
```

Check your test inbox: did it arrive? Inbox (not spam)? Subject correct?
Body looks right (personalized greeting + hook)? Attachment (if any) opens?

If it lands in spam, slow down: lower `MAX_PER_DAY`, warm up the sender
address, and re-check with [mail-tester.com](https://www.mail-tester.com).

## Then send for real

```bash
python3 send_emails.py --mode all --limit 5    # first small batch
python3 send_emails.py --mode all              # full run (respects daily cap)
```

The script remembers who was emailed (`state.json`) and never sends
duplicates; re-run each day until the list is done.

## Setup

1. Create a Gmail **App Password** for the sender account
   (`ravalmeetkumar0@gmail.com`): Google Account → Security → 2-Step
   Verification → App passwords.
2. `cp .env.example .env` and fill in `GMAIL_APP_PASSWORD` + your facts
   (degree, university, skills, availability, phone, German level).
3. No packages to install — pure Python standard library (`smtplib`).

## Configuration

| Key | Meaning |
|---|---|
| `SENDER_EMAIL` / `GMAIL_APP_PASSWORD` | The Gmail account that sends (needs the App Password) |
| `SENDER_NAME` | Name in the From header + signature |
| `CONTACT_EMAIL` | Where replies go (Reply-To + signature) |
| `TEST_RECIPIENT` | Your own test inbox (test mode only) |
| `SEND_MODE` | `test` (one email) or `all` (whole list) |
| `CSV_PATH` | Recipient list (default `contacts_to_send.csv`, from `build_email_list.py`) |
| `RESUME_PATH` | Optional attachment; empty = none |
| `DEGREE` / `UNIVERSITY` / `SKILLS` / `AVAILABILITY` / `GERMAN_LEVEL` / `PHONE` | Facts filled into the message |
| `SENDER_ROLES` | Roles you're open to, matched vs company `relevant_roles` (Layer 4) |
| `SENDER_LOCATION` | "Based in ..." line (default Berlin) |
| `EDUCATION_EXTRA` | Optional one-liner about your education |
| `LINKEDIN` / `GITHUB` / `PORTFOLIO` | Optional signature links (at most one used) |
| `EMAIL_HOOKS_CSV` | CSV of pre-written per-company hooks (`company_name,hook`); default `data/email_hooks.csv`, from `generate_hooks.py` |
| `GEMINI_API_KEY` / `GEMINI_API_KEY_2` | Optional Gemini keys for hook generation (else `GEMINI_API_KEYS`, else `streamlit_app/settings.json`) |
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODELS` | Primary + fallback Gemini models for hooks |
| `DELAY_SECONDS` / `JITTER_SECONDS` | Delay between sends + random jitter |
| `MAX_PER_COMPANY` / `MAX_PER_DAY` | Safety caps |
| `LOCAL_KEYWORDS` | Address parts to prioritise |
| `STATE_FILE` / `LOG_FILE` / `HISTORY_FILE` | Progress tracking |

## Files

| File | Purpose |
|---|---|
| `build_email_list.py` | Phase 2 contacts + Phase 1 research → `contacts_to_send.csv` |
| `generate_hooks.py` | Phase E: Gemini per-company openings → `data/email_hooks.csv` |
| `hooks_client.py` | Multi-key rotating Gemini client (+ fake for dry runs) |
| `send_emails.py` | The engine (read CSV → filter → personalise → send → log) |
| `email_text.py` | The personalised subject + body templates (layers 1–7) |
| `audit_personalization.py` | Verifies personalization guarantees before sending |
| `.env.example` / `.env` | Configuration (`.env` is git-ignored — holds the password) |
| `sample_contacts.csv` | 3 dummy companies in the legacy 2-column format (still accepted) |
| `state.json` / `send_log.txt` / `sent_history.csv` | Auto-created run tracking |

## Commands cheat-sheet

```bash
python3 build_email_list.py                       # build contacts_to_send.csv
python3 build_email_list.py --dry-run             # per-company counts, no write
python3 audit_personalization.py                  # personalization checks
python3 generate_hooks.py --probe                 # verify Gemini keys + models
python3 generate_hooks.py                         # Layer 7: per-company hooks
python3 generate_hooks.py --dry-run               # fake client, write nothing
cp .env.example .env                              # once
python3 send_emails.py --mode test --dry-run      # preview test
python3 send_emails.py --mode test                # send 1 test email
python3 send_emails.py --to you@other.com         # test to any address
python3 send_emails.py --mode all --limit 5       # first small batch
python3 send_emails.py --mode all                 # full run (respects daily cap)
python3 send_emails.py --mode all --dry-run       # preview full plan
```
