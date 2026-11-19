"""E2E build test: the TWO-PHASE flow with the real templates + tectonic.

Phase 1 (step 5):  resume record -> build_record -> resume_report.json
Phase 2 (step 6):  build_letter from the SAME record -> letter tex/pdf/docx/txt
                   -> letters_report.json + application_bundles.json

Verifies (skipped automatically if no LaTeX engine):
  - the letter gates L1-L4 pass on a full German letter
  - SEPARATE FILES per letter (Anschreiben_<Company>_<Role>.{tex,pdf,docx,txt})
  - the compiled letter PDF parses back: name, email, phone, DD.MM.YYYY date
  - the resume phase output is untouched by the letter phase
  - a gate-failing letter parks the LETTER only (resume artifacts remain)
All output dirs are redirected to tmp_path (hermetic; no real writes).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from resume_content_improve_research import config
from resume_content_improve_research.templates.build import find_latex_engine

pytestmark = pytest.mark.skipif(find_latex_engine() is None, reason="no LaTeX engine (tectonic) available")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect every output dir to tmp_path; clear the KB lru_cache."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(config, "TEX_DIR", tmp_path / "resume" / "tex")
    monkeypatch.setattr(config, "PDF_DIR", tmp_path / "resume" / "pdf")
    monkeypatch.setattr(config, "DOCX_DIR", tmp_path / "resume" / "docx")
    monkeypatch.setattr(config, "LETTERS_TEX_DIR", tmp_path / "letters" / "tex")
    monkeypatch.setattr(config, "LETTERS_PDF_DIR", tmp_path / "letters" / "pdf")
    monkeypatch.setattr(config, "LETTERS_DOCX_DIR", tmp_path / "letters" / "docx")
    monkeypatch.setattr(config, "LETTERS_TXT_DIR", tmp_path / "letters" / "textfield")
    monkeypatch.setattr(config, "RUNS_FAILED_DIR", tmp_path / "failed")
    # REPORT_PATH is a module-level absolute path, not derived dynamically from
    # OUTPUT_DIR. Redirect every report/manifest path too, or this integration
    # test can overwrite the user's real output_v2 reports.
    monkeypatch.setattr(config, "REPORT_PATH", tmp_path / "resume_report.json")
    monkeypatch.setattr(config, "LETTERS_REPORT_PATH", tmp_path / "letters_report.json")
    monkeypatch.setattr(config, "BUNDLES_PATH", tmp_path / "application_bundles.json")
    return tmp_path


RECORD = {
    "job_url": "https://example.com/job/1",
    "title": "Working Student Data Analytics (m/f/d)",
    "company": "Muster GmbH",
    "status": "gated_ok",
    "analysis": {
        "language": "de",
        "required": ["python", "sql"],
        "preferred": ["datenanalyse"],
        "tools": ["Tableau"],
        "languages_required": [{"language": "German", "level": None}],
    },
    "components": {
        "objective": "Software Engineer mit Quant- und ML-Erfahrung, zielt auf Data-Rollen.",
        "skills_section": {
            "languages": ["Python", "SQL"],
            "specialized_areas": ["Machine Learning"],
            "areas": [
                {"label": "AI und Daten", "skills": ["Python", "Machine Learning"]},
                {"label": "Web und Werkzeuge", "skills": ["SQL", "Django"]},
            ],
        },
        "experiences": [
            {"id": "soham", "role": "Software Engineer", "company": "Soham Infotech",
             "location": "Gujarat, India", "dates": "Dec 2023 - Jan 2025",
             "description": "Entwickelte Quant-Modelle und Echtzeit-Algorithmen.",
             "skills": ["Python", "SQL", "Data Analytics"]},
            {"id": "pantechelearning", "role": "Machine Learning Intern", "company": "Pantechelearning",
             "location": "Chennai, India", "dates": "Dec 2021 - Feb 2022",
             "description": "Implementierte Machine-Learning-Modelle.",
             "skills": ["Machine Learning", "NLP", "Django"]},
        ],
        "projects": [
            {"id": "hft", "title": "High Frequency Trading Platform",
             "description": "Echtzeit-Marktdatensystem mit Quant- und KI-Modellen.",
             "skills": ["Python", "Django", "Data Analytics"]},
            {"id": "resume-gen", "title": "Automated Resume Generation",
             "description": "Open-Source-LLM-System für rollenspezifische Lebensläufe.",
             "skills": ["Python", "Streamlit", "LLM"]},
        ],
        "profile": {"full_name": "RAVAL MEETKUMAR RITESHKUMAR",
                    "contact_line": "ravalmeett@gmail.com | +49 15565 468731"},
    },
    "letter_input": {
        "posting": {
            "title": "Working Student Data Analytics (m/f/d)",
            "company": "Muster GmbH",
            "detail_company_name": "Muster GmbH",
            "source": "stepstone",
            "job_url": "https://example.com/job/1",
            "location": "Essen",
            "detail_location": "Essen, Nordrhein-Westfalen",
            "job_description": "Wir suchen einen Working Student für Data Analytics. Referenz: E2E-2026-001.",
            "about_us": "Muster GmbH ist ein führender Anbieter für Datenlösungen in Essen.",
        },
        "analysis": {
            "language": "de",
            "required": ["python", "sql"],
            "preferred": ["datenanalyse"],
            "tools": ["Tableau"],
            "languages_required": [{"language": "German", "level": None}],
        },
    },
    "gate_findings": [],
    "generation_meta": {"calls": 2},
}

# HERMETICITY: the letter-creation LLM call is mocked with a fixed KB-licensed
# body. Without the mock the call hits the REAL Ollama endpoint (measured: the
# machine's active keys made it succeed — a real 65-word motivation then
# rightly failed L1, and the test was slow and network-dependent).
MOCK_BODY_JSON = '''{
    "opening": "mit großem Interesse habe ich Ihre Stellenanzeige gelesen und mich beworben. Die Rolle verbindet quantitative Arbeit mit moderner Softwareentwicklung und passt zu meinem Profil.",
    "fit": "Als Software Engineer bringe ich Python und SQL mit. Machine Learning und Data Analytics prägen meine bisherige Arbeit. Weitere Erfahrungen mit Datenpipelines fließen in meine tägliche Projektarbeit ein. Deshalb passt mein Profil gut zu Ihrer ausgeschriebenen Position.",
    "motivation": "Die Rolle verbindet Datenanalyse mit Softwareentwicklung. Genau diese Kombination suche ich für meinen nächsten Schritt. Machine Learning und Data Analytics sind der Kern meiner Motivation. Ich möchte meine Erfahrung gezielt in Ihre Aufgaben einbringen und weiter ausbauen.",
    "closing": "Für ein persönliches Gespräch stehe ich Ihnen gerne zur Verfügung. Auch per Video-Konferenz bin ich flexibel erreichbar. Ich freue mich auf Ihre Rückmeldung und wünsche Ihnen einen guten Tag."
}'''


def _mock_llm(monkeypatch) -> dict:
    """Mock the letter-creation LLM call; returns the call counter."""
    from resume_content_improve_research.generation import cover_letter as cl

    calls = {"n": 0}

    def fake_call_llm(prompt, token, temperature=0.1, max_tokens=2000, attempts=3):
        calls["n"] += 1
        return MOCK_BODY_JSON

    monkeypatch.setattr(cl, "call_llm", fake_call_llm)
    return calls


def _write_resume_report(tmp_path: Path, resume_pdf: str, resume_docx: str) -> None:
    """Phase-1 output: what step 5 would have written to resume_report.json."""
    config.REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.REPORT_PATH.write_text(json.dumps({
        "generated_at_utc": "2026-09-23T12:00:00+00:00",
        "engine": "v2",
        "total_jobs": 1,
        "results": [{
            "job_url": RECORD["job_url"],
            "title": RECORD["title"],
            "company": RECORD["company"],
            "status": "verified",
            "pdf": resume_pdf,
            "docx": resume_docx,
            "artifacts": {"resume_pdf": resume_pdf, "resume_docx": resume_docx},
        }],
    }, indent=2), encoding="utf-8")


class TestLetterE2EBuild:
    def test_two_phase_flow_builds_verified_letter(self, env, monkeypatch):
        """Phase 1 (resume) -> phase 2 (letter) with SEPARATE files, both verified."""
        from resume_content_improve_research import run_step5, run_step6
        from resume_content_improve_research.generation import kb_loader

        _mock_llm(monkeypatch)

        # ---- phase 1: the resume builds and its report is written
        result = run_step5.build_record(dict(RECORD), find_latex_engine(), name="test-letter-job")
        assert result["status"] == "verified", result.get("build_error")
        resume_pdf = result["pdf"]
        assert Path(resume_pdf).exists()
        _write_resume_report(env, resume_pdf, result.get("docx", ""))

        # ---- phase 2: the letter, created AFTER the resume work
        kb = kb_loader.load_kb()
        letter_result = run_step6.build_letter(dict(RECORD), kb, token="tok", engine=find_latex_engine())

        assert letter_result["letter_gates_passed"] is True, letter_result.get("letter_error")
        artifacts = letter_result["artifacts"]
        # SEPARATE FILES: Anschreiben_<Company>_<Role>.{tex,pdf,docx,txt}
        assert artifacts["letter_pdf"] and Path(artifacts["letter_pdf"]).exists()
        assert artifacts["letter_docx"] and Path(artifacts["letter_docx"]).exists()
        assert artifacts["letter_txt"] and Path(artifacts["letter_txt"]).exists()
        stem = Path(artifacts["letter_pdf"]).stem
        assert stem.startswith("Anschreiben_Muster-GmbH_"), stem
        assert artifacts["letter_tex"].endswith(f"{stem}.tex")
        # bundle completeness joins the REAL phase-1 resume paths
        assert artifacts["resume_pdf"] == resume_pdf
        assert letter_result["artifacts_complete"], letter_result.get("bundle_missing")

        # the compiled letter PDF parses back: identity + EU contact + date
        from resume_content_improve_research.verification.parse_sim import parse_pdf
        parsed = parse_pdf(Path(artifacts["letter_pdf"]))
        assert "RAVAL" in parsed.text
        assert parsed.email_extracted
        assert parsed.phone_extracted
        import re

        assert re.search(r"\d{2}\.\d{2}\.\d{4}", parsed.text)
        assert "Sehr geehrte Damen und Herren" in parsed.text
        assert "Mit freundlichen Gr" in parsed.text  # ü may extract as composed form
        # one page
        with __import__("pdfplumber").open(artifacts["letter_pdf"]) as pdf:
            assert len(pdf.pages) == 1

    def test_letter_gate_failure_parks_letter_not_resume(self, env):
        """A gate-failing letter parks the LETTER; phase-1 resume artifacts remain."""
        from resume_content_improve_research import run_step5, run_step6
        from resume_content_improve_research.generation import kb_loader

        result = run_step5.build_record(dict(RECORD), find_latex_engine(), name="test-letter-resume")
        assert result["status"] == "verified"
        _write_resume_report(env, result["pdf"], result.get("docx", ""))

        kb = kb_loader.load_kb()
        # legacy migration path: a stored letter with an EMPTY closing must park
        legacy = dict(RECORD)
        # Exercise the legacy stored-letter migration path below. The normal
        # fixture also has letter_input, which correctly takes precedence and
        # would otherwise call the LLM instead of testing the empty closing.
        legacy.pop("letter_input", None)
        legacy["components"] = {**RECORD["components"], "cover_letter": {
            "language": "de",
            "subject": "Working Student Data Analytics (m/f/d) - Reference: E2E-2026-001",
            "salutation": "Sehr geehrte Damen und Herren,",
            "opening": "mit großem Interesse habe ich Ihre Stellenanzeige gelesen und mich beworben.",
            "fit": "Als Software Engineer bringe ich Python und SQL mit. Machine Learning und "
                   "Data Analytics prägen meine bisherige Arbeit. Weitere Erfahrungen fließen in "
                   "meine tägliche Projektarbeit ein. Deshalb passt mein Profil zu Ihrer Position.",
            "motivation": "Die Rolle verbindet Datenanalyse mit Softwareentwicklung. Genau diese "
                          "Kombination suche ich für meinen nächsten Schritt. Machine Learning und "
                          "Data Analytics sind der Kern meiner Motivation. Ich möchte mich einbringen.",
            "closing": "",  # <- trips L1
            "signoff": "Mit freundlichen Grüßen",
            "name_print": "RAVAL MEETKUMAR RITESHKUMAR",
            "sender": {"name": "RAVAL MEETKUMAR", "address": "Ernestinenstraße 21, 45141 Essen, Germany",
                       "contact": "+49 15565 468731 | ravalmeett@gmail.com", "links": ""},
            "company_block": "Muster GmbH\nEssen, Nordrhein-Westfalen",
            "date_line": "Essen, 23.09.2026",
            "reference": "E2E-2026-001",
            "portal": "stepstone",
            "company_name": "Muster GmbH",
            "meta": {},
        }}
        letter_result = run_step6.build_letter(legacy, kb, token="tok", engine=find_latex_engine())

        assert letter_result["letter_gates_passed"] is False
        assert "letter gates failed" in letter_result["letter_error"]
        assert not letter_result["artifacts"].get("letter_pdf")   # letter parked
        assert not letter_result["artifacts_complete"]
        assert Path(result["pdf"]).exists()                       # resume still shipped (phase 1)

    def test_bundles_manifest_from_step6_results(self, env, monkeypatch):
        """The bundles manifest reflects step-6 letter completeness + portal slots."""
        from resume_content_improve_research import run_step6
        from resume_content_improve_research.generation import kb_loader

        _mock_llm(monkeypatch)

        records = [dict(RECORD)]
        resume_pdf = env / "resume.pdf"
        resume_docx = env / "resume.docx"
        resume_pdf.touch()
        resume_docx.touch()
        _write_resume_report(env, str(resume_pdf), str(resume_docx))
        letters = [run_step6.build_letter(dict(RECORD), kb_loader.load_kb(),
                                          token="tok", engine=find_latex_engine())]
        assert letters[0]["letter_gates_passed"] is True, letters[0].get("letter_error")

        report = run_step6._collect_bundles(records, letters)
        assert report["total"] == 1 and report["complete"] == 1
        bundle = report["bundles"][0]
        assert bundle["portal"] == "stepstone"
        assert bundle["status"] == "letters_ok"
        assert bundle["upload_slot"]
