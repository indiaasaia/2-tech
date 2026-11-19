from contact_discovery.parsing import (
    SENTINEL_NO_NEW,
    SENTINEL_NO_PUBLIC,
    dedupe_contacts,
    parse_contact_output,
)


def test_parses_name_email_lines():
    raw = "Jane Smith | jane.smith@company.com\nJohn Doe | john@company.com"
    result = parse_contact_output(raw)
    assert [(c.name, c.email) for c in result.contacts] == [
        ("Jane Smith", "jane.smith@company.com"),
        ("John Doe", "john@company.com"),
    ]
    assert result.sentinel is None
    assert result.problems == []


def test_parses_role_based_emails():
    raw = "Recruiting Team | recruiting@company.com\nHR Team | hr@company.com"
    result = parse_contact_output(raw)
    assert result.contacts[0].name == "Recruiting Team"
    assert result.contacts[0].email == "recruiting@company.com"


def test_detects_no_public_email_sentinel():
    result = parse_contact_output("NO_PUBLIC_EMAIL_FOUND")
    assert result.sentinel == SENTINEL_NO_PUBLIC
    assert result.contacts == []


def test_detects_no_new_public_email_sentinel():
    result = parse_contact_output("NO_NEW_PUBLIC_EMAIL_FOUND")
    assert result.sentinel == SENTINEL_NO_NEW
    assert result.contacts == []


def test_no_new_sentinel_not_confused_with_plain():
    # "NO_NEW_PUBLIC_EMAIL_FOUND" must be reported as NO_NEW, not NO_PUBLIC.
    result = parse_contact_output("NO_NEW_PUBLIC_EMAIL_FOUND")
    assert result.sentinel == SENTINEL_NO_NEW
    assert result.sentinel != SENTINEL_NO_PUBLIC


def test_deduplicates_case_insensitively():
    raw = "John@Company.com | john@company.com\nJohn Doe | JOHN@COMPANY.COM"
    result = parse_contact_output(raw)
    assert len(result.contacts) == 1
    assert result.contacts[0].email == "john@company.com"


def test_skips_markdown_fences():
    raw = (
        "```text\n"
        "Jane Smith | jane.smith@company.com\n"
        "```\n"
    )
    result = parse_contact_output(raw)
    assert len(result.contacts) == 1
    assert result.contacts[0].email == "jane.smith@company.com"
    assert not any("fence" in p for p in result.problems)


def test_skips_literal_header_line():
    raw = "Name | Email\nJane Smith | jane@company.com"
    result = parse_contact_output(raw)
    assert len(result.contacts) == 1
    assert result.contacts[0].name == "Jane Smith"


def test_skips_invalid_emails_and_prose():
    raw = (
        "Here are the results for the company:\n"
        "Jane Smith | jane.smith@company.com\n"
        "Bad | not-an-email\n"
        "Nope | jane@ company.com\n"
    )
    result = parse_contact_output(raw)
    assert len(result.contacts) == 1
    assert any("skipped line without '|'" in p for p in result.problems)
    assert any("invalid email" in p for p in result.problems)


def test_skips_empty_output():
    result = parse_contact_output("   ")
    assert result.contacts == []
    assert any("empty model output" in p for p in result.problems)


def test_dedupe_contacts_first_wins():
    from contact_discovery.parsing import Contact

    contacts = [
        Contact("HR", "hr@company.com"),
        Contact("HR Team", "HR@company.com"),
        Contact("CTO", "cto@company.com"),
    ]
    unique = dedupe_contacts(contacts)
    assert [c.email for c in unique] == ["hr@company.com", "cto@company.com"]
