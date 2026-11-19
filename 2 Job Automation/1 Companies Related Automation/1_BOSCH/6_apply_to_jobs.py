"""Bosch pipeline step 6: apply to Bosch jobs using their tailored resumes.

Closes the loop: every resume built by step 5 belongs to one Bosch posting
(job_url -> resume pdf/docx). This step drives the existing automation
3_bosch_job_apply.py unchanged - semantic form filling, dry-run safety,
CAPTCHA stop, unknown-question blocking all come from that module. This file
only selects WHICH jobs to apply to and WHICH resume to upload.

Selection:
  --job-url <URL>       apply to one specific posting
  --job-id <number>     apply to one posting by its SmartRecruiters id
  --resume <PATH>       use this resume file (otherwise the tailored resume
                        for the job is looked up in step 5's resume report)
  --limit N             with --all: apply to at most N jobs (default 1)
  --all                 walk every job that has a tailored resume
  --submit              really submit (otherwise dry-run: stops before Absenden)
  --headless            run the browser headless

Default (no flags): dry-run the single job configured in config/candidate.json.

Run directly: python 6_apply_to_jobs.py [--job-url URL | --job-id ID | --all] [--submit]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BOSCH_OUTPUT_DIR = PROJECT_ROOT.parent / "resume_creation" / "program_files" / "output_v2" / "state"
RESUME_REPORT = BOSCH_OUTPUT_DIR / "resume_report_bosch.json"
MASTER_CSV = BOSCH_OUTPUT_DIR / "job_resume_map_bosch.csv"


def _load_apply_module():
    """Import 3_bosch_job_apply.py by path (module name starts with a digit)."""
    path = PROJECT_ROOT / "3_bosch_job_apply.py"
    spec = importlib.util.spec_from_file_location("bosch_job_apply", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_resume_index() -> tuple[dict[str, dict], dict[str, str]]:
    """Load (url -> resume record) from step 5's report and (url -> title)."""
    if not RESUME_REPORT.exists():
        raise RuntimeError(
            f"resume report not found: {RESUME_REPORT} - run steps 4 and 5 first"
        )
    report = json.loads(RESUME_REPORT.read_text(encoding="utf-8"))
    by_url: dict[str, dict] = {}
    for record in report.get("results", []):
        url = str(record.get("job_url") or "")
        if url and record.get("pdf") and not record.get("error"):
            by_url[url] = record

    titles: dict[str, str] = {}
    if MASTER_CSV.exists():
        import csv as _csv

        with open(MASTER_CSV, encoding="utf-8", newline="") as f:
            for row in _csv.DictReader(f):
                url = str(row.get("job_url") or "")
                if url:
                    titles[url] = str(row.get("title") or "")
    return by_url, titles


def pick_targets(args: argparse.Namespace,
                 by_url: dict[str, dict], titles: dict[str, str]) -> list[tuple[str, Path]]:
    """Resolve the CLI selection into (job_url, resume_path) pairs."""
    if args.job_url:
        record = by_url.get(args.job_url)
        if args.resume:
            return [(args.job_url, Path(args.resume))]
        if record is None:
            raise RuntimeError(
                f"no tailored resume for {args.job_url} - pass --resume explicitly"
            )
        return [(args.job_url, Path(record["pdf"]))]

    if args.job_id:
        matches = [(url, rec) for url, rec in by_url.items() if args.job_id in url]
        if not matches:
            raise RuntimeError(f"no tailored resume found for job id {args.job_id!r}")
        url, record = matches[0]
        if args.resume:
            return [(url, Path(args.resume))]
        return [(url, Path(record["pdf"]))]

    if args.all:
        targets = [(url, Path(rec["pdf"])) for url, rec in by_url.items()]
        if args.limit:
            targets = targets[: args.limit]
        return targets

    # Default: the single job configured in config/candidate.json.
    config_path = PROJECT_ROOT / "config" / "candidate.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    url = str(config.get("job_url") or "")
    if not url:
        raise RuntimeError("no --job-url/--job-id/--all given and config/candidate.json has no job_url")
    if args.resume:
        return [(url, Path(args.resume))]
    record = by_url.get(url)
    if record is None:
        print(f"[APPLY] note: no tailored resume for {url} - falling back to the configured resume_path")
        return [(url, Path(config.get("resume_path") or ""))]
    return [(url, Path(record["pdf"]))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply to Bosch jobs with tailored resumes.")
    parser.add_argument("--job-url", default="", help="apply to this one posting")
    parser.add_argument("--job-id", default="", help="apply to this posting id (substring match)")
    parser.add_argument("--resume", default="", help="resume file override (default: tailored resume)")
    parser.add_argument("--all", action="store_true", help="apply to every job with a tailored resume")
    parser.add_argument("--limit", type=int, default=1, help="with --all: at most N jobs")
    parser.add_argument("--submit", action="store_true", help="really submit (default: dry-run)")
    parser.add_argument("--headless", action="store_true", help="run the browser headless")
    parser.add_argument("--wait-after-captcha", type=int, default=0,
                        help="seconds to wait for a manual CAPTCHA solve in the browser window")
    args = parser.parse_args()

    if args.submit:
        answer = input("Really SUBMIT application(s)? Type YES to confirm: ")
        if answer.strip() != "YES":
            print("Aborted.")
            return 1

    by_url, titles = load_resume_index()
    targets = pick_targets(args, by_url, titles)
    apply_mod = _load_apply_module()

    print(f"[APPLY] {'SUBMIT' if args.submit else 'DRY-RUN'} run over {len(targets)} job(s)\n")
    summary: list[dict] = []
    for index, (url, resume_path) in enumerate(targets, 1):
        title = titles.get(url, "")[:70]
        print(f"[APPLY] [{index}/{len(targets)}] {title or url}")
        print(f"[APPLY]           resume: {resume_path}")
        try:
            outcome = apply_mod.apply_to_bosch_job(
                job_url=url,
                resume_path=resume_path,
                dry_run=not args.submit,
                headless=args.headless,
                wait_after_captcha_s=args.wait_after_captcha,
            )
        except Exception as exc:  # noqa: BLE001 - one failed job never stops the batch
            outcome = {"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
        summary.append({
            "job_url": url,
            "title": title,
            "resume": str(resume_path),
            "status": outcome.get("status"),
            "error": outcome.get("error"),
            "questionsAnswered": outcome.get("questionsAnswered"),
            "unknownQuestions": outcome.get("unknownQuestions"),
        })
        print(f"[APPLY]           -> {outcome.get('status')}"
              + (f" ({outcome.get('error')})" if outcome.get("error") else "") + "\n")

    report = BOSCH_OUTPUT_DIR / "apply_report.json"
    report.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for s in summary if s["status"] in ("SUCCESS", "DRY_RUN", "DISCOVERED"))
    print(f"[APPLY] {ok}/{len(summary)} run(s) OK; report -> {report}")
    return 0 if ok == len(summary) and summary else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
