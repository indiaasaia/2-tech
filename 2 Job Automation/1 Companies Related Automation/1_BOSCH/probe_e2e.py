"""E2E probe v2: fill via oc-input internal inputs (get_by_label returned an
invisible element), verify input values, click Next, dump page-2 questions.
Never submits."""
import importlib.util
import json
import re
import sys
import time
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

CAND = json.loads((Path(__file__).parent / "config" / "candidate.json").read_text(encoding="utf-8"))
prof = CAND.get("profile", CAND)

with pw.sync_playwright() as p:
    browser = p.chromium.launch(headless=False, channel="chrome")
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(8_000)

    if bot._detect_captcha(page):
        print("interstitial; clearing...")
        if not bot._wait_for_manual_captcha_clear(page, 150):
            print("STILL BLOCKED")
            sys.exit(2)
    bot._dismiss_cookie_banner(page)
    page.wait_for_timeout(3_000)

    # upload resume
    page.locator("oc-resume-upload input[type=file]").first.set_input_files(str(RESUME), timeout=15_000)
    for _ in range(10):
        page.wait_for_timeout(2_000)
        if bot._norm_key(RESUME.stem) in bot._norm_key(bot._body_text(page)):
            print("upload verified"); break

    # fill via JS on the spl-input internal inputs
    fills = [("first-name-input", prof.get("first_name", "")),
             ("last-name-input", prof.get("last_name", ""))]
    # email inputs have no stable id: use two oc-input email-ish fields
    js_fill = """([sel, val]) => {
        const el = document.getElementById(sel);
        if (!el) return 'no-element';
        const set = (inp) => {
            const proto = Object.getPrototypeOf(inp);
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            desc.set.call(inp, val);
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
        };
        if (el.tagName === 'INPUT') { set(el); return 'ok'; }
        const inp = el.querySelector('input') || (el.shadowRoot && el.shadowRoot.querySelector('input'));
        if (!inp) return 'no-input';
        set(inp);
        return 'ok-inner';
    }"""
    for sel, val in fills:
        print(sel, "->", page.evaluate(js_fill, [sel, val]))
    # email fields: pick the two text/email inputs under oc-input whose label text is Email / Confirm
    email_js = """(val) => {
        const out = [];
        const walk = (r) => r.querySelectorAll('*').forEach(el => {
            if (el.tagName === 'OC-INPUT') {
                const lbl = (el.textContent || '').toLowerCase();
                const inp = (el.shadowRoot && el.shadowRoot.querySelector('input')) ||
                            el.querySelector('input');
                if (inp && (lbl.includes('email') || inp.type === 'email')) {
                    const proto = Object.getPrototypeOf(inp);
                    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                    desc.set.call(inp, val);
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                    out.push(lbl.slice(0, 20));
                }
            }
            if (el.shadowRoot) walk(el.shadowRoot);
        });
        walk(document);
        return out;
    }"""
    print("email fills:", page.evaluate(email_js, prof.get("email", "")))

    # verify values
    vals = page.evaluate("""() => { const o=[]; const walk=r=>r.querySelectorAll('*').forEach(el=>{ if(el.tagName==='INPUT' && el.value && el.type!=='file') o.push(el.id+'='+el.value); if(el.shadowRoot)walk(el.shadowRoot);}); walk(document); return o; }""")
    print("input values:", vals)
    page.screenshot(path="results/probe-e2e-2-filled.png")

    # click Next
    page.get_by_role("button", name=re.compile(r"^next$", re.I)).first.click(timeout=8_000)
    print("clicked Next")
    page.wait_for_timeout(10_000)
    page.screenshot(path="results/probe-e2e-3-page2.png", full_page=True)

    # dump page-2 questions
    inv = bot._inventory(page)
    qs = [e for e in inv if e["type"] in ("select", "radio", "checkbox", "textarea") or
          (e["type"] == "text" and e.get("label"))]
    print("page-2 controls:", len(qs))
    for q in qs[:15]:
        print("  -", q["type"], "|", (q.get("label") or q.get("blockText", ""))[:70].replace("\n", " "))
    body2 = bot._body_text(page)
    print("page-2 body snippet:", body2[:600].replace("\n", " | "))
    browser.close()
