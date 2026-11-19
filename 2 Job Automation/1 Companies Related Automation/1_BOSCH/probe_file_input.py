"""Probe: try each file input on the Bosch oneclick form, report which one
shows the resume filename chip in the UI. Read-only diagnostic, never submits."""
import json
import sys
import time
from pathlib import Path

import playwright.sync_api as pw

sys.path.insert(0, str(Path(__file__).parent))
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "bosch_bot", Path(__file__).parent / "3_bosch_job_apply.py")
bot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bot)

URL = sys.argv[1] if len(sys.argv) > 1 else (
    "https://jobs.smartrecruiters.com/BoschGroup/"
    "744000149868802-mandatory-internship-model-based-systems-engineering-?oga=true")
RESUME = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
    r"..\resume_creation\program_files\output_v2\resume_bosch\pdf"
    r"\Mandatory-Internship-Model-Based-Systems-Engineering.pdf")

stem = bot._norm_key(RESUME.stem)

with pw.sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome")
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(6_000)
    # wait for hydration: poll for file inputs up to 60s
    files = []
    for _ in range(30):
        files = [e for e in bot._inventory(page) if e["type"] == "file"]
        if len(files) >= 2:
            break
        page.wait_for_timeout(2_000)
    print(f"file inputs found: {len(files)}")
    for i, e in enumerate(files):
        print(f"  [{i}] label={e.get('label')!r} css={e['cssPath'][:90]}")

    for i, e in enumerate(files):
        css = e["cssPath"]
        label = e.get("label") or ""
        if "profile image" in label.lower():
            print(f"[{i}] skip avatar/profile-image input")
            continue
        try:
            page.locator(css).first.set_input_files(str(RESUME), timeout=10_000)
        except Exception as exc:
            print(f"[{i}] set FAILED: {type(exc).__name__}: {str(exc)[:120]}")
            continue
        # watch for the chip
        found = False
        for _ in range(12):
            body = bot._norm_key(bot._body_text(page))
            if stem in body:
                found = True
                break
            page.wait_for_timeout(2_000)
        print(f"[{i}] css={css[:60]} -> chip={'YES' if found else 'no'}")
        page.screenshot(path=f"results/probe-input-{i}.png")
        if found:
            break

    page.screenshot(path="results/probe-final.png")
    print("done")
    browser.close()
