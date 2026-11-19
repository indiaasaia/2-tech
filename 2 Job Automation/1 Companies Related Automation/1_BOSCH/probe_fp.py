"""Probe: is _detect_captcha false-positiving on a page that is actually clean?
Loads the form, prints body-text matches + frame URLs so we can see the source."""
import importlib.util
import re
from pathlib import Path

import playwright.sync_api as pw

_spec = importlib.util.spec_from_file_location(
    "bosch_bot", Path(__file__).parent / "3_bosch_job_apply.py")
bot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bot)

URL = ("https://jobs.smartrecruiters.com/BoschGroup/"
       "744000149868802-mandatory-internship-model-based-systems-engineering-?oga=true")

with pw.sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome")
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(10_000)

    body = bot._body_text(page)
    m = bot.CAPTCHA_TEXT.search(body)
    print("TEXT match:", m.group(0) if m else None)
    if m:
        i = m.start()
        print("context:", body[max(0, i-200):i+200].replace("\n", " "))
    hits = [f.url for f in page.frames if bot.CAPTCHA_FRAME_URL.search(f.url)]
    print("FRAME hits:", hits)
    print("all frames:", [f.url[:100] for f in page.frames])
    # file inputs actually present?
    n = page.evaluate("""() => { let n=0; const walk=r=>r.querySelectorAll('*').forEach(el=>{ if(el.tagName==='INPUT'&&el.type==='file')n++; if(el.shadowRoot)walk(el.shadowRoot);}); walk(document); return n; }""")
    print("file inputs:", n)
    browser.close()
