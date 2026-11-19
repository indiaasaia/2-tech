"""Live probe: run the exact verify-JS from 3_bosch_job_apply.py against the
real Bosch form and print every file input's value. Diagnostic only."""
import importlib.util
import sys
from pathlib import Path

import playwright.sync_api as pw

_spec = importlib.util.spec_from_file_location(
    "bosch_bot", Path(__file__).parent / "3_bosch_job_apply.py")
bot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bot)

URL = ("https://jobs.smartrecruiters.com/BoschGroup/"
       "744000149868802-mandatory-internship-model-based-systems-engineering-?oga=true")
RESUME = Path(r"..\resume_creation\program_files\output_v2\resume_bosch\pdf"
              r"\Mandatory-Internship-Model-Based-Systems-Engineering.pdf").resolve()

VERIFY_JS = """() => {
    let vals = [];
    const walk = (r) => r.querySelectorAll('*').forEach(el => {
        if (el.tagName === 'INPUT' && el.type === 'file' && el.value) vals.push(el.value);
        if (el.shadowRoot) walk(el.shadowRoot);
    });
    walk(document);
    return vals.join(' | ');
}"""

with pw.sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome")
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(8_000)
    if bot._detect_captcha(page):
        print("interstitial present; waiting for it to clear...")
        for _ in range(30):
            page.wait_for_timeout(5_000)
            if not bot._detect_captcha(page):
                break
    print("clean:", not bot._detect_captcha(page))
    # wait for inputs
    for _ in range(30):
        files = [e for e in bot._inventory(page) if e["type"] == "file"]
        if len(files) >= 2:
            break
        page.wait_for_timeout(2_000)
    print("file inputs:", len(files))
    # set the resume into the scoped oc-resume-upload input
    page.locator("oc-resume-upload input[type=file]").first.set_input_files(str(RESUME), timeout=10_000)
    print("set done")
    for i in range(10):
        vals = page.evaluate(VERIFY_JS)
        print(f"t={i*2}s values={vals!r}")
        if "fakepath" in vals.lower():
            print("UPLOAD DETECTED via verify JS")
            break
        page.wait_for_timeout(2_000)
    body = bot._norm_key(bot._body_text(page))
    print("stem in body:", bot._norm_key(RESUME.stem) in body)
    browser.close()
