"""sap_apply_new_jobs.py — apply to un-submitted ENGLISH_OK SAP jobs, end to end.

For each requested job id:
  1. Skip when a result JSON already records SUCCESS (never re-apply).
  2. Resolve the resume: hub map (job_resume_map_sap.csv) first, else base CV.
  3. DRY-RUN first; only a clean DRY_RUN unlocks the real submit.
  4. Submit with up to --attempts attempts; transient automation errors
     (timeouts, render races) are retried after a pause, form rejections are
     NOT retried (deterministic server state).
  5. Every outcome is appended to results/apply_session_log.csv.

Usage:
    python sap_apply_new_jobs.py 1437848533 1437947533 ...
"""
import argparse
import csv
import importlib.util
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
MAP_CANDIDATES = [
    ROOT.parent / "resume_creation" / "program_files" / "output_v2" / "state" / "job_resume_map_sap.csv",
    ROOT.parent.parent / "resume_creation" / "program_files" / "output_v2" / "state" / "job_resume_map_sap.csv",
    Path(r"E:\WorkSpace\2 Tech\2 Job Automation\Companies Related Automation\resume_creation\program_files\output_v2\state\job_resume_map_sap.csv"),
]
MAP_CSV = next((p for p in MAP_CANDIDATES if p.exists() and p.is_file()), MAP_CANDIDATES[0])
LOCAL_MAP_CSV = ROOT / "sub_program_files" / "output" / "job_resume_map_local.csv"
BASE_CV = Path(r"E:\WorkSpace\2 Tech\1 Cold Emailing\Cold Emaling\RAVAL_MEETKUMAR_RESUME.pdf")
SESSION_LOG = RESULTS / "apply_session_log.csv"
RETRYABLE = {"NEEDS_ATTENTION"}
TRANSIENT_MARKERS = ("timeout", "timed out", "did not reach the sap career site")


def load_apply_module():
    spec = importlib.util.spec_from_file_location("sap_job_apply", ROOT / "sap_job_apply.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def submitted_ids() -> set[str]:
    done = set()
    for f in RESULTS.glob("sap-*-result.json"):
        match = re.search(r"sap-(\d+)", f.name)
        if match and json.loads(f.read_text(encoding="utf-8")).get("status") == "SUCCESS":
            done.add(match.group(1))
    return done


def resolve_resume(job_id: str) -> Path | None:
    for map_file in (LOCAL_MAP_CSV, MAP_CSV):
        if map_file.exists():
            for row in csv.DictReader(map_file.open(encoding="utf-8-sig")):
                if job_id in row.get("job_url", "") and row.get("resume_pdf") and Path(row["resume_pdf"]).is_file():
                    return Path(row["resume_pdf"])
    return BASE_CV if BASE_CV.is_file() else None


def job_url_for(job_id: str) -> str | None:
    for row in csv.DictReader((ROOT / "sap_results.csv").open(encoding="utf-8-sig")):
        if row.get("Job ID") == job_id:
            return row.get("Link", "")
    return None


def log_session(job_id: str, stage: str, status: str, detail: str) -> None:
    new = not SESSION_LOG.exists()
    with SESSION_LOG.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(["timestamp", "job_id", "stage", "status", "detail"])
        writer.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), job_id, stage, status, detail[:180]])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_ids", nargs="+")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--pause", type=float, default=20.0)
    args = parser.parse_args()

    sap = load_apply_module()
    already = submitted_ids()
    summary = []

    for job_id in args.job_ids:
        if job_id in already:
            print(f"[{job_id}] SKIP — already SUCCESS on record")
            summary.append((job_id, "SKIPPED_APPLIED"))
            continue
        url = job_url_for(job_id)
        resume = resolve_resume(job_id)
        if not url or not resume:
            print(f"[{job_id}] SKIP — missing {'url' if not url else 'resume'}")
            summary.append((job_id, "SKIPPED_MISSING_INPUT"))
            continue

        # 1) dry-run gate
        print(f"\n[{job_id}] DRY-RUN (resume: {resume.name})")
        dry = sap.apply_to_sap_job(url, resume, dry_run=True, headless=False)
        log_session(job_id, "dry_run", dry.get("status", "?"), str(dry.get("errors", [])))
        if dry.get("status") != "DRY_RUN":
            print(f"[{job_id}] STOP — dry-run {dry.get('status')}, not submitting")
            summary.append((job_id, f"DRY_{dry.get('status')}"))
            continue

        # 2) real submit with retries for transient errors only
        outcome = None
        for attempt in range(1, args.attempts + 1):
            print(f"[{job_id}] SUBMIT attempt {attempt}/{args.attempts}")
            outcome = sap.apply_to_sap_job(url, resume, dry_run=False, headless=False)
            log_session(job_id, f"submit#{attempt}", outcome.get("status", "?"), str(outcome.get("errors", [])))
            status = outcome.get("status")
            if status == "SUCCESS":
                break
            if status not in RETRYABLE:
                break  # FAILED / form-rejected: deterministic, no retry
            messages = " ".join(str(e.get("message", "")) for e in outcome.get("errors", [])).lower()
            if not any(marker in messages for marker in TRANSIENT_MARKERS):
                break  # non-transient NEEDS_ATTENTION
            if attempt < args.attempts:
                print(f"[{job_id}] transient failure — pausing {args.pause:.0f}s")
                time.sleep(args.pause)
        final = outcome.get("status") if outcome else "NO_OUTCOME"
        print(f"[{job_id}] FINAL: {final}")
        summary.append((job_id, final))

    print("\n=== SESSION SUMMARY ===")
    for job_id, final in summary:
        print(f"  {job_id}: {final}")
    ok = sum(1 for _, s in summary if s == "SUCCESS")
    print(f"{ok}/{len(summary)} submitted successfully")
    return 0 if ok == len(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
