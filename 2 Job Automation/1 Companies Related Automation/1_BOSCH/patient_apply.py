"""Unattended Bosch apply driver — patient retry rounds over the tailored-resume jobs.

Delegates every decision to 3_bosch_job_apply.py (semantic filling, dry-run
safety, CAPTCHA stop). This driver only:
  1. skips jobs already SUCCESS in this ledger or the bot's own results dir,
  2. runs each remaining job with --submit and a bounded CAPTCHA wait window,
  3. loops up to --rounds times (DataDome is probabilistic per IP/session),
  4. never bypasses a CAPTCHA and never retries a job that truly submitted.

Ledger: results/patient_apply_ledger.json  (job_id -> status/history)

Run:  python patient_apply.py --rounds 3 --captcha-wait 45
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
STATE_DIR = PROJECT_ROOT.parent / "resume_creation" / "program_files" / "output_v2" / "state"
RESULTS_DIR = PROJECT_ROOT / "results"
LEDGER = RESULTS_DIR / "patient_apply_ledger.json"


def load_map() -> list[dict]:
    path = STATE_DIR / "job_resume_map_bosch.csv"
    import csv

    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if r.get("status") == "OK"]


def already_success(job_url: str, ledger: dict, results: dict) -> bool:
    entry = ledger.get(job_url)
    if entry and entry.get("status") == "SUCCESS":
        return True
    return results.get(job_url, {}).get("status") == "SUCCESS"


def bot_result_for(job_url: str) -> dict | None:
    """Load the bot's own result JSON for this job, if a run happened."""
    import re

    m = re.search(r"/BoschGroup/(\d+)", job_url)
    if not m:
        return None
    path = RESULTS_DIR / f"bosch-{m.group(1)}-result.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def run_job(job_url: str, resume: str, captcha_wait: int, timeout_s: int) -> dict:
    cmd = [sys.executable, "3_bosch_job_apply.py",
           "--url", job_url, "--resume", resume,
           "--submit", "--wait-after-captcha", str(captcha_wait)]
    try:
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              input="YES\n", timeout=timeout_s)
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        out += "\nDRIVER: per-job timeout exceeded"
        return {"status": "TIMEOUT", "tail": out[-600:]}
    status = "FAILED"
    for token in ("Final status: SUCCESS", "DRY_RUN_COMPLETE"):
        if token in out:
            status = "SUCCESS" if "SUCCESS" in token else "DRY_RUN"
            break
    if "Final status: CAPTCHA_DETECTED" in out or "CAPTCHA / bot protection detected" in out:
        status = "CAPTCHA_DETECTED"
    elif "Final status: FAILED" in out:
        status = "FAILED"
    elif "UNKNOWN_FORM" in out:
        status = "UNKNOWN_FORM"
    # prefer the bot's own persisted verdict if present
    bot = bot_result_for(job_url)
    if bot and bot.get("status"):
        status = bot["status"] if bot["status"] in ("SUCCESS", "FAILED", "CAPTCHA_DETECTED") else status
    tail = "\n".join(out.strip().splitlines()[-6:])
    return {"status": status, "tail": tail}


def main() -> int:
    ap = argparse.ArgumentParser(description="Patient unattended Bosch apply rounds")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--captcha-wait", type=int, default=45,
                    help="seconds each attempt waits in case the gate passes")
    ap.add_argument("--per-job-timeout", type=int, default=180)
    ap.add_argument("--only", default="", help="process only the job whose URL contains this substring")
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ledger: dict = {}
    if LEDGER.exists():
        try:
            ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            ledger = {}

    jobs = load_map()
    if args.only:
        jobs = [j for j in jobs if args.only in j["job_url"]]
        if not jobs:
            print(f"[patient] no staged job matches --only {args.only!r}")
            return 1
    results_index: dict = {}
    for job in jobs:
        bot = bot_result_for(job["job_url"])
        if bot:
            results_index[job["job_url"]] = bot

    print(f"[patient] {len(jobs)} staged job(s), {args.rounds} round(s) planned\n")
    for round_no in range(1, args.rounds + 1):
        pending = [j for j in jobs if not already_success(j["job_url"], ledger, results_index)]
        if not pending:
            break
        print(f"[patient] === ROUND {round_no}/{args.rounds}: {len(pending)} job(s) ===")
        for i, job in enumerate(pending, 1):
            url, resume = job["job_url"], job["resume_pdf"]
            print(f"[patient] [{i}/{len(pending)}] {job['title'][:60]}")
            outcome = run_job(url, resume, args.captcha_wait, args.per_job_timeout)
            print(f"[patient]     -> {outcome['status']}")
            if outcome.get("tail"):
                for line in outcome["tail"].splitlines():
                    print(f"[patient]     | {line[:110]}")
            entry = ledger.setdefault(url, {"history": []})
            entry["status"] = outcome["status"]
            entry["history"].append({"round": round_no, "status": outcome["status"],
                                     "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            LEDGER.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
            if outcome["status"] == "SUCCESS":
                results_index[url] = {"status": "SUCCESS"}
            time.sleep(3)
    done = sum(1 for j in jobs if already_success(j["job_url"], ledger, results_index))
    print(f"\n[patient] DONE: {done}/{len(jobs)} submitted successfully "
          f"(ledger -> {LEDGER.name}). CAPTCHAs were never bypassed; "
          "remaining jobs stay pending for a session where the gate passes.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
