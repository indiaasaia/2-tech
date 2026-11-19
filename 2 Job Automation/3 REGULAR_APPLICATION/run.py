"""Regular application run: fetch -> filter -> keys -> resumes -> cover letters.

    python run.py --days 1          # jobs posted in the last 24 hours (default)
    python run.py --days 3          # last 3 days
    python run.py --skip-fetch      # reuse output/jobs/fetched_jobs.csv (no scraping)

Steps: fetch -> keep last N days -> LLM screening (role type, German requirement,
country) -> keys -> analyze -> resumes -> cover letters.

Documents land in output/applications/ (resume/, letters/, prep/). Jobs from
earlier runs are kept; only this run's jobs are built.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "steps"))


def _stage(name: str, fn):
    """Run one stage; returns (ok, result). An exception is a failed stage."""
    print(f"\n=== {name} ===")
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - report the failing stage with its traceback
        print(f"[RUN] {name} FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False, None
    return True, result


def _run_urls(csv_path: Path) -> list[str]:
    import pandas as pd

    if not csv_path.exists():
        return []
    frame = pd.read_csv(csv_path)
    if frame.empty or "job_url" not in frame.columns:
        return []
    return [str(u) for u in frame["job_url"].dropna().tolist()]


def _summary(urls: set[str]) -> None:
    """Print this run's documents (paths are relative to REGULAR_APPLICATION)."""
    import json

    from engine import config

    def load(path: Path) -> list[dict]:
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("results", [])
        except (OSError, json.JSONDecodeError):
            return []

    resumes = {r.get("job_url"): r for r in load(config.REPORT_PATH)}
    letters = {r.get("job_url"): r for r in load(config.LETTERS_REPORT_PATH)}
    rel = lambda p: str(Path(p).resolve().relative_to(ROOT)) if p else "-"  # noqa: E731
    done = 0
    print("\n=== THIS RUN ===")
    for url in sorted(urls):
        resume, letter = resumes.get(url), letters.get(url)
        if not resume:
            continue                      # removed by the domain filter or parked in step 4
        arts = letter.get("artifacts") if letter and isinstance(letter.get("artifacts"), dict) else {}
        ok = resume.get("status") == "verified" and bool(letter and letter.get("letter_gates_passed"))
        done += ok
        print(f"[{'OK ' if ok else '-- '}] {resume.get('company', '')} | {str(resume.get('title', ''))[:60]}")
        print(f"      resume: {rel(resume.get('pdf'))}")
        print(f"      letter: {rel(arts.get('letter_pdf'))}"
              + (f"  ({letter.get('letter_source')})" if letter and letter.get("letter_source") else ""))
    print(f"\n[RUN] {done} complete application(s) from {len(urls)} filtered job(s). "
          f"All documents: {rel(config.OUTPUT_DIR)}; interview prep: {rel(config.OUTPUT_DIR / 'prep')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fetch jobs of the last N days and create resume + cover letter for each")
    parser.add_argument("--days", type=float, default=1.0, help="posting window in days (default 1 = last 24 hours)")
    parser.add_argument("--pages", type=int, default=None, help="max listing pages per source/keyword (default: automatic)")
    parser.add_argument("--headless", action="store_true", help="run Stepstone's Chrome without a window")
    parser.add_argument("--skip-fetch", action="store_true", help="reuse output/jobs/fetched_jobs.csv instead of scraping")
    parser.add_argument("--max-jobs", type=int, default=None, help="create documents for at most N new jobs")
    parser.add_argument("--force", action="store_true", help="regenerate resumes for jobs already done")
    parser.add_argument("--force-letters", action="store_true", help="rewrite cover letters for jobs already done")
    parser.add_argument("--no-domain-filter", action="store_true", help="keep jobs outside the AI/tech domain filter")
    parser.add_argument("--no-screen", action="store_true", help="skip the LLM screening (role / German / country)")
    parser.add_argument("--include-thesis", action="store_true", help="screening: also keep thesis positions")
    parser.add_argument("--keep-abroad", action="store_true", help="screening: also keep jobs outside Germany")
    args = parser.parse_args(argv)
    if args.days <= 0:
        parser.error("--days must be greater than 0")

    import fetch_jobs
    import filter_jobs
    import screen_jobs
    import test_keys
    from engine import config, run_step4, run_step5, run_step6
    config.ensure_utf8_stdout()

    if not args.skip_fetch:
        ok, _ = _stage(f"STEP 1 | fetch jobs (last {args.days:g} day(s))",
                       lambda: fetch_jobs.fetch_jobs(days=args.days, pages=args.pages, headless=args.headless))
        if not ok:
            return 1
    ok, kept = _stage(f"STEP 2 | keep jobs from the last {args.days:g} day(s)",
                      lambda: filter_jobs.filter_jobs(days=args.days))
    if not ok:
        return 1
    if not kept:
        print("[RUN] no jobs in this window - nothing to create. Try a larger --days.")
        return 0
    # Keys first: the screening already uses the LLM.
    ok, active = _stage("STEP 3 | test Ollama keys", test_keys.test_ollama_keys)
    if not ok or not active:
        print(f"[RUN] no working Ollama key - add one to {test_keys.KEYS_FILE}")
        return 1
    if args.no_screen:
        import shutil

        shutil.copyfile(screen_jobs.INPUT_CSV, screen_jobs.OUTPUT_CSV)
        print("\n=== STEP 3b | screening skipped (--no-screen) ===")
    else:
        ok, kept = _stage("STEP 3b | LLM screening: role type, German requirement, country",
                          lambda: screen_jobs.screen_jobs(include_thesis=args.include_thesis,
                                                          keep_abroad=args.keep_abroad))
        if not ok:
            return 1
        if not kept:
            print(f"[RUN] the screening kept no job - see {screen_jobs.REPORT_CSV}")
            return 0

    urls = set(_run_urls(config.FILTERED_JOBS_CSV))
    # Steps 4-6 return 1 when SOME job was parked (e.g. an ad the KB cannot match);
    # that is a normal outcome, so only an exception stops the run.
    ok, _ = _stage("STEP 4 | analyze jobs and write resume content", lambda: run_step4.run_pipeline(
        limit=args.max_jobs, force=args.force, no_domain_filter=args.no_domain_filter))
    if not ok:
        return 1
    ok, _ = _stage("STEP 5 | build and verify resumes (PDF + DOCX)", lambda: run_step5.main(only_urls=urls))
    if not ok:
        return 1
    ok, _ = _stage("STEP 6 | write and verify cover letters",
                   lambda: run_step6.run_pipeline(force=args.force_letters, only_urls=urls))
    if not ok:
        return 1
    try:
        import build_dashboard
        _stage("STEP 7 | generate application dashboard", build_dashboard.main)
    except Exception as exc:
        print(f"[RUN] warning: dashboard generation failed: {exc}")
    _summary(urls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
