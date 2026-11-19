"""Regressions from the 4-job live audit (2026-10-17): done-work claims over
unbacked keywords, credential keywords, typography, file stems. No LLM calls."""
from __future__ import annotations

from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.claim_check import (
    claim_violations,
    honest_profile,
    unbacked_terms,
)
from resume_content_improve_research.generation.keywords import _classify_term, build_keyword_plan
from resume_content_improve_research.generation.text_norm import plain_typography
from resume_content_improve_research.templates.build import safe_name
from resume_content_improve_research.verification.prep import learning_priorities

KB = kb_loader.load_kb()
JOB = {"title": "Working Student Data Science (m/f/d)", "company": "SIXT",
       "job_description": "Analyse data with Python, pandas, scikit-learn and NumPy; ingest CSV and JSON.",
       "requirements": "Machine Learning, Data Visualization, Matplotlib, REST APIs."}
ANALYSIS = {"language": "en", "required": ["Python", "pandas", "scikit-learn", "Machine Learning"],
            "preferred": ["NumPy", "Matplotlib"], "tools": ["CSV", "JSON"], "languages_required": []}
PLAN = build_keyword_plan(JOB, ANALYSIS).to_dict()


def test_unbacked_terms_are_the_non_kb_keywords():
    terms = unbacked_terms(PLAN, KB)
    assert "pandas" in terms and "NumPy" in terms
    assert "Python" not in terms and "Machine Learning" not in terms


def test_live_letter_sentence_is_flagged():
    text = ("Using Python, pandas, scikit-learn, NumPy, Matplotlib and Streamlit I prepared features, "
            "trained models and monitored performance.")
    findings = claim_violations(text, KB, PLAN)
    assert findings and "pandas" in findings[0]


def test_skills_list_framing_is_allowed():
    assert claim_violations("My toolkit also includes pandas, NumPy and Matplotlib.", KB, PLAN) == []
    assert claim_violations("Role-relevant skills: pandas and NumPy.", KB, PLAN) == []


def test_backed_claims_pass():
    assert claim_violations("I built REST APIs in Python and trained Machine Learning models.", KB, PLAN) == []


def test_honest_profile_moves_unbacked_terms_to_a_skills_sentence():
    live = ("MSc Artificial Intelligence student and Software Engineer with hands-on experience in Python, "
            "Machine Learning, pandas, scikit-learn, NumPy and Data Visualization. Strong communication skills.")
    fixed, findings = honest_profile(live, KB, PLAN)
    assert findings
    assert claim_violations(fixed, KB, PLAN) == []
    assert "Role-relevant skills:" in fixed
    for term in ("pandas", "NumPy", "scikit-learn"):
        assert term in fixed                         # keyword coverage kept
    assert fixed.startswith("MSc Artificial Intelligence")


def test_clean_profile_unchanged():
    clean = "MSc Artificial Intelligence student and Software Engineer building Python REST APIs."
    assert honest_profile(clean, KB, PLAN) == (clean, [])


def test_credentials_are_not_printable_keywords():
    for term in ("Published CVE", "Security blog", "Meetup talk", "AWS Certified Developer"):
        assert _classify_term(term, "", "en")[0] == "eligibility", term
    assert _classify_term("Bug Bounty", "", "en")[0] == "keywords"


def test_plain_typography():
    assert plain_typography("black‑box and real‐time") == "black-box and real-time"


def test_safe_name_collapses_dashes():
    assert safe_name("Working Student - AI Automation, Procurement (m/f/d)") == "Working-Student-AI-Automation-Procurement"


def test_learning_priorities_prefer_ad_spelling():
    results = [{"status": "verified", "company": "A", "prep_terms": ["CI CD"]},
               {"status": "verified", "company": "B", "prep_terms": ["CI/CD"]}]
    top = learning_priorities(results)[0]
    assert top["term"] == "CI/CD" and len(top["companies"]) == 2


def test_quoted_job_title_is_not_a_claim():
    """Regression (live 2026-10-17): 12/18 letters parked on 'I am applying for the
    Working Student Data Science position' (title quoted, 'applying' read as a claim)."""
    title = "Working Student Data Science (m/f/d)"
    plan = build_keyword_plan(dict(JOB, title=title, requirements=JOB["requirements"] + " Data Science."),
                              dict(ANALYSIS, required=ANALYSIS["required"] + ["Data Science"])).to_dict()
    text = "I am applying for the Working Student Data Science position at SIXT."
    assert claim_violations(text, KB, plan, exclude=(title, "Working Student Data Science")) == []
    assert claim_violations("I used pandas daily.", KB, plan, exclude=(title,)) != []


def test_free_phrase_keyword_is_not_backed_by_a_sub_term():
    """Regression: 'AI assistants' counted as KB-backed because the KB has 'AI'."""
    from resume_content_improve_research.verification.keyword_gate import kb_backing

    plan = build_keyword_plan(dict(JOB, requirements="Experience with AI assistants and AI Agents."),
                              dict(ANALYSIS, required=["AI assistants", "AI Agents"])).to_dict()
    split = kb_backing(plan, KB)
    assert "AI assistants" in split["prep_terms"] and "AI Agents" in split["kb_backed"]


def test_background_in_is_a_claim():
    assert claim_violations("Software Engineer with background in pandas and NumPy.", KB, PLAN)


def test_percentage_bullet_is_dropped():
    from resume_content_improve_research.generation.factual_content import bullet_findings
    from resume_content_improve_research.generation.claimable_set import build_claimable_set
    from resume_content_improve_research.generation.evidence_vocab import find_entry

    cset = build_claimable_set(ANALYSIS, KB, keywords=PLAN["targets"])
    hft = find_entry(KB, "hft")
    found = bullet_findings("Implemented AI models achieving 70 percent accuracy in cash segment.",
                            hft, KB, cset, kb_loader.licensed_digits(KB), PLAN)
    assert any("percentage" in f for f in found)


def test_motivation_about_the_role_is_not_a_claim():
    plan = build_keyword_plan(dict(JOB, requirements=JOB["requirements"] + " Data Science."),
                              dict(ANALYSIS, required=ANALYSIS["required"] + ["Data Science"])).to_dict()
    role = "The opportunity to apply Data Science to business decisions aligns with my goal of using AI."
    assert claim_violations(role, KB, plan, first_person_only=True) == []
    assert claim_violations("I used pandas at Soham Infotech.", KB, plan, first_person_only=True) != []


def test_stems_cut_at_word_boundary():
    from resume_content_improve_research.templates.build import cut_stem

    assert cut_stem("Process-Improvement-Specialist-Intern-2027", 38) == "Process-Improvement-Specialist-Intern"
    assert cut_stem("Short-Title", 40) == "Short-Title"


def test_stale_files_are_moved_not_deleted(tmp_path):
    from resume_content_improve_research.templates.build import archive_stale

    pdf = tmp_path / "resume" / "pdf"
    pdf.mkdir(parents=True)
    (pdf / "keep.pdf").write_text("x")
    (pdf / "old.pdf").write_text("y")
    moved = archive_stale([pdf], {"keep"}, tmp_path / "stale")
    assert moved == ["old.pdf"] and (pdf / "keep.pdf").exists()
    assert (tmp_path / "stale" / "resume" / "pdf" / "old.pdf").read_text() == "y"


def test_letter_keywords_extend_an_existing_toolkit_sentence():
    from types import SimpleNamespace

    from resume_content_improve_research.generation import cover_letter

    letter = SimpleNamespace(language="en", opening="I apply.", motivation="", closing="",
                             fit="I built pipelines. My toolkit also includes pandas and NumPy.")
    added = cover_letter.ensure_letter_keywords(letter, PLAN)
    assert added and letter.fit.count("My toolkit") == 1
    assert "pandas" in letter.fit and all(t in letter.fit for t in added)


def test_forward_looking_tail_is_not_a_claim():
    """'I can apply my API experience to Webhooks': Webhooks is the job's work."""
    plan = build_keyword_plan(dict(JOB, requirements=JOB["requirements"] + " Webhooks."),
                              dict(ANALYSIS, required=ANALYSIS["required"] + ["Webhooks"])).to_dict()
    assert claim_violations("I built REST APIs, which prepares me to secure Webhooks.", KB, plan) == []
    assert claim_violations("I built Webhooks and REST APIs.", KB, plan) != []
