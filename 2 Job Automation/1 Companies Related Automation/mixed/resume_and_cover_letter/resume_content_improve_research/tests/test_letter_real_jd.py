"""Live regression: REAL German DB JD + REAL KB -> step-4 letter path (mocked
LLM body) -> step-5 build_record with tectonic.

Asserts NO L2/G2 false positives on realistic German body text (own skills
mentioned naturally, no English-tech misfires), and that the real KB licenses
the body. Skipped automatically when no LaTeX engine is available.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research import config
from resume_content_improve_research.templates.build import find_latex_engine

pytestmark = pytest.mark.skipif(find_latex_engine() is None, reason="no LaTeX engine (tectonic) available")

# Real German JD fragment (Deutsche Bank entry programme, from the shipped run)
REAL_DE_JOB = {
    "job_url": "https://www.stepstone.de/stellenangebote--Deutsche-Bank.woff",
    "title": "Deutsche Bank Entry level Programme - Investment Bank Corporate Finance - MAECM (m/w/d)",
    "company": "Deutsche Bank",
    "detail_company_name": "Deutsche Bank",
    "source": "stepstone",
    "job_description": (
        "Deutsche Bank ist einer der weltweit führenden Finanzdienstleister. Für unser "
        "Entry Level Programme in der Investment Bank Corporate Finance suchen wir dich. "
        "Referenz: 2025-10-4567. Deine Ansprechpartnerin: Frau Kristina Weber, HR Talent Acquisition. "
        "Du solltest ein abgeschlossenes Studium bzw. aktuelle Fortschritte im Studium mitbringen, "
        "Kenntnisse in Datenanalyse und MS Office, sehr gute Englischkenntnisse und Freude an "
        "quantitativen Themen. Bash, SQL-Kenntnisse sind von Vorteil."
    ),
}

# Body the LLM would realistically produce from the real KB (German, own skills only)
REAL_BODY = {
    "opening": "mit großem Interesse habe ich Ihre Stellenanzeige im Entry Level Programme der "
               "Investment Bank gelesen. Die Verbindung von quantitativen Themen und moderner "
               "Softwareentwicklung spricht mich besonders an.",
    "fit": "Als Software Engineer mit quantitativen Modellen im Trading bringe ich Python, SQL und "
           "Machine Learning mit. Data Analytics und Deep Learning prägen meine bisherige Arbeit in "
           "einem Handelsunternehmen. Bash nutze ich täglich im Entwicklungsalltag.",
    "motivation": "Genau die Kombination aus Finanzwirtschaft und Datenanalyse, die Sie beschreiben, "
                  "suche ich für meinen nächsten Schritt. Ich möchte meine Erfahrung mit Quant-Modellen "
                  "in Ihr Team einbringen und mich fachlich gezielt weiterentwickeln.",
    "closing": "Für ein persönliches Gespräch stehe ich Ihnen gerne zur Verfügung, jederzeit auch per "
               "Video-Konferenz. Ich freue mich auf Ihre Rückmeldung und wünsche Ihnen einen guten Tag.",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(config, "TEX_DIR", tmp_path / "resume" / "tex")
    monkeypatch.setattr(config, "PDF_DIR", tmp_path / "resume" / "pdf")
    monkeypatch.setattr(config, "DOCX_DIR", tmp_path / "resume" / "docx")
    monkeypatch.setattr(config, "LETTERS_TEX_DIR", tmp_path / "letters" / "tex")
    monkeypatch.setattr(config, "LETTERS_PDF_DIR", tmp_path / "letters" / "pdf")
    monkeypatch.setattr(config, "LETTERS_DOCX_DIR", tmp_path / "letters" / "docx")
    monkeypatch.setattr(config, "LETTERS_TXT_DIR", tmp_path / "letters" / "textfield")
    monkeypatch.setattr(config, "RUNS_FAILED_DIR", tmp_path / "failed")


class TestRealGermanJDLetter:
    def test_step6_letter_passes_real_gates(self, monkeypatch):
        """Creation + gating on the REAL German JD through the step-6 path."""
        from resume_content_improve_research import run_step4, run_step6
        from resume_content_improve_research.generation import cover_letter as cl, kb_loader

        kb = kb_loader.load_kb()
        analysis = {"language": "de", "required": ["Datenanalyse", "SQL"],
                    "preferred": ["Englisch"], "tools": ["MS Office", "SQL", "Bash"],
                    "languages_required": [{"language": "English", "level": None}]}

        def fake_call_llm(prompt, token, temperature=0.1, max_tokens=2000, attempts=3):
            import json

            return json.dumps(REAL_BODY)

        monkeypatch.setattr(cl, "call_llm", fake_call_llm)
        record = {
            "job_url": REAL_DE_JOB["job_url"],
            "title": REAL_DE_JOB["title"],
            "company": REAL_DE_JOB["company"],
            "status": "gated_ok",
            "analysis": analysis,
            "letter_input": run_step4.build_letter_input(REAL_DE_JOB, analysis),
            "components": {},
        }
        letter_result = run_step6.build_letter(record, kb, token="tok", engine=find_latex_engine())
        # the REAL-KB-licensed German body passes L1-L4 with ZERO false positives
        assert letter_result["letter_gates"]["L2"]["passed"] is True, letter_result["letter_gates"]["L2"]["findings"]
        # gendered salutation from the real posting's contact person
        assert letter_result["letter"]["salutation"] == "Sehr geehrte Frau Kristina Weber,"
        assert "Referenz" in letter_result["letter"]["subject"]  # German label, not "Reference"

    def test_step6_builds_letter_for_real_job(self, env, monkeypatch):
        """Full step-6 build for the real JD: tectonic PDF + parse-back."""
        from resume_content_improve_research import run_step4, run_step6
        from resume_content_improve_research.generation import cover_letter as cl, kb_loader

        kb = kb_loader.load_kb()
        analysis = {"language": "de", "required": ["Datenanalyse", "SQL"],
                    "preferred": ["Englisch"], "tools": ["MS Office", "SQL", "Bash"],
                    "languages_required": [{"language": "English", "level": None}]}

        def fake_call_llm(prompt, token, temperature=0.1, max_tokens=2000, attempts=3):
            import json

            return json.dumps(REAL_BODY)

        monkeypatch.setattr(cl, "call_llm", fake_call_llm)

        record = {
            "job_url": REAL_DE_JOB["job_url"],
            "title": REAL_DE_JOB["title"],
            "company": REAL_DE_JOB["company"],
            "status": "gated_ok",
            "analysis": analysis,
            "letter_input": run_step4.build_letter_input(REAL_DE_JOB, analysis),
            "components": {},
        }
        letter_result = run_step6.build_letter(record, kb, token="tok", engine=find_latex_engine())
        assert letter_result["letter_gates_passed"] is True, letter_result.get("letter_error")
        artifacts = letter_result["artifacts"]
        assert artifacts["letter_pdf"] and Path(artifacts["letter_pdf"]).exists()

        # parsed-back letter: gendered salutation, German sign-off, reference
        from resume_content_improve_research.verification.parse_sim import parse_pdf

        parsed = parse_pdf(Path(artifacts["letter_pdf"]))
        assert "Sehr geehrte Frau Kristina Weber" in parsed.text
        assert "Deutsche Bank Entry level Programme" in parsed.text
        assert "Referenz: 2025-10-4567" in parsed.text
        txt = Path(artifacts["letter_txt"]).read_text(encoding="utf-8")
        assert "Sehr geehrte Frau Kristina Weber" in txt  # paste-ready .txt carries the salutation too
