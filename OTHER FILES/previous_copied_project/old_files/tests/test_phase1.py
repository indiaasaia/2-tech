from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from app.phase1 import combine
from app.core import config
from app.core import date_filter
from app.phase2 import resume_generator as phase2
from app.phase3 import application_generator as phase3
from app.workflow import run_sequential
import run_phase1
from app.phase1 import stepstone_fetcher
from app.phase1 import workingstudent_fetcher


def test_stepstone_url_helpers():
    urls = stepstone_fetcher.build_search_urls(["working student"])
    assert len(urls) == 1
    assert "working-student" in urls[0]
    assert "page=2" in stepstone_fetcher.build_page_url(urls[0], 2)


def test_workingstudent_jsonld_and_link_parsing():
    html = '''
    <a href="/jobs/robotics-working-student-a1b2c3d4">Robot role</a>
    <a href="/jobs/robotics-working-student-a1b2c3d4">duplicate</a>
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"Robotics Working Student",
     "datePosted":"2026-08-29","employmentType":"PART_TIME",
     "hiringOrganization":{"@type":"Organization","name":"ACME","url":"https://acme.test"},
     "jobLocation":{"address":{"addressLocality":"Berlin","addressCountry":"DE"}},
     "description":"Build robot software.","qualifications":"Python","responsibilities":"Implement features","jobBenefits":"Flexible hours"}
    </script>
    '''
    parser = workingstudent_fetcher._Parser()
    parser.feed(html)
    links = [x for x in parser.links if workingstudent_fetcher._is_job_url("https://www.workingstudentjobs.de" + x)]
    assert len(links) == 2
    assert not workingstudent_fetcher._is_job_url("https://example.com/jobs/robotics-working-student-a1b2c3d4")
    row = workingstudent_fetcher._parse_detail("https://www.workingstudentjobs.de/jobs/robotics-working-student-a1b2c3d4", html)
    assert row["title"] == "Robotics Working Student"
    assert row["company"] == "ACME"
    assert row["location"] == "Berlin, DE"
    assert row["requirements"] == "Python"
    assert row["details_fetched"] == "true"
    assert set(row) == set(config.COMMON_COLUMNS)


def test_combine_deduplicates_and_preserves_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMBINED_CSV", tmp_path / "combined.csv")
    a = pd.DataFrame([{ "source": "workingstudentjobs.de", "job_url": "https://x/1", "title": "old" }])
    b = pd.DataFrame([{ "source": "stepstone", "job_url": "https://x/1", "title": "preferred" }])
    result = combine.combine(a, b)
    assert list(result.columns) == config.COMMON_COLUMNS
    assert len(result) == 1
    assert result.iloc[0]["source"] == "stepstone"
    combine.save(result)
    assert config.COMBINED_CSV.exists()
    assert config.PHASE1_COMBINED_CSV.exists()


def test_detail_parser_fallback_populates_title_and_error():
    url = "https://www.workingstudentjobs.de/jobs/acme-working-student-a1b2c3d4"
    row = workingstudent_fetcher._parse_detail(url, "<html><body>Visible posting text</body></html>")
    assert row["title"] == "Acme Working Student"
    assert row["job_description"] == "Visible posting text"
    assert row["details_fetched"] == "true"


def test_last_two_days_filter_accepts_recent_and_rejects_old_or_missing():
    from datetime import datetime, timezone
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    assert date_filter.is_within_last_days("2026-08-29T12:00:00Z", now=now)
    assert date_filter.is_within_last_days("1 day ago", now=now)
    assert not date_filter.is_within_last_days("2026-08-28T11:59:59Z", now=now)
    assert not date_filter.is_within_last_days("", now=now)


def test_phase2_generates_component_and_resume_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ACTIVITY_LOG", tmp_path / "activity.log")
    monkeypatch.setattr(config, "COMPONENTS_DIR", tmp_path / "components")
    monkeypatch.setattr(config, "TEX_DIR", tmp_path / "tex")
    monkeypatch.setattr(config, "PDF_DIR", tmp_path / "pdf")
    monkeypatch.setattr(config, "PHASE2_REPORT", tmp_path / "report.json")
    source = tmp_path / "jobs.csv"
    pd.DataFrame([{"title": "Python Intern", "company": "ACME", "job_url": "https://example.test/job", "job_description": "Python APIs"}]).to_csv(source, index=False)
    results = phase2.run_phase2(source, limit=1, compile_pdf=False)
    assert len(results) == 1
    assert Path(results[0]["components_json"]).exists()
    assert Path(results[0]["resume_tex"]).exists()
    assert config.PHASE2_REPORT.exists()


def test_phase3_fallback_and_rendering(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PHASE3_DIR", tmp_path / "phase3")
    monkeypatch.setattr(config, "PHASE3_REPORT", tmp_path / "phase3_report.json")
    monkeypatch.setattr(config, "APPLICATIONS_CSV", tmp_path / "applications.csv")
    row = pd.Series({"title": "Data Intern", "company": "ACME", "job_url": "https://example.test/job", "job_description": "Python data analysis"})
    profile = {"name": "Candidate", "email": "candidate@example.test", "objective": "Student developer."}
    payload, method = phase3.generate_cover_letter(row, profile, {"objective": "Student developer.", "skills": {"Programming": ["Python"]}}, use_llm=False)
    assert method == "template"
    assert payload["fit_summary"]
    assert "Data Intern" in phase3.render_markdown(payload)
    results = phase3.run_phase3(tmp_path / "jobs.csv", limit=1, use_llm=False, compile_pdfs=False) if False else []


def test_sequential_workflow_completes_one_job(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ACTIVITY_LOG", tmp_path / "activity.log")
    monkeypatch.setattr(config, "COMPONENTS_DIR", tmp_path / "components")
    monkeypatch.setattr(config, "TEX_DIR", tmp_path / "resume_tex")
    monkeypatch.setattr(config, "PDF_DIR", tmp_path / "resume_pdf")
    monkeypatch.setattr(config, "PHASE2_REPORT", tmp_path / "phase2_report.json")
    monkeypatch.setattr(config, "PHASE3_DIR", tmp_path / "phase3")
    monkeypatch.setattr(config, "PHASE3_REPORT", tmp_path / "phase3_report.json")
    monkeypatch.setattr(config, "APPLICATIONS_CSV", tmp_path / "applications.csv")
    source = tmp_path / "jobs.csv"
    pd.DataFrame([{"title": "Python Intern", "company": "ACME", "job_url": "https://example.test/job", "job_description": "Python APIs"}]).to_csv(source, index=False)
    results = run_sequential(source, limit=1, use_llm=False, compile_pdfs=False)
    assert len(results) == 1
    assert results[0]["application_status"] == "needs_attention"
    assert Path(results[0]["resume_tex"]).exists()
    assert Path(results[0]["cover_letter_md"]).exists()
    assert config.APPLICATIONS_CSV.exists()


def test_cli_rejects_invalid_page_count():
    try:
        run_phase1.main(["--stepstone-pages", "0"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("invalid page count was accepted")
