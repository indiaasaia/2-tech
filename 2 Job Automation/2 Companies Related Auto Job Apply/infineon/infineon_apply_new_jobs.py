"""infineon_apply_new_jobs.py — apply to un-submitted ENGLISH_OK Infineon jobs.

For each requested job id:
  1. Skip when a result JSON already records SUCCESS (never re-apply).
  2. Skip when a prior REAL submit attempt exists with no clear outcome
     (Eightfold shows no applied-status on its pages - verified 2026-09-22 -
     so the local ledger is the duplicate guard; ambiguous cases need
     manual review, not a blind re-click).
  3. DRY-RUN first; only a clean DRY_RUN unlocks the real submit
     (apply_to_infineon_job itself: resume upload -> autofill verification ->
     location + question selects -> validation -> gated submit).
  4. Append every outcome to results/apply_session_log.csv.

Usage:
    python infineon_apply_new_jobs.py <job_id> [<job_id> ...] [--pause 15]
"""
import argparse
import csv
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("infineon_job_apply", ROOT / "infineon_job_apply.py")
inf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inf)

RESULTS_DIR = ROOT / "results"
LOG = RESULTS_DIR / "apply_session_log.csv"

# Proven client-side rejects (submit clicked, portal re-rendered the form with
# inline errors, nothing was submitted). Evidence: results/08-after-submit-
# <id>.png shows the open form with the red 'errors found' badges. Safe to
# retry after the fix; reviewed manually 2026-09-22.
RETRY_AFTER_CLIENTSIDE_REJECT = {"563808959893172"}


def _load_results() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in RESULTS_DIR.glob("*-result.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        jid = str(d.get("job_id") or p.name.split("-result")[0])
        out[jid] = d
    return out


def _log_row(jid: str, stage: str, status: str, detail: str) -> None:
    LOG.parent.mkdir(exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "job_id", "stage", "status", "detail"])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    jid, stage, status, detail])


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_ids", nargs="+")
    parser.add_argument("--pause", type=int, default=15,
                        help="seconds between jobs")
    parser.add_argument("--dry-run-only", action="store_true",
                        help="run the dry-runs but never submit")
    args = parser.parse_args()

    ledger = _load_results()
    outcomes: list[tuple[str, str]] = []
    for jid in args.job_ids:
        prior = ledger.get(jid)
        url = f"https://jobs.infineon.com/careers/apply?pid={jid}"

        if prior and prior.get("status") == "SUCCESS":
            print(f"[{jid}] SKIP: ledger already records SUCCESS.", flush=True)
            _log_row(jid, "skip", "ALREADY_APPLIED", "ledger SUCCESS")
            outcomes.append((jid, "ALREADY_APPLIED"))
            continue
        if prior and prior.get("mode") == "submit":
            # A client-side reject is NOT a submission: when the portal's own
            # validation refused the form, the submit click never left the
            # page - verified via the 'errors found' UI state + open form.
            # Those are safe to retry; any other unclear outcome is not.
            clientside_reject = (
                prior.get("validation_errors")
                or jid in RETRY_AFTER_CLIENTSIDE_REJECT
            )
            if clientside_reject:
                print(f"[{jid}] prior submit was client-side rejected - retrying "
                      f"after the fix.", flush=True)
            else:
                print(f"[{jid}] SKIP: prior real submit attempt with unclear outcome "
                      f"(status {prior.get('status')!r}) - needs manual review.", flush=True)
                _log_row(jid, "skip", "NEEDS_MANUAL_REVIEW", f"prior submit, status {prior.get('status')}")
                outcomes.append((jid, "NEEDS_MANUAL_REVIEW"))
                continue

        # ---- gated dry-run -------------------------------------------------
        print(f"[{jid}] DRY RUN starting...", flush=True)
        dry = inf.apply_to_infineon_job(url, None, dry_run=True, headless=False,
                                        browser_hold_s=2)
        _log_row(jid, "dry_run", dry["status"],
                 json.dumps(dry.get("errors", []), ensure_ascii=False)[:180])
        if dry.get("status") != "DRY_RUN":
            print(f"[{jid}] dry-run did not come back clean "
                  f"({dry.get('status')}) - NOT submitting.", flush=True)
            outcomes.append((jid, dry.get("status", "FAILED")))
            continue

        if args.dry_run_only:
            print(f"[{jid}] DRY_RUN clean (--dry-run-only: submit skipped).", flush=True)
            outcomes.append((jid, "DRY_RUN"))
            continue

        # ---- real submission ----------------------------------------------
        print(f"[{jid}] dry-run clean - submitting...", flush=True)
        time.sleep(3)
        real = inf.apply_to_infineon_job(url, None, dry_run=False, headless=False,
                                         browser_hold_s=5)
        _log_row(jid, "submit#1", real["status"],
                 json.dumps(real.get("errors", []), ensure_ascii=False)[:180])
        print(f"[{jid}] submit status: {real['status']}", flush=True)
        outcomes.append((jid, real["status"]))
        ledger = _load_results()  # pick up the fresh result
        time.sleep(args.pause)

    print("\n=== SESSION SUMMARY ===")
    for jid, status in outcomes:
        print(f"  {jid}: {status}")
    ok = sum(1 for _, s in outcomes if s == "SUCCESS")
    print(f"{ok}/{len(outcomes)} submitted successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
