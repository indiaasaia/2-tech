"""Smoke test: fill the REAL letter templates with sample values.

Verifies: CL tokens all resolvable, filled text passes L3, DD.MM.YYYY date,
German sign-off present, no @@ left, and every @@...@@ literal in the
templates is a known CL token. No compilation here (live E2E builds).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research import config
from resume_content_improve_research.generation.cover_letter import CoverLetter, to_fill_values
from resume_content_improve_research.templates.fill import fill_template
from resume_content_improve_research.verification.cl_gates import check_l3_artifact

CL_TOKENS = config.CL_ALL_TOKENS


@pytest.fixture(scope="module")
def letter() -> CoverLetter:
    return CoverLetter(
        language="de",
        subject="Working Student Data Analytics (m/f/d) - Reference: STX-2026-1188",
        salutation="Sehr geehrte Damen und Herren,",
        opening="mit großem Interesse habe ich Ihre Stellenanzeige gelesen.",
        fit="Meine Erfahrung mit Python und SQL passt zu Ihren Anforderungen.",
        motivation="Besonders reizt mich die Rolle, weil ich meine Quant- und ML-Erfahrung einbringen kann.",
        closing="Über ein persönliches Gespräch freue ich mich sehr.",
        signoff="Mit freundlichen Grüßen",
        name_print="RAVAL MEETKUMAR RITESHKUMAR",
        sender_name="RAVAL MEETKUMAR",
        sender_address="Ernestinenstraße 21, 45141 Essen, Germany",
        sender_contact="+49 15565 468731 | ravalmeett@gmail.com",
        sender_links="https://www.linkedin.com/in/meetraval/ | https://github.com/ravalmeet",
        company_block="Muster GmbH\nPersonalabteilung\nHauptstraße 1\n12345 Berlin",
        date_line="Essen, 23.09.2026",
        reference="STX-2026-1188",
        portal="stepstone",
        company_name="Muster GmbH",
    )


@pytest.fixture(scope="module")
def filled_de(letter: CoverLetter) -> str:
    template = config.LETTER_TEMPLATE_DE.read_text(encoding="utf-8")
    return fill_template(template, to_fill_values(letter), tokens=CL_TOKENS)


@pytest.fixture(scope="module")
def filled_en(letter: CoverLetter) -> str:
    template = config.LETTER_TEMPLATE_EN.read_text(encoding="utf-8")
    return fill_template(template, to_fill_values(letter), tokens=CL_TOKENS)


class TestFilledLetterTemplates:
    def test_no_tokens_left_de(self, filled_de):
        assert "@@" not in filled_de

    def test_no_tokens_left_en(self, filled_en):
        assert "@@" not in filled_en

    def test_l3_clean(self, filled_de, filled_en):
        assert check_l3_artifact(filled_de) == []
        assert check_l3_artifact(filled_en) == []

    def test_parser_safe_date(self, filled_de):
        assert re.search(r"\d{2}\.\d{2}\.\d{4}", filled_de)
        assert not re.search(r"[A-Z][a-z]{2}'\d{2}", filled_de)

    def test_full_name_present(self, filled_de):
        assert "RAVAL MEETKUMAR RITESHKUMAR" in filled_de

    def test_subject_and_salutation_present(self, filled_de):
        assert "Working Student Data Analytics" in filled_de
        assert "Sehr geehrte Damen und Herren," in filled_de

    def test_ligature_fix_present(self):
        for path in (config.LETTER_TEMPLATE_DE, config.LETTER_TEMPLATE_EN):
            template = path.read_text(encoding="utf-8")
            assert "Ligatures=NoCommon" in template
            assert "texgyrepagella" in template

    def test_template_tokens_all_declared(self):
        """Every @@...@@ literal in both templates must be a known CL token."""
        for path in (config.LETTER_TEMPLATE_DE, config.LETTER_TEMPLATE_EN):
            template = path.read_text(encoding="utf-8")
            found = set(re.findall(r"@@[A-Z0-9_]+@@", template))
            assert found <= set(config.CL_ALL_TOKENS), f"unknown tokens in {path.name}: {found - set(config.CL_ALL_TOKENS)}"

    def test_parser_safe_fonts_active(self):
        """No \\scshape in the active LaTeX (comment lines stripped)."""
        for path in (config.LETTER_TEMPLATE_DE, config.LETTER_TEMPLATE_EN):
            template = path.read_text(encoding="utf-8")
            active = "\n".join(l for l in template.splitlines() if not l.lstrip().startswith("%"))
            assert r"\scshape" not in active
