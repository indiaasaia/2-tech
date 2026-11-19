"""The per-company contact discovery loop.

For every company in the Phase 1 list (that has no outcome record yet):

  1. Run iteration 1 with the main research prompt.
  2. Run iterations 2..max with the repeat prompt, passing every email
     found so far as the exclusion list ({{PREVIOUS_EMAILS}}).
  3. Stop early when the model signals saturation (NO_NEW_PUBLIC_EMAIL_FOUND)
     or returns nothing new; stop immediately when iteration 1 reports
     NO_PUBLIC_EMAIL_FOUND.
  4. Consolidate (case-insensitive dedup), then persist the contacts and
     the per-company outcome.

The outcomes CSV doubles as the progress tracker: a company present there
is considered done and is skipped on rerun, so a campaign always resumes.
Both CSVs are rewritten after every company, mirroring Phase 1's
"CSV is the source of truth" principle.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from . import context, parsing, storage
from .config import Config
from .parsing import SENTINEL_NO_NEW, SENTINEL_NO_PUBLIC

_RETRY_RE = re.compile(r"retry\s+in\s+([0-9.]+)s", re.I)


def _retry_seconds(exc: Exception, default: float = 65.0) -> float:
    """Wait derived from the API's 'retry in Xs', else the free-tier window."""
    m = _RETRY_RE.search(str(exc))
    if m:
        return min(float(m.group(1)) + 5.0, 300.0)
    return default

STATUS_FOUND = "CONTACTS_FOUND"
STATUS_NO_PUBLIC = "NO_PUBLIC_EMAIL_FOUND"
STATUS_ERROR = "ERROR"


class StoppedByUser(Exception):
    """Raised when the user requests a stop mid-run; partial results are kept."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _process_company(client, config: Config, company: dict, log_fn=print, should_stop=None) -> dict:
    name = str(company.get("company_name") or "?")
    log_fn(f"--- {name} ---")

    found: dict[str, tuple[parsing.Contact, int]] = {}  # email.lower() -> (contact, iteration)
    iterations_run = 0
    errors = 0

    for iteration in range(1, config.max_iterations + 1):
        if should_stop is not None and should_stop():
            log_fn("  Stopped by user mid-company; this company will be retried next run.")
            raise StoppedByUser()
        iterations_run = iteration
        ctx = context.build_context(
            config, company, iteration, [c for c, _ in found.values()]
        )
        try:
            raw = client.discover(ctx["system_instruction"], ctx["user_content"], config.temperature)
        except Exception as exc:  # API/network errors must not kill the campaign
            errors += 1
            log_fn(f"  [iter {iteration}] API error: {exc}")
            time.sleep(_retry_seconds(exc))
            continue

        served = getattr(client, "last_model", None)
        tag = f" · {served}" if served else ""

        parsed = parsing.parse_contact_output(raw)
        new = [c for c in parsed.contacts if c.email.lower() not in found]
        for contact in new:
            found[contact.email.lower()] = (contact, iteration)
        log_fn(f"  [iter {iteration}{tag}] returned {len(parsed.contacts)} | new {len(new)} | total {len(found)}")
        for problem in parsed.problems[:3]:
            log_fn(f"    {problem}")

        if iteration == 1 and parsed.sentinel == SENTINEL_NO_PUBLIC and not new:
            log_fn("  => no public email found; stopping.")
            break
        if iteration > 1 and (parsed.sentinel == SENTINEL_NO_NEW or not new):
            log_fn("  => saturation: no new emails; stopping.")
            break
        if parsed.sentinel == SENTINEL_NO_PUBLIC:
            # Model claims nothing exists (also possible mid-campaign); stop.
            log_fn("  => no public email found; stopping.")
            break

    if found:
        status = STATUS_FOUND
    elif errors == iterations_run:
        status = STATUS_ERROR
    else:
        status = STATUS_NO_PUBLIC

    timestamp = _now()
    contacts_records = [
        {
            "company_name": name,
            "website": company.get("website", ""),
            "contact_name": contact.name,
            "contact_email": contact.email,
            "iteration": iteration_found,
            "discovered_at": timestamp,
        }
        for contact, iteration_found in found.values()
    ]
    outcome = {
        "company_name": name,
        "website": company.get("website", ""),
        "status": status,
        "contacts_found": len(contacts_records),
        "iterations_run": iterations_run,
        "completed_at": timestamp,
    }
    log_fn(f"  => {status} ({len(contacts_records)} contacts, {iterations_run} iteration(s))")
    return {"company_name": name, "contacts": contacts_records, "outcome": outcome}


def run_contact_discovery(client, config: Config, log_fn=print, should_stop=None) -> dict:
    """Run the per-company contact discovery campaign.

    ``should_stop`` is an optional zero-arg callable; when it returns True
    the run stops cleanly. Companies fully processed before the stop are
    persisted (and skipped next run); the in-flight company is abandoned
    so it is reprocessed from scratch.
    """
    if config.max_iterations <= 0:
        raise ValueError(f"max_iterations must be positive, got {config.max_iterations}")

    companies = storage.load_companies(config.companies_path)
    outcomes = storage.load_outcomes(config.outcomes_path)
    contacts = storage.load_contacts(config.csv_path)

    # ERROR outcomes are transient (e.g. a quota/rate-limit outage): those
    # companies are retried on the next run, not treated as finished.
    done = {row["company_name"] for row in outcomes if row["status"] != STATUS_ERROR}
    pending = [c for c in companies if c["company_name"] not in done]
    if config.limit is not None and config.limit >= 0:
        pending = pending[: config.limit]

    # Idempotency guard: contacts may already exist on disk (e.g. a crash
    # after writing contacts but before writing the outcome for a company).
    # Never store the same (company, email) twice across sessions.
    stored_keys = {(row["company_name"], row["contact_email"].lower()) for row in contacts}

    reports = []
    stored_this_session = 0
    stopped = False
    for company in pending:
        if should_stop is not None and should_stop():
            log_fn("=== Run stopped by user ===")
            stopped = True
            break
        try:
            report = _process_company(client, config, company, log_fn, should_stop)
        except StoppedByUser:
            log_fn("=== Run stopped by user ===")
            stopped = True
            break
        reports.append(report)
        added = [
            row for row in report["contacts"]
            if (row["company_name"], row["contact_email"].lower()) not in stored_keys
        ]
        for row in added:
            stored_keys.add((row["company_name"], row["contact_email"].lower()))
        contacts.extend(added)
        stored_this_session += len(added)
        # One row per company, last attempt wins (e.g. a retried ERROR
        # replaces the previous ERROR row instead of duplicating it).
        outcomes = [o for o in outcomes if o["company_name"] != report["company_name"]]
        outcomes.append(report["outcome"])
        storage.write_contacts(config.csv_path, contacts)
        storage.write_outcomes(config.outcomes_path, outcomes)

    return {
        "companies_total": len(companies),
        "companies_processed": len(reports),
        "companies_skipped": len(companies) - len(pending),
        "contacts_found": stored_this_session,
        "stopped": stopped,
        "reports": reports,
    }
