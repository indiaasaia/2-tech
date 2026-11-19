import json

from startup_discovery.config import Config
from startup_discovery.discovery import run_discovery
from startup_discovery.gemini_client import FakeGeminiClient
from startup_discovery.storage import load_records


class ScriptedClient:
    """Returns pre-scripted raw texts, in order; empty responses after exhaustion."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    def discover(self, system_instruction, user_content, temperature=0.2):
        self.calls += 1
        if not self._responses:
            return json.dumps({"companies": []})
        return self._responses.pop(0)


def _company(name, score=70, domain=None, **overrides):
    domain = domain or f"{name.lower().replace(' ', '')}.com"
    candidate = {
        "company_name": name,
        "website": f"https://www.{domain}",
        "location": "Berlin, Germany",
        "company_size": "11-50",
        "startup_stage": "Series A",
        "technical_focus": "AI/ML",
        "relevant_roles": "Working Student",
        "english_hiring_evidence": "English is the company language (careers page).",
        "student_intern_evidence": "Internships listed on careers page.",
        "current_hiring_evidence": "Open positions.",
        "cold_outreach_potential": "Small team.",
        "hiring_probability_score": score,
        "priority": "High Priority",
        "why_target": "Good fit.",
        "sources": [f"https://{domain}/careers"],
    }
    candidate.update(overrides)
    return candidate


def _response(*companies, notes=None):
    return json.dumps({"companies": list(companies), "notes": notes})


def _config(tmp_path, **overrides):
    defaults = dict(
        api_key="",
        model="gemini-3.7-flash",
        batch_size=5,
        total_cap=10,
        min_hiring_score=55,
        max_runs=10,
        empty_run_retries=1,
        temperature=0.2,
        csv_path=str(tmp_path / "companies.csv"),
        prompt_path=str(tmp_path / "prompt.md"),
        max_exclusion_entries=None,
    )
    defaults.update(overrides)
    (tmp_path / "prompt.md").write_text(
        "Research instructions for {target_count} companies, cap {total_cap}.",
        encoding="utf-8",
    )
    return Config(**defaults)


def test_loop_stores_until_cap_dedupes_and_validates(tmp_path, capsys):
    client = ScriptedClient(
        [
            _response(_company("Alpha"), _company("Beta"), _company("Gamma"), _company("Delta"), _company("Epsilon")),
            # 1 dupe by domain, 1 below threshold, 3 new
            _response(
                _company("Alpha Corp", domain="alpha.com"),  # dupe of Alpha
                _company("Zeta"),
                _company("Eta", score=30),                   # invalid: below minimum
                _company("Theta"),
                _company("Iota"),
            ),
            # 2 new, then duplicates to finish the cap
            _response(
                _company("Kappa"),
                _company("Lambda"),
                _company("Beta GmbH", domain="beta.com"),    # dupe
                _company("Gamma AG", domain="gamma.com"),    # dupe
                _company("Delta Inc", domain="delta.com"),   # dupe
            ),
        ]
    )
    config = _config(tmp_path)
    result = run_discovery(client, config)

    assert result["total_stored"] == 10
    assert result["runs"] == 3

    records = load_records(config.csv_path)
    assert len(records) == 10
    assert len({r["company_name"] for r in records}) == 10
    assert len({r["website"] for r in records}) == 10
    assert [r["discovery_batch"] for r in records].count(1) == 5
    assert [r["discovery_batch"] for r in records].count(2) == 3
    assert [r["discovery_batch"] for r in records].count(3) == 2
    assert all(r["hiring_probability_score"] >= 55 for r in records)
    assert all(r["discovered_at"] for r in records)

    out = capsys.readouterr().out
    assert "below minimum" in out  # the rejected candidate was logged


def test_loop_stops_after_repeated_empty_runs(tmp_path):
    client = ScriptedClient(
        [
            _response(_company("Alpha"), _company("Beta"), _company("Gamma"), _company("Delta"), _company("Epsilon")),
            _response(),  # empty
            _response(),  # empty again -> stop
        ]
    )
    config = _config(tmp_path, total_cap=50)
    result = run_discovery(client, config)
    assert result["total_stored"] == 5
    assert result["runs"] == 3


def test_loop_recovers_after_single_empty_run(tmp_path):
    client = ScriptedClient(
        [
            _response(_company("Alpha")),
            _response(),
            _response(_company("Beta")),
        ]
    )
    config = _config(tmp_path, total_cap=50, batch_size=1)
    result = run_discovery(client, config)
    assert result["total_stored"] == 2
    # runs 1 & 3 stored; runs 4-5 are empty (client exhausted) -> stop
    assert result["runs"] == 5


def test_unparseable_output_treated_as_empty_run(tmp_path):
    client = ScriptedClient(
        [
            _response(_company("Alpha")),
            "totally not json",
            _response(_company("Beta")),
        ]
    )
    config = _config(tmp_path, total_cap=50, batch_size=1)
    result = run_discovery(client, config)
    assert result["total_stored"] == 2
    # run 2 was unparseable; run 3 stored; runs 4-5 empty -> stop
    assert result["runs"] == 5


def test_max_runs_respected(tmp_path):
    client = ScriptedClient([_response(_company(f"Co {i}")) for i in range(20)])
    config = _config(tmp_path, total_cap=50, batch_size=1, max_runs=3)
    result = run_discovery(client, config)
    assert result["total_stored"] == 3
    assert result["runs"] == 3


def test_final_batch_truncated_to_cap(tmp_path):
    client = ScriptedClient([_response(_company("Alpha"), _company("Beta"), _company("Gamma"))])
    config = _config(tmp_path, total_cap=2, batch_size=5)
    result = run_discovery(client, config)
    assert result["total_stored"] == 2
    assert len(load_records(config.csv_path)) == 2


def test_api_error_counts_as_empty_run(tmp_path):
    class FailingClient:
        def discover(self, *args, **kwargs):
            raise RuntimeError("boom")

    config = _config(tmp_path, total_cap=50, batch_size=5, empty_run_retries=1)
    result = run_discovery(FailingClient(), config)
    assert result["total_stored"] == 0
    assert result["runs"] == 2  # error, error -> stop


def test_resumes_from_existing_csv(tmp_path):
    from startup_discovery.storage import write_records

    path = tmp_path / "companies.csv"
    write_records(path, [_company("Alpha")])
    client = ScriptedClient([_response(_company("Beta"), _company("Gamma"))])
    config = _config(tmp_path, total_cap=50, batch_size=5, max_runs=1)
    result = run_discovery(client, config)
    assert result["total_stored"] == 3
    names = [r["company_name"] for r in load_records(path)]
    assert names == ["Alpha", "Beta", "Gamma"]
    assert client.calls == 1


def test_batch_numbers_continue_across_sessions(tmp_path):
    from startup_discovery.storage import write_records

    path = tmp_path / "companies.csv"
    # Simulate a previous session that ran 3 batches (last batch number 3).
    write_records(path, [_company("Alpha", **{"discovery_batch": 3})])
    client = ScriptedClient(
        [
            _response(_company("Beta"), _company("Gamma")),
            _response(_company("Delta")),
        ]
    )
    config = _config(tmp_path, total_cap=50, batch_size=2)
    result = run_discovery(client, config)
    assert result["total_stored"] == 4
    batches = [r["discovery_batch"] for r in load_records(path)]
    assert sorted(batches) == [3, 4, 4, 5]  # continues after the previous session


def test_non_dict_company_entry_does_not_crash(tmp_path, capsys):
    raw = json.dumps({"companies": [_company("Alpha"), "not-a-dict", 42]})
    client = ScriptedClient([raw, _response(), _response()])
    config = _config(tmp_path, total_cap=50, batch_size=5)
    result = run_discovery(client, config)
    assert result["total_stored"] == 1  # only the valid company was stored
    out = capsys.readouterr().out
    assert "entry is not an object" in out  # logged, not crashed


def test_fake_client_serves_pool_and_injects_duplicates():
    pool = [_company(f"Co {i}", domain=f"co{i}.com") for i in range(7)]
    client = FakeGeminiClient(pool, batch_size=5)
    data1 = json.loads(client.discover("sys", "user"))
    data2 = json.loads(client.discover("sys", "user"))
    assert len(data1["companies"]) == 5
    assert len(data2["companies"]) == 2
    # second batch: first slot is a near-duplicate of the last served company
    assert data2["companies"][0]["website"] == data1["companies"][-1]["website"]
    assert data2["companies"][0]["company_name"] != data1["companies"][-1]["company_name"]
    assert data2["companies"][1]["website"] == "https://www.co6.com"
