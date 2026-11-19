"""Repair stale absolute resume paths in job_resume_map_*.csv files.

The workspace folder was renamed at some point (BOSCH FETCHER ->
2 Job Automation/Companies Related Automation), so resume_pdf paths recorded
by earlier hub runs point at the old tree. Rewrite the prefix in place,
verify every repaired path exists, and print an audit table.

Run:
    python tools/fix_resume_paths.py            # repair + verify + report
"""
import csv
from pathlib import Path

STATE = Path(__file__).resolve().parents[1] / "program_files" / "output_v2" / "state"
OLD = "E:\\WorkSpace\\2 Tech\\BOSCH FETCHER\\"
NEW = "E:\\WorkSpace\\2 Tech\\2 Job Automation\\Companies Related Automation\\"

MAPS = [
    "job_resume_map_mercedes.csv",
    "job_resume_map_bosch.csv",
    "job_resume_map_bmw.csv",
    "job_resume_map_sap.csv",
    "job_resume_map_infineon.csv",
]

# step-5 report JSONs hold a "pdf" (and sometimes "docx") path per record
REPORTS = [
    "resume_report_bosch.json",
    "resume_report.json",
]


def main() -> int:
    if not STATE.exists():
        print(f"state dir not found: {STATE}")
        return 1
    any_issue = False
    for name in MAPS:
        path = STATE / name
        if not path.exists():
            print(f"{name}: absent (skipped)")
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        fixed = missing = 0
        for row in rows:
            pdf = row.get("resume_pdf", "")
            if OLD in pdf:
                row["resume_pdf"] = pdf.replace(OLD, NEW)
                fixed += 1
            if row.get("resume_pdf") and not Path(row["resume_pdf"]).is_file():
                missing += 1
        if fixed:
            with path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        print(f"{name}: {len(rows)} rows | repaired {fixed} | missing-after-fix {missing}")
        if missing:
            any_issue = True

    import json

    for name in REPORTS:
        path = STATE / name
        if not path.exists():
            print(f"{name}: absent (skipped)")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        fixed = missing = 0
        for record in data.get("results", []):
            for key in ("pdf", "docx"):
                val = str(record.get(key) or "")
                if OLD in val:
                    record[key] = val.replace(OLD, NEW)
                    fixed += 1
                # per-company snapshot dirs hold the real artifacts
                generic = str(STATE.parent) + "\\resume\\"
                snapshot = str(STATE.parent) + "\\resume_bosch\\"
                if key == "pdf" and generic in val:
                    record[key] = val.replace(generic, snapshot)
                    fixed += 1
                if key == "docx" and generic in val:
                    record[key] = val.replace(generic, snapshot)
                    fixed += 1
            chk = str(record.get("pdf") or "")
            if chk and not Path(chk).is_file():
                missing += 1
        if fixed:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: repaired {fixed} | missing-after-fix {missing}")
        if missing:
            any_issue = True
    return 1 if any_issue else 0


if __name__ == "__main__":
    raise SystemExit(main())
