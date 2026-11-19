"""Letter v3 (plan v3 §5): LLM-written body, deterministic logistics, keyword
guarantee, biography gate, repair round and fallback. All LLM output is mocked
(tests/conftest.py blocks live calls)."""
from __future__ import annotations

import pytest

from resume_content_improve_research import run_step4
from resume_content_improve_research.generation import cover_letter as cl
from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.keywords import build_keyword_plan
from resume_content_improve_research.verification.cl_gates import check_l2_truth, run_letter_gates

KB = kb_loader.load_kb()
JOB = {"title": "Working Student AI Engineering (m/f/d)", "company": "Muster GmbH",
       "detail_company_name": "Muster GmbH", "location": "Essen",
       "job_description": "You build REST APIs in Python and Generative AI features.",
       "your_tasks": "Build REST APIs in Python; develop Generative AI features with LLMs.",
       "requirements": "Python, REST APIs, Docker, Kubernetes. Cover letter is optional.",
       "about_us": "Muster GmbH builds logistics software for mid-sized companies."}
ANALYSIS = {"language": "en", "required": ["python", "REST APIs"], "preferred": ["Docker"],
            "tools": ["Kubernetes"], "languages_required": []}
PLAN = build_keyword_plan(JOB, ANALYSIS).to_dict()

CLEAN = ('{"opening": "I am applying for the Working Student AI Engineering position at Muster GmbH. '
         'My MSc Artificial Intelligence and my Software Engineer role at Soham Infotech connect directly to it.",'
         '"fit": "At Soham Infotech I built modular REST APIs and automated data pipelines in Python. '
         'In my Automated Resume Generation project I implemented AI agent workflows with open-source '
         'Large Language Models. I work with Python, REST APIs and Generative AI.",'
         '"motivation": "Muster GmbH builds logistics software for mid-sized companies, a domain where '
         'reliable APIs matter. I want to bring my backend and AI experience to that product."}')
BIOGRAPHY = CLEAN.replace("My MSc Artificial Intelligence", "As a Computer Science student, my background")


def _letter(language: str = "en", title: str = JOB["title"]):
    letter = cl.build_skeleton({**JOB, "title": title}, {**ANALYSIS, "language": language}, KB)
    letter.language = language        # JOB is an English ad; force the language under test
    letter.opening, letter.fit, letter.motivation = "Opening text.", "Fit text.", "Motivation text."
    return letter


def test_skeleton_follows_the_ads_real_language():
    """Regression: an English ad labelled 'de' (Deutsche Bank, 'Düsseldorf' + 'und')
    must still get an English letter."""
    letter = cl.build_skeleton(JOB, {**ANALYSIS, "language": "de"}, KB)
    assert letter.language == "en" and letter.salutation.startswith("Dear")


class TestLogistics:
    def test_english_paragraph_uses_kb_facts(self):
        text = cl.logistics_paragraph(KB, "en", "Working Student AI Engineering")
        assert "until October 2027" in text and "available immediately" in text
        assert "20 hours per week during lecture periods" in text and "up to 40 hours per week" in text
        assert "valid until December 2028" in text
        assert "mandatory internship" not in text            # not an internship role

    def test_internship_roles_mention_the_mandatory_internship(self):
        assert "mandatory internship" in cl.logistics_paragraph(KB, "en", "Internship in Risk 2027")
        de = cl.logistics_paragraph(KB, "de", "Praktikum KI (m/w/d)")
        assert "Pflichtpraktikum" in de and "Oktober 2027" in de and "Dezember 2028" in de
        assert "20 Stunden pro Woche in der Vorlesungszeit" in de

    def test_logistics_pass_the_truth_gate(self):
        letter = _letter()
        letter.closing = cl.logistics_paragraph(KB, "en", JOB["title"])
        cset = cl.build_letter_claimable_set(ANALYSIS, KB, JOB)
        assert check_l2_truth(letter, cset, kb_loader.licensed_digits(KB)) == []


class TestKeywordsAndOptional:
    def test_missing_top_keywords_are_appended_once(self):
        letter = _letter()
        added = cl.ensure_letter_keywords(letter, PLAN)
        assert set(added) >= {"Python", "REST APIs", "Docker", "Kubernetes"}
        assert letter.fit.endswith(".") and "My toolkit also includes" in letter.fit
        assert cl.ensure_letter_keywords(letter, PLAN) == []

    def test_german_sentence(self):
        letter = _letter("de")
        cl.ensure_letter_keywords(letter, PLAN)
        assert "Zu meinen weiteren Kenntnissen gehören" in letter.fit

    @pytest.mark.parametrize("text,expected", [
        ("Cover letter is optional.", True), ("Ein Anschreiben ist nicht erforderlich.", True),
        ("Bewerbung ohne Anschreiben möglich.", True), ("Please send your cover letter.", False),
    ])
    def test_letter_optional(self, text, expected):
        assert cl.letter_optional({"job_description": text}) is expected


class TestBiographyGate:
    def _findings(self, opening: str, title: str = JOB["title"]) -> list[str]:
        letter = _letter(title=title)
        letter.opening = opening
        cset = cl.build_letter_claimable_set(ANALYSIS, KB, JOB)
        return [f for f in check_l2_truth(letter, cset, set()) if "biography" in f]

    @pytest.mark.parametrize("claim", [
        "As a Computer Science student I apply.", "I hold a degree in Informatics.",
        "I am in my third semester.", "With five years of experience I apply.",
        "Mein Informatikstudium passt.", "I am a bachelor's student.",
    ])
    def test_invented_biography_is_flagged(self, claim):
        assert self._findings(claim)

    def test_job_title_is_not_a_biography_claim(self):
        title = "Working Student in Data Science (m/f/d)"
        assert self._findings(f"I am applying for the {title} position.", title=title) == []

    def test_real_degree_passes(self):
        assert self._findings("My MSc Artificial Intelligence at BTU connects to this role.") == []


class TestPrompt:
    def test_prompt_carries_tasks_company_facts_links_and_repair(self):
        letter = _letter()
        prompt = cl._body_prompt(letter, JOB, PLAN, KB, findings=["L2: biography not in the KB"])
        assert "Generative AI features with LLMs" in prompt                    # tasks excerpt
        assert "logistics software for mid-sized companies" in prompt           # About text
        assert "Software Engineer at Soham Infotech: " in prompt and "REST APIs" in prompt
        assert "FAILED THESE CHECKS" in prompt and "L2: biography" in prompt
        assert '{"opening": "...", "fit": "...", "motivation": "..."}' in prompt


class TestStep4Path:
    def _run(self, monkeypatch, replies, verdicts=('{"unsupported": []}',)):
        prompts: list[str] = []
        checks: list[str] = []

        def fake(prompt, token, temperature=0.1, max_tokens=2000, attempts=3):
            if "strict fact checker" in prompt:                 # verify_letter_facts
                checks.append(prompt)
                return verdicts[min(len(checks), len(verdicts)) - 1]
            prompts.append(prompt)
            return replies[min(len(prompts), len(replies)) - 1]

        monkeypatch.setattr(cl, "call_llm", fake)
        letter_input = run_step4.build_letter_input(JOB, ANALYSIS)
        letter_dict, meta = run_step4.process_letter_input(letter_input, KB, token="tok")
        return letter_dict, meta, prompts

    def test_clean_llm_letter_ships_with_logistics_and_keywords(self, monkeypatch):
        letter_dict, meta, prompts = self._run(monkeypatch, [CLEAN])
        assert meta["letter_source"] == "llm" and meta["calls"] == 2      # letter + fact check
        assert letter_dict["subject"].startswith("Application for Working Student AI Engineering")
        assert "until October 2027" in letter_dict["closing"]
        assert "Docker" in letter_dict["fit"] and "Kubernetes" in letter_dict["fit"]   # top keywords guaranteed
        assert meta["letter_optional"] is True

    def test_biography_violation_is_repaired_on_the_second_call(self, monkeypatch):
        letter_dict, meta, prompts = self._run(monkeypatch, [BIOGRAPHY, CLEAN])
        assert meta["letter_source"] == "llm" and meta["calls"] == 3      # 2 letters + 1 fact check
        assert "FAILED THESE CHECKS" in prompts[1] and "Computer Science" not in letter_dict["opening"]

    def test_fact_check_finding_is_repaired(self, monkeypatch):
        """Regression (live Quantum letter): an invented activity passes every keyword
        rule; the fact check sends it back to the repair round."""
        flagged = ('{"unsupported": [{"sentence": "I assessed automation use cases during my internship.", '
                   '"reason": "not in the facts"}]}')
        letter_dict, meta, prompts = self._run(monkeypatch, [CLEAN, CLEAN], verdicts=(flagged, '{"unsupported": []}'))
        assert meta["letter_source"] == "llm" and meta["calls"] == 4
        assert "unsupported claim" in prompts[1]

    def test_flagged_sentence_is_trimmed_not_discarded(self, monkeypatch):
        """Both attempts flag the same invented sentence: it is removed, the rest is
        re-gated and fact-checked again, and the LLM letter ships."""
        invented = CLEAN.replace("connect directly to it.", "connect directly to it. "
                                 "I assessed automation use cases for Muster GmbH.")
        flagged = ('{"unsupported": [{"sentence": "I assessed automation use cases for Muster GmbH.", '
                   '"reason": "not in the facts"}]}')
        letter_dict, meta, _prompts = self._run(
            monkeypatch, [invented, invented], verdicts=(flagged, flagged, '{"unsupported": []}'))
        assert meta["letter_source"] == "llm" and meta["trimmed_sentences"]
        assert "assessed automation" not in letter_dict["opening"]
        assert meta["fact_checks"][-1]["after_trim"] is True
        assert "_claim_sentences" not in meta

    def test_trim_that_guts_the_letter_falls_back(self, monkeypatch):
        """Regression (live SIXT letter): trimming must not ship a skeleton letter."""
        flagged = ('{"unsupported": [{"sentence": "At Soham Infotech I built modular REST APIs and automated data '
                   'pipelines in Python.", "reason": "x"}, {"sentence": "In my Automated Resume Generation project '
                   'I implemented AI agent workflows with open-source Large Language Models.", "reason": "x"}]}')
        letter_dict, meta, _prompts = self._run(monkeypatch, [CLEAN, CLEAN], verdicts=(flagged,))
        assert meta["letter_source"] == "fallback"

    def test_misspelled_employer_is_corrected(self, monkeypatch):
        letter_dict, meta, _prompts = self._run(monkeypatch, [CLEAN.replace("Soham Infotech", "Sohum Infotech")])
        assert "Sohum" not in letter_dict["opening"] + letter_dict["fit"] and meta["name_fixes"]

    def test_invalid_fact_check_never_blocks(self, monkeypatch):
        letter_dict, meta, _prompts = self._run(monkeypatch, [CLEAN], verdicts=("not json",))
        assert meta["letter_source"] == "llm" and meta["fact_checks"][0]["error"]

    def test_persistent_violation_falls_back_to_grounded_letter(self, monkeypatch):
        letter_dict, meta, _prompts = self._run(monkeypatch, [BIOGRAPHY, BIOGRAPHY])
        assert meta["letter_source"] == "fallback"
        assert "Computer Science student" not in " ".join(
            letter_dict[k] for k in ("opening", "fit", "motivation", "closing"))
        letter = cl.letter_from_dict(letter_dict)
        cset = cl.build_letter_claimable_set(ANALYSIS, KB, JOB)
        assert all(r.passed for r in run_letter_gates(letter, cset, kb_loader.licensed_digits(KB)))


def test_compiled_letter_layout(monkeypatch, tmp_path):
    """Built PDF: address block on separate lines, one page, logistics + keywords present."""
    import pdfplumber

    from resume_content_improve_research import config
    from resume_content_improve_research import run_step6
    from resume_content_improve_research.templates.build import find_latex_engine

    engine = find_latex_engine()
    if engine is None:
        pytest.skip("no LaTeX engine")
    for attr, sub in (("LETTERS_TEX_DIR", "tex"), ("LETTERS_PDF_DIR", "pdf"),
                      ("LETTERS_DOCX_DIR", "docx"), ("LETTERS_TXT_DIR", "txt")):
        monkeypatch.setattr(config, attr, tmp_path / sub)
    monkeypatch.setattr(cl, "call_llm", lambda *a, **k: CLEAN)
    letter_dict, _meta = run_step4.process_letter_input(run_step4.build_letter_input(JOB, ANALYSIS), KB, "tok")
    letter = cl.letter_from_dict(letter_dict)
    cl.probe_date_line(letter)
    artifacts, error = run_step6._build_artifacts(letter, "letter_test", engine)
    assert artifacts.get("letter_pdf"), error
    with pdfplumber.open(artifacts["letter_pdf"]) as pdf:
        assert len(pdf.pages) == 1
        lines = [line.strip() for line in pdf.pages[0].extract_text().splitlines()]
    assert "Muster GmbH" in lines and "Essen" in lines        # company block: one item per line
    text = " ".join(lines)
    assert "until October 2027" in text and "Kubernetes" in text


def test_company_names_ending_in_legal_form_letters_are_not_split():
    """Regression: 'Fraunhofer IESE' was read as 'Fraunhofer IE' + 'SE'."""
    from resume_content_improve_research.verification.cl_gates import company_mentions

    assert company_mentions("I admire Fraunhofer IESE and its research.") == []
    assert company_mentions("Muster GmbH and Beispiel AG cooperate.") == ["Muster GmbH", "Beispiel AG"]


def test_letter_file_stem_by_language():
    from resume_content_improve_research.run_step6 import letter_stem_for

    assert letter_stem_for("Werkstudent KI (m/w/d)", "Muster GmbH", "de").startswith(
        "Meetkumar_Raval_Anschreiben_Muster-GmbH_")
    assert letter_stem_for("Working Student AI (m/f/d)", "Muster GmbH", "en").startswith(
        "Meetkumar_Raval_Cover_Letter_Muster-GmbH_")
