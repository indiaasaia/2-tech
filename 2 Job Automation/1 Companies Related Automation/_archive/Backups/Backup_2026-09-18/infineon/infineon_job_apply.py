"""
infineon_job_apply.py -- Apply to ONE Infineon job (Eightfold career site).

Standards: Python + Playwright + Chromium, DOM/semantic selectors only,
no coordinates, no OS file-picker automation, never invent candidate data.

Manual use:
    python infineon_job_apply.py --dry-run --resume "<PATH.pdf>"          # test run, no submit
    python infineon_job_apply.py --submit  --resume "<PATH.pdf>"          # REAL submission (asks YES)
    python infineon_job_apply.py --url "https://jobs.infineon.com/careers/apply?pid=<ID>" ...
    python infineon_job_apply.py --url "https://jobs.infineon.com/careers/job/<ID>" ...   # auto-clicks Apply

Pipeline use:
    from infineon_job_apply import apply_to_infineon_job
    result = apply_to_infineon_job(job_url, resume_path, dry_run=True)

Flow (single long form, sections handled in order):
    open application -> upload resume -> wait for Infineon resume parsing
    -> privacy popup (OK) -> verify autofilled contact info (never overwrite)
    -> position location (leave preselected single location) -> Gender=Male
    -> Country of Residence=Germany -> Language of Application=English
    -> Preferred Start Date=01 Oct 2026 -> Germany-specific disability=No
    -> validate -> stop (dry-run) or Submit application (submit mode)

Exit status is exactly one of: SUCCESS | DRY_RUN | FAILED | BLOCKED | NEEDS_ATTENTION
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Page,
    Locator,
)

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
JOB_RESUME_MAP = ROOT / "program_files" / "output_infineon" / "job_resume_map.csv"

VIEWPORT = {"width": 1440, "height": 1000}
DEFAULT_TIMEOUT_MS = 20_000
RESUME_PROCESSING_WAIT_S = 10          # spec: allow ~10 s after parsing finishes
POPUP_TIMEOUT_MS = 30_000              # privacy popup can lag behind the upload

DEFAULT_JOB_URL = (
    "https://jobs.infineon.com/careers/apply?pid=563808971922747"
)

# ---------------------------------------------------------------------------
# text classifiers
# ---------------------------------------------------------------------------
SUCCESS_TEXT = re.compile(
    r"thank\s+you|application\s+(?:has\s+been\s+)?(?:received|submitted|sent)"
    r"|success(?:fully)?\s+submitted|we\s+have\s+received\s+your\s+application"
    r"|vielen\s+dank|bewerbung\s+(?:erfolgreich|wurde|ist\s+eingegangen)"
    r"|your\s+application\s+was\s+submitted",
    re.I,
)
ERROR_TEXT = re.compile(
    r"something went wrong|an error occurred|technical error|server error"
    r"|upload failed|invalid file|please correct|required field|fehler|ungültig",
    re.I,
)
HUMAN_VERIFICATION_TEXT = re.compile(
    r"captcha|recaptcha|hcaptcha|verify you are human|human verification"
    r"|are you a robot|multi[- ]factor|two[- ]factor|security challenge",
    re.I,
)
CHALLENGE_FRAME_URL = re.compile(
    r"recaptcha/api|hcaptcha\.com|challenges\.cloudflare\.com|captcha-delivery\.com|geetest",
    re.I,
)
PRIVACY_POPUP_TITLE = re.compile(r"privacy\s+policy\s+of\s+the\s+infineon", re.I)
SELECT_PLACEHOLDER = re.compile(
    r"^\s*(select.*|no selection|choose.*|—|-|n/a)\s*$", re.I)

# field label -> exact option text (per spec, sections 8-12).
# All selects are Eightfold custom comboboxes; matching is EXACT - a
# has_text 'Male' filter was proven live to select 'Female' by substring.
FIELD_PLAN = [
    # (label regex, exact option text)
    (re.compile(r"^gender\b", re.I), "Male"),
    (re.compile(r"country\s+of\s+residence", re.I), "Germany"),
    (re.compile(r"language\s+of\s+application", re.I), "English"),
]
DISABILITY_LABEL = re.compile(r"severely\s+disabled", re.I)
START_DATE_LABEL = re.compile(r"preferred\s+start\s+date", re.I)
START_DATE_US = "10/01/2026"       # input parses US MM/DD/YYYY (verified live)
START_DATE_DISPLAY = "01 Oct 2026"  # what the field shows afterwards
CONTACT_LABELS = {
    "first_name": re.compile(r"first\s*name", re.I),
    "last_name": re.compile(r"(last|family)\s*name", re.I),
    "email": re.compile(r"e-?mail", re.I),
    "phone": re.compile(r"phone", re.I),
}
# Stable field IDs verified live on the Infineon (Eightfold) application form
CONTACT_FIELD_IDS = {
    "first_name": "Contact_Information_firstname",
    "last_name": "Contact_Information_lastname",
    "email": "Contact_Information_email",
    "phone": "Contact_Information_phone",
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _job_id(job_url: str) -> str:
    m = re.search(r"pid=(\d+)", job_url) or re.search(r"/careers/job/(\d+)", job_url)
    return m.group(1) if m else "unknown"


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _visible_body_text(page: Page) -> str:
    """Visible text only - text_content() would also match <script> bodies
    (e.g. embedded reCAPTCHA references) and cause false BLOCKED positives."""
    try:
        return _norm(page.locator("body").inner_text(timeout=5_000) or "")
    except Exception:  # noqa: BLE001
        return ""


def _shot(page: Page, name: str) -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:  # noqa: BLE001
        page.screenshot(path=str(path))
    return str(path)


def _detect_human_verification(page: Page) -> bool:
    """True only for a VISIBLE challenge. Eightfold pages embed a hidden
    reCAPTCHA iframe proactively - that alone must not block the run."""
    try:
        for frame in page.frames:
            if not CHALLENGE_FRAME_URL.search(frame.url or ""):
                continue
            try:
                el = frame.frame_element()
                box = el.bounding_box()
                if el.is_visible() and box and box["width"] > 100 and box["height"] > 100:
                    return True
            except Exception:  # noqa: BLE001
                continue  # detached/hidden challenge frame
    except Exception:  # noqa: BLE001
        pass
    return bool(HUMAN_VERIFICATION_TEXT.search(_visible_body_text(page)))


def _pick_resume(job_url: str, explicit_resume: str | None) -> Path:
    """Resolve the resume to upload for this job.

    Priority: explicit --resume path > tailored resume for this job URL from
    program_files/output_infineon/job_resume_map.csv (written by step 5) >
    error. This is what lets a batch driver apply to many jobs, each with its
    own tailored resume, without changing this script.
    """
    if explicit_resume:
        return _validate_resume_path(Path(explicit_resume))
    # the map may hold job-page URLs while the caller passes apply URLs -
    # match by pid (both URL forms carry it), falling back to exact match
    wanted_pid = _job_id(job_url)
    if JOB_RESUME_MAP.exists():
        import csv
        with open(JOB_RESUME_MAP, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                same = (str(row.get("job_url") or "") == job_url
                        or (_job_id(str(row.get("job_url") or "")) == wanted_pid
                            and wanted_pid != "unknown"))
                if same and row.get("status") == "OK" and row.get("resume_pdf"):
                    path = Path(row["resume_pdf"])
                    if path.is_file():
                        _log("resume", f"auto-picked tailored resume: {path.name}")
                        return path
                    raise FileNotFoundError(
                        f"map lists {path} for {job_url} but the file is missing")
    raise FileNotFoundError(
        "no resume given and no tailored resume in job_resume_map.csv "
        "for this job URL - run step 5 or pass --resume")


def _validate_resume_path(resume_path: Path) -> Path:
    path = Path(resume_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Resume not found: {path}")
    if path.suffix.lower() not in {".pdf", ".doc", ".docx"}:
        raise ValueError(f"Resume must be pdf/doc/docx, got: {path.suffix}")
    return path


# ---------------------------------------------------------------------------
# generic form interaction (Eightfold custom dropdowns + native selects)
# ---------------------------------------------------------------------------
def _settle(page: Page, timeout_ms: int = 6_000) -> None:
    """Let SPA rendering/animations finish without a blind fixed wait."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:  # noqa: BLE001
        pass


def _field_container(page: Page, label_re: re.Pattern) -> Locator | None:
    """Locate the form-group containing a label matching label_re."""
    candidates = page.locator(
        "div:has(> label), div:has(> div > label), fieldset:has(label)"
    )
    for i in range(min(candidates.count(), 60)):
        group = candidates.nth(i)
        label = group.locator("label").first
        try:
            text = _norm(label.text_content(timeout=1_000) or "")
        except Exception:  # noqa: BLE001
            continue
        if label_re.search(text):
            return group
    # fallback: label-by-text parent
    try:
        label = page.get_by_text(label_re, exact=False).first
        if label.count():
            return label.locator("xpath=ancestor::div[contains(@class,'form') or self::fieldset][1]")
    except Exception:  # noqa: BLE001
        pass
    return None


def _find_combobox_by_label(page: Page, label_re: re.Pattern) -> Locator | None:
    """Find an Eightfold custom combobox input by its aria-labelledby label.

    Verified live: every select renders as input[role=combobox] whose label
    id lives in aria-labelledby; the current value sits in input_value().
    """
    combos = page.locator("[role='combobox']")
    for i in range(min(combos.count(), 30)):
        combo = combos.nth(i)
        try:
            labelledby = combo.get_attribute("aria-labelledby") or ""
            label_text = ""
            for ref in labelledby.split():
                ref_loc = page.locator(f"#{ref}")
                if ref_loc.count():
                    label_text += (ref_loc.first.inner_text(timeout=1_000) or "") + " "
            # aria-label fallback
            if not label_text.strip():
                label_text = combo.get_attribute("aria-label") or ""
            label_text = _norm(label_text)
        except Exception:  # noqa: BLE001
            continue
        if label_re.search(label_text):
            return combo
    return None


def _open_combobox_options(page: Page, combo: Locator, timeout_ms: int = 6_000) -> list[str]:
    """Open a combobox and return the visible option texts (exact, stripped)."""
    combo.scroll_into_view_if_needed()
    combo.click(timeout=timeout_ms)
    deadline = time.time() + 3
    while time.time() < deadline:
        options = page.locator("[role='option']")
        if options.count():
            texts = []
            for i in range(min(options.count(), 200)):
                try:
                    if options.nth(i).is_visible(timeout=300):
                        texts.append(_norm(options.nth(i).inner_text(timeout=800)))
                except Exception:  # noqa: BLE001
                    continue
            if texts:
                return texts
        page.wait_for_timeout(400)
    return []


def _select_combobox_exact(page: Page, combo: Locator, option_text: str) -> str:
    """Select EXACTLY option_text in an Eightfold combobox and verify.

    Exact equality (case-insensitive) only - substring filters are forbidden
    because 'Male' as has_text matched 'Female' in live testing.
    """
    try:
        current = _norm(combo.input_value(timeout=2_000))
    except Exception:  # noqa: BLE001
        current = ""
    if current.lower() == option_text.lower():
        return current

    last_texts: list[str] = []
    for attempt in range(3):  # clicks occasionally land on a re-rendered node
        texts = _open_combobox_options(page, combo)
        last_texts = texts or last_texts
        page.wait_for_timeout(300)  # let the open list stabilize
        options = page.locator("[role='option']")
        target = None
        for i in range(min(options.count(), 200)):
            try:
                text = _norm(options.nth(i).inner_text(timeout=800))
            except Exception:  # noqa: BLE001
                continue
            if text.lower() == option_text.lower():
                target = options.nth(i)
                break
        if target is None:
            try:
                page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError(
                f"option {option_text!r} not offered exactly; available: {texts!r}"
            )
        try:
            target.scroll_into_view_if_needed()
            target.click(timeout=6_000)
        except Exception:  # noqa: BLE001
            continue  # list re-rendered mid-click -> reopen and retry
        page.wait_for_timeout(600)
        try:
            new_value = _norm(combo.input_value(timeout=2_000))
        except Exception:  # noqa: BLE001
            new_value = ""
        if new_value.lower() == option_text.lower():
            return new_value
        # value did not stick -> close any open list, reopen on next attempt
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(400)
    raise RuntimeError(
        f"combobox verification failed after retries: expected {option_text!r}; "
        f"options seen: {last_texts!r}"
    )


def _read_field_value(group: Locator) -> str:
    """Best-effort read of a field's real current value.

    Strict: empty inputs and 'Select'/'No selection' trigger texts count as
    EMPTY. Never falls back to the group's text_content - that would return
    the label text (e.g. 'Last Name') instead of the value.
    """
    for sel in ["input", "textarea"]:
        loc = group.locator(sel).first
        if loc.count():
            try:
                val = loc.input_value(timeout=2_000)
                if _norm(val):
                    return _norm(val)
            except Exception:  # noqa: BLE001
                pass
    for role in ["combobox", "listbox", "button"]:
        loc = group.get_by_role(role).first
        if loc.count():
            try:
                text = _norm(loc.text_content(timeout=2_000) or "")
                if text and not SELECT_PLACEHOLDER.match(text):
                    return text
            except Exception:  # noqa: BLE001
                pass
    return ""


def _select_option(page: Page, group: Locator, option_text: str) -> str:
    """Select option_text in a field group (native select or custom dropdown).

    Returns the verified visible value afterwards. Raises RuntimeError when
    the exact option cannot be selected - never picks a lookalike.
    """
    # 1) native <select>
    native = group.locator("select").first
    if native.count():
        try:
            options = native.locator("option").all_text_contents()
            match = next((o for o in options if _norm(o).lower() == option_text.lower()), None)
            if match is None:
                raise RuntimeError(
                    f"native select options {options!r} do not contain {option_text!r}"
                )
            native.select_option(label=match)
            page.wait_for_timeout(400)
            return _norm(native.input_value()) or _norm(
                native.locator("option:checked").text_content() or ""
            )
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            pass  # fall through to custom handling

    # 2) custom dropdown: click trigger, pick exact visible option
    trigger = None
    for sel in [
        "[role='combobox']",
        "[aria-haspopup='listbox']",
        "[aria-expanded]",
        "div[class*='select'] >> nth=0",
    ]:
        cand = group.locator(sel).first
        if cand.count():
            trigger = cand
            break
    if trigger is None:
        # MUI-style: the whole group is clickable
        trigger = group.locator("div, span").filter(
            has_text=re.compile(r"no selection|select|choose|—", re.I)
        ).first
        if not trigger.count():
            trigger = group.first

    trigger.scroll_into_view_if_needed()
    trigger.click(timeout=6_000)
    page.wait_for_timeout(600)

    option = page.get_by_role("option", name=_norm(option_text), exact=True).first
    if not option.count():
        option = page.locator(
            "[role='option'], li[role='option'], [role='listbox'] *"
        ).filter(has_text=re.compile(rf"^{re.escape(_norm(option_text))}$", re.I)).first
    if not option.count():
        page.keyboard.press("Escape")
        raise RuntimeError(f"option {option_text!r} not found in opened dropdown")

    option.scroll_into_view_if_needed()
    option.click(timeout=6_000)
    page.wait_for_timeout(500)

    # verify
    try:
        value = _read_field_value(group)
    except Exception:  # noqa: BLE001
        value = ""
    if option_text.lower() not in value.lower():
        raise RuntimeError(f"verification failed: expected {option_text!r}, field shows {value!r}")
    return value


COOKIE_BANNER_BUTTON = re.compile(
    r"accept\s+all|alle\s+akzeptieren|zustimmen|confirm\s+my\s+choices|einverstanden",
    re.I,
)


def _dismiss_cookie_banner(page: Page, timeout_s: int = 15) -> bool:
    """Dismiss the OneTrust cookie-consent banner if present.

    Its dark-filter overlay intercepts every pointer event, so this must
    happen before any other interaction. The standard OneTrust accept button
    id is used directly (on Infineon its text is just 'Accept'); reject is a
    safe fallback that also removes the overlay.
    """
    deadline = time.time() + timeout_s
    clicked = False
    while time.time() < deadline and not clicked:
        for sel in ["#onetrust-accept-btn-handler", "#onetrust-reject-all-handler"]:
            loc = page.locator(sel)
            if not loc.count():
                continue
            try:
                if loc.first.is_visible(timeout=500):
                    loc.first.click(timeout=4_000)
                    clicked = True
                    _log("cookies", f"cookie banner dismissed via {sel}")
                    break
            except Exception:  # noqa: BLE001
                continue
        if not clicked:
            page.wait_for_timeout(1_000)
    if clicked:
        try:
            page.locator(".onetrust-pc-dark-filter").first.wait_for(
                state="hidden", timeout=8_000)
        except Exception:  # noqa: BLE001
            page.wait_for_timeout(2_000)
    return clicked


def _confirm_resume_upload(page: Page, timeout_s: int = 45) -> bool:
    """Click the upload-confirmation dialog button (#confirmUploadResume).

    Eightfold shows a dialog after the file is chosen; resume parsing only
    starts after it is confirmed.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        btn = page.locator(
            "#confirmUploadResume, [data-test-id='confirm-upload-resume']").first
        if btn.count():
            try:
                if btn.is_visible(timeout=500):
                    btn.click(timeout=8_000)
                    _log("resume", "upload confirmed via confirm-upload dialog")
                    return True
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(1_000)
    return False


def _handle_privacy_popup(page: Page, timeout_ms: int = POPUP_TIMEOUT_MS) -> str:
    """Wait for the 'Privacy Policy of the Infineon Group' popup and click OK.

    Returns 'ok-clicked' | 'not-present'. Never clicks Cancel.
    """
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if _detect_human_verification(page):
            raise RuntimeError("BLOCKED: human-verification challenge detected")
        dialogs = page.locator(
            "[role='dialog'], [role='alertdialog'], div[class*='modal'], div[class*='Modal']"
        )
        for i in range(min(dialogs.count(), 6)):
            dialog = dialogs.nth(i)
            try:
                if not dialog.is_visible(timeout=500):
                    continue
                title = _norm(dialog.inner_text(timeout=1_000) or "")
            except Exception:  # noqa: BLE001
                continue

            # privacy-policy modal -> exact OK button, never Cancel
            if PRIVACY_POPUP_TITLE.search(title):
                ok_btn = dialog.get_by_role("button", name=re.compile(r"^ok$", re.I)).first
                if not ok_btn.count():
                    # last resort: a button whose entire text is OK
                    ok_btn = dialog.locator(
                        "button").filter(has_text=re.compile(r"^\s*ok\s*$", re.I)).first
                if not ok_btn.count():
                    raise RuntimeError("privacy popup found but no OK button - refusing to guess")
                try:
                    ok_btn.scroll_into_view_if_needed()
                    ok_btn.click(timeout=6_000)
                    dialog.wait_for(state="hidden", timeout=8_000)
                    _log("popup", "Privacy popup confirmed and closed via OK")
                    return "ok-clicked"
                except Exception as exc:  # noqa: BLE001
                    _log("popup", f"OK click failed, retrying: {exc}")
                    continue

            # resume-processing confirmation dialog -> confirm button
            confirm = dialog.locator("#confirmUploadResume, [data-test-id='confirm-upload-resume']").first
            if confirm.count():
                try:
                    confirm.scroll_into_view_if_needed()
                    confirm.click(timeout=6_000)
                    try:
                        dialog.wait_for(state="hidden", timeout=8_000)
                    except PlaywrightTimeoutError:
                        pass
                    _log("popup", "Resume-processing dialog confirmed")
                    return "resume-confirm-clicked"
                except Exception as exc:  # noqa: BLE001
                    _log("popup", f"resume-confirm click failed: {exc}")
                    continue
        page.wait_for_timeout(1_000)
    return "not-present"


def _wait_resume_processing(page: Page, resume_name: str) -> dict:
    """Wait for upload + parsing: file chip visible, then contact autofill or settle."""
    stem = Path(resume_name).stem
    chip = page.get_by_text(re.compile(re.escape(stem[:24]), re.I)).first
    chip_seen = False
    try:
        chip.wait_for(state="visible", timeout=20_000)
        chip_seen = True
    except PlaywrightTimeoutError:
        _log("resume", "file chip not found by name; continuing with settle-wait")

    # parsing is asynchronous: done when the email input carries a value
    contact_filled = False
    email_loc = page.locator(f"#{CONTACT_FIELD_IDS['email']}")
    deadline = time.time() + 90
    while time.time() < deadline:
        if email_loc.count():
            try:
                if _norm(email_loc.first.input_value(timeout=2_000)):
                    contact_filled = True
                    break
            except Exception:  # noqa: BLE001
                pass
        page.wait_for_timeout(2_000)

    if contact_filled:
        page.wait_for_timeout(RESUME_PROCESSING_WAIT_S * 1000)  # spec: ~10 s settle
    _settle(page)
    return {"chip_seen": chip_seen, "autofill_window_waited": contact_filled}


def _verify_contact_information(page: Page) -> dict:
    """Read-only verification of autofilled contact info. NEVER overwrites.

    Uses the stable field IDs (verified live) first, label lookup as fallback.
    """
    report: dict[str, str] = {}
    for key, field_id in CONTACT_FIELD_IDS.items():
        loc = page.locator(f"#{field_id}")
        value = ""
        if loc.count():
            try:
                value = _norm(loc.first.input_value(timeout=3_000))
            except Exception:  # noqa: BLE001
                value = ""
        if not value:
            group = _field_container(page, CONTACT_LABELS[key])
            value = _read_field_value(group) if group else ""
        report[key] = value
    # country phone code: combobox with placeholder 'Select country code'
    # (verified live: value renders like '🇩🇪 (+49) Germany')
    cc = ""
    cc_combo = page.locator(
        "input[role='combobox'][placeholder*='country code' i]"
    ).first
    if not cc_combo.count():
        group = _field_container(page, re.compile(r"phone", re.I))
        if group:
            cc_combo = group.locator(
                "input[role='combobox'], input[aria-haspopup='listbox']"
            ).first
    if cc_combo.count():
        try:
            cc = _norm(cc_combo.input_value(timeout=2_000))
        except Exception:  # noqa: BLE001
            cc = ""
    report["phone_country_code"] = cc
    return report


def _check_position_location(page: Page) -> dict:
    """Verify the job-specific location combobox without inventing preferences.

    Verified live: for single-location jobs the site PRE-SELECTS the location
    in React state (option carries aria-selected="true", the React 'selected'
    prop and the selected-option CSS class) even though the visible input
    text stays empty. Per spec: one location already selected -> leave it
    unchanged.
    """
    combo = _find_combobox_by_label(page, re.compile(r"preferred\s+location", re.I))
    info: dict = {"field_found": bool(combo)}
    if combo is None:
        info["status"] = "field-not-found"
        return info
    try:
        value = _norm(combo.input_value(timeout=3_000))
    except Exception:  # noqa: BLE001
        value = ""
    info["value"] = value
    if value:
        info["status"] = "preselected"
        return info

    texts = _open_combobox_options(page, combo)
    options = page.locator("[role='option']")
    selected_texts: list[str] = []
    for i in range(min(options.count(), 200)):
        opt = options.nth(i)
        try:
            if opt.get_attribute("aria-selected") != "true":
                continue
            selected_texts.append(_norm(opt.inner_text(timeout=800)))
        except Exception:  # noqa: BLE001
            continue
    try:
        page.keyboard.press("Escape")  # close the list untouched
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        pass

    if len(selected_texts) == 1:
        info["status"] = "preselected-aria"
        info["value"] = selected_texts[0]
        return info
    if value == "" and len(texts) == 1 and not selected_texts:
        try:
            info["value"] = _select_combobox_exact(page, combo, texts[0])
            info["status"] = "selected-only-option"
            return info
        except RuntimeError as exc:
            info["status"] = f"select-failed: {exc}"
            return info
    info["options"] = texts
    info["selected"] = selected_texts
    info["status"] = "empty-multiple-options"
    return info


def _set_start_date(page: Page) -> str:
    """Set Preferred Start Date = 01 Oct 2026 (typed as US 10/01/2026)."""
    combo = _find_combobox_by_label(page, START_DATE_LABEL)
    if combo is None:
        raise RuntimeError("Preferred Start Date field not found")
    try:
        current = _norm(combo.input_value(timeout=3_000))
    except Exception:  # noqa: BLE001
        current = ""
    if "oct" in current.lower() and "2026" in current.lower():
        return current  # already correct
    combo.scroll_into_view_if_needed()
    combo.click(timeout=6_000)
    page.wait_for_timeout(400)
    # close the calendar popover, then type the date (US format, verified live)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    page.keyboard.press("Control+A")
    page.keyboard.type(START_DATE_US, delay=60)
    page.wait_for_timeout(800)
    new_value = _norm(combo.input_value(timeout=3_000))
    if not ("oct" in new_value.lower() and "2026" in new_value.lower()):
        raise RuntimeError(
            f"start date verification failed: typed {START_DATE_US!r}, field shows {new_value!r}"
        )
    return new_value


def _scan_validation_errors(page: Page) -> list[str]:
    errors: list[str] = []
    selectors = [
        "[role='alert']",
        ".error, [class*='error']", "[class*='invalid']", "[class*='required']",
    ]
    seen: set[str] = set()
    for sel in selectors:
        try:
            locs = page.locator(sel)
        except Exception:  # noqa: BLE001
            continue
        for i in range(min(locs.count(), 20)):
            el = locs.nth(i)
            try:
                if not el.is_visible(timeout=500):
                    continue
                text = _norm(el.text_content(timeout=1_000) or "")
            except Exception:  # noqa: BLE001
                continue
            if text and text not in seen and len(text) < 300:
                # static form legends, not validation errors (verified live)
                if re.search(r"required\s+fields?\s+are\s+(marked|indicated)", text, re.I):
                    continue
                if ERROR_TEXT.search(text) or re.search(
                    r"required|please|muss|bitte|pflicht", text, re.I
                ):
                    seen.add(text)
                    errors.append(text)
    return errors


def _find_submit_button(page: Page) -> Locator:
    btn = page.get_by_role("button", name=re.compile(r"submit\s+application", re.I)).first
    if btn.count():
        return btn
    btn = page.locator("button:has-text('Submit application')").first
    if btn.count():
        return btn
    raise RuntimeError("'Submit application' button not found on page")


def _wait_submission_confirmation(page: Page, timeout_s: int = 90) -> str:
    deadline = time.time() + timeout_s
    start_url = page.url
    while time.time() < deadline:
        body = _visible_body_text(page)
        if SUCCESS_TEXT.search(body):
            return _norm(SUCCESS_TEXT.search(body).group(0))
        if page.url != start_url and SUCCESS_TEXT.search(_visible_body_text(page)):
            return "confirmation after redirect"
        page.wait_for_timeout(2_000)
    return ""


# ---------------------------------------------------------------------------
# main flow
# ---------------------------------------------------------------------------
def apply_to_infineon_job(job_url: str, resume_path: Path | str | None, dry_run: bool = True,
                          headless: bool = False, browser_hold_s: int = 12) -> dict:
    resume_path = _pick_resume(job_url, str(resume_path) if resume_path else None)
    job_id = _job_id(job_url)
    result: dict = {
        "status": "FAILED", "job_id": job_id, "job_url": job_url,
        "resume": str(resume_path), "mode": "dry-run" if dry_run else "submit",
        "timestamp": _now(), "screenshots": {}, "contact_information": {},
        "errors": [], "confirmation": "",
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        def fail(status: str, reason: str) -> dict:
            result["status"] = status
            result["errors"].append(reason)
            result["error"] = reason
            result["screenshots"]["error"] = _shot(page, f"error-{job_id}.png")
            _log("error", reason)
            if browser_hold_s > 0:
                page.wait_for_timeout(browser_hold_s * 1000)
            browser.close()
            (RESULTS_DIR / f"{job_id}-result.json").write_text(
                json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8"
            )
            return result

        try:
            # [1/8] open application -------------------------------------------
            _log("1/8", "Opening Infineon application...")
            last_goto_exc: Exception | None = None
            for attempt in range(3):  # transient network hiccups happen
                try:
                    page.goto(job_url, wait_until="domcontentloaded", timeout=45_000)
                    last_goto_exc = None
                    break
                except PlaywrightTimeoutError as exc:
                    last_goto_exc = exc
                    _log("1/8", f"goto timeout (attempt {attempt + 1}/3), retrying...")
            if last_goto_exc is not None:
                return fail("FAILED", f"page did not load after 3 attempts: {last_goto_exc}")
            _settle(page, 12_000)
            if _detect_human_verification(page):
                return fail("BLOCKED", "human-verification challenge on load")
            # the SPA renders asynchronously - poll until the form sections appear
            form_ready = False
            deadline = time.time() + 30
            while time.time() < deadline:
                body = _visible_body_text(page)
                if re.search(r"resume|contact\s+information|lebenslauf", body, re.I):
                    form_ready = True
                    break
                page.wait_for_timeout(2_000)
            if not form_ready:
                return fail("NEEDS_ATTENTION",
                            f"application form did not load; URL now {page.url}")
            result["screenshots"]["01-application-loaded"] = _shot(
                page, f"01-application-loaded-{job_id}.png")
            result["cookie_banner"] = _dismiss_cookie_banner(page)

            # [2/8] resume upload ---------------------------------------------
            _log("2/8", "Uploading resume...")
            file_input = page.locator(
                "input[type='file'][accept*='pdf'], input[type='file']"
            ).first
            if not file_input.count():
                return fail("NEEDS_ATTENTION", "resume file input not found")
            file_input.set_input_files(str(resume_path))
            result["screenshots"]["02-resume-uploaded"] = _shot(
                page, f"02-resume-uploaded-{job_id}.png")

            # confirm the upload dialog so parsing actually starts
            result["resume_confirm_clicked"] = _confirm_resume_upload(page)

            # [3/8] resume processing -----------------------------------------
            _log("3/8", "Waiting for resume processing/autofill...")
            proc = _wait_resume_processing(page, resume_path.name)
            result["resume_processing"] = proc
            result["screenshots"]["03-resume-processing-complete"] = _shot(
                page, f"03-resume-processing-complete-{job_id}.png")

            # [4/8] privacy popup ----------------------------------------------
            _log("4/8", "Handling privacy popup (if present)...")
            result["popup"] = _handle_privacy_popup(page)

            # [5/8] contact information ----------------------------------------
            _log("5/8", "Verifying contact information (read-only)...")
            contact = _verify_contact_information(page)
            result["contact_information"] = contact
            missing = [k for k, v in contact.items()
                       if k in {"first_name", "last_name", "email", "phone"} and not v]
            if missing:
                return fail("NEEDS_ATTENTION",
                            f"autofill left required contact fields empty: {missing} "
                            f"(observed: {contact})")
            result["screenshots"]["04-contact-information"] = _shot(
                page, f"04-contact-information-{job_id}.png")

            # [6/8] location + additional information ---------------------------
            _log("6/8", "Filling position location + additional information...")
            result["location"] = _check_position_location(page)
            if result["location"].get("status") in {"empty-multiple-options",
                                                    "select-failed"}:
                return fail("NEEDS_ATTENTION",
                            f"position location unresolved: {result['location']}")

            filled: dict[str, str] = {}
            for label_re, option in FIELD_PLAN:
                combo = _find_combobox_by_label(page, label_re)
                if combo is None:
                    return fail("NEEDS_ATTENTION",
                                f"field {label_re.pattern!r} not found on form")
                try:
                    filled[label_re.pattern] = _select_combobox_exact(page, combo, option)
                except RuntimeError as exc:
                    return fail("NEEDS_ATTENTION", f"{label_re.pattern!r}: {exc}")
            result["additional_information"] = filled
            result["start_date"] = _set_start_date(page)
            result["screenshots"]["05-additional-information"] = _shot(
                page, f"05-additional-information-{job_id}.png")

            # [7/8] germany-specific --------------------------------------------
            _log("7/8", "Verifying Germany-specific information (disability=No)...")
            # the Germany-specific section can render late (conditional UI
            # after Country=Germany) - wait for it instead of failing fast
            combo = None
            deadline = time.time() + 15
            while time.time() < deadline and combo is None:
                combo = _find_combobox_by_label(page, DISABILITY_LABEL)
                if combo is None:
                    page.wait_for_timeout(2_000)
            if combo is None:
                return fail("NEEDS_ATTENTION", "disability status field not found")
            try:
                current = _norm(combo.input_value(timeout=3_000))
            except Exception:  # noqa: BLE001
                current = ""
            # Verified live: options are ['No selection', 'Disabled'] - there is
            # NO 'No' option; 'No selection' IS the explicit no-answer state.
            if "no selection" in current.lower():
                result["disability"] = "No selection (no answer given)"
            elif current == "":
                result["disability"] = _select_combobox_exact(page, combo, "No selection")
            else:
                return fail("NEEDS_ATTENTION",
                            f"disability field has unexpected value {current!r}; "
                            "spec requires No/No selection - refusing to select 'Disabled'")
            result["screenshots"]["06-germany-specific-information"] = _shot(
                page, f"06-germany-specific-information-{job_id}.png")

            # [8/8] validation ----------------------------------------------------
            _log("8/8", "Validating application...")
            _settle(page, 4_000)
            validation_errors = _scan_validation_errors(page)
            result["validation_errors"] = validation_errors
            result["screenshots"]["07-before-submit"] = _shot(
                page, f"07-before-submit-{job_id}.png")

            submit_btn = _find_submit_button(page)  # must exist even in dry-run
            result["submit_button_found"] = True

            if dry_run:
                result["status"] = "DRY_RUN"
                (RESULTS_DIR / f"{job_id}-result.json").write_text(
                    json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
                print("DRY_RUN_COMPLETE")
                print("Application was NOT submitted.")
                if browser_hold_s > 0:
                    page.wait_for_timeout(browser_hold_s * 1000)
                browser.close()
                return result

            # [FINAL] real submission ------------------------------------------
            if validation_errors:
                return fail("NEEDS_ATTENTION",
                            f"validation errors present before submit: {validation_errors}")
            _log("FINAL", "Submitting application...")
            submit_btn.scroll_into_view_if_needed()
            submit_btn.click(timeout=10_000)
            confirmation = _wait_submission_confirmation(page)
            result["confirmation"] = confirmation
            result["screenshots"]["08-after-submit"] = _shot(
                page, f"08-after-submit-{job_id}.png")
            if not confirmation:
                return fail("NEEDS_ATTENTION",
                            "submit clicked but no confirmation message/redirect detected")
            result["status"] = "SUCCESS"
            (RESULTS_DIR / f"{job_id}-result.json").write_text(
                json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
            if browser_hold_s > 0:
                page.wait_for_timeout(min(browser_hold_s, 5) * 1000)
            browser.close()
            return result

        except Exception as exc:  # noqa: BLE001
            return fail("FAILED", f"unexpected error: {exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    # Windows consoles default to cp1252 - the result JSON can contain
    # non-latin1 characters (e.g. the phone-code flag emoji)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="Apply to ONE Infineon job (Eightfold).")
    parser.add_argument("--url", default=DEFAULT_JOB_URL,
                        help="job page or careers/apply?pid= URL")
    parser.add_argument("--resume", default=None,
                        help="path to the resume PDF/DOCX (optional: auto-picks the "
                             "tailored resume from job_resume_map.csv when omitted)")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="everything except the final submit (default)")
    parser.add_argument("--submit", action="store_true",
                        help="REAL submission (overrides --dry-run; asks YES)")
    parser.add_argument("--headless", action="store_true",
                        help="run without visible browser (default: visible)")
    parser.add_argument("--browser-hold", type=int, default=12,
                        help="seconds to keep the browser open at the end")
    args = parser.parse_args()

    dry_run = not args.submit
    if args.submit:
        answer = input("Type YES to really submit this application: ").strip()
        if answer != "YES":
            print("Aborted - no submission.")
            return 1

    result = apply_to_infineon_job(
        args.url, args.resume, dry_run=dry_run,
        headless=args.headless, browser_hold_s=args.browser_hold,
    )
    print(json.dumps({k: v for k, v in result.items()
                      if k != "screenshots"}, indent=1, ensure_ascii=False))
    print(f"Final status: {result['status']}")
    return 0 if result["status"] in {"SUCCESS", "DRY_RUN"} else 1


if __name__ == "__main__":
    sys.exit(main())
