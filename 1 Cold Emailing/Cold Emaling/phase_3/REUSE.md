# How to reuse this cold-email template for a new campaign

This folder is a **self-contained copy** of the working cold-email system.
It has no credentials, no real contact data, and no send history - it's a
clean template you can copy again and again for any new purpose (different
audience, different CSV, different message).

## What's in here

| File | Purpose |
|---|---|
| `send_emails.py` | The engine: reads CSV, filters/dedupes, personalises, sends, logs everything to `sent_history.csv` |
| `email_text.py` | The message template (subject + plain text + HTML). **Edit this for your campaign** |
| `.env.example` | Configuration template - copy to `.env` and fill in |
| `sample_contacts.csv` | Example recipient list (3 dummy companies) |
| `README.md` | Full documentation of the original project |
| `REUSE.md` | This guide |

## Quick start (new campaign)

1. **Copy this whole folder** to a new location and name it for your purpose,
   e.g. `~/Desktop/my_new_campaign/`. (Keep the original as a template.)

2. **Edit `email_text.py`** - change the subject and body to say what you
   actually want to send. Everything that varies per recipient (company name,
   sender name, phone, etc.) is passed in as variables - see the `make_facts()`
   function in `send_emails.py` for what's available.

3. **Create your CSV** in the same format:
   ```
   Company One,"email1@x.de, email2@x.de"
   Company Two,"info@y.de"
   ```
   One row per company. The emails are a comma-separated list **inside one
   quoted cell** (that's how the parser expects them - this is the format of
   the original `list_of_companies.csv`).

4. **Copy `.env.example` to `.env`** and fill in:
   - `SENDER_EMAIL` + `GMAIL_APP_PASSWORD` (the account that sends)
   - `CONTACT_EMAIL` (where replies go)
   - `TEST_RECIPIENT` (your own test inbox)
   - `CSV_PATH` (your new CSV)
   - `RESUME_PATH` (optional attachment - empty = no attachment)
   - `SEND_MODE` stays `test` until you're sure

5. **Test, then launch:**
   ```bash
   python3 send_emails.py --mode test --dry-run    # preview, nothing sent
   python3 send_emails.py --mode test              # 1 email to your test inbox
   python3 send_emails.py --mode all --limit 5     # first 5 real recipients
   python3 send_emails.py --mode all               # the rest
   ```

## Safety rules that carry over

- **Always test first** to your own address and check inbox + spam.
- **Keep the daily cap low for new sender accounts** (30/day, or lower).
  Raise it only once replies stay in the inbox.
- One recipient per message, delay + jitter between sends, blocked-address
  filters (datenschutz/compliance) - all built in.
- Everything you send is recorded in `sent_history.csv` (time, from, to,
  company, subject, full body, status). `state.json` makes runs resumable.

## What NOT to copy into this template

- Your real `.env` (contains the App Password)
- `state.json`, `send_log.txt`, `sent_history.csv` (previous run's data)
- Real recipient lists you don't want shared

That's it - same engine, new message, new list.
