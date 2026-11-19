"""Deterministic tests for the shadow-DOM apply machinery.

Runs the REAL functions from 3_bosch_job_apply.py (inventory, upload, email,
question grouping/answering, checkbox, submit-button lookup) against a local
fixture that mimics the SmartRecruiters oneclick form: every control lives in
an OPEN shadow root of a spl-* web component.

Run:  python -m pytest tests/test_oneclick_shadow.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (PROJECT_ROOT / "tests" / "oneclick_fixture.html").as_uri()

spec = importlib.util.spec_from_file_location("apply_mod", PROJECT_ROOT / "3_bosch_job_apply.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(10_000)
        page.goto(FIXTURE)
        page.wait_for_timeout(500)
        yield page
        browser.close()


def test_inventory_sees_shadow_controls(page):
    entries = mod._inventory(page)
    types = [e["type"] for e in entries]
    assert "file" in types, f"file input not found: {types}"
    assert "email" in types, f"email input not found: {types}"
    assert "radio" in types, f"radios not found: {types}"
    assert "checkbox" in types, f"checkbox not found: {types}"
    assert "select" in types, f"select not found: {types}"
    assert all(e["inShadow"] for e in entries), "all fixture controls live in shadow roots"


def test_body_text_includes_shadow_content(page):
    text = mod._body_text(page)
    assert "immatrikuliert" in mod._norm_key(text)
    assert "lebenslauf" in mod._norm_key(text)


def test_upload_resume_into_shadow_dropzone(page, tmp_path):
    resume = tmp_path / "TEST_CANDIDATE_RESUME.pdf"
    resume.write_bytes(b"%PDF-1.4 fake")
    shown = mod.upload_resume(page, resume)
    assert shown == "TEST_CANDIDATE_RESUME.pdf"


def test_email_fill_and_readback(page):
    got = mod.fill_email(page, "shadow.test@example.com")
    assert got == "shadow.test@example.com"


def test_question_grouping_and_yesno_in_shadow(page):
    disc = mod.discover_questions(page)
    keys = {g["spec"]["key"] for g in disc["matched"]}
    assert "enrollment" in keys, f"enrollment question not matched: {keys}"
    group = next(g for g in disc["matched"] if g["spec"]["key"] == "enrollment")
    mod._answer_yesno_group(page, group, want_yes=True)
    fresh = mod._resolve_path(page, group["blockPath"], "checked_radios_in").get("values", [])
    assert fresh == ["Ja"]


def test_consent_checkbox_in_shadow(page):
    state = mod.handle_consent(page, allow=True)
    assert state == "checked"


def test_submit_button_lookup(page):
    btn = mod._find_button(page, [r"^weiter$", r"^next$"])
    assert btn is not None, "Weiter/Next button not found by accessible name"


def test_radios_validated_as_one_group(page):
    """Ja/Nein sharing one name must merge into ONE question group."""
    disc = mod.discover_questions(page)
    radio_groups = [g for g in disc["groups"]
                    if any(c["type"] == "radio" for c in g["controls"])]
    names = {c["name"] for g in radio_groups for c in g["controls"] if c.get("name")}
    assert names == {"immatrikulation"}, f"radio grouping broken: {names}"
