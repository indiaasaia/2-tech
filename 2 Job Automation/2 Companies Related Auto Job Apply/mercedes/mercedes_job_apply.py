"""
4_MERCEDES_job_apply.py -- Apply to ONE Mercedes-Benz Tech Innovation job
(MyWorkdayJobs / Workday candidate portal, tenant mercedesbenztechinnovation).

Public API:

    from mercedes_job_apply import apply_to_mercedes_job

    result = apply_to_mercedes_job(JOB_URL, RESUME_PATH, dry_run=True)  # 1. always dry-run first
    if result["status"] == "DRY_RUN":                                   # 2. user verifies
        result = apply_to_mercedes_job(JOB_URL, RESUME_PATH, dry_run=False)  # 3. real submit

Manual use:

    python 4_MERCEDES_job_apply.py --url "<JOB_URL>" --resume "<RESUME_PATH>" --dry-run
    python 4_MERCEDES_job_apply.py --url "<JOB_URL>" --resume "<RESUME_PATH>" --submit

Design rules (mirrors the SAP reference architecture):
- Never invents data. Every answer comes from the ANSWERS spec below or from the
  candidate's own resume autofill.
- Dry-run walks the ENTIRE flow up to the Review page and stops. Submit is only
  clicked in --submit mode after full pre-submit validation.
- CAPTCHA / MFA / human-verification detection stops with status BLOCKED.
- NEEDS_ATTENTION is reported whenever success cannot be strongly proven.

Verified live against MBTI_JOBPORTAL (2026-09-15) via DOM probes:
- Deep /details/... URLs 404; the flow must enter via the portal home, resolve
  the requisition id in the search list, then open /job/<city>/<slug>_<id>.
- Apply button: <a role=button data-automation-id="adventureButton">.
- Start-Your-Application dialog buttons carry data-automation-id
  autofillWithResume / applyManually / useMyLastApplication.
- Steps are an SPA: the URL never changes; the current step is read from the
  progress rail text "current step N of 6".
- Workday picker widgets need: open -> hover option -> JS-click the inner
  [data-automation-id=promptLeafNode] -> verify aria 'checked' flip -> Tab to
  commit. Escape REVERTS uncommitted picker selections - never used to close.
- Date questions are three spinbuttons (Month/Day/Year) with ids ending
  dateSectionMonth-input / -Day- / -Year-; they need real keyboard events.
- Review page Submit reuses data-automation-id="pageFooterNextButton".
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

# ===========================================================================
# CONFIGURATION SECTION - defaults live here; config/candidate.json OVERRIDES
# them when present. Personal data belongs in the JSON, never hardcoded.
# ===========================================================================

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "candidate.json"


def _load_config() -> dict:
    """Optional external candidate profile. If config/candidate.json exists,
    its values OVERRIDE the built-in constants below. Edit the JSON, never the
    source, when your personal data changes."""
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: Could not parse {CONFIG_PATH} ({exc}); using built-in constants.", flush=True)
        return {}


_CONFIG = _load_config()


def _cfg(key: str, default):
    value = _CONFIG.get(key)
    return default if value is None else value


JOB_URL = _cfg(
    "job_url",
    "https://mercedesbenztechinnovation.wd3.myworkdayjobs.com"
    "/en-US/MBTI_JOBPORTAL/details/"
    "Werkstudent-fr-Android-Entwicklung--in-car---m-w-d-x-_R0006909/apply",
)
RESUME_PATH = Path(_cfg("resume_path", r"E:\WorkSpace\2 Tech\Cold Emaling\RAVAL_MEETKUMAR_RESUME.pdf"))

PORTAL_BASE = "https://mercedesbenztechinnovation.wd3.myworkdayjobs.com/en-US/MBTI_JOBPORTAL"

VIEWPORT = {"width": 1440, "height": 1000}
DEFAULT_TIMEOUT_MS = 20_000
HEADLESS = False  # set True for unattended runs; CLI --headless also available


# ---------------------------------------------------------------------------
# ANSWERS - human-confirmed 2026-09-15. Overridable via config/candidate.json.
# ---------------------------------------------------------------------------

# 'Job Portals' is a hierarchical CATEGORY (verified live: clicking it drills
# down, it cannot be selected itself). Its verified children are: Agentur fuer
# Arbeit, Google for Jobs, herCareer, Indeed, Mercedes-Benz career portal,
# Stepstone. The user chose the 'Job Portals' category; the accurate leaf for
# this run is 'Mercedes-Benz career portal' (the portal the application is
# actually made through). No 'Career Fair' option exists anywhere in the tree.
SOURCE_OPTION = _cfg("source_option", "Mercedes-Benz career portal")
SOURCE_CATEGORY = _cfg("source_category", "Job Portals")
GIVEN_NAME = _cfg("given_name", "Meetkumar Riteshkumar")  # user-confirmed correction of parser swap
FAMILY_NAME = _cfg("family_name", "Raval")
STREET = _cfg("street", "Ernestristrasse")  # required by Workday, absent in resume
POSTAL_CODE = _cfg("postal_code", "45141")
CITY = _cfg("city", "Essen")  # required by Workday, absent in resume autofill
PHONE_NATIONAL = _cfg("phone_national", "015567018163")  # digits-only format passes validator

EARLIEST_ENTRY = tuple(_cfg("earliest_entry_date", ["09", "30", "2026"]))  # (month, day, year)
SEVERE_DISABILITY = _cfg("severe_disability", "No")
WORK_PERMIT_OPTION = _cfg(
    "work_permit_option",
    "Yes, I have a work and residence permit for Germany, but I am not a citizen "
    "of a member state of the EU/Iceland/Liechtenstein/Norway/Switzerland",
)
DATA_TRANSFER_OPTION = _cfg(
    "data_transfer_option",
    "Yes, I agree to the transfer of my data within Mercedes-Benz Tech Innovation "
    "and thus have the greatest possible chance of finding a suitable position for me.",
)
GENDER = _cfg("gender", "Male")
DATE_OF_BIRTH = tuple(_cfg("date_of_birth", ["02", "28", "2002"]))
NATIONALITY = _cfg("nationality", "India")
PRONOUN = _cfg("pronoun", "He/Him/His")
TERMS_CHECKBOX_ID = "termsAndConditions--acceptTermsAndAgreements"

RESULT_FILE_PREFIX = "mercedes-R0006909"  # overwritten per-run by requisition id

# ---------------------------------------------------------------------------
# Classifiers
# ---------------------------------------------------------------------------

SUCCESS_TEXT = re.compile(
    r"thank\s+you|application\s+(?:has\s+been\s+)?(?:received|submitted|sent)"
    r"|your\s+application\s+(?:was|has\s+been)\s+submitted"
    r"|vielen\s+dank|we\s+have\s+received\s+your\s+application",
    re.I,
)
HUMAN_VERIFICATION_TEXT = re.compile(
    r"captcha|recaptcha|hcaptcha|verify you are human|human verification"
    r"|are you a robot|multi[- ]factor|two[- ]factor|security code required",
    re.I,
)
CHALLENGE_FRAME_URL = re.compile(
    r"recaptcha/api|hcaptcha\.com|challenges\.cloudflare\.com|captcha-delivery\.com|geetest",
    re.I,
)
STEP_NAMES = [
    "Autofill with Resume",
    "My Information",
    "My Experience",
    "Application Questions",
    "Voluntary Disclosures",
    "Review",
]


# ===========================================================================
# Small helpers
# ===========================================================================

def _log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _requisition_id(job_url: str) -> str:
    match = re.search(r"(R\d{6,})", job_url)
    if not match:
        raise RuntimeError(f"ERROR: Could not extract a requisition id (R...) from URL: {job_url}")
    return match.group(1)


def _validate_resume_path(resume_path: Path) -> Path:
    if not resume_path.exists():
        raise RuntimeError(f"ERROR: Resume file not found: {resume_path}")
    if not resume_path.is_file():
        raise RuntimeError(f"ERROR: Resume path is not a file: {resume_path}")
    if resume_path.suffix.lower() != ".pdf":
        raise RuntimeError(f"ERROR: Resume must be a PDF: {resume_path}")
    return resume_path


# ===========================================================================
# DOM primitives (all verified against the live Workday DOM)
# ===========================================================================

def _body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=8_000)
    except Exception:  # noqa: BLE001
        return ""


def _dismiss_cookie_banner(page) -> bool:
    for name in ("Accept Cookies", "Decline"):
        button = page.get_by_role("button", name=name)
        try:
            if button.count() and button.first.is_visible():
                button.first.click(timeout=4_000)
                page.wait_for_timeout(700)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _detect_human_verification(page) -> bool:
    text = _body_text(page)
    if HUMAN_VERIFICATION_TEXT.search(text):
        return True
    return any(CHALLENGE_FRAME_URL.search(f.url) for f in page.frames)


def _current_step(page) -> tuple[int, str] | None:
    """(step_number, step_name) from the progress rail; None if not found."""
    return page.evaluate(
        """() => {
            const t = document.body.innerText.replace(/\\r/g, '');
            const m = t.match(/current step (\\d) of 6\\s*\\n\\s*([^\\n]+)/);
            return m ? [parseInt(m[1], 10), m[2].trim()] : null;
        }"""
    )


def _wait_for_step(page, expected_name: str, timeout_s: int = 40) -> tuple[int, str]:
    """Wait until the progress rail shows the expected current step."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = _current_step(page)
        if last and expected_name.lower() in last[1].lower():
            return last
        page.wait_for_timeout(1_000)
    raise RuntimeError(
        f"ERROR: Expected step {expected_name!r} never became current "
        f"(last seen: {last})."
    )


def _page_errors(page) -> list[str]:
    errs = page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll(
              '[role=alert], [data-automation-id*=error i], [aria-invalid=true]'
            ).forEach(e => {
                const t = (e.textContent || '').trim().replace(/\\s+/g, ' ');
                if (t && t.length < 300 && out.indexOf(t) === -1) out.push(t);
            });
            return out;
        }"""
    )
    return [e for e in errs if re.search(r"rror|required|must have|valid format|Field and Value", e)]


def _set_input_text(page, el_id: str, value: str) -> bool:
    """Native-setter + React events for a text input; returns success."""
    return page.evaluate(
        """([id, val]) => {
            const el = document.getElementById(id);
            if (!el) return false;
            const proto = el.tagName === 'TEXTAREA'
                ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.blur();
            return true;
        }""",
        [el_id, value],
    )


def _js_click_option(page, visible_text: str) -> str:
    """Click an open dropdown option's inner promptLeafNode (Workday attaches
    its React handler there; a plain Playwright click is unreliable)."""
    return page.evaluate(
        """(txt) => {
            const o = [...document.querySelectorAll('[role=option]')]
                .filter(x => x.offsetParent !== null)
                .find(x => (x.textContent || '').trim() === txt);
            if (!o) return 'not found';
            const inner = o.querySelector('[data-automation-id="promptLeafNode"]') || o;
            inner.click();
            return 'clicked';
        }""",
        visible_text,
    )


def _hover_option(page, visible_text: str) -> bool:
    """Real mouse hover over the option (Workday's virtualized list needs a
    genuine pointer position for its handlers)."""
    opts = page.locator('[role="option"]')
    for i in range(opts.count()):
        o = opts.nth(i)
        try:
            if o.is_visible() and (o.text_content() or "").strip() == visible_text:
                box = o.bounding_box()
                if box:
                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    page.wait_for_timeout(300)
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _options_visible_count(page) -> int:
    return page.evaluate(
        "() => [...document.querySelectorAll('[role=option]')]"
        ".filter(o => o.offsetParent !== null).length"
    )


def _field_area_text(page, daid: str) -> str:
    """Text of a formField widget region - the ground truth for what a picker
    shows as its committed value."""
    return page.evaluate(
        """(d) => {
            const ff = document.querySelector('[data-automation-id="' + d + '"]');
            return ff ? (ff.textContent || '').replace(/\\s+/g, ' ').trim() : null;
        }""",
        daid,
    ) or ""


def _input_summary_text(page, input_id: str) -> str:
    """Text of an input-based picker's widget region (found by climbing
    parents from the input until the 'N items selected' summary appears)."""
    return page.evaluate(
        """(id) => {
            const inp = document.getElementById(id);
            if (!inp) return null;
            let el = inp;
            for (let i = 0; i < 10 && el; i++) {
                el = el.parentElement;
                if (el && /items? selected|Select One/.test(el.textContent || '')) {
                    return (el.textContent || '').replace(/\\s+/g, ' ').trim();
                }
            }
            return null;
        }""",
        input_id,
    ) or ""


def _picker_committed(page, daid: str, text: str) -> bool:
    """Ground truth: does the picker's own widget region show the value?
    Input-based pickers (source) show 'N item(s) selected, ...'; Select One
    widgets live in formField containers and must not say 'Select One'."""
    if daid == "formField-source--source":
        area = _input_summary_text(page, "source--source")
        return bool(re.search(r"[1-9]\d* items? selected", area)) and (text in area)
    area = _field_area_text(page, daid)
    return ("Select One" not in area) and (text in area)


def _close_dropdown(page) -> None:
    """Close any open dropdown WITHOUT Escape (Escape reverts uncommitted
    picks): click a neutral page area and wait for options to disappear."""
    for _ in range(3):
        try:
            page.locator("body").click(position={"x": 700, "y": 120}, timeout=4_000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1_000)
        if not _options_visible_count(page):
            return


# ---------------------------------------------------------------------------
# Pickers
# ---------------------------------------------------------------------------

def _open_picker(page, opener_daid: str, tries: int = 4) -> bool:
    """Open a dropdown. Input-based pickers (multi-select search widgets) are
    opened via their input; 'Select One' widgets via the inner trigger of
    their formField container. Handles popup-overlay interception."""
    ff = page.locator(f"[data-automation-id='{opener_daid}']")
    page.keyboard.press("Escape")  # dismiss stale overlays; picker not open yet
    page.wait_for_timeout(500)
    for _ in range(tries):
        try:
            if opener_daid == "formField-source--source":
                page.locator("#source--source").click(timeout=5_000)
            else:
                trig = ff.locator(
                    "[aria-haspopup='listbox'], [role='combobox'], "
                    "[data-automation-id='promptAriaInstruction']"
                )
                if trig.count():
                    trig.first.click(timeout=5_000)
                else:
                    ff.click(timeout=5_000)
        except Exception:  # noqa: BLE001
            try:
                if opener_daid == "formField-source--source":
                    page.locator("#source--source").click(timeout=5_000, force=True)
                else:
                    trig = ff.locator(
                        "[aria-haspopup='listbox'], [role='combobox'], "
                        "[data-automation-id='promptAriaInstruction']"
                    )
                    if trig.count():
                        trig.first.click(timeout=5_000, force=True)
                    else:
                        ff.click(timeout=5_000, force=True)
            except Exception:  # noqa: BLE001
                page.evaluate(
                    """(d) => {
                        const ff = document.querySelector('[data-automation-id="' + d + '"]');
                        const inp = ff ? ff.querySelector('input') : null;
                        if (inp) { inp.focus(); inp.click(); }
                    }""",
                    opener_daid,
                )
        deadline = time.time() + 6
        while time.time() < deadline:
            if _options_visible_count(page):
                page.wait_for_timeout(1_000)  # hydration margin
                return True
            page.wait_for_timeout(400)
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
    return False


def _select_picker_option(page, opener_daid: str, option_text: str,
                          category: str | None = None, max_rounds: int = 4) -> bool:
    """Select an exact option and verify the FIELD AREA shows it committed.
    For hierarchical pickers, pass category: if the leaf is not in the open
    list, the category is clicked first to drill down."""

    def _leaf_state() -> str | None:
        return page.evaluate(
            """(txt) => {
                const o = [...document.querySelectorAll('[role=option]')]
                    .filter(x => x.offsetParent !== null)
                    .find(x => (x.textContent || '').trim() === txt);
                return o ? (o.getAttribute('aria-label') || '') : null;
            }""",
            option_text,
        )

    for attempt in range(1, max_rounds + 1):
        if _picker_committed(page, opener_daid, option_text):
            return True
        if not _open_picker(page, opener_daid):
            _log(f"    picker {opener_daid[-20:]}", f"attempt {attempt}: would not open")
            _close_dropdown(page)
            continue
        if category and not _leaf_state():
            drill = _js_click_option(page, category)
            page.wait_for_timeout(2_000)
            if not _leaf_state():
                _log(f"    picker {opener_daid[-20:]}",
                     f"attempt {attempt}: drill into {category!r} failed ({drill})")
                _close_dropdown(page)
                continue
        for _ in range(4):
            _hover_option(page, option_text)
            result = _js_click_option(page, option_text)
            if result == "not found":
                break
            page.wait_for_timeout(1_400)
            if _picker_committed(page, opener_daid, option_text):
                break
        if _picker_committed(page, opener_daid, option_text):
            if _options_visible_count(page):
                page.keyboard.press("Tab")  # commit + close (Escape would revert)
                page.wait_for_timeout(1_200)
            _close_dropdown(page)
            return True
        _close_dropdown(page)
    return _picker_committed(page, opener_daid, option_text)


# ---------------------------------------------------------------------------
# Date spinbuttons (Month / Day / Year) - need REAL keyboard events
# ---------------------------------------------------------------------------

def _fill_date_spinbuttons(page, month: str, day: str, year: str) -> dict:
    """Fill the visible dateSection* spinbuttons (MM/DD/YYYY).

    Verified live behavior: Workday ignores synthetic value-setters for these
    (Review then shows 'No Response'), and the three segments auto-advance as
    digits are typed. The reliable method is: JS-focus the MONTH segment,
    confirm document.activeElement, then type the full MMDDYYYY sequence and
    let Workday distribute it. Every attempt is verified against the intended
    date; failures are cleared and retried.
    """
    intended = {"month": str(int(month)), "day": str(int(day)), "year": str(int(year))}
    full_sequence = f"{int(month):02d}{int(day):02d}{int(year):04d}"

    def _read_all() -> dict:
        return page.evaluate(
            """() => {
                const read = (suffix) => {
                    const el = [...document.querySelectorAll('input')]
                        .find(i => i.id.endsWith(suffix));
                    return el ? (el.value || '').trim() : null;
                };
                return {month: read('dateSectionMonth-input'),
                        day: read('dateSectionDay-input'),
                        year: read('dateSectionYear-input')};
            }"""
        )

    last = None
    for attempt in range(1, 4):
        focused = page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('input')]
                    .find(i => i.id.endsWith('dateSectionMonth-input'));
                if (!el) return false;
                el.scrollIntoView({block: 'center'});
                el.focus();
                return document.activeElement === el;
            }"""
        )
        if not focused:
            raise RuntimeError("ERROR: Date fields not found on this page.")
        page.wait_for_timeout(500)
        page.keyboard.press("Delete")  # clear the month segment
        page.wait_for_timeout(200)
        for ch in full_sequence:
            page.keyboard.press(ch)
            page.wait_for_timeout(170)
        page.wait_for_timeout(800)

        got = _read_all()
        last = got
        if all(got.get(k) == intended[k] for k in intended):
            return got
        _log("date", f"attempt {attempt}: fields show {got}, expected {intended}; retrying")
        # clear every segment before the next attempt
        for suffix in ("dateSectionYear-input", "dateSectionDay-input", "dateSectionMonth-input"):
            page.evaluate(
                """(suffix) => {
                    const el = [...document.querySelectorAll('input')]
                        .find(i => i.id.endsWith(suffix));
                    if (el) el.focus();
                }""",
                suffix,
            )
            page.wait_for_timeout(250)
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
            page.wait_for_timeout(200)

    raise RuntimeError(
        f"ERROR: Date fields would not accept {month}/{day}/{year} "
        f"after 3 attempts (last read: {last})."
    )


def _date_fields_present(page) -> bool:
    return page.locator("input[id$='dateSectionMonth-input']").count() > 0


# ---------------------------------------------------------------------------
# My Information helpers
# ---------------------------------------------------------------------------

def _wait_myinfo_autofill(page, timeout_s: int = 60) -> dict:
    """Wait for the resume autofill to populate Given/Family/Email."""
    deadline = time.time() + timeout_s
    vals = {"first": "", "last": "", "email": ""}
    while time.time() < deadline:
        vals = page.evaluate(
            """() => {
                const g = document.getElementById('name--legalName--firstName');
                const f = document.getElementById('name--legalName--lastName');
                const e = document.getElementById('emailAddress--emailAddress');
                return {first: g && g.value, last: f && f.value, email: e && e.value};
            }"""
        )
        if vals.get("first") or vals.get("last") or vals.get("email"):
            return vals
        page.wait_for_timeout(2_000)
    return vals


def _phone_needs_reformat(page) -> bool:
    """True if the current phone value is one Workday rejects. Workday shows
    the error only after a Next attempt; we proactively accept only digit
    strings of plausible national length, else flag."""
    value = page.locator("#phoneNumber--phoneNumber").input_value().strip()
    return bool(re.search(r"[+\s]", value)) or not re.fullmatch(r"\d{7,13}", value)


# ===========================================================================
# Flow steps
# ===========================================================================

def _open_job_and_apply(page, job_url: str, req_id: str) -> None:
    """Enter the portal, resolve the requisition, open details, click Apply,
    verify the Start Your Application dialog."""
    page.goto(PORTAL_BASE, wait_until="load", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(2_500)
    _dismiss_cookie_banner(page)

    # Deep links 404 on this tenant; navigate client-side from the search list.
    title_link = page.locator(f"a[data-automation-id='jobTitle'][href*='{req_id}']")
    if not title_link.count():
        try:
            search = page.get_by_role("textbox", name=re.compile("search", re.I)).first
            if search.count():
                search.click()
                search.fill(req_id)
                page.keyboard.press("Enter")
                page.wait_for_timeout(4_000)
        except Exception:  # noqa: BLE001
            pass
        title_link = page.locator(f"a[data-automation-id='jobTitle'][href*='{req_id}']")
    if not title_link.count():
        raise RuntimeError(
            f"ERROR: Requisition {req_id} not found in the MBTI job portal search list."
        )
    title_link.first.click()
    try:
        page.wait_for_url(re.compile(r"/job/"), timeout=20_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(3_000)
    _dismiss_cookie_banner(page)

    apply_btn = page.get_by_role("button", name="Apply", exact=True)
    if not apply_btn.count():
        raise RuntimeError("ERROR: Apply button not found on the job details page.")
    apply_btn.first.click()

    dialog = page.locator("[role='dialog']")
    try:
        dialog.first.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "ERROR: 'Start Your Application' dialog did not appear after clicking Apply."
        ) from exc
    dialog_text = _norm(dialog.first.inner_text())
    if "Start Your Application" not in dialog_text:
        raise RuntimeError(
            f"ERROR: Unexpected dialog after Apply: {dialog_text[:120]!r}"
        )


def _choose_autofill_with_resume(page) -> None:
    btn = page.locator("[data-automation-id='autofillWithResume']")
    if not btn.count():
        raise RuntimeError(
            "ERROR: 'Autofill with Resume' button not found in the start dialog. "
            "(Refusing to choose Apply Manually or Use My Last Application.)"
        )
    btn.first.click()
    _wait_for_step(page, "Autofill with Resume")


def _upload_resume(page, resume_path: Path) -> str:
    """Upload via the real file input; wait for Workday's 'Successfully
    Uploaded!' state. Returns the filename shown."""
    # The upload widget hydrates lazily after the step renders - wait for it.
    file_input = page.locator("input[type='file']").first
    deadline = time.time() + 25
    while time.time() < deadline and not file_input.count():
        page.wait_for_timeout(1_000)
    if not file_input.count():
        raise RuntimeError("ERROR: Resume file input not found on the upload page (25s wait).")
    file_input.set_input_files(str(resume_path))

    stem = resume_path.stem
    deadline = time.time() + 90
    uploaded = False
    while time.time() < deadline:
        text = _body_text(page)
        if stem in text and "successfully uploaded" in text.lower():
            uploaded = True
            break
        page.wait_for_timeout(2_000)
    if not uploaded:
        raise RuntimeError(
            f"ERROR: Resume upload did not reach 'Successfully Uploaded!' state "
            f"within 90s (file {resume_path.name!r})."
        )
    _log("4/10", "Upload confirmed by page state ('Successfully Uploaded!').")
    return resume_path.name


def _process_my_information(page) -> dict:
    _wait_for_step(page, "My Information")
    info = _wait_myinfo_autofill(page)
    _log("5/10", f"Autofill present: given={info.get('first')!r} family={info.get('last')!r} "
                 f"email={info.get('email')!r}")

    changed = {}

    # -- name correction (user-confirmed parse swap) --
    first_field = page.locator("#name--legalName--firstName")
    last_field = page.locator("#name--legalName--lastName")
    if first_field.input_value().strip() != GIVEN_NAME:
        _set_input_text(page, "name--legalName--firstName", GIVEN_NAME)
        changed["givenName"] = GIVEN_NAME
    if last_field.input_value().strip() != FAMILY_NAME:
        _set_input_text(page, "name--legalName--lastName", FAMILY_NAME)
        changed["familyName"] = FAMILY_NAME

    # -- required address fields missing from resume --
    if not page.locator("#address--addressLine1").input_value().strip():
        _set_input_text(page, "address--addressLine1", STREET)
        changed["street"] = STREET
    if not page.locator("#address--postalCode").input_value().strip():
        _set_input_text(page, "address--postalCode", POSTAL_CODE)
        changed["postalCode"] = POSTAL_CODE
    if not page.locator("#address--city").input_value().strip():
        _set_input_text(page, "address--city", CITY)
        changed["city"] = CITY

    # -- 'How Did You Hear About Us?' (required multi-select) --
    src_field = "formField-source--source"
    if "Select One" in _field_area_text(page, src_field) or not _field_area_text(page, src_field):
        pass  # fresh page shows empty summary
    if SOURCE_OPTION not in _field_area_text(page, src_field) and not _picker_committed(page, src_field, SOURCE_OPTION):
        if not _select_picker_option(page, src_field, SOURCE_OPTION, category=SOURCE_CATEGORY):
            raise RuntimeError(
                f"ERROR: Could not select {SOURCE_OPTION!r} in 'How Did You Hear About Us?'. "
                f"Field area: {_input_summary_text(page, 'source--source')[:120]!r}"
            )
        changed["source"] = SOURCE_OPTION

    # -- phone: keep autofill unless invalid/unset (user-confirmed value) --
    phone_field = page.locator("#phoneNumber--phoneNumber")
    current_phone = phone_field.input_value().strip()
    if not current_phone or _phone_needs_reformat(page):
        _set_input_text(page, "phoneNumber--phoneNumber", PHONE_NATIONAL)
        changed["phone"] = PHONE_NATIONAL

    # -- verify every value we are responsible for --
    checks = {
        "givenName": page.locator("#name--legalName--firstName").input_value().strip() == GIVEN_NAME,
        "familyName": page.locator("#name--legalName--lastName").input_value().strip() == FAMILY_NAME,
        "street": page.locator("#address--addressLine1").input_value().strip() == STREET,
        "postalCode": page.locator("#address--postalCode").input_value().strip() == POSTAL_CODE,
        "source": _picker_committed(page, src_field, SOURCE_OPTION),
        "phone": re.fullmatch(r"\d{7,13}", page.locator("#phoneNumber--phoneNumber").input_value().strip()) is not None,
        "email": bool(page.locator("#emailAddress--emailAddress").input_value().strip()),
        "city": bool(page.locator("#address--city").input_value().strip()),
        "countryCode": bool(page.locator("#phoneNumber--countryPhoneCode").input_value().strip())
                       or bool(re.search(r"[1-9]\d* items? selected",
                                         _input_summary_text(page, "phoneNumber--countryPhoneCode"))),
    }
    failed = [k for k, ok in checks.items() if not ok]
    if failed:
        raise RuntimeError(
            f"ERROR: My Information verification failed for: {failed}. Not continuing."
        )
    return {"autofill": info, "changed": changed, "verified": True}


def _click_next(page) -> None:
    """Click the footer Next (reused as Submit on Review) and wait for the
    page to settle."""
    btn = page.locator(
        "[data-automation-id='pageFooterNextButton'], "
        "[data-automation-id='bottom-next-button'], button:has-text('Next')"
    )
    if not btn.count():
        raise RuntimeError("ERROR: Next button not found.")
    btn.first.click()
    page.wait_for_timeout(2_500)
    try:
        page.wait_for_load_state("networkidle", timeout=12_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1_500)


def _process_my_experience(page) -> dict:
    _wait_for_step(page, "My Experience")
    text = _body_text(page)
    resume_name = None
    match = re.search(r"([\w\-.]+\.pdf)\s*\n?\s*[\d.]+ KB", text)
    if match:
        resume_name = match.group(1)
    return {"documentsShown": resume_name, "modified": False}


def _find_selectone_fields(page) -> list[dict]:
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-automation-id^="formField-"]')]
               .filter(ff => ff.offsetParent !== null)
               .filter(ff => (ff.textContent || '').includes('Select One'))
               .map(ff => ({daid: ff.getAttribute('data-automation-id'),
                            label: (ff.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 120)}))"""
    )


def _map_fields(fields: list[dict], patterns: dict) -> dict:
    """Map formField daids to logical names by label keyword. Ambiguity is an
    error, never a guess."""
    result = {}
    for logical, pattern in patterns.items():
        matches = [f["daid"] for f in fields if re.search(pattern, f["label"], re.I)]
        if len(matches) != 1:
            raise RuntimeError(
                f"ERROR: Could not uniquely identify the {logical!r} field "
                f"(pattern {pattern!r}, matches: {matches})."
            )
        result[logical] = matches[0]
    return result


def _process_application_questions(page) -> dict:
    _wait_for_step(page, "Application Questions")

    # The question widgets render asynchronously after the step becomes current;
    # poll for the date fields instead of failing on the first check.
    deadline = time.time() + 20
    while time.time() < deadline and not _date_fields_present(page):
        page.wait_for_timeout(1_000)
    if not _date_fields_present(page):
        raise RuntimeError("ERROR: 'Earliest possible entry date?' fields not found.")
    date_vals = _fill_date_spinbuttons(page, *EARLIEST_ENTRY)
    if not all(date_vals.values()):
        raise RuntimeError(f"ERROR: Entry date did not take: {date_vals}")

    fields = _find_selectone_fields(page)
    mapping = _map_fields(fields, {
        "disability": r"severe disability|disability",
        "work_permit": r"valid work permit",
        "data_transfer": r"transfer of your data|transfer of my data",
    })
    answers = {
        "disability": SEVERE_DISABILITY,
        "work_permit": WORK_PERMIT_OPTION,
        "data_transfer": DATA_TRANSFER_OPTION,
    }
    values = {}
    for logical, option in answers.items():
        if not _select_picker_option(page, mapping[logical], option):
            raise RuntimeError(
                f"ERROR: Could not select answer for {logical!r}: {option[:80]!r}. "
                f"Field area: {_field_area_text(page, mapping[logical])[:120]!r}"
            )
        values[logical] = option
    return {"entryDate": date_vals, **values}


def _process_voluntary_disclosures(page) -> dict:
    _wait_for_step(page, "Voluntary Disclosures")

    if not _date_fields_present(page):
        raise RuntimeError("ERROR: 'Date of Birth' fields not found on Voluntary Disclosures.")
    dob_vals = _fill_date_spinbuttons(page, *DATE_OF_BIRTH)
    if not all(dob_vals.values()):
        raise RuntimeError(f"ERROR: Date of Birth did not take: {dob_vals}")

    fields = _find_selectone_fields(page)
    mapping = _map_fields(fields, {
        "gender": r"gender",  # label is 'GenderSelect One' - no word boundary
        "nationality": r"nationality",
        "pronoun": r"pronoun",
    })
    answers = {"gender": GENDER, "nationality": NATIONALITY, "pronoun": PRONOUN}
    values = {}
    for logical, option in answers.items():
        if not _select_picker_option(page, mapping[logical], option):
            raise RuntimeError(
                f"ERROR: Could not select {option!r} for {logical!r}. "
                f"Field area: {_field_area_text(page, mapping[logical])[:120]!r}"
            )
        values[logical] = option

    # terms checkbox: check only, never uncheck
    terms = page.locator(f"#{TERMS_CHECKBOX_ID}")
    if not terms.count():
        raise RuntimeError("ERROR: Terms and Conditions checkbox not found.")
    if not terms.is_checked():
        terms.check()
        page.wait_for_timeout(1_000)
    if not terms.is_checked():
        raise RuntimeError("ERROR: Terms checkbox could not be checked.")
    values["termsChecked"] = True
    return {"dateOfBirth": dob_vals, **values}


def _verify_review_page(page) -> dict:
    """Ground-truth verification of the Review page content."""
    report = {"passed": True, "problems": []}

    def problem(msg: str) -> None:
        report["passed"] = False
        report["problems"].append(msg)

    text = _body_text(page)

    if "Review" not in text:
        problem("Review heading not found.")

    for label, expected in [
        ("Given/Family name", f"{GIVEN_NAME} {FAMILY_NAME}"),
        ("Email", "ravalmeett@gmail.com"),  # from autofill, asserted present only
        ("Street", STREET),
        ("Postal/City", POSTAL_CODE),
        ("Source", SOURCE_OPTION),
    ]:
        if expected not in text:
            problem(f"Review does not show expected {label}: {expected!r}")

    if "RAVAL_MEETKUMAR_RESUME" not in text and not re.search(r"\.pdf\s*\n?\s*[\d.]+ KB", text):
        problem("Review does not show an uploaded PDF document.")

    for expected in [
        WORK_PERMIT_OPTION[:60],
        DATA_TRANSFER_OPTION[:60],
        GENDER,
        NATIONALITY,
        PRONOUN,
        "Yes, I have read and consent to the terms and conditions",
    ]:
        if expected not in text:
            problem(f"Review does not show expected value: {expected[:60]!r}")

    # dates: Workday shows 'current value is M/D/YYYY' contextually; absence
    # of 'No Response' next to the date questions is what we can assert.
    if re.search(r"No Response", text):
        problem("Review contains 'No Response' entries (unset required answers).")

    report["problems"] = [p for p in report["problems"]]
    return report


def _find_submit_button(page):
    """The Review page footer button: data-automation-id pageFooterNextButton
    whose text is exactly 'Submit' (verified live)."""
    btn = page.locator("[data-automation-id='pageFooterNextButton']")
    if btn.count() != 1:
        raise RuntimeError(
            f"ERROR: Expected exactly one footer action button on Review, found {btn.count()}."
        )
    name = _norm(btn.first.text_content() or "")
    if not re.fullmatch(r"submit", name, re.I):
        raise RuntimeError(
            f"ERROR: Footer button is named {name!r}, not 'Submit'; refusing to click."
        )
    return btn.first


# ===========================================================================
# Main driver
# ===========================================================================

def apply_to_mercedes_job(job_url: str, resume_path: Path, dry_run: bool = True,
                          headless: bool = HEADLESS) -> dict:
    resume_path = _validate_resume_path(Path(resume_path))
    req_id = _requisition_id(job_url)
    started = time.perf_counter()

    result: dict = {
        "requisitionId": req_id,
        "jobUrl": job_url,
        "resume": str(resume_path),
        "status": "NEEDS_ATTENTION",
        "dryRun": dry_run,
        "startedAt": _now(),
        "finishedAt": None,
        "stagesReached": [],
        "fields": {"changed": {}, "verified": {}, "problems": []},
        "successIndicators": {},
        "errors": [],
        "screenshots": {},
        "notes": [],
    }

    results_dir = Path(__file__).resolve().parent / "results"

    def _shot(page, name: str) -> None:
        results_dir.mkdir(parents=True, exist_ok=True)
        path = results_dir / f"{req_id}-{name}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            result["screenshots"][name] = str(path)
        except Exception as exc:  # noqa: BLE001
            result["notes"].append(f"Could not save screenshot {name}: {exc}")

    def _save() -> None:
        results_dir.mkdir(parents=True, exist_ok=True)
        result["finishedAt"] = _now()
        result["durationSeconds"] = round(time.perf_counter() - started, 1)
        path = results_dir / f"mercedes-{req_id}-result.json"
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Result saved to results/mercedes-{req_id}-result.json", flush=True)

    def _stage(name: str) -> None:
        result["stagesReached"].append(name)

    network_responses: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        def _on_response(response):
            try:
                if response.request.method in ("POST", "PUT"):
                    network_responses.append({
                        "ts": int(time.time() * 1000),
                        "url": response.url[:180],
                        "status": response.status,
                    })
            except Exception:  # noqa: BLE001
                pass

        context.on("response", _on_response)

        try:
            _log("1/10", "Opening Mercedes-Benz job portal and locating the job...")
            _open_job_and_apply(page, job_url, req_id)
            _stage("job_page")
            _shot(page, "01-job-page")

            _log("2/10", "Clicking Apply and verifying Start Your Application dialog...")
            _stage("apply_dialog")

            _log("3/10", "Selecting 'Autofill with Resume'...")
            _choose_autofill_with_resume(page)
            _stage("autofill_with_resume")
            _shot(page, "02-application-start")

            _log("4/10", "Uploading resume...")
            shown = _upload_resume(page, resume_path)
            _stage("resume_uploaded")
            _shot(page, "03-resume-uploaded")
            result["fields"]["verified"]["resume"] = shown

            _log("5/10", "Processing My Information...")
            _click_next(page)
            my_info = _process_my_information(page)
            _stage("my_information")
            _shot(page, "04-my-information")
            result["fields"]["changed"].update(my_info["changed"])

            _log("6/10", "Processing My Experience...")
            _click_next(page)
            experience = _process_my_experience(page)
            _stage("my_experience")
            _shot(page, "05-my-experience")
            result["fields"]["verified"]["experience"] = experience

            _log("7/10", "Filling Application Questions...")
            _click_next(page)
            aq = _process_application_questions(page)
            _stage("application_questions")
            _shot(page, "06-application-questions")
            result["fields"]["verified"]["applicationQuestions"] = aq

            _log("8/10", "Filling Voluntary Disclosures...")
            _click_next(page)
            vd = _process_voluntary_disclosures(page)
            _stage("voluntary_disclosures")
            _shot(page, "07-voluntary-disclosures")
            result["fields"]["verified"]["voluntaryDisclosures"] = vd

            _log("9/10", "Verifying Review page...")
            _click_next(page)
            _wait_for_step(page, "Review")
            page.wait_for_timeout(2_500)
            _stage("review")
            _shot(page, "08-review-before-submit")

            review = _verify_review_page(page)
            result["fields"]["problems"] = review["problems"]
            if not review["passed"]:
                result["status"] = "FAILED"
                _shot(page, "review-validation-failed")
                raise RuntimeError(
                    f"ERROR: Review page verification failed: {review['problems']} "
                    "The application was not submitted."
                )

            if _detect_human_verification(page):
                result["status"] = "BLOCKED"
                _shot(page, "blocked-human-verification")
                raise RuntimeError("BLOCKED: Human verification detected on Review page.")

            if dry_run:
                result["status"] = "DRY_RUN"
                result["notes"].append("DRY RUN: final submission intentionally skipped.")
                _log("10/10", "DRY RUN complete - Submit was NOT clicked.")
                _save()
                print("\nDRY_RUN_COMPLETE\nApplication was NOT submitted.", flush=True)
                return result

            _log("10/10", "Submitting application...")
            submit_btn = _find_submit_button(page)
            submit_started = int(time.time() * 1000)
            submit_btn.scroll_into_view_if_needed()
            submit_btn.click()
            try:
                page.wait_for_load_state("networkidle", timeout=25_000)
            except PlaywrightTimeoutError:
                pass

            # Strong-evidence success check (never trust a click alone)
            confirmation = False
            for _ in range(20):
                page.wait_for_timeout(1_500)
                text = _body_text(page)
                if SUCCESS_TEXT.search(text) or "submitted" in text.lower():
                    confirmation = True
                    break
            result["afterSubmitUrl"] = page.url
            result["successIndicators"] = {
                "confirmationMessage": confirmation,
                "footerSubmitGone": page.locator("[data-automation-id='pageFooterNextButton']").count() == 0,
                "networkResponses": [r for r in network_responses if r["ts"] >= submit_started][-15:],
            }
            _shot(page, "09-after-submit")

            network_ok = any(
                200 <= r["status"] < 300
                for r in result["successIndicators"]["networkResponses"]
            )
            if confirmation and (
                result["successIndicators"]["footerSubmitGone"] or network_ok
            ):
                result["status"] = "SUCCESS"
            else:
                result["status"] = "NEEDS_ATTENTION"
                result["notes"].append(
                    "Post-submit evidence did not meet the strong-evidence threshold."
                )
            _save()
            print(f"\nFinal status: {result['status']}", flush=True)

        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if message.startswith("BLOCKED"):
                result["status"] = "BLOCKED"
            elif result["status"] != "FAILED":
                result["status"] = "NEEDS_ATTENTION"
            result["errors"].append({"type": "automation", "message": message})
            try:
                _shot(page, f"error-{result['status'].lower()}")
            except Exception:  # noqa: BLE001
                pass
            _save()
            print(f"\n{message}", flush=True)
        finally:
            context.close()
            browser.close()

    return result


# ===========================================================================
# CLI
# ===========================================================================

def _pick_resume(requested: str | None, current_url: str | None = None) -> Path:
    """Choose the resume PDF for this run.

    Priority: explicit --resume argument > local job_resume_map_local.csv entry > configured fallback.
    """
    if requested:
        p = Path(requested)
        if p.exists() and p.is_file():
            return p
        print(f"WARNING: requested resume {requested} not found; falling back.")

    target_url = str(current_url or JOB_URL).strip().rstrip("/")
    # 1. Local resume map
    local_map = Path(__file__).resolve().parent / "sub_program_files" / "output" / "job_resume_map_local.csv"
    if local_map.exists():
        try:
            frame = pd.read_csv(local_map, keep_default_na=False)
            for _, row in frame.iterrows():
                r_url = str(row.get("job_url") or "").strip().rstrip("/")
                if r_url == target_url or (target_url and target_url in r_url):
                    pdf_p = Path(str(row.get("resume_pdf") or ""))
                    if pdf_p.exists() and pdf_p.is_file():
                        print(f"Using local tailored resume: {pdf_p.name}")
                        return pdf_p
        except Exception as exc:
            print(f"WARNING: could not read local map {local_map} ({exc})")

    # 2. Configured fallback
    if RESUME_PATH.exists() and RESUME_PATH.is_file():
        return RESUME_PATH

    # 3. Any compiled PDF in local resume directory
    local_pdf_dir = Path(__file__).resolve().parent / "sub_program_files" / "output" / "resume" / "pdf"
    if local_pdf_dir.exists():
        pdfs = list(local_pdf_dir.glob("*.pdf"))
        if pdfs:
            print(f"Using first available local tailored resume: {pdfs[0].name}")
            return pdfs[0]

    return RESUME_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply to ONE Mercedes-Benz Tech Innovation job.")
    parser.add_argument("--url", default=JOB_URL, help="Workday job posting URL")
    parser.add_argument("--resume", default=None,
                        help="Path to the resume PDF (default: tailored resume from step 2, else configured)")
    parser.add_argument("--dry-run", action="store_true", help="Stop before Submit (default)")
    parser.add_argument("--submit", action="store_true", help="Really submit the application")
    parser.add_argument("--headless", action="store_true", help="Run without a visible browser window")
    args = parser.parse_args()

    if args.submit:
        answer = input(
            f"Really SUBMIT this application?\n  url: {args.url}\nType YES to confirm: "
        )
        if answer.strip() != "YES":
            print("Aborted.")
            return 1

    outcome = apply_to_mercedes_job(
        job_url=args.url,
        resume_path=_pick_resume(args.resume, current_url=args.url),
        dry_run=not args.submit,
        headless=args.headless or HEADLESS,
    )
    print(json.dumps(
        {k: outcome[k] for k in ("status", "stagesReached", "fields", "screenshots", "notes")},
        indent=2, default=str,
    ))
    return 0 if outcome["status"] in ("SUCCESS", "DRY_RUN") else 1


if __name__ == "__main__":
    raise SystemExit(main())
