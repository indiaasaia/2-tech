from contact_discovery.validation import is_plausible_name, is_valid_email


def test_valid_emails():
    assert is_valid_email("hr@company.com")
    assert is_valid_email("jane.smith+tag@company.co.uk")
    assert is_valid_email("founder@startup-berlin.de")


def test_invalid_emails():
    assert not is_valid_email("")
    assert not is_valid_email("not-an-email")
    assert not is_valid_email("jane@ company.com")   # whitespace
    assert not is_valid_email("a@b@c.com")            # two @
    assert not is_valid_email("jane@nope")            # no TLD
    assert not is_valid_email("jane.smith|company.com")


def test_plausible_names():
    assert is_plausible_name("Jane Smith")
    assert is_plausible_name("Recruiting Team")
    assert is_plausible_name("CTO")
    assert not is_plausible_name("")
    assert not is_plausible_name("n/a")
    assert not is_plausible_name("---")
