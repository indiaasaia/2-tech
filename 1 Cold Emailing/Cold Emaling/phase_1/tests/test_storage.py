from startup_discovery.storage import COLUMNS, load_records, write_records


def test_round_trip(tmp_path):
    path = tmp_path / "companies.csv"
    records = [
        {
            "company_name": "Acme",
            "website": "https://acme.com",
            "sources": ["https://a.com", "https://b.com"],
            "hiring_probability_score": 80,
            "discovery_batch": 1,
            "discovered_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    write_records(path, records)
    loaded = load_records(path)
    assert len(loaded) == 1
    assert loaded[0]["company_name"] == "Acme"
    assert loaded[0]["website"] == "https://acme.com"
    assert loaded[0]["hiring_probability_score"] == 80
    assert loaded[0]["sources"] == ["https://a.com", "https://b.com"]
    assert loaded[0]["discovery_batch"] == 1


def test_missing_file_returns_empty(tmp_path):
    assert load_records(tmp_path / "nope.csv") == []


def test_write_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "companies.csv"
    write_records(path, [])
    assert path.exists()
    assert load_records(path) == []


def test_all_columns_present_after_round_trip(tmp_path):
    path = tmp_path / "companies.csv"
    record = {col: f"v{i}" for i, col in enumerate(COLUMNS)}
    record["sources"] = []
    write_records(path, [record])
    loaded = load_records(path)[0]
    assert set(loaded.keys()) == set(COLUMNS)


def test_load_tolerates_bom(tmp_path):
    # Excel and other tools prepend a UTF-8 BOM; it must not corrupt the
    # first column name.
    path = tmp_path / "bom.csv"
    path.write_bytes(
        b"\xef\xbb\xbfcompany_name,website\nM\xc3\xbcnchen GmbH,https://muenchen.de\n"
    )
    records = load_records(path)
    assert records[0]["company_name"] == "München GmbH"
    assert records[0]["website"] == "https://muenchen.de"


def test_unicode_round_trip(tmp_path):
    path = tmp_path / "u.csv"
    write_records(path, [{"company_name": "München GmbH", "website": "https://muenchen.de", "sources": []}])
    records = load_records(path)
    assert records[0]["company_name"] == "München GmbH"
    assert records[0]["website"] == "https://muenchen.de"


def test_append_style_usage_preserves_existing(tmp_path):
    path = tmp_path / "companies.csv"
    write_records(path, [{"company_name": "One", "website": "https://one.com"}])
    records = load_records(path)
    records.append({"company_name": "Two", "website": "https://two.com"})
    write_records(path, records)
    loaded = load_records(path)
    assert [r["company_name"] for r in loaded] == ["One", "Two"]
