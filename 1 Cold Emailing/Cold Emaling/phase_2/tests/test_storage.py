import csv

from contact_discovery.storage import (
    load_companies,
    load_contacts,
    load_outcomes,
    write_contacts,
    write_outcomes,
)


def test_missing_files_load_empty(tmp_path):
    assert load_companies(tmp_path / "nope.csv") == []
    assert load_contacts(tmp_path / "nope.csv") == []
    assert load_outcomes(tmp_path / "nope.csv") == []


def test_contacts_round_trip(tmp_path):
    path = tmp_path / "contacts.csv"
    records = [
        {
            "company_name": "Acme GmbH",
            "website": "https://acme.de",
            "contact_name": "HR Team",
            "contact_email": "hr@acme.de",
            "iteration": 1,
            "discovered_at": "2026-08-18T10:00:00+00:00",
        },
        {
            "company_name": "Acme GmbH",
            "website": "https://acme.de",
            "contact_name": "CTO",
            "contact_email": "cto@acme.de",
            "iteration": 2,
            "discovered_at": "2026-08-18T10:01:00+00:00",
        },
    ]
    write_contacts(path, records)
    loaded = load_contacts(path)
    assert len(loaded) == 2
    assert loaded[0]["contact_email"] == "hr@acme.de"
    assert loaded[0]["iteration"] == 1
    assert loaded[1]["iteration"] == 2
    # ints come back as ints
    assert isinstance(loaded[0]["iteration"], int)


def test_outcomes_round_trip(tmp_path):
    path = tmp_path / "outcomes.csv"
    records = [
        {
            "company_name": "Acme GmbH",
            "website": "https://acme.de",
            "status": "CONTACTS_FOUND",
            "contacts_found": 3,
            "iterations_run": 3,
            "completed_at": "2026-08-18T10:00:00+00:00",
        },
        {
            "company_name": "Beta GmbH",
            "website": "https://beta.de",
            "status": "NO_PUBLIC_EMAIL_FOUND",
            "contacts_found": 0,
            "iterations_run": 1,
            "completed_at": "2026-08-18T10:05:00+00:00",
        },
    ]
    write_outcomes(path, records)
    loaded = load_outcomes(path)
    assert len(loaded) == 2
    assert loaded[0]["status"] == "CONTACTS_FOUND"
    assert loaded[0]["contacts_found"] == 3
    assert isinstance(loaded[1]["iterations_run"], int)


def test_write_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "contacts.csv"
    write_contacts(path, [])
    assert path.exists()
    assert load_contacts(path) == []


def test_load_companies_returns_rows(tmp_path):
    path = tmp_path / "companies.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["company_name", "website", "priority"])
        writer.writeheader()
        writer.writerow({"company_name": "Acme GmbH", "website": "https://acme.de", "priority": "High"})
    rows = load_companies(path)
    assert rows[0]["company_name"] == "Acme GmbH"
    assert rows[0]["priority"] == "High"
