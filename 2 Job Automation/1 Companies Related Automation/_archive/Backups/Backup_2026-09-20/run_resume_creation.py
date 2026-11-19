"""Run the V2 resume engine (steps 4+5) for one company's jobs.

Flow: prepare_jobs_csv.prepare(company) -> run_step4 (components) ->
run_step5 (build + verify PDF/DOCX). All outputs land in
resume_creation/program_files/output_v2/ with per-company state:

  output_v2/state/components_v2_<company>.json   persistent components per company
  output_v2/state/resume_report_<company>.json   last report copy
  output_v2/state/shortlist_<company>.json       last triage copy
  output_v2/resume_<company>/{tex,pdf,docx}      last build's artifacts

This keeps companies isolated even though the engine's internal paths are
single-slot (components_v2.json / resume_report.json) — and without touching
the engine itself.

Usage:
    python run_resume_creation.py mercedes                # full run
    python run_resume_creation.py mercedes --limit 2      # first N jobs only
    python run_resume_creation.py mercedes --jobs 7440001 # job_url substring filter
    python run_resume_creation.py mercedes --force        # re-run gated_ok jobs
    python run_resume_creation.py --list                  # companies + sources
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # makes `resume_content_improve_research` importable

from prepare_jobs_csv import list_companies, prepare  # noqa: E402

OUTPUT_V2 = ROOT / "program_files" / "output_v2"
STATE_DIR = OUTPUT_V2 / "state"


def _state_path(kind: str, company: str) -> Path:
    return STATE_DIR / f"{kind}_{company}.json"


def restore_state(company: str) -> None:
    """Load this company's persistent components into the engine's slot (or start fresh)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    slot = OUTPUT_V2 / "components_v2.json"
    state = _state_path("components_v2", company)
    if state.exists():
        shutil.copy2(state, slot)
        count = len(json.loads(slot.read_text(encoding="utf-8")))
        print(f"[runner] {company}: restored {count} record(s) from {state.name}")
    else:
        slot.unlink(missing_ok=True)
        print(f"[runner] {company}: fresh start (no previous state)")


def snapshot_state(company: str) -> None:
    """Copy the engine's single-slot outputs into this company's state + artifact dirs."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    slot = OUTPUT_V2 / "components_v2.json"
    if slot.exists():
        shutil.copy2(slot, _state_path("components_v2", company))
    for kind in ("resume_report", "shortlist"):
        src = OUTPUT_V2 / f"{kind}.json"
        if src.exists():
            shutil.copy2(src, _state_path(kind, company))
    for sub in ("tex", "pdf", "docx"):
        d = OUTPUT_V2 / "resume" / sub
        if d.exists() and any(d.iterdir()):
            dest = OUTPUT_V2 / f"resume_{company}" / sub
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(d, dest)


def clear_shared_builds() -> None:
    """Empty the engine's shared tex/pdf/docx dirs so a run's artifacts (and
    therefore this company's snapshot) contain exactly its own builds."""
    for sub in ("tex", "pdf", "docx"):
        d = OUTPUT_V2 / "resume" / sub
        if d.exists():
            shutil.rmtree(d)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run the V2 resume engine (steps 4+5) for one company")
    parser.add_argument("company", nargs="?",
                        help="bosch | mercedes | infineon | sap | bmw | simense | bwi | airbus | simense_energy")
    parser.add_argument("--limit", type=int, default=None, help="process only the first N jobs")
    parser.add_argument("--jobs", type=str, default=None, help="comma-separated job_url substrings to filter")
    parser.add_argument("--force", action="store_true", help="re-run gated_ok jobs too")
    parser.add_argument("--no-tailor", action="store_true", help="disable the per-job tailoring pass")
    parser.add_argument("--no-domain-filter", action="store_true", help="skip the engine's domain gate")
    parser.add_argument("--loose-filter", action="store_true", help="keyword-only domain gate")
    args = parser.parse_args(argv)

    if not args.company or args.company == "--list":
        print("companies (source resolved):")
        for company, source in list_companies().items():
            print(f"  {company:15} {source}")
        return 0

    prepare(args.company)
    restore_state(args.company)
    clear_shared_builds()

    from resume_content_improve_research import run_step4, run_step5

    started = time.time()
    step4_rc = run_step4.run_pipeline(
        limit=args.limit, jobs=args.jobs, force=args.force,
        no_tailor=args.no_tailor, no_domain_filter=args.no_domain_filter,
        loose_filter=args.loose_filter)
    # Run step 5 even when some jobs parked: it skips non-gated_ok records
    # internally, so the verified ones still get their PDFs built.
    step5_rc = run_step5.main()
    snapshot_state(args.company)
    elapsed = time.time() - started

    print(f"\n[runner] {args.company}: step4 rc={step4_rc}, step5 rc={step5_rc} in {elapsed:.0f}s")
    return 0 if (step4_rc == 0 and step5_rc == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
