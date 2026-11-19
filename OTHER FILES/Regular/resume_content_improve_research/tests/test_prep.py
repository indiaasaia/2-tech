"""Step 6 (plan v3 §6-7): interview prep sheets, learning priorities, requested
documents in bundles, and a headless render of the dashboard pages."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_content_improve_research import config
from resume_content_improve_research.generation import kb_loader
from resume_content_improve_research.generation.keywords import build_keyword_plan
from resume_content_improve_research.generation.portal_delivery import requested_documents
from resume_content_improve_research.verification.keyword_gate import kb_backing
from resume_content_improve_research.verification.prep import (
    learning_priorities,
    prep_markdown,
    write_prep_files,
)

KB = kb_loader.load_kb()
JOB = {"title": "Working Student AI Engineering (m/f/d)", "company": "Muster GmbH",
       "job_url": "https://example.test/ai",
       "job_description": "Build REST APIs in Python and deploy them with Docker on Kubernetes.",
       "requirements": "Python, REST APIs, Docker, Kubernetes. Please attach your Immatrikulationsbescheinigung "
                       "and your transcript of records."}
ANALYSIS = {"language": "en", "required": ["python", "REST APIs", "enrolled student"], "preferred": ["Docker"],
            "tools": ["Kubernetes"], "languages_required": [{"language": "English", "level": "fluent"}]}
PLAN = build_keyword_plan(JOB, ANALYSIS).to_dict()
RECORD = {"job_url": JOB["job_url"], "title": JOB["title"], "company": JOB["company"],
          "analysis": ANALYSIS, "keywords": PLAN, "letter_input": {"posting": JOB, "analysis": ANALYSIS}}


def _result(**over) -> dict:
    backing = kb_backing(PLAN, KB)
    data = {"job_url": JOB["job_url"], "title": JOB["title"], "company": JOB["company"],
            "status": "verified", "pdf": "x/Meetkumar_Raval_CV_Muster-GmbH.pdf",
            "kb_backed_share": backing["kb_backed_share"], "prep_terms": backing["prep_terms"],
            "keyword_gate": {"eligibility": ["enrolled student"], "languages_required": ["English (fluent)"],
                             "education_gaps": []}}
    data.update(over)
    return data


class TestPrepSheet:
    def test_sections(self):
        sheet = prep_markdown(_result(), RECORD, KB)
        assert sheet.startswith("# Interview prep: Working Student AI Engineering (m/f/d) @ Muster GmbH")
        learn = sheet.split("## Learn before the interview")[1].split("##")[0]
        assert "- [ ] Docker" in learn and "- [ ] Kubernetes" in learn and "Python" not in learn
        talk = sheet.split("## Talk about these with real examples")[1].split("##")[0]
        assert "**Python**" in talk and "Software Engineer at Soham Infotech" in talk
        assert "**REST APIs**" in talk
        assert "deploy them with Docker on Kubernetes" in sheet          # the ad's tasks
        assert "Eligibility: enrolled student" in sheet and "English (fluent)" in sheet

    def test_learning_priorities_rank_by_job_count(self):
        results = [_result(company="A", prep_terms=["Docker", "Kubernetes"]),
                   _result(company="B", prep_terms=["Docker"]),
                   _result(company="C", prep_terms=["Docker"], status="gated_failed")]
        ranked = learning_priorities(results)
        assert ranked[0] == {"term": "Docker", "jobs": 2, "companies": ["A", "B"]}
        assert ranked[1]["term"] == "Kubernetes"

    def test_distinct_companies_outrank_one_employers_duplicates(self):
        results = [_result(company="Amazon", prep_terms=["Minitab"]) for _ in range(4)]
        results += [_result(company=c, prep_terms=["Java"]) for c in ("A", "B", "C")]
        assert [p["term"] for p in learning_priorities(results)] == ["Java", "Minitab"]

    def test_write_prep_files(self, tmp_path):
        results = [_result(), _result(status="gated_failed", job_url="other")]
        summary = write_prep_files(results, [RECORD], KB, out_dir=tmp_path)
        assert summary["prep_files"] == 1
        sheet = Path(results[0]["prep_file"])
        assert sheet.parent == tmp_path and sheet.name.startswith("Muster-GmbH_")
        payload = json.loads((tmp_path / "learning_priorities.json").read_text(encoding="utf-8"))
        assert payload["verified_jobs"] == 1 and payload["priorities"][0]["jobs"] == 1
        md = (tmp_path / "learning_priorities.md").read_text(encoding="utf-8")
        assert "| Skill | Companies | Jobs | Who asks |" in md


class TestRequestedDocuments:
    def test_detection_and_configured_files(self):
        docs = {d["name"]: d for d in requested_documents(JOB)}
        assert docs["enrolment_certificate"]["available"] is True
        assert docs["enrolment_certificate"]["path"].endswith("certificate_of_enrolment_small.pdf")
        assert docs["transcript"]["available"] is False                     # not provided in config
        assert "certificates" not in docs

    def test_bundle_lists_missing_and_attach_notes(self):
        from resume_content_improve_research.generation.cover_letter import CoverLetter
        from resume_content_improve_research.generation.portal_delivery import bundle_for

        letter = CoverLetter(language="en", portal="stepstone")
        bundle = bundle_for(JOB, letter, {"letter_pdf": "l.pdf", "resume_pdf": "r.pdf"})
        assert any(m.startswith("transcript (requested by the posting") for m in bundle.missing)
        assert "attach certificate_of_enrolment_small.pdf" in bundle.notes
        assert bundle.artifacts_complete is False

    @pytest.mark.parametrize("text", ["Send your CV and cover letter.", "We transcribe audio."])
    def test_no_false_requests(self, text):
        assert requested_documents({"job_description": text}) == []


def test_dashboard_pages_render_headless():
    """The dashboard reads v2 outputs and its read-only pages render without an exception.
    (Job Tracker is skipped: rendering it persists new Pending rows to job_status.csv.)"""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(config.PROJECT_ROOT / "program_files" / "6_dashboard.py"), default_timeout=60)
    app.run()
    assert not app.exception
    for page in ("Resumes", "Learn Before Interview"):
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page
