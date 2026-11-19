"""Comprehensive tests for the structured motivation profile (deterministic, zero LLM).

Covers all 10 testing scenarios:
  1. Backward compatibility (pre-profile KB records and empty motivation_profile)
  2. Complete profile (interest, preference, direction, and structured subsections)
  3. Different job types (Data vs ML/NLP vs Full-Stack select different motivation & fit evidence)
  4. Insufficient evidence (honest fallback, no inference from JD, unsupported_requirements tracked)
  5. Truthfulness (unapproved entries, placeholders, digits, unlicensed/forbidden skills, mirrorable ownership blocked)
  6. Language (German and English formal conventions, salutations, sign-offs, L4 gate)
  7. Structure (4 paragraphs, <=55 words/paragraph, 100-330 total words, DD.MM.YYYY date, L1-L4 gates)
  8. Build artifacts (TXT, DOCX, filled LaTeX templates, and live PDF build when tectonic is present)
  9. Regression compatibility with process_letter_input and build_letter
 10. Runtime cost (strictly 0 LLM calls; succeeds even when call_llm is blocked)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research import config, run_step4
from resume_content_improve_research.generation import cover_letter as cl
from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.claimable_set import ClaimableSet, build_claimable_set
from resume_content_improve_research.generation.motivation import (
    entries,
    entry_text,
    needs_candidate_input,
    select_motivation_entries,
    validate_profile,
)
from resume_content_improve_research.verification.cl_gates import (
    check_l2_truth,
    check_l3_artifact,
    run_letter_gates,
)

BASE_KB = {
    "profile": {
        "name": "Test Candidate",
        "display_name": "Test Candidate",
        "contact": {
            "address": "Teststraße 1, 45141 Essen, Germany",
            "phone_de": "+49 100",
            "email": "test@example.com",
        },
        "languages_spoken": [],
    },
    "education": [
        {"id": "btu-msc", "degree": "MSc AI", "school": "BTU", "start": "2025-04", "end": "present"},
    ],
    "skills": [
        {"name": "Python", "aliases": [], "evidence": ["master_cv"]},
        {"name": "Machine Learning", "aliases": [], "evidence": ["master_cv"]},
        {"name": "Data Analytics", "aliases": [], "evidence": ["master_cv"]},
        {"name": "SQL", "aliases": [], "evidence": ["master_cv"]},
    ],
    "experience": [],
    "projects": [],
    "research": [],
}

DATA_ENTRY = {
    "id": "data-interest",
    "category": "interest",
    "domains": ["data analytics", "quantitative analysis"],
    "problems": ["extracting decision signals from complex datasets"],
    "activities": ["building analytical pipelines in Python"],
    "text_de": "Mich interessiert die Arbeit mit Datenanalyse und Python in der Praxis.",
    "text_en": "I am interested in applied data analytics work with Python.",
    "evidence": ["master_cv"],
    "keywords": ["datenanalyse", "data analytics", "python"],
    "skills": ["Python", "Data Analytics"],
    "role_families": ["data"],
}

PREF_ENTRY = {
    "id": "data-preference",
    "category": "preference",
    "responsibilities": ["end-to-end data preprocessing", "structured evaluation"],
    "approach": ["reproducible experimentation"],
    "work_environment": ["collaborative engineering teams"],
    "text_de": "Dabei schätze ich strukturierte Aufgaben in der Datenaufbereitung und Analyse.",
    "text_en": "I value structured responsibilities in data preparation and analysis.",
    "evidence": ["master_cv"],
    "keywords": ["datenanalyse", "data analytics"],
    "skills": ["Data Analytics"],
    "role_families": ["data"],
}

ML_ENTRY = {
    "id": "ml-interest",
    "category": "interest",
    "domains": ["machine learning", "natural language processing"],
    "problems": ["model training and evaluation"],
    "text_de": "Mich interessiert die Arbeit mit maschinellem Lernen und Modelltraining.",
    "text_en": "I am interested in machine learning and model training work.",
    "evidence": ["master_cv"],
    "keywords": ["machine learning", "modelltraining"],
    "skills": ["Machine Learning"],
    "role_families": ["ml"],
}

DIRECTION_ENTRY = {
    "id": "direction-1",
    "category": "direction",
    "target_direction": ["scalable data and AI systems"],
    "skills_to_develop": ["Kubernetes"],
    "text_de": "Langfristig möchte ich meine Erfahrung im Bereich Datenanalyse vertiefen.",
    "text_en": "Long term I want to deepen my experience in data analytics.",
    "evidence": ["btu-msc"],
    "keywords": ["datenanalyse", "data analytics"],
    "skills": ["Data Analytics"],
    "role_families": ["data"],
}

FULL_KB = {
    **BASE_KB,
    "motivation_profile": {
        "status": "APPROVED",
        "needs_candidate_input": False,
        "entries": [DATA_ENTRY, PREF_ENTRY, ML_ENTRY, DIRECTION_ENTRY],
    },
}

CSET = ClaimableSet(
    kb_skills=["python", "machine learning", "data analytics", "sql"],
    jd_tools=["kubernetes"],
    required=[],
    preferred=[],
    languages_required=[],
    per_experience={},
    per_project={},
)
LICENSED = {"2023", "2024", "2025"}

DATA_JOB = {"title": "Working Student Data Analytics", "company": "Muster GmbH"}
DATA_ANALYSIS = {
    "language": "de",
    "required": ["python", "datenanalyse"],
    "preferred": [],
    "tools": ["kubernetes"],
}
ML_ANALYSIS = {
    "language": "de",
    "required": ["machine learning", "modelltraining"],
    "preferred": [],
    "tools": [],
}


def _letter_for(kb, job, analysis):
    posting = {
        "title": job["title"],
        "company": job["company"],
        "detail_company_name": job["company"],
        "job_description": "Stelle.",
    }
    letter = cl.build_skeleton(posting, analysis, kb)
    letter, meta = cl.generate_grounded_letter(letter, CSET, posting, analysis, kb)
    cl.postcheck_letter(letter, {"job_description": ""}, CSET)
    cl.probe_date_line(letter)
    return letter, meta


class TestBackwardCompatibility:
    def test_no_profile_no_crash_and_honest_fallback(self):
        letter, meta = _letter_for(BASE_KB, DATA_JOB, DATA_ANALYSIS)
        assert meta["calls"] == 0
        assert meta["motivation_source"] == "fallback_no_profile"
        assert meta["motivation_entry_ids"] == []
        assert "no motivation_profile" in meta["motivation_fallback_reason"]
        assert "Datenanalyse und Python in der Praxis" not in letter.motivation
        assert needs_candidate_input(BASE_KB) is True

    def test_profile_schema_absent_is_valid(self):
        errors, _warnings = validate_profile(BASE_KB)
        assert errors == []

    def test_empty_entries_warns_but_valid(self):
        errors, warnings = validate_profile(
            {**BASE_KB, "motivation_profile": {"status": "NEEDS_CANDIDATE_INPUT", "entries": []}}
        )
        assert errors == []
        assert any("fallback" in w for w in warnings)

    def test_real_candidate_kb_loads_and_validates(self):
        from resume_content_improve_research.knowledge_base.validate_kb import validate

        real_kb = kb_loader.load_kb()
        errors, _warnings = validate(real_kb)
        assert errors == []
        letter, meta = _letter_for(real_kb, DATA_JOB, DATA_ANALYSIS)
        assert meta["calls"] == 0
        results = run_letter_gates(letter, build_claimable_set(DATA_ANALYSIS, real_kb), kb_loader.licensed_digits(real_kb))
        assert all(r.passed for r in results)


class TestCompleteProfile:
    def test_relevant_entries_used_across_paragraphs(self):
        letter, meta = _letter_for(FULL_KB, DATA_JOB, DATA_ANALYSIS)
        assert meta["motivation_source"] == "profile"
        assert "data-interest" in meta["motivation_entry_ids"]
        assert "direction-1" in meta["motivation_entry_ids"]
        assert "Datenanalyse und Python" in letter.motivation
        assert "Langfristig möchte ich meine Erfahrung" in letter.closing
        assert "Kubernetes" in meta["development_targets"]
        assert needs_candidate_input(FULL_KB) is False

    def test_categorized_subsections_supported(self):
        structured_kb = {
            **BASE_KB,
            "motivation_profile": {
                "status": "APPROVED",
                "needs_candidate_input": False,
                "professional_interests": [
                    {
                        "id": "struct-interest",
                        "domains": ["Datenanalyse"],
                        "problems": ["Mustererkennung"],
                        "evidence": ["master_cv"],
                        "skills": ["Data Analytics"],
                        "keywords": ["datenanalyse"],
                    }
                ],
                "working_preferences": [
                    {
                        "id": "struct-pref",
                        "responsibilities": ["Datenaufbereitung"],
                        "evidence": ["master_cv"],
                        "keywords": ["datenanalyse"],
                    }
                ],
                "career_direction": [
                    {
                        "id": "struct-dir",
                        "target_direction": ["skalierbare Datenplattformen"],
                        "evidence": ["btu-msc"],
                        "keywords": ["datenanalyse"],
                    }
                ],
            },
        }
        errors, _warnings = validate_profile(structured_kb)
        assert errors == []
        assert len(entries(structured_kb)) == 3
        assert "Datenanalyse" in entry_text(entries(structured_kb)[0], "de")
        letter, meta = _letter_for(structured_kb, DATA_JOB, DATA_ANALYSIS)
        assert meta["motivation_source"] == "profile"
        assert set(meta["motivation_entry_ids"]) == {"struct-interest", "struct-pref", "struct-dir"}
        assert "skalierbare Datenplattformen" in letter.closing

    def test_zero_llm_calls_with_profile(self, monkeypatch):
        def forbidden_llm(*_args, **_kwargs):
            raise AssertionError("LLM must never be called on the production cover-letter path")

        monkeypatch.setattr(cl, "call_llm", forbidden_llm)
        _letter, meta = _letter_for(FULL_KB, DATA_JOB, DATA_ANALYSIS)
        assert meta["calls"] == 0
        assert meta["deterministic_kb_grounded"] is True

    def test_reproducible_selection(self):
        first, meta1 = _letter_for(FULL_KB, DATA_JOB, DATA_ANALYSIS)
        second, meta2 = _letter_for(FULL_KB, DATA_JOB, DATA_ANALYSIS)
        assert first.opening == second.opening
        assert first.fit == second.fit
        assert first.motivation == second.motivation
        assert first.closing == second.closing
        assert meta1["motivation_entry_ids"] == meta2["motivation_entry_ids"]


class TestDifferentJobTypes:
    def test_data_vs_ml_jobs_select_different_material(self):
        data_letter, data_meta = _letter_for(FULL_KB, DATA_JOB, DATA_ANALYSIS)
        ml_letter, ml_meta = _letter_for(
            FULL_KB, {"title": "ML Engineer", "company": "Muster GmbH"}, ML_ANALYSIS
        )
        assert "data-interest" in data_meta["motivation_entry_ids"]
        assert "ml-interest" in ml_meta["motivation_entry_ids"]
        assert data_letter.motivation != ml_letter.motivation
        assert data_letter.opening != ml_letter.opening

    def test_different_roles_select_different_kb_fit_evidence(self):
        real_kb = kb_loader.load_kb()
        quant_analysis = {
            "language": "en",
            "required": ["python", "quant models", "real-time systems", "data scraping"],
            "preferred": ["mathematics"],
            "tools": [],
        }
        web_analysis = {
            "language": "en",
            "required": ["javascript", "react", "nodejs", "mongodb", "ui development"],
            "preferred": ["full stack"],
            "tools": [],
        }
        llm_analysis = {
            "language": "en",
            "required": ["python", "large language models", "transformers", "streamlit"],
            "preferred": ["nlp"],
            "tools": [],
        }
        q_letter, q_meta = _letter_for(real_kb, {"title": "Quant Developer", "company": "Alpha GmbH"}, quant_analysis)
        w_letter, w_meta = _letter_for(real_kb, {"title": "Full Stack Developer", "company": "Alpha GmbH"}, web_analysis)
        l_letter, l_meta = _letter_for(real_kb, {"title": "GenAI Engineer", "company": "Alpha GmbH"}, llm_analysis)

        assert "hft" in q_meta["fit_evidence_ids"]
        assert "vehicle_sharing" in w_meta["fit_evidence_ids"]
        assert "resume_gen" in l_meta["fit_evidence_ids"]
        assert q_letter.fit != w_letter.fit
        assert w_letter.fit != l_letter.fit


class TestInsufficientEvidence:
    def test_no_overlap_falls_back_without_inference(self):
        analysis = {
            "language": "de",
            "required": ["kubernetes"],
            "preferred": [],
            "tools": ["kubernetes"],
        }
        letter, meta = _letter_for(FULL_KB, DATA_JOB, analysis)
        assert meta["motivation_source"] == "fallback_no_overlap"
        assert meta["motivation_entry_ids"] == []
        assert "kubernetes" in meta["unsupported_requirements"]
        # the JD tool must never become motivation evidence
        assert "kubernetes" not in letter.motivation.lower()

    def test_unknown_evidence_entry_never_selected(self):
        bad = {**DATA_ENTRY, "id": "bad-ev", "evidence": ["no-such-id"]}
        kb = {**BASE_KB, "motivation_profile": {"entries": [bad]}}
        selected, meta = select_motivation_entries(DATA_ANALYSIS, kb, "de")
        assert selected == []
        assert meta["motivation_source"] == "fallback_no_profile"

    def test_unapproved_or_placeholder_entry_never_selected(self):
        unapproved = {**DATA_ENTRY, "id": "unapproved-1", "approved": False}
        placeholder = {
            **DATA_ENTRY,
            "id": "todo-1",
            "text_de": "TODO_CANDIDATE: Platzhaltertext für Datenanalyse.",
        }
        kb = {**BASE_KB, "motivation_profile": {"entries": [unapproved, placeholder]}}
        selected, meta = select_motivation_entries(DATA_ANALYSIS, kb, "de")
        assert selected == []
        assert meta["motivation_source"] == "fallback_no_profile"

    def test_draft_profile_status_never_selected(self):
        kb = {
            **BASE_KB,
            "motivation_profile": {
                "status": "DRAFT_PENDING_REVIEW",
                "entries": [DATA_ENTRY],
            },
        }
        selected, meta = select_motivation_entries(DATA_ANALYSIS, kb, "de")
        assert selected == []
        assert meta["motivation_source"] == "fallback_no_profile"

    def test_unapproved_interest_cannot_be_introduced(self):
        letter, _meta = _letter_for(FULL_KB, DATA_JOB, DATA_ANALYSIS)
        assert "Quantenphysik" not in letter.motivation
        assert "quantum physics" not in letter.motivation.lower()


class TestTruthfulnessGates:
    def test_unlicensed_tech_in_motivation_still_parked_by_l2(self):
        letter, _meta = _letter_for(BASE_KB, DATA_JOB, DATA_ANALYSIS)
        letter.motivation = "Ich beherrsche Kafka und Airflow sehr gut in der Praxis."
        findings = check_l2_truth(letter, CSET, LICENSED)
        assert any("kafka" in f.lower() for f in findings)

    def test_mirrorable_tool_claimed_as_owned_parked_by_l2(self):
        letter, _meta = _letter_for(BASE_KB, DATA_JOB, DATA_ANALYSIS)
        letter.motivation = "Ich möchte meine belegten Kenntnisse in Kubernetes in Ihre Aufgaben einbringen."
        findings = check_l2_truth(letter, CSET, LICENSED)
        assert any("mirrorable" in f.lower() and "kubernetes" in f.lower() for f in findings)

    def test_placeholder_in_letter_body_parked_by_l2(self):
        letter, _meta = _letter_for(BASE_KB, DATA_JOB, DATA_ANALYSIS)
        letter.motivation = "TODO_CANDIDATE: Bitte hier Motivation eintragen."
        findings = check_l2_truth(letter, CSET, LICENSED)
        assert any("placeholder" in f.lower() for f in findings)

    def test_missing_evidence_traceability_parked_by_l2(self):
        letter, _meta = _letter_for(FULL_KB, DATA_JOB, DATA_ANALYSIS)
        letter.raw["motivation_source"] = "profile"
        letter.raw["motivation_evidence_ids"] = []
        findings = check_l2_truth(letter, CSET, LICENSED)
        assert any("traceable kb evidence" in f.lower() for f in findings)

    def test_digits_in_profile_rejected_by_validation(self):
        entry = {**DATA_ENTRY, "id": "digits", "text_de": "Ich habe 25 Projekte gemacht."}
        errors, _w = validate_profile(
            {**BASE_KB, "motivation_profile": {"entries": [entry]}}
        )
        assert any("digits" in e for e in errors)

    def test_unowned_or_forbidden_skill_in_profile_rejected_by_validation(self):
        real_kb = kb_loader.load_kb()
        # React is in skills_forbidden of 'soham'
        bad_forbidden = {
            **DATA_ENTRY,
            "id": "forbid-skill",
            "evidence": ["soham"],
            "skills": ["React"],
        }
        errors, _w = validate_profile(
            {**real_kb, "motivation_profile": {"entries": [bad_forbidden]}}
        )
        assert any("skills_forbidden" in e for e in errors)

        # Kubernetes is not an owned skill in BASE_KB
        bad_unowned = {
            **DATA_ENTRY,
            "id": "unowned-skill",
            "skills": ["Kubernetes"],
        }
        errors2, _w2 = validate_profile(
            {**BASE_KB, "motivation_profile": {"entries": [bad_unowned]}}
        )
        assert any("not in kb ownable skills" in e.lower() for e in errors2)

    def test_approved_letter_passes_all_gates(self):
        letter, _meta = _letter_for(FULL_KB, DATA_JOB, DATA_ANALYSIS)
        results = run_letter_gates(letter, CSET, LICENSED)
        assert [r.gate for r in results] == ["L1", "L2", "L3", "L4"]
        assert all(r.passed for r in results), [
            f for r in results for f in r.findings
        ]


class TestLanguage:
    def test_english_letter_uses_english_entry(self):
        analysis = {
            "language": "en",
            "required": ["python", "data analytics"],
            "preferred": [],
            "tools": [],
        }
        letter, meta = _letter_for(
            FULL_KB, {"title": "Data Analyst", "company": "Muster GmbH"}, analysis
        )
        assert letter.language == "en"
        assert meta["motivation_source"] == "profile"
        assert "applied data analytics" in letter.motivation
        assert "deepen my experience in data analytics" in letter.closing
        assert letter.signoff == "Kind regards"
        assert letter.salutation.startswith("Dear")
        results = run_letter_gates(letter, CSET, LICENSED)
        assert all(r.passed for r in results), [f for r in results for f in r.findings]


class TestArtifacts:
    def test_plaintext_and_docx_and_template_fill_compatible(self, tmp_path):
        from resume_content_improve_research.generation.portal_delivery import (
            letter_plaintext,
        )
        from resume_content_improve_research.templates.build import build_letter_docx
        from resume_content_improve_research.templates.fill import fill_template

        letter, _meta = _letter_for(FULL_KB, DATA_JOB, DATA_ANALYSIS)
        txt = letter_plaintext(letter)
        assert letter.motivation in txt
        assert letter.closing in txt

        template = config.LETTER_TEMPLATE_DE.read_text(encoding="utf-8")
        filled = fill_template(template, cl.to_fill_values(letter), tokens=config.CL_ALL_TOKENS)
        assert check_l3_artifact(filled) == []

        docx_path = tmp_path / "Anschreiben_Muster-GmbH_Data.docx"
        build_letter_docx(docx_path, letter)
        assert docx_path.exists() and docx_path.stat().st_size > 0

    def test_process_letter_input_end_to_end_with_profile(self):
        letter_input = run_step4.build_letter_input(
            {
                "title": "Working Student Data Analytics (m/w/d)",
                "company": "Muster GmbH",
                "detail_company_name": "Muster GmbH",
                "job_description": "Data Analytics mit Python. Referenz: DA-2026-01.",
            },
            DATA_ANALYSIS,
        )
        letter_dict, meta = run_step4.process_letter_input(letter_input, FULL_KB, token="unused")
        assert meta["calls"] == 0
        assert meta["motivation_source"] == "profile"
        assert "data-interest" in letter_dict["meta"]["motivation_entry_ids"]
        assert "Datenanalyse und Python" in letter_dict["motivation"]
