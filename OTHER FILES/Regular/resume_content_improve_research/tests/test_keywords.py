"""Keyword engine (plan v3 §4): full-ad analyst input, lexicon sweep, target plan.

Every fixture is inline — no previous-run files, no LLM calls.
"""
from __future__ import annotations

import pytest

from resume_content_improve_research.generation import keywords as kw
from resume_content_improve_research.verification.coverage import INELIGIBLE_TERM_RE


def _terms(text: str) -> list[str]:
    return [hit["term"] for hit in kw.sweep(text)]


# ---------------------------------------------------------------------------
# Posting text: the analyst must see the whole ad
# ---------------------------------------------------------------------------
class TestPostingText:
    def test_requirements_column_reaches_the_analyst(self):
        """Regression: 17/36 jobs kept requirements outside job_description."""
        job = {"job_description": "Pentest our platform end to end.",
               "requirements": "Burp Suite, OWASP Top 10, SAST and DAST tooling."}
        text = kw.analysis_text(job)
        assert "Pentest our platform" in text and "Burp Suite" in text

    def test_duplicate_columns_are_joined_once(self):
        job = {"job_description": "Build ML models.", "your_tasks": "Build ML models.",
               "requirements": "Python and SQL.", "applicant_profile": "Python and SQL."}
        assert kw.analysis_text(job).count("Build ML models.") == 1
        assert kw.analysis_text(job).count("Python and SQL.") == 1

    def test_longer_column_replaces_contained_shorter_one(self):
        job = {"job_description": "Python and SQL.", "requirements": "Must have: Python and SQL. Nice: Docker."}
        assert kw.analysis_text(job) == "Must have: Python and SQL. Nice: Docker."

    def test_benefits_are_not_keyword_material(self):
        job = {"job_description": "Use Python.", "what_they_offer": "Free MacBook and Udemy budget."}
        assert "MacBook" not in kw.analysis_text(job)

    @pytest.mark.parametrize("title,expected", [
        ("Working Student Data Science (m/f/d)", "Working Student Data Science"),
        ("Working Student (f/m/d) - SAP Signavio Product Excellence",
         "Working Student - SAP Signavio Product Excellence"),
        ("Werkstudent KI (m/w/d)", "Werkstudent KI"),
        ("STUDENT ASSISTANT (all genders) - DATA SPACE", "STUDENT ASSISTANT - DATA SPACE"),
        ("Backend Engineer - Internship (6 months)", "Backend Engineer - Internship (6 months)"),
    ])
    def test_headline_drops_gender_markers_only(self, title, expected):
        assert kw.clean_headline(title) == expected


# ---------------------------------------------------------------------------
# Lexicon sweep
# ---------------------------------------------------------------------------
class TestSweep:
    def test_symbol_names_survive(self):
        terms = _terms("You know C++, C# and Node.js, ship via CI/CD, and maybe .NET.")
        for expected in ("C++", "C#", "Node.js", "CI/CD", ".NET"):
            assert expected in terms

    def test_multiword_terms_match_across_hyphens_and_newlines(self):
        """Regression: a double regex rewrite once broke every multi-word term."""
        terms = _terms("Experience in threat-modeling and machine\nlearning; Burp Suite daily.")
        assert {"Threat Modeling", "Machine Learning", "Burp Suite"} <= set(terms)

    def test_longest_variant_wins_and_consumes_its_span(self):
        assert _terms("We build on Azure OpenAI.") == ["Azure OpenAI"]

    def test_case_sensitive_acronyms(self):
        assert "AI" in _terms("Generative work with AI tools")
        assert "AI" not in _terms("she said hi")
        assert _terms("the rest of the team") == []
        assert "REST APIs" in _terms("design REST APIs")

    def test_single_letter_languages_need_list_context(self):
        assert "R" in _terms("Python, R or SQL")
        assert "R" not in _terms("Our R&D department")
        assert "Go" in _terms("Backend in Python, Go, Rust")
        assert "Go" not in _terms("Go-to-market strategy")

    def test_ad_spelling_is_kept(self):
        assert "NodeJS" in _terms("Strong NodeJS skills")
        assert "Python" in _terms("python scripting")          # canonical casing
        assert "Microservices" in _terms("microservices architecture")
        assert "Machine Learning" in _terms("solid machine-learning basics")   # hyphen folds
        assert "multi-tenant" in _terms("a multi-tenant SaaS")                # ad punctuation kept

    def test_soft_skills_use_the_canonical_label(self):
        assert "Communication Skills" in _terms("excellent communication with stakeholders")

    def test_generic_initiative_is_not_a_soft_skill(self):
        assert "Taking Initiative" not in _terms("an internal AI initiative")
        assert "Taking Initiative" in _terms("you take initiative")

    def test_german_terms_carry_english(self):
        hits = {h["term"]: h for h in kw.sweep("Kenntnisse in Datenanalyse und Teamfähigkeit")}
        assert hits["Datenanalyse"]["english"] == "Data Analysis"
        assert hits["Teamfähigkeit"]["category"] == "soft_skills"


# ---------------------------------------------------------------------------
# Analyst term cleaning + classification
# ---------------------------------------------------------------------------
class TestCleaning:
    @pytest.mark.parametrize("raw,expected", [
        ("pandas library", "pandas"),
        ("experience with APIs", "APIs"),
        ("strong interest generative AI", "generative AI"),
        ("low-code tools", "low-code"),
        ("Python proficiency", "Python"),
        ("Kenntnisse in SQL", "SQL"),
        ("programming", "programming"),            # never cleans to ''
    ])
    def test_clean_phrase(self, raw, expected):
        assert kw.clean_phrase(raw) == expected

    def test_eligibility_language_and_education(self):
        assert kw._classify_term("enrolled student")[0] == "eligibility"
        assert kw._classify_term("penultimate or final year")[0] == "eligibility"
        assert kw._classify_term("English fluency")[0] == "language"
        assert kw._classify_term("C1 level or above")[0] == "language"
        bucket, items = kw._classify_term("currently studying business informatics")
        assert bucket == "keywords" and items[0] == {
            "term": "Business Informatics", "canonical": "", "category": "education_field", "english": ""}
        assert kw._classify_term("computer science studies")[1][0]["term"] == "Computer Science"

    def test_years_and_counts_never_become_phrases(self):
        bucket, items = kw._classify_term("3+ years Python experience")
        assert [i["term"] for i in items] == ["Python"]

    def test_generic_single_words_are_skipped(self):
        assert kw._classify_term("programming", "we need programming")[0] == "skip"

    def test_analyst_paraphrase_reduced_to_lexicon_terms(self):
        ad = "pentest our web app and api"
        _, items = kw._classify_term("pentest web applications", ad)
        assert [i["term"] for i in items] == ["Pentest"]      # lexicon variant casing

    def test_verbatim_free_phrase_is_kept(self):
        ad = "you will compute mass properties of aircraft parts"
        _, items = kw._classify_term("mass properties", ad)
        assert items[0]["term"] == "mass properties" and items[0]["category"] == "domain"


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------
JOB = {
    "title": "Working Student Data Science (m/f/d)",
    "company": "SIXT SE",
    "job_description": "Analyse data with Python. Use SIXTgpt and Claude daily.",
    "requirements": "pandas, NumPy, scikit-learn; Docker is a plus. Communication skills.",
}
ANALYSIS = {
    "language": "en",
    "required": ["pandas library", "enrolled student", "studying Computer Science"],
    "preferred": ["Docker"],
    "tools": ["NumPy", "SIXTgpt"],
    "languages_required": [{"language": "English", "level": "fluent"}],
    "knockouts": [],
}


class TestPlan:
    def test_order_required_tools_preferred_sweep(self):
        plan = kw.build_keyword_plan(JOB, ANALYSIS)
        sources = [k.sources[0] for k in plan.keywords]
        assert sources == sorted(sources, key=kw.SOURCE_ORDER.index)
        assert plan.targets()[:2] == ["pandas", "Computer Science"]

    def test_requirements_only_terms_are_targets(self):
        targets = kw.build_keyword_plan(JOB, ANALYSIS).targets()
        for term in ("pandas", "NumPy", "scikit-learn", "Docker", "Python", "Claude"):
            assert term in targets

    def test_ad_spelling_beats_analyst_paraphrase(self):
        job = {"title": "Intern", "job_description": "You maintain our CI/CD pipelines."}
        plan = kw.build_keyword_plan(job, {"required": ["CI CD processes"]})
        assert "CI/CD" in plan.targets() and "CI CD" not in plan.targets()

    def test_dedupe_merges_sources(self):
        plan = kw.build_keyword_plan(JOB, ANALYSIS)
        numpy = next(k for k in plan.keywords if k.term == "NumPy")
        assert numpy.sources == ["tools", "sweep"]

    def test_employer_products_are_dropped(self):
        assert not any("sixt" in t.lower() for t in kw.build_keyword_plan(JOB, ANALYSIS).targets())

    def test_eligibility_languages_headline_split_off(self):
        plan = kw.build_keyword_plan(JOB, ANALYSIS)
        assert plan.eligibility == ["enrolled student"]
        assert plan.languages == ["English (fluent)"]
        assert plan.headline == "Working Student Data Science"
        assert "enrolled student" not in plan.targets()

    def test_contained_keyword_is_printed_by_the_longer_one(self):
        job = {"title": "Intern", "job_description": "Know Generative AI and AI basics."}
        targets = kw.build_keyword_plan(job, {}).targets()
        assert "Generative AI" in targets and "AI" not in targets

    def test_common_words_in_company_name_do_not_drop_phrases(self):
        job = {"title": "Intern", "company": "Deutsche Bank AG",
               "job_description": "Support banking regulations reporting."}
        plan = kw.build_keyword_plan(job, {"required": ["banking regulations"]})
        assert "banking regulations" in plan.targets()

    def test_to_dict_round_trip_fields(self):
        data = kw.build_keyword_plan(JOB, ANALYSIS).to_dict()
        assert set(data) == {"headline", "language", "keywords", "eligibility", "languages",
                             "targets", "by_category"}
        assert data["targets"] == [k["term"] for k in data["keywords"]]

    def test_plan_for_record_reads_letter_input_posting(self):
        record = {"letter_input": {"posting": JOB}, "analysis": ANALYSIS}
        assert "scikit-learn" in kw.plan_for_record(record).targets()


# ---------------------------------------------------------------------------
# Coverage exclusion regex: real skills must no longer be dropped
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("term", ["Very good MS Office", "Card authorization", "Scrum Master",
                                  "structured data", "master data management"])
def test_real_skills_are_not_ineligible(term):
    assert INELIGIBLE_TERM_RE.search(term) is None


@pytest.mark.parametrize("term", ["enrolled student", "Master's degree", "20 hours per week",
                                  "3 to 6 months", "own car", "office days", "fast learner"])
def test_eligibility_items_stay_ineligible(term):
    assert INELIGIBLE_TERM_RE.search(term) is not None


# ---------------------------------------------------------------------------
# Step 4 wiring: the analyst call receives the joined ad text
# ---------------------------------------------------------------------------
def test_step4_sends_the_whole_ad_to_the_analyst(monkeypatch):
    from resume_content_improve_research import run_step4
    from resume_content_improve_research.generation.analyst import LLMAnalysisError

    seen: dict = {}

    def fake_analyze(title, description, token):
        seen["description"] = description
        raise LLMAnalysisError("stop after capture")

    monkeypatch.setattr(run_step4, "analyze_job", fake_analyze)
    record = run_step4.process_job(
        {"job_url": "u", "title": "T", "job_description": "Tasks here.",
         "requirements": "Burp Suite and OWASP."}, token="x", kb={})
    assert "Burp Suite and OWASP." in seen["description"]
    assert record["status"] == "parked"
