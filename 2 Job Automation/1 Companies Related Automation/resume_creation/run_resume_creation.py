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
    """Merge this company's persistent components with any newer partial progress
    in the engine's slot (the engine saves after every job, so an interrupted
    run leaves recoverable records there), then write the merged store to both."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    slot = OUTPUT_V2 / "components_v2.json"
    state = _state_path("components_v2", company)

    def _records(path: Path) -> dict[str, dict]:
        if not path.exists():
            return {}
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return {str(r.get("job_url") or ""): r for r in records}

    merged = _records(state)                    # last snapshot is the base
    # Only trust engine-slot partials owned by THIS company (an interrupted
    # run of a different company must not bleed into this one's state).
    owner_path = STATE_DIR / "slot_owner.json"
    owner = ""
    if owner_path.exists():
        try:
            owner = (json.loads(owner_path.read_text(encoding="utf-8")) or {}).get("company", "")
        except (json.JSONDecodeError, OSError):
            owner = ""
    partial = _records(slot) if owner == company else {}
    if owner and owner != company:
        slot.unlink(missing_ok=True)            # stale other-company slot: drop it
    recovered = 0
    for url, rec in partial.items():
        prior = merged.get(url)
        if prior is None:
            merged[url] = rec
            recovered += 1
        elif prior.get("status") != "gated_ok" and rec.get("status") == "gated_ok":
            merged[url] = rec                   # slot finished what state had parked/pending
            recovered += 1
        elif prior.get("status") == "parked" and rec.get("status") == "parked":
            merged[url] = rec                   # fresher error message
    merged_records = list(merged.values())
    slot.write_text(json.dumps(merged_records, indent=2, ensure_ascii=False), encoding="utf-8")
    state.write_text(json.dumps(merged_records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[runner] {company}: {len(merged_records)} record(s) restored"
          + (f" ({recovered} recovered from an interrupted run)" if recovered else ""))


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


def write_resume_map(company: str) -> None:
    """Write state/job_resume_map_<company>.csv (job_url, status, resume_pdf, title,
    score) from the company's resume report — the file the apply bots in the
    company folders consume to pick each job's tailored PDF."""
    report_path = _state_path("resume_report", company)
    if not report_path.exists():
        return
    import csv

    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = []
    for entry in report.get("results", []):
        stem = entry.get("file_stem")
        pdf = OUTPUT_V2 / f"resume_{company}" / "pdf" / f"{stem}.pdf" if stem else None
        if entry.get("status") == "verified" and pdf and pdf.is_file():
            rows.append({
                "job_url": entry.get("job_url", ""),
                "status": "OK",
                "resume_pdf": str(pdf),
                "title": entry.get("title", ""),
                "score": entry.get("score", ""),
            })
    if not rows:
        return
    map_path = STATE_DIR / f"job_resume_map_{company}.csv"
    with map_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["job_url", "status", "resume_pdf", "title", "score"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"[runner] {company}: resume map -> {map_path.name} ({len(rows)} job(s))")


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
    parser.add_argument("--refilter", action="store_true",
                        help="strict role gate: prune saved state (role_filter_config.json), "
                             "then rebuild WITHOUT new LLM calls (step 4 skipped)")
    parser.add_argument("--build-only", action="store_true",
                        help="rebuild pdf/docx from saved components only (no prepare, no step 4)")
    args = parser.parse_args(argv)

    if not args.company or args.company == "--list":
        print("companies (source resolved):")
        for name, source in list_companies().items():
            print(f"  {name:15} {source}")
        return 0

    if not args.build_only:
        prepare(args.company)
    restore_state(args.company)
    if args.refilter:
        from role_filter import role_filter_prune
        role_filter_prune(args.company, dry_run=False)
        records = json.loads(_state_path("components_v2", args.company).read_text(encoding="utf-8"))
        slot = OUTPUT_V2 / "components_v2.json"
        slot.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        (STATE_DIR / "slot_owner.json").write_text(
            json.dumps({"company": args.company}), encoding="utf-8")
    clear_shared_builds()

    from resume_content_improve_research import run_step4, run_step5

    started = time.time()
    if args.build_only or args.refilter:
        mode = "--build-only" if args.build_only else "--refilter"
        print(f"[runner] {args.company}: {mode} -> step 4 skipped, rebuilding from saved components")
        step4_rc = 0
    else:
        pre_step4_state = _state_path("components_v2", args.company).read_text(encoding="utf-8")
        step4_rc = run_step4.run_pipeline(
            limit=args.limit, jobs=args.jobs, force=args.force,
            no_tailor=args.no_tailor, no_domain_filter=args.no_domain_filter,
            loose_filter=args.loose_filter)
        # Checkpoint step-4 output immediately: a kill during step 5 must not
        # lose the (expensive) LLM component work.
        slot = OUTPUT_V2 / "components_v2.json"
        if slot.exists():
            shutil.copy2(slot, _state_path("components_v2", args.company))
            # --jobs guard: step 4 keeps prior results only for SELECTED jobs, so a
            # targeted run would silently drop the company's other gated_ok records
            # from its save. Re-attach every gated_ok record that existed before the
            # run and is missing from the checkpoint (restores cost nothing; their
            # LLM work is already paid for).
            try:
                checkpoint = json.loads(
                    _state_path("components_v2", args.company).read_text(encoding="utf-8"))
                pre_records = json.loads(pre_step4_state)
                have = {str(r.get("job_url") or "") for r in checkpoint}
                rescued = [r for r in pre_records
                           if str(r.get("job_url") or "") not in have
                           and r.get("status") == "gated_ok"]
                if rescued:
                    checkpoint.extend(rescued)
                    merged = json.dumps(checkpoint, indent=2, ensure_ascii=False)
                    _state_path("components_v2", args.company).write_text(merged, encoding="utf-8")
                    slot.write_text(merged, encoding="utf-8")
                    print(f"[runner] {args.company}: re-attached {len(rescued)} gated_ok "
                          f"record(s) outside the --jobs selection")
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[runner] {args.company}: --jobs guard skipped ({exc})")
            (STATE_DIR / "slot_owner.json").write_text(
                json.dumps({"company": args.company}), encoding="utf-8")
    # Run step 5 even when some jobs parked: it skips non-gated_ok records
    # internally, so the verified ones still get their PDFs built.
    step5_rc = run_step5.main()
    snapshot_state(args.company)
    write_resume_map(args.company)
    elapsed = time.time() - started

    print(f"\n[runner] {args.company}: step4 rc={step4_rc}, step5 rc={step5_rc} in {elapsed:.0f}s")
    return 0 if (step4_rc == 0 and step5_rc == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
