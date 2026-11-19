import csv

from contact_discovery.config import Config
from contact_discovery.discovery import run_contact_discovery
from contact_discovery.parsing import SENTINEL_NO_NEW, SENTINEL_NO_PUBLIC
from contact_discovery.storage import load_contacts, load_outcomes


class ScriptedClient:
    """Returns pre-scripted raw texts, in order; records every call."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def discover(self, system_instruction, user_content, temperature=0.2):
        self.calls.append((system_instruction, user_content))
        if not self._responses:
            return SENTINEL_NO_NEW
        return self._responses.pop(0)


class FailingClient:
    def discover(self, system_instruction, user_content, temperature=0.2):
        raise RuntimeError("boom")


def _company(name, website=None):
    return {"company_name": name, "website": website or f"https://{name.lower().replace(' ', '')}.de"}


def _write_companies(path, companies):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["company_name", "website"])
        writer.writeheader()
        for company in companies:
            writer.writerow(company)


def _config(tmp_path, **overrides):
    defaults = dict(
        api_key="",
        model="gemini-3.7-flash",
        temperature=0.2,
        max_iterations=3,
        limit=None,
        companies_path=str(tmp_path / "companies.csv"),
        csv_path=str(tmp_path / "contacts.csv"),
        outcomes_path=str(tmp_path / "outcomes.csv"),
        prompt_path=str(tmp_path / "prompt.md"),
        repeat_prompt_path=str(tmp_path / "repeat.md"),
    )
    defaults.update(overrides)
    (tmp_path / "prompt.md").write_text("Main prompt for {{COMPANY_NAME}}", encoding="utf-8")
    (tmp_path / "repeat.md").write_text(
        "Repeat prompt for {{COMPANY_NAME}}\n{{PREVIOUS_EMAILS}}", encoding="utf-8"
    )
    return Config(**defaults)


def test_full_three_iteration_arc(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    client = ScriptedClient(
        [
            "HR Team | hr@acme.de\nRecruiting Team | recruiting@acme.de",
            "CTO | cto@acme.de",
            SENTINEL_NO_NEW,
        ]
    )
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["companies_processed"] == 1
    assert result["contacts_found"] == 3
    assert len(client.calls) == 3

    contacts = load_contacts(tmp_path / "contacts.csv")
    assert len(contacts) == 3
    assert {c["contact_email"] for c in contacts} == {"hr@acme.de", "recruiting@acme.de", "cto@acme.de"}
    assert {c["iteration"] for c in contacts} == {1, 2}

    outcomes = load_outcomes(tmp_path / "outcomes.csv")
    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "CONTACTS_FOUND"
    assert outcomes[0]["contacts_found"] == 3
    assert outcomes[0]["iterations_run"] == 3


def test_stops_early_on_no_new_sentinel(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    client = ScriptedClient(
        [
            "HR Team | hr@acme.de",
            SENTINEL_NO_NEW,
        ]
    )
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["contacts_found"] == 1
    assert len(client.calls) == 2
    outcomes = load_outcomes(tmp_path / "outcomes.csv")
    assert outcomes[0]["iterations_run"] == 2
    assert outcomes[0]["status"] == "CONTACTS_FOUND"


def test_stops_early_when_iteration_returns_nothing_new(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    client = ScriptedClient(
        [
            "HR Team | hr@acme.de",
            " ",  # empty response counts as nothing new
        ]
    )
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["contacts_found"] == 1
    assert len(client.calls) == 2


def test_no_public_email_outcome(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    client = ScriptedClient([SENTINEL_NO_PUBLIC])
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["contacts_found"] == 0
    assert len(client.calls) == 1
    outcomes = load_outcomes(tmp_path / "outcomes.csv")
    assert outcomes[0]["status"] == "NO_PUBLIC_EMAIL_FOUND"
    assert outcomes[0]["contacts_found"] == 0
    assert load_contacts(tmp_path / "contacts.csv") == []


def test_error_outcome_when_all_iterations_fail(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    config = _config(tmp_path, max_iterations=2)
    result = run_contact_discovery(FailingClient(), config)
    assert result["contacts_found"] == 0
    outcomes = load_outcomes(tmp_path / "outcomes.csv")
    assert outcomes[0]["status"] == "ERROR"
    assert outcomes[0]["iterations_run"] == 2


def test_error_iteration_recovers_in_next(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    client = ScriptedClient(
        [
            "HR Team | hr@acme.de",
            "CTO | cto@acme.de",  # iteration 3; iteration 2 raised before consuming
        ]
    )
    # Make exactly the 2nd call fail.
    original = client.discover
    failed = False

    def flaky(system_instruction, user_content, temperature=0.2):
        nonlocal failed
        if len(client.calls) == 1 and not failed:
            failed = True
            raise RuntimeError("boom")
        return original(system_instruction, user_content, temperature)

    client.discover = flaky
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["contacts_found"] == 2
    assert load_outcomes(tmp_path / "outcomes.csv")[0]["status"] == "CONTACTS_FOUND"


def test_resume_skips_completed_companies(tmp_path):
    from contact_discovery.storage import write_outcomes

    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH"), _company("Beta GmbH")])
    write_outcomes(
        tmp_path / "outcomes.csv",
        [{
            "company_name": "Acme GmbH",
            "website": "https://acme.de",
            "status": "CONTACTS_FOUND",
            "contacts_found": 2,
            "iterations_run": 2,
            "completed_at": "2026-08-18T10:00:00+00:00",
        }],
    )
    client = ScriptedClient(["HR Team | hr@beta.de", SENTINEL_NO_NEW])
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["companies_processed"] == 1
    assert result["companies_skipped"] == 1
    assert len(client.calls) == 2
    outcomes = load_outcomes(tmp_path / "outcomes.csv")
    assert {o["company_name"] for o in outcomes} == {"Acme GmbH", "Beta GmbH"}


def test_limit_restricts_processing(tmp_path):
    _write_companies(
        tmp_path / "companies.csv",
        [_company("A GmbH"), _company("B GmbH"), _company("C GmbH")],
    )
    client = ScriptedClient(
        [
            "HR | hr@a.de",
            SENTINEL_NO_NEW,
            "HR | hr@b.de",
            SENTINEL_NO_NEW,
        ]
    )
    result = run_contact_discovery(client, _config(tmp_path, limit=2))
    assert result["companies_processed"] == 2
    assert result["companies_skipped"] == 1  # C GmbH left for a later session
    assert len(client.calls) == 4


def test_dedup_across_iterations_case_insensitive(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    client = ScriptedClient(
        [
            "HR Team | hr@acme.de\nCTO | cto@acme.de",
            "HR Team | HR@ACME.DE\nFounder | founder@acme.de",
            SENTINEL_NO_NEW,
        ]
    )
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["contacts_found"] == 3
    contacts = load_contacts(tmp_path / "contacts.csv")
    assert {c["contact_email"] for c in contacts} == {"hr@acme.de", "cto@acme.de", "founder@acme.de"}
    # The duplicate HR row was dropped entirely (only the iteration-1 row kept).
    assert sum(1 for c in contacts if c["contact_email"] == "hr@acme.de") == 1


def test_prompt_selection_and_exclusion_list(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    client = ScriptedClient(["HR Team | hr@acme.de", "CTO | cto@acme.de", SENTINEL_NO_NEW])
    run_contact_discovery(client, _config(tmp_path))

    iter1_instruction, _ = client.calls[0]
    assert "Main prompt" in iter1_instruction
    assert "Acme GmbH" in iter1_instruction

    iter2_instruction, _ = client.calls[1]
    assert "Repeat prompt" in iter2_instruction
    assert "hr@acme.de" in iter2_instruction  # exclusion list carries forward

    iter3_instruction, _ = client.calls[2]
    assert "hr@acme.de" in iter3_instruction
    assert "cto@acme.de" in iter3_instruction


def test_max_iterations_one(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    client = ScriptedClient(["HR Team | hr@acme.de"])
    result = run_contact_discovery(client, _config(tmp_path, max_iterations=1))
    assert result["contacts_found"] == 1
    assert len(client.calls) == 1
    outcomes = load_outcomes(tmp_path / "outcomes.csv")
    assert outcomes[0]["iterations_run"] == 1
    assert outcomes[0]["status"] == "CONTACTS_FOUND"


def test_empty_iteration_one_continues_to_next(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    client = ScriptedClient(
        [
            "",  # empty output on iteration 1: keep trying
            "Recruiting Team | recruiting@acme.de",
            SENTINEL_NO_NEW,
        ]
    )
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["contacts_found"] == 1
    assert len(client.calls) == 3
    assert load_outcomes(tmp_path / "outcomes.csv")[0]["iterations_run"] == 3


def test_error_outcome_is_retried_on_next_run(tmp_path):
    """ERROR companies are not treated as done — a later run retries them."""
    from contact_discovery.storage import write_outcomes

    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    write_outcomes(
        tmp_path / "outcomes.csv",
        [{
            "company_name": "Acme GmbH",
            "website": "https://acme.de",
            "status": "ERROR",
            "contacts_found": 0,
            "iterations_run": 3,
            "completed_at": "2026-08-18T10:00:00+00:00",
        }],
    )
    client = ScriptedClient(["HR Team | hr@acme.de", SENTINEL_NO_NEW])
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["companies_processed"] == 1  # retried despite the ERROR outcome
    assert result["contacts_found"] == 1
    outcomes = load_outcomes(tmp_path / "outcomes.csv")
    assert outcomes[-1]["status"] == "CONTACTS_FOUND"


def test_retry_replaces_previous_error_outcome(tmp_path):
    """A retried company's outcome replaces its old row, never duplicates."""
    from contact_discovery.storage import write_outcomes

    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    write_outcomes(
        tmp_path / "outcomes.csv",
        [{
            "company_name": "Acme GmbH",
            "website": "https://acme.de",
            "status": "ERROR",
            "contacts_found": 0,
            "iterations_run": 3,
            "completed_at": "2026-08-18T10:00:00+00:00",
        }],
    )
    client = ScriptedClient(["HR Team | hr@acme.de", SENTINEL_NO_NEW])
    run_contact_discovery(client, _config(tmp_path))
    outcomes = load_outcomes(tmp_path / "outcomes.csv")
    assert len(outcomes) == 1  # replaced, not duplicated
    assert outcomes[0]["status"] == "CONTACTS_FOUND"


def test_max_iterations_zero_raises(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    try:
        run_contact_discovery(ScriptedClient([]), _config(tmp_path, max_iterations=0))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for max_iterations=0")


def test_reprocess_after_crash_does_not_duplicate_contacts(tmp_path):
    """Contacts already on disk (outcome write crashed) must not be re-stored."""
    from contact_discovery.storage import write_contacts

    _write_companies(tmp_path / "companies.csv", [_company("Acme GmbH")])
    write_contacts(
        tmp_path / "contacts.csv",
        [{
            "company_name": "Acme GmbH",
            "website": "https://acme.de",
            "contact_name": "HR Team",
            "contact_email": "hr@acme.de",
            "iteration": 1,
            "discovered_at": "2026-08-18T00:00:00+00:00",
        }],
    )
    # outcomes.csv missing -> company is reprocessed, same email found again.
    client = ScriptedClient(["HR Team | hr@acme.de", SENTINEL_NO_NEW])
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["contacts_found"] == 0  # nothing NEW stored
    contacts = load_contacts(tmp_path / "contacts.csv")
    assert len(contacts) == 1  # still exactly one row for hr@acme.de


def test_multiple_companies_write_full_tracker(tmp_path):
    _write_companies(tmp_path / "companies.csv", [_company("A GmbH"), _company("B GmbH")])
    client = ScriptedClient(
        [
            "HR | hr@a.de",
            SENTINEL_NO_NEW,
            SENTINEL_NO_PUBLIC,
        ]
    )
    result = run_contact_discovery(client, _config(tmp_path))
    assert result["companies_processed"] == 2
    assert result["contacts_found"] == 1
    outcomes = load_outcomes(tmp_path / "outcomes.csv")
    assert {o["company_name"] for o in outcomes} == {"A GmbH", "B GmbH"}
    statuses = {o["company_name"]: o["status"] for o in outcomes}
    assert statuses["A GmbH"] == "CONTACTS_FOUND"
    assert statuses["B GmbH"] == "NO_PUBLIC_EMAIL_FOUND"
