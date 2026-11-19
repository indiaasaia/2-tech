"""100% keyword gate (plan v3 step 4): matching, pre-build insert, artifact check,
KB backing, triage fields, and two real step-5 builds (skip without LaTeX)."""
from __future__ import annotations

import pytest

from resume_content_improve_research import config
from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.keywords import build_keyword_plan
from resume_content_improve_research.verification.keyword_gate import (
    check_artifacts,
    ensure_keywords,
    kb_backing,
    keyword_in_text,
    normalize_text,
)
from resume_content_improve_research.verification.triage import build_shortlist, fit_tier_for

KB = kb_loader.load_kb()
JOB = {"title": "Working Student Data Science (m/f/d)", "company": "Muster GmbH",
       "job_description": "Analyse data with Python, pandas and scikit-learn; build REST APIs on Kubernetes.",
       "requirements": "Machine Learning, NLP, Docker, MS Office, communication skills. "
                       "Studying Business Informatics."}
ANALYSIS = {"language": "en", "title_core": "Working Student Data Science",
            "required": ["python", "machine learning", "studying Business Informatics", "enrolled student"],
            "preferred": ["Docker"], "tools": ["pandas", "scikit-learn", "Kubernetes"],
            "languages_required": [{"language": "English", "level": "fluent"}]}
PLAN = build_keyword_plan(JOB, ANALYSIS).to_dict()


class TestMatching:
    def test_normalization(self):
        assert normalize_text("Data–Driven  \n Runner’s") == "data-driven runner's"

    @pytest.mark.parametrize("term,text,expected", [
        ("ML", "machine learning (ml)", True),
        ("Machine Learning", "AI: Machine Learning (ML), NLP", True),
        ("C", "c++ and c#", False),
        ("Java", "javascript, typescript", False),
        ("Node.js", "we use node.js daily.", True),
        ("Space Traffic Management", "space traffic\nmanagement", True),
        ("MS Office", "ms of{}fice", False),            # the rendering bug must be caught
    ])
    def test_keyword_in_text(self, term, text, expected):
        assert keyword_in_text(term, normalize_text(text)) is expected


class TestEnsureKeywords:
    def test_missing_terms_go_to_their_category_row(self):
        doc = {"skill_rows": [("Programming Languages", ["Python"])], "profile": "", "experiences": []}
        added = ensure_keywords(doc, PLAN)
        assert "Docker" in added and "Kubernetes" in added and "Python" not in added
        rows = dict(doc["skill_rows"])
        assert "Docker" in rows["Software, Cloud & DevOps"] and "pandas" in rows["Data & Analytics"]
        labels = [label for label, _ in doc["skill_rows"]]
        assert labels[0] == "Programming Languages"                  # category order kept

    def test_education_fields_are_never_inserted(self):
        doc = {"skill_rows": [], "profile": ""}
        ensure_keywords(doc, PLAN)
        assert not any("Business Informatics" in items for _, items in doc["skill_rows"])

    def test_idempotent(self):
        doc = {"skill_rows": [], "profile": ""}
        ensure_keywords(doc, PLAN)
        assert ensure_keywords(doc, PLAN) == []


class TestArtifactCheck:
    def _all_terms_text(self) -> str:
        return " | ".join(k["term"] for k in PLAN["keywords"] if k["category"] != "education_field")

    def test_passes_when_every_keyword_present(self):
        text = self._all_terms_text()
        gate = check_artifacts(PLAN, text, text)
        assert gate["passed"] and gate["coverage"] == 1.0
        assert gate["education_gaps"] == ["Business Informatics"]       # reported, not failed
        assert gate["eligibility"] == ["enrolled student"]
        assert gate["languages_required"] == ["English (fluent)"]

    def test_fails_when_pdf_or_docx_loses_a_keyword(self):
        text = self._all_terms_text()
        gate = check_artifacts(PLAN, text.replace("Docker", "Dock{}er"), text)
        assert not gate["passed"] and gate["missing_pdf"] == ["Docker"]
        gate = check_artifacts(PLAN, text, text.replace("pandas", ""))
        assert not gate["passed"] and gate["missing_docx"] == ["pandas"]

    def test_no_docx_judges_pdf_only(self):
        gate = check_artifacts(PLAN, self._all_terms_text(), None)
        assert gate["passed"] and gate["missing_docx"] == []


class TestKbBacking:
    def test_backed_vs_prep(self):
        backing = kb_backing(PLAN, KB)
        assert "Python" in backing["kb_backed"]
        assert "Kubernetes" in backing["prep_terms"] and "Docker" in backing["prep_terms"]
        assert "Communication Skills" not in backing["kb_backed"] + backing["prep_terms"]
        assert 0 < backing["kb_backed_share"] < 1


class TestTriageFit:
    def test_fit_tiers(self):
        assert fit_tier_for(0.7) == "strong" and fit_tier_for(0.4) == "good"
        assert fit_tier_for(0.1) == "stretch" and fit_tier_for(None) == ""

    def test_shortlist_ranks_by_kb_backed_share(self):
        def rec(name, share, score):
            return {"status": "verified", "title": name, "company": "C", "job_url": name, "score": score,
                    "kb_backed_share": share, "keyword_coverage": 1.0, "prep_terms": ["Docker"],
                    "gap_report": {"missing_required": [], "missing_preferred": []}}
        payload = build_shortlist([rec("a", 0.2, 95), rec("b", 0.8, 60)])
        assert [j["title"] for j in payload["jobs"]] == ["b", "a"]
        assert payload["jobs"][0]["fit_tier"] == "strong" and payload["jobs"][1]["prep_terms"] == ["Docker"]
        assert payload["fit_counts"] == {"strong": 1, "stretch": 1}


# ---------------------------------------------------------------------------
# real step-5 builds
# ---------------------------------------------------------------------------
COMPONENTS = {
    "objective": "Data Science working student candidate with an MSc Artificial Intelligence and "
                 "Software Engineer experience in Python.",
    "skills_section": {"languages": ["Python"], "specialized_areas": ["Machine Learning"],
                       "areas": [{"label": "A", "skills": ["Git"]}, {"label": "B", "skills": ["SQL"]}]},
    "experiences": [{"id": "soham", "bullets": [], "skills": ["Python"]},
                    {"id": "pantechelearning", "bullets": [], "skills": []}],
    "projects": [{"id": "resume_gen", "bullets": [], "skills": []},
                 {"id": "hft", "bullets": [], "skills": []}],
}
RECORD = {"job_url": "https://example.test/job", "title": JOB["title"], "company": JOB["company"],
          "status": "gated_ok", "analysis": ANALYSIS, "components": COMPONENTS,
          "letter_input": {"posting": JOB, "analysis": ANALYSIS}}


@pytest.fixture()
def step5(tmp_path, monkeypatch):
    from resume_content_improve_research import run_step5
    from resume_content_improve_research.templates.build import find_latex_engine

    engine = find_latex_engine()
    if engine is None:
        pytest.skip("no LaTeX engine")
    for attr, sub in (("TEX_DIR", "tex"), ("PDF_DIR", "pdf"), ("DOCX_DIR", "docx"), ("RUNS_FAILED_DIR", "failed")):
        monkeypatch.setattr(config, attr, tmp_path / sub)
    return run_step5, engine, tmp_path


def test_build_ships_only_at_full_keyword_coverage(step5):
    run_step5, engine, _tmp = step5
    out = run_step5.build_record(RECORD, engine, name="gate_ok")
    assert out["status"] == "verified", out["build_error"]
    assert out["gates"]["KW"] is True and out["keyword_coverage"] == 1.0
    assert out["keyword_gate"]["missing_docx"] == []
    assert "Kubernetes" in out["prep_terms"]
    assert out["gap_report"]["education_gaps"] == ["Business Informatics"]


def test_keyword_lost_in_rendering_is_quarantined(step5, monkeypatch):
    run_step5, engine, tmp = step5
    real = run_step5.latex_fill_values

    def lossy(doc):     # replay the 2026-10-17 escaping bug: braces printed literally
        values = real(doc)
        token = config.TOKENS["skills_rows"]
        values[token] = values[token].replace("Kubernetes", r"Kuber\{\}netes")
        return values

    monkeypatch.setattr(run_step5, "latex_fill_values", lossy)
    out = run_step5.build_record(RECORD, engine, name="gate_lost")
    assert out["status"] != "verified" and out["gates"]["KW"] is False
    assert "Kubernetes" in out["keyword_gate"]["missing_pdf"]
    assert out["pdf"] == "" and (tmp / "failed" / "gate_lost.pdf").exists()
