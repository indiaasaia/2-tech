"""The discovery loop.

Drives repeated Gemini calls (batches of `batch_size`) until the total cap
is reached or the model stops producing new companies. The CSV is written
after every batch, so it is always the source of truth — even if the
process is interrupted mid-campaign.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from . import context, dedup, storage, validation
from .config import Config


_RATE_HINTS = (
    "quota", "too_many_requests", "rate limit", "429", "high demand",
    "api_error", "500", "502", "503", "504", "529", "unavailable",
)
_RETRY_RE = re.compile(r"retry\s+in\s+([0-9.]+)s", re.I)


def _is_rate_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(h in msg for h in _RATE_HINTS)


def _retry_seconds(exc: Exception, default: float = 65.0) -> float:
    """Wait derived from the API's 'retry in Xs', else the free-tier window."""
    m = _RETRY_RE.search(str(exc))
    if m:
        return min(float(m.group(1)) + 5.0, 300.0)
    return default


def run_discovery(client, config: Config, log_fn=print, should_stop=None) -> dict:
    """Run the discovery campaign.

    ``should_stop`` is an optional zero-arg callable; when it returns True
    the loop breaks cleanly after the current batch (partial results are
    already persisted, so the run resumes where it stopped).
    """
    records = storage.load_records(config.csv_path)
    # Batch numbers continue across sessions so the audit trail is global.
    next_batch = max((r.get("discovery_batch") or 0 for r in records), default=0) + 1
    runs = 0
    empty_streak = 0
    rate_streak = 0
    batch_reports = []

    while len(records) < config.total_cap and runs < config.max_runs:
        if should_stop is not None and should_stop():
            log_fn("  Stopped by user.")
            break
        runs += 1
        batch_number = next_batch + runs - 1
        ctx = context.build_context(config, batch_number, records)

        try:
            raw = client.discover(
                ctx["system_instruction"], ctx["user_content"], config.temperature
            )
        except Exception as exc:  # network/API errors must not kill the campaign
            log_fn(f"  [batch {batch_number}] API error: {exc}")
            batch_reports.append({"batch": batch_number, "error": str(exc), "stored": 0, "total": len(records)})
            if _is_rate_error(exc):
                # Rate limits are transient: wait out the window, then retry.
                rate_streak += 1
                if rate_streak >= 12:
                    log_fn("  Stopping: API rate limit looks exhausted.")
                    break
                wait = _retry_seconds(exc)
                log_fn(f"  Waiting {wait:.0f}s for the rate limit to reset ...")
                time.sleep(wait)
                continue
            empty_streak += 1
            if empty_streak > config.empty_run_retries:
                log_fn("  Stopping: repeated failures with no results.")
                break
            continue

        try:
            accepted, rejected, notes = validation.parse_response(raw, config.min_hiring_score)
        except validation.ParseError as exc:
            log_fn(f"  [batch {batch_number}] unparseable model output: {exc}")
            batch_reports.append({"batch": batch_number, "error": f"parse: {exc}", "stored": 0, "total": len(records)})
            empty_streak += 1
            if empty_streak > config.empty_run_retries:
                log_fn("  Stopping: repeated unparseable output.")
                break
            continue

        new_records = dedup.filter_new(accepted, records)

        # Never overshoot the cap: truncate the final batch.
        remaining = config.total_cap - len(records)
        if len(new_records) > remaining:
            new_records = new_records[:remaining]

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        stamped = [dict(c, discovery_batch=batch_number, discovered_at=now) for c in new_records]

        records.extend(stamped)
        storage.write_records(config.csv_path, records)

        duplicates = len(accepted) - len(new_records)
        log_fn(
            f"  [batch {batch_number}] returned {len(accepted)} | stored {len(stamped)} "
            f"| duplicates skipped {duplicates} | invalid {len(rejected)} | total {len(records)}"
        )
        if notes:
            log_fn(f"    notes: {notes}")
        for entry, problems in rejected:
            name = entry.get("company_name", "?") if isinstance(entry, dict) else repr(entry)[:40]
            log_fn(f"    rejected: {name} -> {'; '.join(problems)}")
        batch_reports.append(
            {
                "batch": batch_number,
                "returned": len(accepted),
                "stored": len(stamped),
                "duplicates": duplicates,
                "invalid": len(rejected),
                "total": len(records),
            }
        )

        if not stamped:
            empty_streak += 1
            if empty_streak > config.empty_run_retries:
                log_fn("  Stopping: no new companies found in consecutive runs.")
                break
        else:
            empty_streak = 0

    return {
        "target": config.total_cap,
        "total_stored": len(records),
        "runs": runs,
        "batches": batch_reports,
    }
