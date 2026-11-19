"""CSV persistence — the application's source of truth.

One CSV file, one row per company. Simple and inspectable, behind a thin
API so it can be swapped for a database later without touching the loop.
"""
from __future__ import annotations

import csv
from pathlib import Path

COLUMNS = [
    "company_name", "website", "location", "company_size", "startup_stage",
    "technical_focus", "relevant_roles", "english_hiring_evidence",
    "student_intern_evidence", "current_hiring_evidence",
    "cold_outreach_potential", "hiring_probability_score", "priority",
    "why_target", "sources", "discovery_batch", "discovered_at",
]

_SOURCES_SEP = " || "


def load_records(path: str | Path) -> list[dict]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    records: list[dict] = []
    # utf-8-sig tolerates the BOM that Excel and other tools prepend.
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        for row in reader:
            record = {col: (row.get(col) or "").strip() for col in COLUMNS}
            sources = record.get("sources") or ""
            record["sources"] = [s.strip() for s in sources.split(_SOURCES_SEP) if s.strip()]
            try:
                record["hiring_probability_score"] = int(record["hiring_probability_score"] or 0)
            except ValueError:
                record["hiring_probability_score"] = 0
            try:
                record["discovery_batch"] = int(record.get("discovery_batch") or 0)
            except ValueError:
                record["discovery_batch"] = 0
            records.append(record)
    return records


def write_records(path: str | Path, records: list[dict]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for record in records:
            row = {col: "" for col in COLUMNS}
            for col in COLUMNS:
                value = record.get(col)
                if col == "sources" and isinstance(value, list):
                    row[col] = _SOURCES_SEP.join(str(s) for s in value)
                else:
                    row[col] = "" if value is None else str(value)
            writer.writerow(row)
