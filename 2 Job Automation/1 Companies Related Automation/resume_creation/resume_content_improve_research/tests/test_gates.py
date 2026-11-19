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
