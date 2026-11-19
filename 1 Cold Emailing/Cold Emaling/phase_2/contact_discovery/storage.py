"""CSV persistence for Phase 2 — the source of truth.

Three files, all behind a thin API so they can be swapped for a database
later without touching the loop:

- companies CSV (Phase 1 output)  — the input list, read-only here.
- contacts CSV                    — one row per discovered email.
- outcomes CSV                    — one row per processed company; doubles
  as the campaign progress tracker (companies present here are done and
  are skipped on rerun).
"""
from __future__ import annotations

import csv
from pathlib import Path

CONTACT_COLUMNS = [
    "company_name", "website", "contact_name", "contact_email",
    "iteration", "discovered_at",
]

OUTCOME_COLUMNS = [
    "company_name", "website", "status", "contacts_found",
    "iterations_run", "completed_at",
]


def _read_csv(path: str | Path) -> list[dict]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    rows: list[dict] = []
    # utf-8-sig tolerates the BOM that Excel and other tools prepend.
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        for row in reader:
            rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def _write_csv(path: str | Path, columns: list[str], records: list[dict]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            row = {col: "" for col in columns}
            for col in columns:
                value = record.get(col)
                row[col] = "" if value is None else str(value)
            writer.writerow(row)


# --- Companies (input, read-only) ---

def load_companies(path: str | Path) -> list[dict]:
    """Load the Phase 1 company list. Returns raw rows; never empty."""
    return _read_csv(path)


# --- Contacts ---

def load_contacts(path: str | Path) -> list[dict]:
    rows = _read_csv(path)
    for row in rows:
        try:
            row["iteration"] = int(row.get("iteration") or 0)
        except ValueError:
            row["iteration"] = 0
    return rows


def write_contacts(path: str | Path, records: list[dict]) -> None:
    _write_csv(path, CONTACT_COLUMNS, records)


# --- Outcomes (progress tracker) ---

def load_outcomes(path: str | Path) -> list[dict]:
    rows = _read_csv(path)
    for row in rows:
        for col in ("contacts_found", "iterations_run"):
            try:
                row[col] = int(row.get(col) or 0)
            except ValueError:
                row[col] = 0
    return rows


def write_outcomes(path: str | Path, records: list[dict]) -> None:
    _write_csv(path, OUTCOME_COLUMNS, records)
