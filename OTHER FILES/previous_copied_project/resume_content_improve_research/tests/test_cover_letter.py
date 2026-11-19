"""Unit tests for the cover-letter engine (no LLM, no network).

Covers: deterministic skeleton (subject/reference/salutation/company/portal),
deterministic sign-off, post-check enforcement, fill-values contract,
letter gates L1-L4, plaintext rendering, per-portal bundles.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research import config
from resume_content_improve_research.generation import cover_letter as cl
from resume_content_improve_research.generation.claimable_set import ClaimableSet
from resume_content_improve_research.verification.cl_gates import (
    check_l1_structure,
    check_l2_truth,
    check_l3_artifact,
    check_l4_language,
    run_letter_gates,
)

KB = {
    "profile": {
        "name": "RAVAL MEETKUMAR RITESHKUMAR",
        "display_name": "RAVAL MEETKUMAR",
        "contact": {
            "address": "Ernestinenstraße 21, 45141 Essen, Germany",
            "phone_de": "+49 15565 468731",
            "email": "ravalmeett@gmail.com",
            "linkedin": "https://www.linkedin.com/in/meetraval/",
            "github": "https://github.com/ravalmeet",
        },
    },
    # the claimable set builds from kb['skills'] (global_skill_names) — the
    # mocked letter bodies must be licensed by the KB, exactly like the real KB
    "skills": [
        {"name": "Python", "aliases": [], "evidence": ["master_cv"]},
        {"name": "SQL", "aliases": [], "evidence": ["master_cv"]},
        {"name": "Data Analytics", "aliases": [], "evidence": ["master_cv"]},
        {"name": "Machine Learning", "aliases": [], "evidence": ["master_cv"]},
    ],
}

JOB = {
    "title": "Working Student Data Analytics (m/f/d)",
    "company": "Muster GmbH",
    "source": "stepstone",
    "job_description": "Wir suchen einen Working Student für Data Analytics. Referenz: STX-2026-1188. "
                       "Kontakt: Frau Marlene Schulz, HR.",
    "about_us": "Muster GmbH ist ein führender Anbieter für Datenlösungen in Essen.",
    "detail_company_name": "Muster GmbH",
}


@pytest.fixture
def letter() -> cl.CoverLetter:
    analysis = {"language": "de", "required": ["python", "sql"], "preferred": [], "tools": []}
    return cl.build_skeleton(JOB, analysis, KB)


def make_letter(**overrides) -> cl.CoverLetter:
    base = dict(
        language="de",
        subject="Working Student Data Analytics - Reference: STX-2026-1188",
        salutation="Sehr geehrte Frau Schulz,",
        opening="mit großem Interesse habe ich Ihre Stellenanzeige gelesen.",
        fit="Meine Erfahrung mit Python und SQL passt zu Ihren Anforderungen.",
        motivation="Besonders reizt mich die Rolle, weil ich meine Quant- und ML-Erfahrung einbringen kann.",
        closing="Über ein persönliches Gespräch freue ich mich sehr.",
        signoff="Mit freundlichen Grüßen",
        name_print="RAVAL MEETKUMAR RITESHKUMAR",
        sender_name="RAVAL MEETKUMAR",
        sender_address="Ernestinenstraße 21, 45141 Essen, Germany",
        sender_contact="+49 15565 468731 | ravalmeett@gmail.com",
        sender_links="linkedin | github",
        company_block="Muster GmbH",
        date_line="Essen, 23.09.2026",
        reference="STX-2026-1188",
        portal="stepstone",
        company_name="Muster GmbH",
    )
    base.update(overrides)
    return cl.CoverLetter(**base)


def full_letter(**overrides) -> cl.CoverLetter:
    """A letter with a realistic full-length body (each paragraph <= 55 words,
    total above the L1 stub floor) — the fixture paragraphs alone are ~39 words."""
    letter = make_letter(**overrides)
    extra = " Weitere einschlägige Erfahrungen mit Python, SQL und modernen Datenpipelines prägen meine bisherige Arbeit."
    letter.fit = letter.fit + extra + extra
    letter.motivation = letter.motivation + extra
    letter.closing = letter.closing + extra + extra
    return letter


CSET = ClaimableSet(kb_skills=["python", "sql", "machine learning"], jd_tools=[], required=[],
                    preferred=[], languages_required=[], per_experience={}, per_project={})
LICENSED = {"2023", "2024", "2025", "70", "40"}


class TestSkeleton:
    def test_subject_has_exact_title_and_reference(self, letter):
        assert letter.subject.startswith("Working Student Data Analytics (m/f/d)")
        assert "STX-2026-1188" in letter.subject

    def test_reference_detected(self, letter):
        assert letter.reference == "STX-2026-1188"

    def test_gendered_salutation_with_detected_name(self, letter):
        # the detected FULL name is used ("Sehr geehrte Frau Marlene Schulz,")
        assert letter.salutation == "Sehr geehrte Frau Marlene Schulz,"

    def test_neutral_salutation_when_unnamed(self):
        analysis = {"language": "de"}
        letter = cl.build_skeleton({"title": "X", "company": "Y", "job_description": "Wir suchen dich."},
                                   analysis, KB)
        assert letter.salutation == "Sehr geehrte Damen und Herren,"

    def test_neutral_when_stopword_misfire(self):
        gender, name = cl.detect_contact_person("Ansprechpartner: Frau und Herr Maier")
        assert (gender, name) == ("", "")

    def test_language_follows_analysis(self):
        letter = cl.build_skeleton({"title": "Data Engineer"}, {"language": "en"}, KB)
        assert letter.language == "en"

    def test_portal_from_source(self, letter):
        assert letter.portal == "stepstone"

    def test_company_from_detail_field(self, letter):
        assert letter.company_name == "Muster GmbH"


class TestSignoffDeterminism:
    def test_signoff_is_never_llm_generated(self, letter):
        assert letter.signoff == "Mit freundlichen Grüßen"

    def test_english_letter_gets_english_signoff_in_postcheck(self):
        letter = make_letter(language="en", signoff="Mit freundlichen Grüßen",
                             salutation="Dear Hiring Team,",
                             opening="I read your posting with great interest.",
                             fit="My Python and SQL experience matches your requirements.",
                             motivation="The role is exciting because I can contribute my ML background.",
                             closing="I look forward to discussing this role with you.")
        fixes = cl.postcheck_letter(letter, JOB, CSET)
        assert letter.signoff == "Kind regards"
        assert any("signoff" in f for f in fixes)


class TestPostcheck:
    def test_salutation_enforced_back(self):
        letter = full_letter(salutation="Hallo,")
        cl.postcheck_letter(letter, JOB, CSET)
        assert letter.salutation == "Sehr geehrte Frau Marlene Schulz,"

    def test_markdown_stripped(self):
        letter = make_letter(fit="**Python** and SQL are my tools.")
        fixes = cl.postcheck_letter(letter, JOB, CSET)
        assert "**" not in letter.fit
        assert any("markdown" in f for f in fixes)

    def test_smart_quotes_normalized(self):
        letter = make_letter(opening="ein \u201cBesuch\u201d bei Ihnen.")
        cl.postcheck_letter(letter, JOB, CSET)
        assert "\u201c" not in letter.opening and "\u201d" not in letter.opening


class TestFillValues:
    def test_all_cl_tokens_present(self, letter):
        values = cl.to_fill_values(letter)
        for token in config.CL_ALL_TOKENS:
            assert token in values

    def test_skeleton_tokens_nonempty(self, letter):
        """Body tokens are filled by generation (LLM); everything else must be set."""
        values = cl.to_fill_values(letter)
        body = {config.CL_TOKENS["cl_opening"], config.CL_TOKENS["cl_fit"],
                config.CL_TOKENS["cl_motivation"], config.CL_TOKENS["cl_closing"]}
        for token, value in values.items():
            if token not in body:
                assert value.strip(), f"skeleton token {token} empty"

    def test_date_is_ddmmyyyy(self, letter):
        import re

        values = cl.to_fill_values(letter)
        assert re.fullmatch(r"Essen, \d{2}\.\d{2}\.\d{4}", values["@@CL_DATE_LINE@@"])

    def test_company_block_latex_linebreaks(self, letter):
        letter.company_block = "Muster GmbH\nPersonalabteilung\nHauptstraße 1\n12345 Berlin"
        values = cl.to_fill_values(letter)
        block = values["@@CL_COMPANY_BLOCK@@"]
        assert block.count("\\") == 3  # one escaped backslash between each pair of lines
        assert "\\\\" not in block     # and never a doubled (corrupted) one


class TestL1Structure:
    def test_clean_letter_passes(self):
        assert check_l1_structure(full_letter()) == []

    def test_empty_paragraph_flagged(self):
        findings = check_l1_structure(make_letter(closing=""))
        assert any("'closing'" in f for f in findings)

    def test_overlong_paragraph_flagged(self):
        findings = check_l1_structure(make_letter(fit="wort " * 60))
        assert any("'fit'" in f for f in findings)

    def test_wrong_date_format_flagged(self):
        findings = check_l1_structure(make_letter(date_line="Essen, 2026-09-23"))
        assert any("DD.MM.YYYY" in f for f in findings)

    def test_wrong_signoff_flagged(self):
        findings = check_l1_structure(make_letter(signoff="Cheers"))
        assert any("Grüßen" in f for f in findings)


class TestL2Truth:
    def test_clean_letter_passes(self):
        assert check_l2_truth(make_letter(), CSET, LICENSED) == []

    def test_unlicensed_tech_token_flagged(self):
        findings = check_l2_truth(make_letter(fit="Ich beherrsche Kafka und Airflow sehr gut."), CSET, LICENSED)
        assert any("kafka" in f.lower() for f in findings)

    def test_mirrorable_tool_as_mention_passes(self):
        cset = ClaimableSet(kb_skills=["python"], jd_tools=["kubernetes"], required=[],
                            preferred=[], languages_required=[], per_experience={}, per_project={})
        letter = make_letter(fit="Ich arbeite gezielt auf Kubernetes-Erfahrung hin.")
        assert check_l2_truth(letter, cset, LICENSED) == []

    def test_salary_demand_flagged(self):
        findings = check_l2_truth(make_letter(closing="Mein Gehaltswunsch liegt bei 45000 Euro."), CSET, LICENSED)
        assert any("salary" in f.lower() or "Gehalt" in f for f in findings)

    def test_unlicensed_number_flagged(self):
        findings = check_l2_truth(make_letter(fit="Ich habe 25 Projekte abgeschlossen."), CSET, LICENSED)
        assert any("25" in f for f in findings)

    def test_company_flattery_flagged(self):
        findings = check_l2_truth(make_letter(motivation="Ihre preisgekrönten Produkte begeistern mich."),
                                  CSET, LICENSED)
        assert any("flattery" in f.lower() for f in findings)


class TestL3Artifact:
    def test_clean_text_passes(self):
        assert check_l3_artifact("Sehr geehrte Damen und Herren, ... Mit freundlichen Grüßen") == []

    def test_leftover_tokens_flagged(self):
        assert check_l3_artifact("Brief @@CL_OPENING@@ Text") != []

    def test_markdown_bold_flagged(self):
        assert any("markdown" in f for f in check_l3_artifact("Ich bin **sehr** gut."))


class TestL4Language:
    def test_german_letter_passes(self):
        letter = make_letter(fit="Meine Erfahrung mit Python passt zu Ihren Anforderungen "
                                 "und ich möchte meine Erfahrung als Software Engineer einbringen.")
        assert check_l4_language(letter) == []

    def test_english_body_in_german_letter_flagged(self):
        letter = make_letter(opening="I am writing to apply for this position.",
                             fit="My Python experience fits your requirements well.",
                             motivation="The role excites me because of my background.",
                             closing="I look forward to your reply.")
        findings = check_l4_language(letter)
        assert any("L4" in f for f in findings)

    def test_english_letter_passes(self):
        letter = make_letter(language="en", salutation="Dear Hiring Team,",
                             opening="I am writing to apply for the position of Working Student.",
                             fit="My Python and SQL experience matches the requirements.",
                             motivation="The role appeals to me because of my machine learning background.",
                             closing="I would welcome the opportunity to discuss my application.",
                             signoff="Kind regards")
        assert check_l4_language(letter) == []


class TestLetterGatesRunner:
    def test_all_four_gates_reported(self):
        results = run_letter_gates(full_letter(), CSET, LICENSED, filled_text="Ein Brief ohne Token")
        assert [r.gate for r in results] == ["L1", "L2", "L3", "L4"]
        assert all(r.passed for r in results)

    def test_failing_letter_has_findings(self):
        results = run_letter_gates(make_letter(closing="", signoff="Cheers"), CSET, LICENSED)
        assert not all(r.passed for r in results)


class TestStep4LetterPath:
    """The full step-4 letter path with a MOCKED LLM (no network).

    Regression guard for the measured critical bug: gating the skeleton with
    an empty date_line failed L1 for EVERY letter (the real date is applied at
    fill time), parking all letters at step 4.
    """

    @pytest.fixture
    def mocked_llm(self, monkeypatch):
        calls = {"n": 0}

        def fake_call_llm(prompt, token, temperature=0.1, max_tokens=2000, attempts=3):
            calls["n"] += 1
            if calls["n"] == 1:
                return "{\"opening\":\"hallöchen :)\"}"  # invalid: missing keys
            return ("{\"opening\":\"mit großem Interesse habe ich Ihre Stellenanzeige gelesen und mich beworben.\","
                    "\"fit\":\"Als Software Engineer bringe ich Python und SQL mit, und Machine Learning prägt meine Arbeit. "
                    "Data Analytics ist der Kern meiner bisherigen Projekte. Weitere Erfahrungen mit modernen "
                    "Datenpipelines fließen in meine tägliche Arbeit ein. Genau diese Kombination sucht Ihr Team.\","
                    "\"motivation\":\"Die Rolle verbindet Datenanalyse mit Softwareentwicklung und passt zu meinem Weg. "
                    "Ich möchte meine Erfahrung in Ihre Aufgaben einbringen und gezielt ausbauen mit und für Ihr Team.\","
                    "\"closing\":\"Für ein persönliches Gespräch stehe ich gerne zur Verfügung, auch per Video. "
                    "Ich freue mich auf Ihre Rückmeldung und wünsche einen guten Tag.\"}")

        monkeypatch.setattr(cl, "call_llm", fake_call_llm)
        return calls

    def test_process_letter_input_gates_ok_and_counts_calls(self, mocked_llm):
        from resume_content_improve_research import run_step4
        from resume_content_improve_research.generation import kb_loader

        kb = KB
        analysis = {"language": "de", "required": ["python"], "preferred": [], "tools": []}
        letter_input = run_step4.build_letter_input(JOB, analysis)
        # the posting fields step 6 needs are all present in the payload
        assert letter_input["posting"]["title"] == JOB["title"]
        assert letter_input["posting"]["detail_company_name"] == "Muster GmbH"
        letter_dict, meta = run_step4.process_letter_input(letter_input, kb, token="tok")
        assert letter_dict["language"] == "de"
        assert letter_dict["opening"] and letter_dict["closing"]
        assert meta["calls"] == 0 and meta["deterministic_kb_grounded"] is True
        assert meta["letter_gates"]["L1"]["passed"] is True

    def test_process_letter_input_analysis_override(self, mocked_llm):
        """The override analysis (retailor-refreshed) wins over the stored one."""
        from resume_content_improve_research import run_step4

        stored = {"language": "de", "required": [], "preferred": [], "tools": []}
        refreshed = {"language": "de", "required": ["python"], "preferred": [], "tools": []}
        letter_input = run_step4.build_letter_input(JOB, stored)
        letter_dict, _meta = run_step4.process_letter_input(
            letter_input, KB, token="tok", analysis_dict=refreshed)
        assert letter_dict["language"] == "de"  # creation ran on the refreshed analysis

    def test_gate_failure_raises_with_findings(self, mocked_llm):
        from resume_content_improve_research import run_step4

        analysis = {"language": "de", "required": ["python"], "preferred": [], "tools": []}
        # a posting whose company name is empty trips L1 (company name missing)
        job = {**JOB, "company": "", "detail_company_name": ""}
        letter_input = run_step4.build_letter_input(job, analysis)
        with pytest.raises(RuntimeError, match="letter gates failed"):
            run_step4.process_letter_input(letter_input, KB, token="tok")


class TestRecheckRegressions:
    """Guards for every defect found in the final recheck round."""

    def test_german_today_is_real_berlin_date(self):
        import re
        from datetime import datetime
        from zoneinfo import ZoneInfo

        expected = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y")
        assert cl.german_today() == expected
        assert re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", cl.german_today())

    def test_probe_date_line_uses_german_today_not_hardcoded(self, monkeypatch):
        # inject a fixed date: proves probe_date_line calls german_today() instead
        # of carrying a hardcoded calendar day (the old 23.09.2026 probe).
        monkeypatch.setattr(cl, "german_today", lambda: "01.01.2000")
        letter = make_letter()
        letter.date_line = ""
        cl.probe_date_line(letter)
        assert letter.date_line == "Essen, 01.01.2000"

    def test_fill_reuses_letter_date_never_rederives(self):
        letter = make_letter(date_line="Essen, 01.01.2000")
        values = cl.to_fill_values(letter)
        token = config.CL_TOKENS["cl_date_line"]
        assert "01.01.2000" in values[token]              # letter's own date wins

    def test_reference_prose_is_not_captured(self):
        assert cl.detect_reference("Bitte geben Sie die Referenznummer bitte an.") == ""
        assert cl.detect_reference("Kennziffer des Stellenangebots") == ""
        assert cl.detect_reference("Referenz: STX-2026-1188") == "STX-2026-1188"  # real ref still works

    def test_mixed_pair_or_slash_contacts_get_neutral_salutation(self):
        for text in ("Ansprechpartner: Frau Weber oder Herr Maier",
                     "Frau/Herr Schmidt", "Frau und Herr Maier"):
            gender, name = cl.detect_contact_person(text)
            assert gender == "" and name == "", text

    def test_unknown_city_gives_no_silent_essen(self):
        assert cl._city_from_kb_address("Hauptstraße 1, Deutschland") == ""

    def test_portfolio_link_included_in_sender_links(self):
        kb_portfolio = {**KB, "profile": {**KB["profile"],
                        "contact": {**KB["profile"]["contact"],
                                    "portfolio": "https://raval.vercel.app/"}}}
        letter = cl.build_skeleton(JOB, {"language": "de"}, kb_portfolio)
        assert "raval.vercel.app" in letter.sender_links

    def test_l2_company_gate_flags_unlicensed_mention(self):
        letter = full_letter(motivation="Die Blaupause GmbH ist mir ein Begriff, doch ich bleibe bei den Fakten.")
        findings = check_l2_truth(letter, CSET, LICENSED, own_employers={"soham infotech"})
        assert any("Blaupause" in f for f in findings)

    def test_l2_company_gate_allows_own_employer_and_target(self):
        letter = full_letter(fit="Meine Arbeit bei Soham Infotech mit Python und SQL passt zu Ihren Anforderungen.")
        assert check_l2_truth(letter, CSET, LICENSED, own_employers={"soham infotech"}) == []

    def test_target_company_name_sap_is_not_an_unlicensed_software_claim(self):
        letter = full_letter(company_name="SAP", company_block="SAP SE")
        assert check_l2_truth(letter, CSET, LICENSED, own_employers={"soham infotech"}) == []

    def test_sap_software_claim_remains_gated_when_unlicensed(self):
        letter = full_letter(company_name="Muster GmbH", fit="Ich verwende SAP täglich bei der Arbeit.")
        findings = check_l2_truth(letter, CSET, LICENSED, own_employers={"soham infotech"})
        assert any("SAP" in finding for finding in findings)

    def test_target_company_legal_suffix_fragment_is_not_an_unlicensed_company(self):
        letter = full_letter(company_name="Kautex Textron GmbH & Co.KG",
                             company_block="Kautex Textron GmbH & Co.KG")
        assert check_l2_truth(letter, CSET, LICENSED, own_employers={"soham infotech"}) == []

    def test_target_company_acronym_is_not_an_unlicensed_skill(self):
        letter = full_letter(company_name="Amazon Web Services (AWS)",
                             company_block="Amazon Web Services (AWS)")
        assert check_l2_truth(letter, CSET, LICENSED, own_employers={"soham infotech"}) == []

    def test_aws_skill_claim_remains_gated_for_other_employer(self):
        letter = full_letter(company_name="Muster GmbH", fit="Ich nutze AWS täglich bei der Arbeit.")
        findings = check_l2_truth(letter, CSET, LICENSED, own_employers={"soham infotech"})
        assert any("AWS" in finding for finding in findings)

    def test_l3_exclamation_prose_is_not_a_latex_error(self):
        assert check_l3_artifact("A strong fit! My skills match. ! Undefined things") == []

    def test_l3_still_catches_real_tex_error_lines(self):
        assert check_l3_artifact("! LaTeX Error: File `x.sty' not found.") != []

    def test_word_bounds_come_from_config(self):
        letter = full_letter()
        findings = check_l1_structure(letter)
        assert not any("too short" in f or "one-page norm" in f for f in findings)


class TestPlaintextAndBundles:
    def test_plaintext_contains_all_sections(self, letter):
        from resume_content_improve_research.generation.portal_delivery import letter_plaintext

        text = letter_plaintext(letter)
        for part in (letter.subject, letter.salutation, letter.opening, letter.fit,
                     letter.motivation, letter.closing, letter.signoff, letter.name_print):
            assert part in text

    def test_bundle_complete_when_artifacts_present(self, letter):
        from resume_content_improve_research.generation.portal_delivery import bundle_for

        artifacts = {"letter_pdf": "a.pdf", "letter_docx": "a.docx", "letter_txt": "a.txt",
                     "resume_pdf": "r.pdf", "resume_docx": "r.docx"}
        bundle = bundle_for(JOB, letter, artifacts)
        assert bundle.artifacts_complete and bundle.missing == []
        assert bundle.upload_slot  # guidance present

    def test_stepstone_needs_pdf_not_docx(self, letter):
        from resume_content_improve_research.generation.portal_delivery import bundle_for, PORTAL_REQUIREMENTS

        assert PORTAL_REQUIREMENTS["stepstone"]["docx"] is False
        artifacts = {"letter_pdf": "a.pdf", "letter_docx": "", "letter_txt": "a.txt",
                     "resume_pdf": "r.pdf", "resume_docx": "r.docx"}
        bundle = bundle_for(JOB, letter, artifacts)
        assert bundle.artifacts_complete

    def test_missing_txt_flagged_for_text_field_portals(self):
        from resume_content_improve_research.generation.portal_delivery import bundle_for

        letter = make_letter(portal="linkedin")
        artifacts = {"letter_pdf": "a.pdf", "letter_docx": "", "letter_txt": "",
                     "resume_pdf": "r.pdf", "resume_docx": ""}
        bundle = bundle_for({"source": "linkedin"}, letter, artifacts)
        assert any("letter_txt" in m for m in bundle.missing)
        assert not bundle.artifacts_complete
