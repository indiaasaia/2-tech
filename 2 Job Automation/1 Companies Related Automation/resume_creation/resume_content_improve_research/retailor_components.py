"""Re-tailor existing components_v2.json records in place (no LLM calls).

Applies generation/tailoring.tailor_components to every gated_ok record that has
no tailoring report yet, re-runs the G2/G3 pre-build gates on the tailored
intent, and reverts any job whose tailored output trips a gate (reported
visibly; the raw generated components stay shippable).

Run:  python resume_content_improve_research/retailor_components.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from resume_content_improve_research import config
from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.claimable_set import build_claimable_set
from resume_content_improve_research.generation.tailoring import tailor_components
from resume_content_improve_research.run_step4 import intent_text_for
from resume_content_improve_research.verification.gates import run_prebuild_gates

config.ensure_utf8_stdout()

COMPONENTS_KEY = "components_v2"


def main() -> int:
    parser = argparse.ArgumentParser(description="re-tailor existing v2 components in place")
    parser.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    args = parser.parse_args()

    kb = kb_loader.load_kb()
    licensed_digits = kb_loader.licensed_digits(kb)
    path = config.OUTPUT_DIR / f"{COMPONENTS_KEY}.json"
    if not path.exists():
        print(f"[V2] not found: {path} — run step 4 first")
        return 1
    records = json.loads(path.read_text(encoding="utf-8"))

    backup = path.with_suffix(".pre_tailor.bak.json")
    if not args.dry_run:
        shutil.copy2(path, backup)
        print(f"[V2] backup -> {backup}")

    tailored_n = 0
    reverted_n = 0
    skipped_n = 0
    for record in records:
        if record.get("status") != "gated_ok" or not record.get("components"):
            continue
        if record.get("tailoring"):
            skipped_n += 1
            continue
        analysis = record.get("analysis") or {}
        cset = build_claimable_set(analysis, kb)
        tailored, report = tailor_components(record["components"], analysis, cset, kb)
        intent = intent_text_for(tailored)
        findings = [f for r in run_prebuild_gates(intent, tailored["experiences"], cset, licensed_digits)
                    for f in r.findings]
        report["gate_findings"] = findings
        title = str(record.get("title") or "?")[:50]
        if findings:
            reverted_n += 1
            print(f"  {title:50} -> REVERTED ({len(findings)} gate finding(s): {findings[0][:70]})")
        else:
            if not args.dry_run:
                record["components"] = tailored
            record["tailoring"] = report
            tailored_n += 1
            print(f"  {title:50} -> {report['summary']}")

    if not args.dry_run:
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[V2] retailor: {tailored_n} tailored, {reverted_n} reverted, {skipped_n} already tailored"
          + (" (dry run — nothing written)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
