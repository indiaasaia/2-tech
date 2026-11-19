"""Run a curated end-to-end application dry-run; this script cannot submit.

Usage from mixed/:
    python tools/auto_apply_sample_dryrun.py --company infineon
    python tools/auto_apply_sample_dryrun.py --all

The final submission button is never clicked; the runner may click the initial
Apply control to open a form. Results are saved under reports/auto_apply_sample_dryruns/.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
OUTPUT_ROOT = ROOT / "reports" / "auto_apply_sample_dryruns"
SAMPLES = {
    "sap": "744000155471239",
    "infineon": "563808972143015",
    # This older requisition is retained as a Workday regression fixture, not a
    # fresh jobs.mercedes-benz.com posting.
    "mercedes": "R0006913",
    "bosch": "744000151829278",
}


def _local_path(value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path
    normalized = value.replace("\\", "/")
    marker = "/mixed/"
    if marker in normalized:
        return ROOT / normalized.split(marker, 1)[1]
    return path


def _sample(company: str) -> dict:
    map_path = ROOT / "resume_and_cover_letter" / "program_files" / "output_v2" / "state" / f"job_bundle_map_{company}.csv"
    if not map_path.is_file():
        raise FileNotFoundError(f"Bundle map not found: {map_path}")
    with map_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    wanted_id = SAMPLES[company]
    historical_workday = None
    if company == "mercedes":
        prior_result_path = ROOT / "reports" / "auto_apply_sample_dryruns" / "mercedes" / "historical_workday_R0006913.json"
        historical_workday = json.loads(prior_result_path.read_text(encoding="utf-8"))
        evidence_url = historical_workday.get("jobUrl", "")
        if historical_workday.get("status") != "DRY_RUN" or not evidence_url:
            raise RuntimeError("Mercedes Workday fixture lacks a prior clean DRY_RUN")
        resume = Path(historical_workday.get("resume", ""))
        if not resume.is_file():
            raise FileNotFoundError(f"Historical Mercedes Workday resume missing: {resume}")
        # The matching cover letter is tracked in mixed output and shares the
        # exact job role filename, unlike the public posting ID.
        letter = ROOT / "resume_and_cover_letter" / "program_files" / "output_v2" / "letters_mercedes" / "pdf" / "Anschreiben_Mercedes-Benz-Tech-Innovation-GmbH_Werkstudent-im-Bereich-Testbenches-und-T.pdf"
        if not letter.is_file():
            raise FileNotFoundError(f"Historical Mercedes Workday cover letter missing: {letter}")
        return {"company": company, "job_id": wanted_id, "job_url": evidence_url, "title": "Werkstudent im Bereich Testbenches und Telematikentwicklung", "score": "35.4", "resume": str(resume), "cover_letter": str(letter), "cover_letter_available": True, "historical_sample": True}

    for row in rows:
        url = row.get("job_url", "")
        match = re.search(r"\d{6,}", url)
        if not match or match.group(0) != wanted_id:
            continue
        if row.get("status") != "OK":
            raise RuntimeError(f"Bundle {wanted_id} has status {row.get('status')!r}, not OK")
        resume = _local_path(row.get("resume_pdf", ""))
        letter = _local_path(row.get("letter_pdf", ""))
        if not resume.is_file() or not letter.is_file():
            raise FileNotFoundError(f"Exact job bundle incomplete for {wanted_id}: resume_exists={resume.is_file()}, letter_exists={letter.is_file()}")
        return {
            "company": company,
            "job_id": wanted_id,
            "job_url": url,
            "title": row.get("title", ""),
            "score": row.get("score", ""),
            "resume": str(resume),
            "cover_letter": str(letter),
            "cover_letter_available": True,
        }
    raise LookupError(f"Sample job {wanted_id} is not in {map_path}")


def _run_bosch(sample: dict, artifact_dir: Path) -> dict:
    """Run Bosch directly so its evidence goes to an isolated directory."""
    script = PROJECT_ROOT / "1_BOSCH" / "3_bosch_job_apply.py"
    spec = importlib.util.spec_from_file_location("bosch_sample_applier", script)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Bosch applier: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.RESULTS_DIR = artifact_dir
    return module.apply_to_bosch_job(
        job_url=sample["job_url"],
        resume_path=Path(sample["resume"]),
        dry_run=True,
        headless=True,
        wait_after_captcha_s=0,
    )


def _run_adapter(company: str, sample: dict, artifact_dir: Path) -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from auto_apply.registry import get_applier

    if company == "mercedes":
        applier = get_applier(company)
        if applier is None:
            raise RuntimeError(f"No registered applier for {company}")
        # The Workday script writes result and screenshot files next to itself.
        # Snapshot its sample-ID outputs, capture fresh diagnostics elsewhere,
        # then restore the repository's pre-existing historical artifacts.
        result_dir = PROJECT_ROOT / "mercedes" / "results"
        result_prefixes = ("mercedes-R0006913-result.json", "R0006913-")
        protected = [p for p in result_dir.iterdir() if p.name.startswith(result_prefixes)]
        before = {p: p.read_bytes() for p in protected if p.is_file()}
        try:
            result = applier.apply_one(
                job_url=sample["job_url"],
                resume_path=sample["resume"],
                letter_path=sample["cover_letter"],
                dry_run=True,
                headless=True,
                captcha_wait=0,
                browser_hold=0,
            )
            artifact_dir.mkdir(parents=True, exist_ok=True)
            for path in result_dir.iterdir():
                if path.is_file() and path.name.startswith(result_prefixes):
                    if path not in before or path.read_bytes() != before[path]:
                        shutil.copy2(path, artifact_dir / path.name)
            return result.to_dict()
        finally:
            for path in result_dir.iterdir():
                if path.is_file() and path.name.startswith(result_prefixes) and path not in before:
                    path.unlink()
            for path, contents in before.items():
                path.write_bytes(contents)

    applier = get_applier(company)
    if applier is None:
        raise RuntimeError(f"No registered applier for {company}")
    result = applier.apply_one(
        job_url=sample["job_url"],
        resume_path=sample["resume"],
        letter_path=sample["cover_letter"],
        dry_run=True,
        headless=True,
        captcha_wait=0,
        browser_hold=0,
    )
    return result.to_dict()


def run(company: str, run_dir: Path) -> dict:
    sample = _sample(company)
    company_dir = run_dir / company
    company_dir.mkdir(parents=True, exist_ok=True)
    if company == "bosch":
        raw_result = _run_bosch(sample, company_dir / "portal_artifacts")
    else:
        raw_result = _run_adapter(company, sample, company_dir / "portal_artifacts")
    result = raw_result.to_dict() if hasattr(raw_result, "to_dict") else raw_result
    record = {
        **sample,
        "dry_run_only": True,
        "final_submit_clicked": False,
        "result": result,
    }
    (company_dir / "sample_run.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely dry-run one sample application without submitting.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--company", choices=sorted(SAMPLES))
    selection.add_argument("--all", action="store_true")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = OUTPUT_ROOT / run_id
    companies = list(SAMPLES) if args.all else [args.company]
    failures = 0
    summaries = []
    for company in companies:
        try:
            record = run(company, run_dir)
            result = record["result"]
            status = result.get("status", "UNKNOWN")
            print(f"[{company}] {record['job_id']} {status}: {record['title']}", flush=True)
            summaries.append({
                "company": company,
                "job_id": record["job_id"],
                "status": status,
                "path": str(run_dir / company / "sample_run.json"),
            })
            if status not in {"DRY_RUN", "DRY_RUN_COMPLETE"}:
                failures += 1
        except Exception as exc:
            failures += 1
            error = {"company": company, "status": "HARNESS_ERROR", "error": f"{type(exc).__name__}: {exc}"}
            company_dir = run_dir / company
            company_dir.mkdir(parents=True, exist_ok=True)
            (company_dir / "sample_run.json").write_text(json.dumps(error, indent=2) + "\n", encoding="utf-8")
            summaries.append(error)
            print(f"[{company}] HARNESS_ERROR: {error['error']}", file=sys.stderr, flush=True)

    (run_dir / "summary.json").write_text(
        json.dumps({"run_id": run_id, "dry_run_only": True, "final_submit_clicked": False, "results": summaries}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Run artifacts: {run_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
