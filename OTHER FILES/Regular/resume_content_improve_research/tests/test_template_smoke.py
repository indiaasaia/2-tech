"""v3 resume template (plan v3 §3.1): text mechanics + one real compile.

TestFilledTemplate: fill the REAL template from the real KB through the
document model (templates/render.py) — every token resolvable, G3 clean, dates
parser-safe, name in normal case, parser-safe font recipe declared.
TestCompiledResume: compile with the bundled tectonic and parse the PDF back —
the measured defects of the v2 template must be gone (dash/apostrophe loss,
merged words, ligatures, missing sections, > 2 pages). Skips without LaTeX.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research import config
from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.factual_content import ground_components
from resume_content_improve_research.generation.keywords import build_keyword_plan
from resume_content_improve_research.templates.fill import fill_template
from resume_content_improve_research.templates.render import latex_fill_values, resume_document
from resume_content_improve_research.verification.gates import check_g3_text

KB = kb_loader.load_kb()
JOB = {"title": "Working Student Data Science (m/f/d)", "company": "Muster GmbH",
       "job_description": "Analyse data with Python, pandas and scikit-learn; build REST APIs.",
       "requirements": "Machine Learning, NLP, Docker, MS Office, traffic forecasting, communication skills."}
ANALYSIS = {"language": "en", "title_core": "Working Student Data Science",
            "required": ["python", "machine learning"], "preferred": ["Docker"],
            "tools": ["pandas", "scikit-learn"], "languages_required": []}
COMPONENTS = {
    "objective": "Data Science working student candidate with an MSc Artificial Intelligence and Software "
                 "Engineer experience in Python, pandas, scikit-learn and REST APIs.",
    "skills_section": {"languages": ["Python", "C++"], "specialized_areas": ["Machine Learning"],
                       "areas": [{"label": "A", "skills": ["Git"]}, {"label": "B", "skills": ["SQL"]}]},
    "experiences": [
        {"id": "soham", "bullets": ["Built modular REST APIs and quant models in Python for trading decisions.",
                                    "Collaborated in an agile engineering team using Git and GitHub."],
         "skills": ["Python"]},
        {"id": "pantechelearning", "bullets": [], "skills": []},
    ],
    "projects": [{"id": "resume_gen", "bullets": [], "skills": []},
                 {"id": "hft", "bullets": [], "skills": []}],
}


@pytest.fixture(scope="module")
def template() -> str:
    return config.TEMPLATE_TEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc() -> dict:
    plan = build_keyword_plan(JOB, ANALYSIS).to_dict()
    grounded = ground_components(COMPONENTS, ANALYSIS, KB, plan=plan)
    return resume_document(grounded, KB, plan)


@pytest.fixture(scope="module")
def filled(template: str, doc: dict) -> str:
    return fill_template(template, latex_fill_values(doc))


def _active(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("%"))


class TestFilledTemplate:
    def test_no_tokens_left(self, filled):
        assert "@@" not in filled

    def test_g3_clean(self, filled):
        assert check_g3_text(filled) == []

    def test_dates_are_parser_safe(self, filled):
        assert not re.search(r"[A-Z][a-z]{2}'\d{2}", filled)
        assert "Dec 2023 - Jan 2025" in filled and "Oct 2027 (expected)" in filled

    def test_name_in_normal_case_and_headline(self, filled):
        assert "Meetkumar Riteshkumar Raval" in filled
        assert "Working Student Data Science | MSc Artificial Intelligence" in filled

    def test_no_scshape_in_active_latex(self, template, filled):
        assert r"\scshape" not in _active(template)
        assert r"\bfseries" in _active(template)
        assert r"\scshape" not in _active(filled)

    def test_parser_safe_font_recipe(self, template):
        active = _active(template)
        assert r"\usepackage{fontspec}" in active
        assert "texgyrepagella" in active and "Ligatures=NoCommon" in active
        assert r"\raggedright" in active and r"\setlength{\spaceskip}" in active
        assert "cfr-lm" not in active

    def test_template_tokens_all_declared(self, template):
        found = set(re.findall(r"@@[A-Z0-9_]+@@", template))
        assert found <= set(config.ALL_TOKENS), f"unknown tokens: {found - set(config.ALL_TOKENS)}"

    def test_no_columnar_hfill_pairs(self, filled):
        """Textkernel code 433: two items on one line read as columns (v2 achievements/certs)."""
        for line in filled.splitlines():
            if line.startswith(r"\item"):
                assert r"\hfill" not in line, line


class TestDocumentModel:
    def test_availability_and_permit_line(self, doc):
        assert doc["availability"].startswith("Available immediately")
        assert "20 h/week during lecture periods" in doc["availability"]
        assert "December 2028" in doc["availability"]

    def test_languages_line_is_well_formed(self, doc):
        assert doc["languages"] == ("English - Fluent (C2) | German - Basic (A2), currently learning | "
                                    "Hindi - Native | Gujarati - Native")

    def test_education_expected_end_faculty_focus(self, doc):
        msc = doc["education"][0]
        assert msc["dates"] == "Apr 2025 - Oct 2027 (expected)"
        assert any("Computer Science" in line for line in msc["lines"])
        assert any(line.startswith("Focus areas: Core AI Fundamentals") for line in msc["lines"])

    def test_links_are_visible_text(self, doc):
        texts = [text for text, _url in doc["contact"]]
        assert "linkedin.com/in/meetraval" in texts and "github.com/ravalmeet" in texts
        assert all("[Link]" not in text for text, _u, _url in doc["additional_projects"])

    def test_skill_rows_are_categories_with_acronym_pairs(self, doc):
        labels = [label for label, _ in doc["skill_rows"]]
        assert labels[0] == "Programming Languages" and "AI & Machine Learning" in labels
        flat = [item for _, items in doc["skill_rows"] for item in items]
        assert "Machine Learning (ML)" in flat and "Natural Language Processing (NLP)" in flat


@pytest.fixture(scope="module")
def compiled(filled, tmp_path_factory):
    from resume_content_improve_research.templates.build import compile_pdf, find_latex_engine

    engine = find_latex_engine()
    if engine is None:
        pytest.skip("no LaTeX engine")
    out = tmp_path_factory.mktemp("v3")
    tex = out / "resume.tex"
    tex.write_text(filled, encoding="utf-8")
    ok, message = compile_pdf(tex, out / "resume.pdf", engine)
    assert ok, message
    return out / "resume.pdf"


class TestCompiledResume:
    def test_parse_back_is_clean(self, compiled):
        import pdfplumber

        from resume_content_improve_research.verification.gates import check_g1
        from resume_content_improve_research.verification.parse_sim import parse_pdf

        parsed = parse_pdf(compiled)
        with pdfplumber.open(compiled) as pdf:
            assert 1 <= len(pdf.pages) <= config.MAX_PAGES
        assert parsed.ligature_count == 0
        assert parsed.name_extracted and parsed.email_extracted and parsed.phone_extracted
        assert parsed.reading_order_ok
        for title in ("Profile", "Technical Skills", "Work Experience", "Projects", "Education", "Languages"):
            assert title in parsed.sections_found, parsed.sections_found
        assert check_g1(parsed.text, parsed.word_count) == []
        # v2 defects: title/company merged, apostrophe lost, words merged
        assert "Software Engineer | Soham Infotech | Gujarat, India" in parsed.text
        assert "Runner’s Up" in parsed.text or "Runner's Up" in parsed.text
        assert "scikit-learn" in parsed.text and "C++" in parsed.text
        # ff words must survive as plain text (the f{}f break must never print)
        assert "MS Office" in parsed.text and "{}" not in parsed.text
