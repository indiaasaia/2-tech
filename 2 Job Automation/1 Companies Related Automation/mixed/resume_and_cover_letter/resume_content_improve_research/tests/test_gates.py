"""Unit tests for the deterministic gates (no LLM, no network)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research.generation.claimable_set import ClaimableSet
from resume_content_improve_research.verification.gates import (
    check_g2_claims,
    check_g3_text,
)


@pytest.fixture
def cset() -> ClaimableSet:
    return ClaimableSet(
        kb_skills=["python", "sql", "machine learning", "django"],
        jd_tools=["kubernetes", "tableau"],
        required=[],
        preferred=[],
        per_experience={"soham": ["python", "sql"]},
        per_project={"hft": ["python", "django"]},
    )


LICENSED_DIGITS = {"40", "24", "70", "2020", "2021", "2022", "2023", "2024", "2025"}


class TestG2TechTokens:
    def test_licensed_token_passes(self, cset):
        assert check_g2_claims("Built services with python and sql", cset, LICENSED_DIGITS) == []

    def test_unlicensed_token_flagged(self, cset):
        findings = check_g2_claims("strong expertise in rexx and gcp", cset, LICENSED_DIGITS)
        assert any("rexx" in f for f in findings)
        assert any("gcp" in f for f in findings)

    def test_mirrorable_tool_allowed_as_mention(self, cset):
        # kubernetes is mirrorable this job -> mentioning it is not a violation
        assert check_g2_claims("targeting kubernetes exposure", cset, LICENSED_DIGITS) == []


class TestG2DigitRule:
    def test_licensed_digit_passes(self, cset):
        assert check_g2_claims("achieved 70 accuracy in the cash segment", cset, LICENSED_DIGITS) == []

    def test_unlicensed_digit_flagged(self, cset):
        findings = check_g2_claims("improved latency by 35", cset, LICENSED_DIGITS)
        assert any("35" in f for f in findings)

    def test_spelled_out_percent_flagged(self, cset):
        findings = check_g2_claims("thirty percent improvement", cset, LICENSED_DIGITS)
        assert any("thirty percent" in f for f in findings)

    def test_percent_symbol_flagged(self, cset):
        findings = check_g2_claims("70% accuracy", cset, LICENSED_DIGITS)
        assert any("%" in f for f in findings)

    def test_year_dates_never_flagged(self, cset):
        assert check_g2_claims("Dec 2023 - Jan 2025", cset, LICENSED_DIGITS) == []

    @pytest.mark.parametrize("product", ["Microsoft 365", "MS 365", "Office 365", "Office365", "Dynamics 365"])
    def test_known_product_version_number_is_not_a_metric(self, cset, product):
        assert check_g2_claims(f"Experience with {product}", cset, LICENSED_DIGITS) == []

    def test_unrelated_365_metric_is_still_flagged(self, cset):
        findings = check_g2_claims("improved throughput by 365 units", cset, LICENSED_DIGITS)
        assert any("365" in finding for finding in findings)

    def test_unrelated_product_context_does_not_license_metric(self, cset):
        findings = check_g2_claims("Used Microsoft 365 and improved throughput by 365 units", cset, LICENSED_DIGITS)
        assert sum("365" in finding for finding in findings) == 1

    def test_work_schedule_exemption_uses_the_matching_occurrence(self, cset):
        assert check_g2_claims("2024 role, 20 hours per week", cset, LICENSED_DIGITS) == []
        findings = check_g2_claims("2024 role, 20 units per week", cset, LICENSED_DIGITS)
        assert any("20" in finding for finding in findings)
        assert not any("20" in finding for finding in check_g2_claims("8 hours/week", cset, LICENSED_DIGITS))

    def test_spelled_out_work_schedule_exemption_uses_its_span(self, cset):
        assert check_g2_claims("2024 role, twenty hours per week", cset, LICENSED_DIGITS) == []
        findings = check_g2_claims("2024 role, twenty units per week", cset, LICENSED_DIGITS)
        assert any("20" in finding for finding in findings)
        assert not any("20" in finding for finding in check_g2_claims("eight hours per week", cset, LICENSED_DIGITS))

    def test_product_suffix_must_be_attached_to_known_name(self, cset):
        findings = check_g2_claims("Microsoft solutions improved by 365 units", cset, LICENSED_DIGITS)
        assert any("365" in finding for finding in findings)

    def test_unrelated_15_number_stays_gated(self, cset):
        findings = check_g2_claims("improved latency by 15", cset, LICENSED_DIGITS)
        assert any("15" in finding for finding in findings)

    def test_working_hour_contract_bound_remains_limited_to_40(self, cset):
        findings = check_g2_claims("50 hours per week", cset, LICENSED_DIGITS)
        assert any("50" in finding for finding in findings)
        assert not any("30" in finding for finding in check_g2_claims("30 hours per week", cset, LICENSED_DIGITS))

    def test_year_dates_never_need_kb_digit_license(self, cset):
        assert check_g2_claims("graduated in 2024", cset, set()) == []

    def test_four_digit_claim_is_still_treated_as_a_year(self, cset):
        # The gate treats four-digit 19xx/20xx strings as dates; claim content
        # must be reviewed separately rather than weakening that date policy.
        assert check_g2_claims("2024 clients served", cset, set()) == []
        # Numeric quantities outside the year range remain strictly licensed.
        assert any("123" in finding for finding in check_g2_claims("123 clients served", cset, set()))

    def test_percent_is_rejected_even_when_number_is_product_suffix(self, cset):
        findings = check_g2_claims("Microsoft 365% efficiency", cset, LICENSED_DIGITS)
        assert any("percentage" in finding for finding in findings)

    def test_large_product_suffix_outside_exception_is_still_gated(self, cset):
        findings = check_g2_claims("Office 3650 users", cset, LICENSED_DIGITS)
        assert any("3650" in finding for finding in findings)

    def test_case_and_punctuation_product_spellings(self, cset):
        assert check_g2_claims("ms office365, Microsoft 365, Dynamics 365.", cset, LICENSED_DIGITS) == []

    def test_number_rule_still_rejects_unlicensed_claims(self, cset):
        for text in ("35", "15", "20", "365", "20.5"):
            findings = check_g2_claims(f"claimed {text} units", cset, LICENSED_DIGITS)
            assert any(text in finding for finding in findings)

    def test_product_version_in_jd_beside_candidate_metric_only_exempts_product(self, cset):
        findings = check_g2_claims("Microsoft 365; reduced processing time by 15", cset, LICENSED_DIGITS)
        assert sum("number" in finding for finding in findings) == 1
        assert any("15" in finding for finding in findings)

    def test_spelled_out_product_suffix_is_not_silently_licensed(self, cset):
        findings = check_g2_claims("Microsoft three hundred sixty-five", cset, LICENSED_DIGITS)
        assert findings  # only the supported exact product suffix 365 is exempt

    def test_product_numbers_remain_nonclaimable_in_plain_numeric_sentence(self, cset):
        findings = check_g2_claims("Microsoft 365 users", cset, LICENSED_DIGITS)
        # Product name is exempt; candidate quantitative context after it is not present.
        assert not findings
        assert check_g2_claims("served 365 users", cset, LICENSED_DIGITS)


class TestG3Artifact:
    def test_clean_text_passes(self):
        assert check_g3_text("Software Engineer - Soham Infotech, Dec 2023 - Jan 2025") == []

    def test_leftover_tokens_flagged(self):
        assert check_g3_text("objective @@CAREER_OBJECTIVE@@ skills") != []

    def test_legacy_collision_prefix_flagged(self):
        assert any("PROJECT-" in f for f in check_g3_text("PROJECT-Integrated backend systems"))

    def test_apostrophe_dates_flagged(self):
        assert any("apostrophe" in f for f in check_g3_text("Dec'23 -- Jan'25"))

    def test_corrupted_titles_flagged(self):
        assert any("AREER BJECTIVE" in f for f in check_g3_text("AREER BJECTIVE"))

    def test_ligatures_flagged(self):
        assert any("ligature" in f for f in check_g3_text("efﬁciency"))
