"""Probe: call the bot's real upload_resume() against the live form and log
every verification poll to see why the chip is missed."""
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
RESUME = Path("../resume_creation/program_files/output_v2/resume_bosch/pdf/Mandatory-Internship-Model-Based-Systems-Engineering.pdf")
print("resume:", RESUME.name)

orig_body = bot._body_text


def chatty_body(page):
    t = orig_body(page)
    hit = bot._norm_key(RESUME.stem) in bot._norm_key(t)
    print(f"  [poll] body len={len(t)} stem_in_body={hit}")
    if not hit:
        # show the region around 'resume' section text if any
        i = t.lower().find("resume")
        if i >= 0:
            print("  ctx:", t[max(0, i-80):i+220].replace("\n", " ")[:300])
    return t


bot._body_text = chatty_body

with pw.sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome")
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(8_000)
    if bot._detect_captcha(page):
        print("interstitial; waiting...")
        bot._wait_for_manual_captcha_clear(page, 150)
    bot._dismiss_cookie_banner(page)
    page.wait_for_timeout(3_000)
    try:
        name = bot.upload_resume(page, RESUME)
        print("UPLOAD OK:", name)
    except Exception as e:
        print("UPLOAD FAILED:", e)
        page.screenshot(path="results/probe-uploadverify-error.png")
    page.wait_for_timeout(2_000)
    browser.close()
