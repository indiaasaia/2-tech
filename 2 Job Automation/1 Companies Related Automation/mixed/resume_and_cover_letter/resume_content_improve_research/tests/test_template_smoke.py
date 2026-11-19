"""Smoke test: fill the REAL v2 template with sample KB-grounded values.

Verifies: template tokens all resolvable, filled text passes G3, no @@ left,
dates in Dec yyyy format, and the template only contains parser-safe constructs.
No compilation here (that is the live E2E run's job) — pure text mechanics.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research import config
from resume_content_improve_research.templates.fill import fill_template
from resume_content_improve_research.verification.gates import check_g3_text


@pytest.fixture(scope="module")
def template() -> str:
    return config.TEMPLATE_TEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def filled(template: str) -> str:
    values = {
        "@@CAREER_OBJECTIVE@@": "Software Engineer with quant and AI experience, targeting backend roles.",
        "@@ROLE_1@@": "Software Engineer",
        "@@COMPANY_1@@": "Soham Infotech",
        "@@LOCATION_1@@": "Gujarat, India",
        "@@DATES_1@@": "Dec 2023 - Jan 2025",
        "@@DESCRIPTION_1@@": "Built quant models and real-time algorithms for trading operations.",
        "@@SKILLS_1@@": "Python, SQL, Quantitative Modeling, Deep Learning",
        "@@ROLE_2@@": "Machine Learning Intern",
        "@@COMPANY_2@@": "Pantechelearning",
        "@@LOCATION_2@@": "Chennai, India",
        "@@DATES_2@@": "Dec 2021 - Feb 2022",
        "@@DESCRIPTION_2@@": "Implemented machine learning models including text-to-speech applications.",
        "@@SKILLS_2@@": "Machine Learning, NLP, Django, Computer Vision",
        "@@PROJECT_TITLE_1@@": "High Frequency Trading Platform",
        "@@PROJECT_DESC_1@@": "End-to-end real-time market data system with quant and AI models.",
        "@@PROJECT_SKILLS_1@@": "Python, Django, Data Analytics",
        "@@PROJECT_TITLE_2@@": "Automated Resume Generation",
        "@@PROJECT_DESC_2@@": "Open-source LLM system generating role-specific resume sections.",
        "@@PROJECT_SKILLS_2@@": "Python, Streamlit, LLM, NLP",
        "@@LANGUAGES@@": "Python, C++, JavaScript, SQL",
        "@@SPECIALIZED_AREAS@@": "Machine Learning, NLP, Quantitative Modeling, Computer Vision",
        "@@SKILLS_AREA_1_LABEL@@": "AI and Data",
        "@@SKILLS_AREA_1@@": "Deep Learning, Reinforcement Learning, Data Analytics",
        "@@SKILLS_AREA_2_LABEL@@": "Web and Tools",
        "@@SKILLS_AREA_2@@": "Django, FastAPI, React, MongoDB",
        "@@EDUCATION@@": r"MSc Artificial Intelligence — Brandenburgische Technische Universität Cottbus-Senftenberg \hfill April 2025 — Present\\BE Computer Engineering — Gujarat Technological University \hfill June 2020 — May 2024",
        "@@RESEARCH@@": r"\item Researching sarcasm in Indic languages.",
        "@@ACHIEVEMENTS@@": r"\item Hackathon winner.",
        "@@CERTIFICATIONS@@": r"\item Google Machine Learning.",
        "@@ADDITIONAL_PROJECTS@@": r"\item TradingView data fetch.",
        "@@SPOKEN_LANGUAGES@@": r"\item English (C2); German (A2).",
    }
    return fill_template(template, values)


class TestFilledTemplate:
    def test_no_tokens_left(self, filled):
        assert "@@" not in filled

    def test_g3_clean(self, filled):
        assert check_g3_text(filled) == []

    def test_dates_are_parser_safe(self, filled):
        import re

        assert not re.search(r"[A-Z][a-z]{2}'\d{2}", filled)
        assert "Dec 2023" in filled and "Feb 2022" in filled

    def test_full_name_in_header(self, filled):
        assert "RAVAL MEETKUMAR RITESHKUMAR" in filled

    def test_no_scshape_in_active_latex(self, template, filled):
        """The ACTIVE LaTeX (comment lines stripped) must contain no small-caps titles."""
        def active_lines(text: str) -> str:
            return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("%"))
        assert r"\scshape" not in active_lines(template)
        assert r"\bfseries" in active_lines(template)
        assert r"\scshape" not in active_lines(filled)

    def test_standard_font_encoding_and_parser_spacing(self, template):
        assert r"\usepackage[T1]{fontenc}" in template
        assert r"\setlength{\spaceskip}" in template
        assert "\\usepackage{fontspec}" not in template

    def test_template_tokens_all_declared(self, template):
        """Every @@...@@ literal in the template must be a known token."""
        import re

        found = set(re.findall(r"@@[A-Z0-9_]+@@", template))
        known = set(config.ALL_TOKENS)
        assert found <= known, f"unknown tokens in template: {found - known}"
