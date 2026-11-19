from startup_discovery.dedup import filter_new, is_duplicate, normalize_domain, normalize_name


def test_normalize_name_strips_legal_suffixes():
    assert normalize_name("Acme GmbH") == "acme"
    assert normalize_name("Acme Inc.") == "acme"
    assert normalize_name("  ACME   AG  ") == "acme"
    assert normalize_name("Acme Technologies GmbH & Co. KG") == "acme technologies"


def test_normalize_name_keeps_distinct_names():
    assert normalize_name("Acme") != normalize_name("Acme 2")
    assert normalize_name("Alpha AI") != normalize_name("Beta AI")


def test_normalize_name_handles_umlauts_and_variants():
    # "München GmbH" vs the umlaut-dropped "Munchen" must dedupe.
    assert normalize_name("München GmbH") == "munchen"
    assert normalize_name("Munchen GmbH") == "munchen"
    assert normalize_name("München GmbH") == normalize_name("Munchen")
    assert normalize_name("Schöneberg AI") == normalize_name("Schoneberg AI")
    assert normalize_name("Müller & Söhne GmbH") == "muller sohne"


def test_normalize_domain():
    assert normalize_domain("https://www.Acme.com/") == "acme.com"
    assert normalize_domain("http://acme.com:8080/careers") == "acme.com"
    assert normalize_domain("acme.com") == "acme.com"
    assert normalize_domain("") == ""
    assert normalize_domain("not a url") == ""


def test_is_duplicate_by_name_and_domain():
    existing = {"company_name": "Acme GmbH", "website": "https://www.acme.com"}
    assert is_duplicate({"company_name": "acme", "website": "https://acme.de"}, existing)  # same name
    assert is_duplicate({"company_name": "Acme Technologies", "website": "https://acme.com"}, existing)  # same domain
    assert not is_duplicate({"company_name": "Other GmbH", "website": "https://other.com"}, existing)


def test_filter_new_dedupes_against_existing_and_within_batch():
    existing = [{"company_name": "Acme GmbH", "website": "https://acme.com"}]
    candidates = [
        {"company_name": "acme", "website": "https://acme.de"},          # dupe by name
        {"company_name": "Beta GmbH", "website": "https://beta.com"},    # new
        {"company_name": "BETA", "website": "https://beta.de"},          # dupe within batch
        {"company_name": "Gamma", "website": "https://gamma.com"},       # new
    ]
    new = filter_new(candidates, existing)
    assert [c["company_name"] for c in new] == ["Beta GmbH", "Gamma"]
