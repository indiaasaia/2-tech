import json

import pytest

from startup_discovery.validation import (
    ParseError,
    extract_json,
    parse_response,
    validate_candidate,
)


def _valid_candidate(**overrides):
    candidate = {
        "company_name": "Acme GmbH",
        "website": "https://acme.com",
        "location": "Berlin, Germany",
        "company_size": "11-50",
        "startup_stage": "Series A",
        "technical_focus": "AI/ML",
        "relevant_roles": "Working Student",
        "english_hiring_evidence": "Careers page: English is company language.",
        "student_intern_evidence": "Listed internships on careers page.",
        "current_hiring_evidence": "Open positions.",
        "cold_outreach_potential": "Small team.",
        "hiring_probability_score": 72,
        "priority": "High Priority",
        "why_target": "Good fit.",
        "sources": ["https://acme.com/careers"],
    }
    candidate.update(overrides)
    return candidate


def test_valid_candidate_passes():
    ok, problems = validate_candidate(_valid_candidate(), min_score=55)
    assert ok
    assert problems == []


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"company_name": ""}, "company_name"),
        ({"website": "not a url"}, "website"),
        ({"website": "https://"}, "website"),
        ({"location": ""}, "location"),
        ({"english_hiring_evidence": ""}, "english_hiring_evidence"),
        ({"english_hiring_evidence": "Not verified."}, "english_hiring_evidence"),
        ({"student_intern_evidence": "n/a"}, "student_intern_evidence"),
        ({"hiring_probability_score": 40}, "below minimum"),
        ({"hiring_probability_score": "high"}, "not an integer"),
        ({"hiring_probability_score": 150}, "out of range"),
        ({"sources": []}, "sources"),
    ],
)
def test_invalid_candidates_rejected(override, fragment):
    ok, problems = validate_candidate(_valid_candidate(**override), min_score=55)
    assert not ok
    assert any(fragment in p for p in problems)


def test_score_equal_to_minimum_passes():
    ok, _ = validate_candidate(_valid_candidate(hiring_probability_score=55), min_score=55)
    assert ok


def test_extract_json_handles_markdown_fences_and_surrounding_text():
    raw = 'Sure! Here is the JSON:\n```json\n{"companies": []}\n```\nHope this helps.'
    assert extract_json(raw) == {"companies": []}


def test_extract_json_rejects_non_json():
    with pytest.raises(ParseError):
        extract_json("this is not json at all")


def test_extract_json_rejects_empty_output():
    with pytest.raises(ParseError):
        extract_json("   ")


def test_parse_response_splits_accepted_and_rejected():
    raw = json.dumps(
        {
            "companies": [
                _valid_candidate(),
                _valid_candidate(company_name="", hiring_probability_score=30),
            ],
            "notes": "one rejected",
        }
    )
    accepted, rejected, notes = parse_response(raw, min_score=55)
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert notes == "one rejected"


def test_parse_response_requires_companies_list():
    with pytest.raises(ParseError):
        parse_response('{"companies": "nope"}', min_score=55)


def test_parse_response_empty_list_allowed():
    accepted, rejected, notes = parse_response('{"companies": [], "notes": "nothing new"}', min_score=55)
    assert accepted == []
    assert rejected == []
    assert notes == "nothing new"


def test_parse_response_rejects_non_dict_entries():
    raw = json.dumps({"companies": [_valid_candidate(), "oops", 7]})
    accepted, rejected, notes = parse_response(raw, min_score=55)
    assert len(accepted) == 1
    assert len(rejected) == 2
    assert all(problems == ["entry is not an object"] for _, problems in rejected)
