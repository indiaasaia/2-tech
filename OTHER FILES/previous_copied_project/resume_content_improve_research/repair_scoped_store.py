"""Repair components_v2.json / reports after a --jobs-scoped step-4 run.

main.py assumes step 4 always starts from a prior store; a scoped run against
an externally added job (add_external_job.py) wipes that store down to the
scoped record. This tool re-attaches the orphaned records from the surviving
output reports and regenerates shortlist.json so the manifest tools see the
full store again.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from resume_content_improve_research import config


def main() -> int:
    comps_path = config.OUTPUT_DIR / "components_v2.json"
    records = json.loads(comps_path.read_text(encoding="utf-8"))
    by_url = {str(r.get("job_url") or ""): r for r in records}
    print(f"components store: {len(records)} record(s)")

    report = json.loads(config.REPORT_PATH.read_text(encoding="utf-8"))
    restored, missing_report = 0, 0
    for res in report.get("results", []):
        url = str(res.get("job_url") or "")
        if url and url not in by_url:
            by_url[url] = {
                "job_url": url,
                "title": res.get("title", ""),
                "company": res.get("company", ""),
                "status": "gated_ok",
                "analysis": res.get("analysis") or {},
                "components": res.get("components") or {},
                "tailoring": res.get("tailoring") or {},
                "error": "",
            }
            restored += 1
    if restored:
        comps_path.write_text(json.dumps(list(by_url.values()), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"components store rebuilt: {len(by_url)} record(s), {restored} restored from resume_report.json")

    letters_path = config.LETTERS_REPORT_PATH
    missing_letters = 0
    if letters_path.exists():
        letters = json.loads(letters_path.read_text(encoding="utf-8"))
        have = {str(r.get("job_url") or "") for r in letters.get("results", [])}
        missing_letters = len([u for u in by_url if u not in have])
        print(f"letters report: {len(letters.get('results', []))} result(s), {missing_letters} store record(s) without a letter result")
    else:
        print("letters report missing entirely")

    bundles = json.loads(config.BUNDLES_PATH.read_text(encoding="utf-8"))
    print(f"bundles manifest: {bundles.get('total')} bundle(s), {bundles.get('complete')} complete")
    if missing_letters or restored:
        print("[REPAIR] re-run the relevant step (5/6) without a --jobs scope to rebuild the full reports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
