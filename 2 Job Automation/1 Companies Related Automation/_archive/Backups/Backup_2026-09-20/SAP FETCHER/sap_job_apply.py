"""
sap_job_apply.py -- Apply to ONE SAP SuccessFactors job posting.

Public API (for use inside a larger pipeline):

    from sap_job_apply import apply_to_sap_job

    result = apply_to_sap_job(JOB_URL, RESUME_PATH, dry_run=True)   # 1. always dry-run first
    if result["status"] == "DRY_RUN":                               # 2. you verify / user approves
        result = apply_to_sap_job(JOB_URL, RESUME_PATH, dry_run=False)  # 3. real submission

apply_to_sap_job takes ONLY the job URL and the resume path. Login credentials
come from the environment (SAP_EMAIL / SAP_PASSWORD), never from source code.
Results and screenshots are written to results/<job_id>-*. The function never
invents data, never bypasses CAPTCHA/MFA, and reports NEEDS_ATTENTION whenever
success cannot be strongly proven.

Manual use:
    python sap_job_apply.py --dry-run                       # the verified test job
    python sap_job_apply.py --dry-run --all                 # every job in resume_report.json
    python sap_job_apply.py --submit                        # submit the test job (asks YES)
    python sap_job_apply.py --submit --all                  # submit every job (asks YES)
    python sap_job_apply.py --dry-run --job-id 1434973333   # one batch job by id
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"

JOB_URL = (
    "https://jobs.sap.com/job/Walldorf-Working-Student-%28fmd%29-"
    "Software-Development-for-SAP-Sailing-Analytics-69190/1387969433/"
)
RESUME_PATH = (
    ROOT / "program_files" / "output_sap" / "resume" / "pdf"
    / "Working-Student---Software-Development-for-SAP-Sailing-Analytics.pdf"
)

VIEWPORT = {"width": 1440, "height": 1000}
DEFAULT_TIMEOUT_MS = 20_000

# ---------------------------------------------------------------------------
# Text classifiers (same approach as 3_job_sending.py, tuned for SAP SF)
# ---------------------------------------------------------------------------
SUCCESS_TEXT = re.compile(
    r"thank\s+you|application\s+(?:has\s+been\s+)?(?:received|submitted|sent)"
    r"|success(?:fully)?\s+submitted|your\s+application\s+(?:was|has been)\s+submitted"
    r"|bewerbung\s+(?:erfolgreich|wurde.{0,20}übermittelt|ist\s+eingegangen)"
    r"|vielen\s+dank|we\s+have\s+received\s+your\s+application",
    re.I,
)
ALREADY_APPLIED_TEXT = re.compile(r"already\s+applied|bereits.{0,40}beworben", re.I)
ERROR_TEXT = re.compile(
    r"something went wrong|an error occurred|technical error|server error"
    r"|upload failed|invalid file|please correct|fehler|ungültig|konnte nicht",
    re.I,
)
HUMAN_VERIFICATION_TEXT = re.compile(
    r"captcha|recaptcha|verify you are human|human verification|are you a robot"
    r"|sind sie ein robot|multi[- ]factor|two[- ]factor|security code required",
    re.I,
)
CHALLENGE_FRAME_URL = re.compile(
    r"recaptcha/api|hcaptcha\.com|challenges\.cloudflare\.com|captcha-delivery\.com|geetest",
    re.I,
)

# ---------------------------------------------------------------------------
# Application-field spec (exact SAP labels -> exact option values, verified
# live on career5.successfactors.eu on 2026-09-14; see results/probe*.png)
# ---------------------------------------------------------------------------
COMBO_FIELDS = [
    # (unique aria-label prefix, exact option text to select)
    ("Are you legally authorized to work", "Yes"),
    ("Are you currently employed by:", "None of the Above"),
    ("Were you previously employed by SAP?", "No"),
    ("Please confirm your current country of residence", "Germany"),
]
GENDER_PREFIX = "What is your gender?"
GENDER_OPTION = "Male"  # must be selected AFTER country of residence (cascading picklist)

LEAVE_EMPTY_FIELDS = ["Former SAP User ID", "SAP Program Code"]
CONSENT_CHECKBOX_NAME = "customAdditionalConsentSPL"
SKILLS_MAX = 100  # SAP hard cap; resume parsing can push the draft above it


def _trim_skills_to_cap(page, max_skills: int = SKILLS_MAX, timeout_s: int = 180) -> int:
    """Enforce SAP's 100-skill cap by removing chips in DOM order.

    Verified live: uploading a resume auto-adds its parsed skills to the
    application draft (base 88 -> 118/121 observed), and Apply is then refused
    with 'You can only add up to 100 skills'. Clicking a skill chip removes it
    (counter 88 -> 87 verified). The SAP counter is authoritative.
    """
    counter = page.locator("[data-testid='my-skills-section-header']")
    if not counter.count():
        return 0  # requisition has no skills section

    def _count() -> int:
        match = re.search(r"\((\d+)\)", counter.text_content(timeout=3_000) or "")
        return int(match.group(1)) if match else -1

    # The resume-skill parsing lands asynchronously AFTER the upload finishes
    # (observed: trim ran at 88, then the counter rose to 118 by submit time).
    # Wait until the counter stops moving before trusting it.
    stable_deadline = time.time() + 90
    previous = _count()
    while time.time() < stable_deadline:
        page.wait_for_timeout(3_000)
        current = _count()
        if current == previous and current >= 0:
            break
        previous = current

    n = previous if previous >= 0 else _count()
    if n < 0 or n <= max_skills:
        return 0

    chips = page.locator("[data-testid='skill-token-container'] button.candidateSkillToken")
    if chips.count() and not chips.first.is_visible():
        bar = page.get_by_role("button", name=re.compile(r"^skills$", re.I))
        if bar.count():
            bar.first.click(timeout=8_000)
            page.wait_for_timeout(1_500)

    removed = 0
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        current = _count()
        if current < 0:
            raise RuntimeError("ERROR: Skills counter disappeared while trimming.")
        if current <= max_skills:
            break
        try:
            chips.first.scroll_into_view_if_needed(timeout=5_000)
            chips.first.click(timeout=8_000)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"ERROR: Could not remove skill chip #{removed + 1}: {exc}") from exc
        removed += 1
        page.wait_for_timeout(1_500)

    final = _count()
    if final > max_skills:
        raise RuntimeError(f"ERROR: Skills trim stalled at {final} (cap {max_skills}).")
    return removed


def _log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_id(job_url: str) -> str:
    match = re.search(r"/(\d{6,})/?$", job_url.rstrip("/"))
    if not match:
        raise RuntimeError(f"ERROR: Could not extract a job id from URL: {job_url}")
    return match.group(1)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _visible_body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)
    except PlaywrightTimeoutError:
        return ""


def _dismiss_cookie_banner(page) -> bool:
    """SAP shows a German cookie banner on jobs.sap.com and career5."""
    for pattern in (r"^alle annehmen$", r"^accept all$", r"^alle akzeptieren$", r"^akzeptieren$", r"^accept$"):
        button = page.get_by_role("button", name=re.compile(pattern, re.I))
        try:
            if button.count() >= 1 and button.first.is_visible():
                button.first.click(timeout=3000)
                page.wait_for_timeout(500)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _detect_human_verification(page) -> bool:
    text = _visible_body_text(page)
    text_hit = HUMAN_VERIFICATION_TEXT.search(text)
    frame_hit = next(
        (f.url for f in page.frames if CHALLENGE_FRAME_URL.search(f.url)),
        None,
    )
    if text_hit or frame_hit:
        print(f"Human-verification indicator detected: {text_hit or frame_hit}", flush=True)
        return True
    return False


def _require_env_credentials() -> tuple[str, str]:
    email = os.environ.get("SAP_EMAIL", "").strip()
    password = os.environ.get("SAP_PASSWORD", "")
    if not email or not password:
        raise RuntimeError(
            "ERROR: SAP_EMAIL / SAP_PASSWORD environment variables are not set. "
            "Never hardcode credentials in this file."
        )
    return email, password


def _validate_resume_path(resume_path: Path) -> Path:
    if not resume_path.exists():
        raise RuntimeError(f"ERROR: Resume file not found: {resume_path}")
    if not resume_path.is_file():
        raise RuntimeError(f"ERROR: Resume path is not a file: {resume_path}")
    if resume_path.suffix.lower() != ".pdf":
        raise RuntimeError(f"ERROR: Resume must be a PDF: {resume_path}")
    return resume_path


# ---------------------------------------------------------------------------
# Page-flow helpers
# ---------------------------------------------------------------------------
def _open_job_and_click_apply(page, job_url: str) -> None:
    page.goto(job_url, wait_until="load", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        pass
    _dismiss_cookie_banner(page)
    page.wait_for_timeout(1_500)

    # Two identical 'Apply now' links exist (top + bottom); try each in turn.
    links = page.get_by_role("link", name=re.compile(r"^apply now", re.I))
    if links.count() == 0:
        raise RuntimeError("ERROR: No 'Apply now' link found on the job page.")
    errors: list[str] = []
    for i in range(links.count()):
        link = links.nth(i)
        try:
            link.scroll_into_view_if_needed(timeout=5_000)
            link.click(timeout=10_000)
            page.wait_for_url(lambda u: "successfactors" in u, timeout=20_000)
            break
        except PlaywrightTimeoutError as exc:
            errors.append(f"attempt {i + 1}: {exc}")
            continue
    else:
        raise RuntimeError(
            "ERROR: Clicking 'Apply now' did not reach the SAP career site. "
            + " | ".join(errors)
        )
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(2_500)
    _dismiss_cookie_banner(page)


def _login(page, email: str, password: str) -> None:
    """Sign in, tolerating the login form's late re-renders.

    Verified failure mode: the form can re-render after fill() and CLEAR the
    values, causing an empty submit. Values are therefore verified immediately
    before every click, and a credential error message never triggers a retry
    (to avoid repeated failed logins against the account).
    """
    last_error = "not attempted"
    for attempt in range(1, 4):
        username = page.locator("#username")
        username.wait_for(state="visible", timeout=20_000)
        page.wait_for_timeout(1_000)  # let late-binding page JS settle
        username.fill(email)
        page.locator("#password").fill(password)
        page.wait_for_timeout(800)

        if username.input_value() != email or page.locator("#password").input_value() != password:
            last_error = "fields cleared by page re-render before submit"
            continue

        _log("3/8", f"Submitting credentials (attempt {attempt})...")
        page.get_by_role("button", name=re.compile(r"^sign in$", re.I)).first.click()
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(3_000)
        _dismiss_cookie_banner(page)

        if not (page.locator("#username").count() and page.locator("#username").first.is_visible()):
            break  # signed in
        body = _visible_body_text(page)
        if re.search(r"incorrect|invalid email|wrong password|login has failed|falsch|ungültig", body, re.I):
            raise RuntimeError("ERROR: Login rejected by SAP (credential error message shown). Not retrying.")
        last_error = "sign-in form still shown after submit"
    else:
        raise RuntimeError(f"ERROR: Login failed - {last_error}.")

    if "career" not in page.url:
        raise RuntimeError(f"ERROR: Unexpected page after login: {page.url}")
    if _detect_human_verification(page):
        raise RuntimeError("BLOCKED: Human verification required after login.")


def _expand_all_sections(page) -> None:
    expander = page.get_by_role("button", name=re.compile(r"expand all sections", re.I))
    try:
        if expander.count() and expander.first.is_visible():
            expander.first.click(timeout=5_000)
            page.wait_for_timeout(2_000)
            return
    except Exception:  # noqa: BLE001
        pass
    # fallback: expand the two sections we actually need
    for name in (r"^my documents$", r"job-specific information"):
        bar = page.get_by_role("button", name=re.compile(name, re.I))
        try:
            if bar.count():
                bar.first.click(timeout=5_000)
                page.wait_for_timeout(1_500)
        except Exception:  # noqa: BLE001
            continue


def _expand_my_documents(page) -> None:
    """Expand My Documents only if its attachment slots are not already visible.
    Clicking an expanded bar collapses it (verified live), so never click blindly.
    """
    slots = _attach_slots(page)
    try:
        if slots.count() and slots.first.is_visible():
            return  # already expanded
    except Exception:  # noqa: BLE001
        pass
    bar = page.get_by_role("button", name=re.compile(r"^my documents$", re.I)).first
    bar.click(timeout=10_000)
    page.wait_for_timeout(2_000)
    if not (_attach_slots(page).count() and _attach_slots(page).first.is_visible()):
        raise RuntimeError("ERROR: My Documents did not expand - attachment slots not visible.")


def _attach_slots(page):
    """All attachment slot wrappers currently in the DOM."""
    return page.locator("div[id$=':_attachWrapper']")


def _slot_label_text(slot) -> str:
    """Filename (or 'Attach a ...' prompt) of one attachment slot."""
    link = slot.locator("[id$=':_attachDownloadLabelLink']").first
    try:
        return _norm(link.text_content(timeout=2_000) or "")
    except Exception:  # noqa: BLE001
        return ""


def _slot_is_filled(slot) -> bool:
    label = _slot_label_text(slot).lower()
    if not label:
        return False
    # filled slots carry a download label ending in an extension; empty slots
    # show prompts like 'Attach a Cover Letter' / 'Add a Document'
    return not label.startswith(("attach", "add"))


def _find_resume_slot(page):
    """The Resume slot = the wrapper whose ariaLabelledby reference contains
    the visible 'Resume' question label, identified via its edit tooltip."""
    slots = _attach_slots(page)
    candidates = []
    for i in range(slots.count()):
        slot = slots.nth(i)
        label = _slot_label_text(slot)
        aria_ref = slot.locator("[id$=':_ariaActionLabel']").first
        tooltip = ""
        try:
            tooltip = _norm(aria_ref.text_content(timeout=1_000) or "")
        except Exception:  # noqa: BLE001
            pass
        if re.search(r"edit document\s+(.+\.pdf)", tooltip, re.I):
            candidates.append((slot, label, tooltip))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise RuntimeError("ERROR: Resume attachment slot not found in My Documents.")
    raise RuntimeError(f"ERROR: Resume slot ambiguous: {[c[1] for c in candidates]}")


def _wait_upload_finished(page, slot, previous_label: str, timeout_ms: int = 90_000) -> str:
    """Wait until SAP confirms the upload.

    Two valid confirmations: the slot filename changes (different file), or SAP's
    own '_attachSuccess' indicator becomes visible (same filename re-uploaded).
    The 'Uploading...' indicator is observed to avoid declaring success too early.
    """
    deadline = time.time() + timeout_ms / 1_000
    saw_uploading = False
    last = previous_label
    while time.time() < deadline:
        label = ""
        try:
            label = _slot_label_text(slot)
        except Exception:  # noqa: BLE001
            pass
        try:
            if slot.locator("[id$=':_attachLoading']:not(.displayNone)").count():
                saw_uploading = True
        except Exception:  # noqa: BLE001
            pass
        try:
            success_visible = bool(slot.locator("[id$=':_attachSuccess']:not(.displayNone)").count())
        except Exception:  # noqa: BLE001
            success_visible = False
        if label and label != previous_label:
            return label
        if success_visible and label and (saw_uploading or label != previous_label):
            return label
        last = label or last
        page.wait_for_timeout(1_000)
    raise RuntimeError(
        f"ERROR: Resume upload did not finish within {timeout_ms / 1000:.0f}s "
        f"(slot label still {last!r}, previously {previous_label!r})."
    )


def _replace_resume(page, resume_path: Path) -> dict:
    """Open the Resume slot's edit dialog and upload via 'Upload from Device'.

    Verified live: the pencil icon ('Edit document ... Opens a dialog') opens a
    dialog that contains a real input[type=file] labelled 'Upload from Device'.
    The chooser-less approach uses that input directly (Playwright set_input_files).
    """
    slot, current_label, _tooltip = _find_resume_slot(page)
    pencil = slot.locator("[id$=':_attachIcon']").first
    pencil.scroll_into_view_if_needed()
    pencil.click(timeout=15_000)
    page.wait_for_timeout(1_500)

    dialog = page.locator("[role=dialog][aria-label*='Select a source' i]")
    try:
        dialog.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError("ERROR: 'Upload from Device' dialog did not appear after clicking Edit.") from exc

    file_input = dialog.locator("input[type=file]").first
    if file_input.count() == 0:
        raise RuntimeError("ERROR: File input not found inside the upload dialog.")
    file_input.set_input_files(str(resume_path))
    page.wait_for_timeout(1_000)

    # If the dialog stays open after choosing a file, confirm INSIDE the dialog
    # only (never the footer Save/Apply buttons).
    try:
        confirm = dialog.get_by_role(
            "button", name=re.compile(r"^(upload|ok|done|attach|submit|hochladen|fertig)$", re.I)
        )
        if dialog.is_visible() and confirm.count():
            confirm.first.click(timeout=4_000)
            page.wait_for_timeout(1_000)
    except Exception:  # noqa: BLE001
        pass

    expected = resume_path.name
    try:
        new_label = _wait_upload_finished(page, slot, current_label)
    except RuntimeError:
        # Same filename re-uploaded: the label legitimately stays unchanged.
        # Accept only if the slot now shows exactly the expected resume.
        final_label = _slot_label_text(slot)
        if _norm(final_label).casefold() != expected.casefold():
            raise
        return {
            "previous": current_label,
            "now": final_label,
            "verified": True,
            "note": "Filename unchanged (same resume re-uploaded); slot verified to contain the expected file.",
        }
    if _norm(new_label).casefold() != expected.casefold():
        raise RuntimeError(
            f"ERROR: Resume slot shows {new_label!r} after upload, expected {expected!r}."
        )
    return {"previous": current_label, "now": new_label, "verified": True}


def _select_combo_option(page, label_prefix: str, option_text: str, max_attempts: int = 3) -> str:
    """Open a SAP paginated-picklist combobox and select an exact option.

    SAP re-renders widgets after each selection, so a click can land on a stale
    dropdown. Every attempt is verified by reading the input value back;
    failures are retried on the fresh widget instead of being trusted.
    """
    last_error = "not attempted"
    for attempt in range(1, max_attempts + 1):
        combo = page.get_by_role("combobox", name=re.compile(re.escape(label_prefix), re.I)).first
        combo.scroll_into_view_if_needed(timeout=15_000)
        combo.click(timeout=15_000)
        page.wait_for_timeout(1_200)

        opt = page.get_by_role("option", name=option_text, exact=True)
        count = opt.count()
        if count == 0:
            page.keyboard.press("Escape")
            last_error = f"option {option_text!r} not found (attempt {attempt})"
            continue
        if count > 1:
            page.keyboard.press("Escape")
            raise RuntimeError(
                f"ERROR: Option {option_text!r} ambiguous ({count} matches) for field {label_prefix!r}."
            )
        opt.first.scroll_into_view_if_needed(timeout=5_000)
        opt.first.click(timeout=10_000)
        page.wait_for_timeout(1_500)

        value = combo.input_value()
        if _norm(value).casefold() == _norm(option_text).casefold():
            return value
        last_error = f"field shows {value!r} after selecting {option_text!r} (attempt {attempt})"
    raise RuntimeError(f"ERROR: Field {label_prefix!r}: {last_error}. Not guessing.")


def _settle(page, timeout_ms: int = 8_000) -> None:
    """Let SAP finish its async re-renders before reading or writing state."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1_500)


def _fill_application_fields(page, max_rounds: int = 3) -> dict:
    """Fill all application fields and keep them filled.

    Verified failure mode: SAP re-renders the form asynchronously (resume
    upload completion, cascading picklist updates) and a selection can be
    cleared in the DOM shortly after it was confirmed. Every round therefore
    re-checks ALL values against SAP's live DOM and re-selects what is missing;
    the function only returns once everything holds across a settle cycle.
    """
    expected_map: dict[str, str] = dict(COMBO_FIELDS)
    expected_map[GENDER_PREFIX] = GENDER_OPTION
    values: dict = {}

    for round_no in range(1, max_rounds + 1):
        _settle(page)

        for prefix, option in COMBO_FIELDS:
            if any(_norm(v).casefold() == _norm(option).casefold() for v in _combo_values(page, prefix)):
                values[prefix] = option
                continue
            _log("6/8", f"(round {round_no}) selecting {prefix[:50]!r} -> {option!r}")
            values[prefix] = _select_combo_option(page, prefix, option)

        # Gender is a cascading picklist: enabled only after country of residence.
        if any(_norm(v).casefold() == _norm(GENDER_OPTION).casefold() for v in _combo_values(page, GENDER_PREFIX)):
            values[GENDER_PREFIX] = GENDER_OPTION
        else:
            gender_combo = page.get_by_role("combobox", name=re.compile(re.escape(GENDER_PREFIX), re.I)).first
            gender_combo.scroll_into_view_if_needed(timeout=15_000)
            enabled_deadline = time.time() + 15
            while not gender_combo.is_enabled():
                if time.time() > enabled_deadline:
                    raise RuntimeError(
                        "ERROR: Gender field stayed disabled - the cascading picklist "
                        "requires country of residence to be selected first."
                    )
                page.wait_for_timeout(500)
            _log("6/8", f"(round {round_no}) selecting gender -> {GENDER_OPTION!r}")
            values[GENDER_PREFIX] = _select_combo_option(page, GENDER_PREFIX, GENDER_OPTION)

        # Required consent checkbox (verified: name=customAdditionalConsentSPL)
        consent = page.locator(f"input[name='{CONSENT_CHECKBOX_NAME}']")
        if consent.count() != 1:
            raise RuntimeError(f"ERROR: Consent checkbox {CONSENT_CHECKBOX_NAME!r} not found or ambiguous.")
        if not consent.is_checked():
            consent.check(timeout=10_000)
            page.wait_for_timeout(500)
        if not consent.is_checked():
            raise RuntimeError("ERROR: Consent checkbox could not be checked.")
        values["consentChecked"] = True
        values["leftEmpty"] = list(LEAVE_EMPTY_FIELDS)

        # Stability gate: everything must still hold after SAP settles.
        _settle(page, 10_000)
        unstable = [
            prefix
            for prefix, option in expected_map.items()
            if not any(_norm(v).casefold() == _norm(option).casefold() for v in _combo_values(page, prefix))
        ]
        if not unstable:
            return values
        _log("6/8", f"SAP re-render cleared {unstable}; re-selecting (round {round_no + 1})...")

    raise RuntimeError(
        "ERROR: Application fields would not hold their values across SAP re-renders. "
        "Not submitting an unstable form."
    )


def _combo_values(page, label_prefix: str) -> list[str]:
    """Input values of every combobox matching the label (SAP re-renders can
    leave stale hidden duplicates - verification must check all of them)."""
    combos = page.get_by_role("combobox", name=re.compile(re.escape(label_prefix), re.I))
    values = []
    for i in range(combos.count()):
        try:
            values.append(combos.nth(i).input_value())
        except Exception:  # noqa: BLE001
            continue
    return values


def _verify_application(page, expected_resume: str) -> dict:
    report: dict = {"passed": True, "problems": []}

    def problem(message: str) -> None:
        report["passed"] = False
        report["problems"].append(message)

    # Combobox values (any DOM instance holding the expected value passes;
    # SAP keeps stale hidden copies whose .first input reads empty)
    for prefix, expected in COMBO_FIELDS + [(GENDER_PREFIX, GENDER_OPTION)]:
        values = _combo_values(page, prefix)
        if not values:
            problem(f"{prefix!r}: no combobox found")
        elif not any(_norm(v).casefold() == _norm(expected).casefold() for v in values):
            problem(f"{prefix!r}: expected {expected!r}, found {values!r}")

    # Leave-empty fields
    for name in ("custompreviousSAPemploymentID", "customSAPProgramCode"):
        field = page.locator(f"input[name='{name}']")
        if field.count() != 1:
            problem(f"Leave-empty field {name!r} not found.")
        elif field.input_value().strip():
            problem(f"Leave-empty field {name!r} must stay empty but contains {field.input_value()!r}")

    # Consent
    consent = page.locator(f"input[name='{CONSENT_CHECKBOX_NAME}']")
    if consent.count() == 1 and not consent.is_checked():
        problem("Consent checkbox is not checked.")

    # Resume slot shows the new file
    try:
        slot, current_label, _t = _find_resume_slot(page)
        report["resumeLabel"] = current_label
        if not _slot_is_filled(slot):
            problem(f"Resume slot appears empty ({current_label!r}).")
        if _norm(current_label).casefold() != _norm(expected_resume).casefold():
            problem(f"Resume slot shows {current_label!r}, expected {expected_resume!r}.")
    except Exception as exc:  # noqa: BLE001
        problem(f"Resume verification failed: {exc}")

    # Browser-native validation on the form
    try:
        validity = page.locator("form#careerform").evaluate(
            """(form) => ({
                valid: form.checkValidity(),
                invalid: [...form.querySelectorAll(':invalid')].map((el) => ({
                    name: el.name || el.id || '',
                    message: el.validationMessage || '',
                })),
            })"""
        )
        report["browserValidation"] = validity
        if not validity["valid"]:
            problem(f"Browser validation reports invalid fields: {validity['invalid']}")
    except Exception as exc:  # noqa: BLE001
        report["browserValidation"] = f"could not evaluate: {exc}"

    return report


def _find_submit_button(page, timeout_s: int = 30):
    """The final Apply button is SAP's footer submit: id ending ':_submitBtn'.
    Verified unique on application pages; rendered either as <button> or as
    <span role=button> depending on the login flow (both observed live). The
    lookup waits and retries because SAP re-renders the footer asynchronously.
    """
    deadline = time.time() + timeout_s
    last_state = "not found"
    while time.time() < deadline:
        apply_btn = page.locator("[id$=':_submitBtn'][role='button']")
        try:
            count = apply_btn.count()
        except Exception:  # noqa: BLE001
            count = 0
        if count > 1:
            raise RuntimeError(f"ERROR: Final Apply button ambiguous ({count} matches).")
        if count == 1:
            btn = apply_btn.first
            try:
                visible = btn.is_visible()
            except Exception:  # noqa: BLE001
                visible = False
            if visible:
                name = _norm(btn.text_content(timeout=3_000) or "")
                if not re.fullmatch(r"apply", name, re.I):
                    raise RuntimeError(f"ERROR: Submit button unexpectedly named {name!r}; refusing to click.")
                return btn
            last_state = "present but not visible"
        else:
            last_state = "0 matches (re-render in progress)"
        page.wait_for_timeout(1_000)
    raise RuntimeError(f"ERROR: Final Apply button unavailable for {timeout_s}s ({last_state}).")


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------
def _detect_already_applied(page) -> bool:
    """True if SAP shows an existing application for this requisition.
    Verified UI: the application landing page then shows a status link
    (id containing 'statusLink', e.g. 'View application status') instead of
    the editable form, and/or body text contains an already-applied message."""
    body = _visible_body_text(page)
    if ALREADY_APPLIED_TEXT.search(body):
        return True
    status_link = page.locator("a[id*='statusLink']")
    form_gone = not page.locator("[id$=':_submitBtn']").count()
    return bool(status_link.count() and status_link.first.is_visible() and form_gone)


def _scan_unknown_required(page) -> list[str]:
    """Names/labels of required-but-empty controls outside the known field set.

    A required field the script does not know must STOP the run: the automation
    must never submit a form with an unanswered required question it cannot
    identify (no guessing, per spec).
    """
    known_names = {
        "customSalutation", "customAcademicTitle", "custompreviousSAPemploymentID",
        "customSAPProgramCode", CONSENT_CHECKBOX_NAME,
    }
    known_aria_fragments = [prefix for prefix, _ in COMBO_FIELDS] + [GENDER_PREFIX]
    findings: list[str] = []
    controls = page.locator(
        "input[aria-required='true'], textarea[aria-required='true'], select[aria-required='true']"
    )
    for i in range(controls.count()):
        el = controls.nth(i)
        try:
            if not el.is_visible() or el.input_value().strip():
                continue
            name = el.get_attribute("name") or ""
            aria = el.get_attribute("aria-label") or ""
            el_type = (el.get_attribute("type") or "").lower()
            if el_type == "checkbox":
                if el.is_checked():
                    continue
            if name in known_names:
                continue
            if any(fragment.casefold() in aria.casefold() for fragment in known_aria_fragments):
                continue
            label = _norm(aria or name or f"index-{i}")[:120]
            findings.append(label)
        except Exception:  # noqa: BLE001
            continue
    return findings


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------
def apply_to_sap_job(job_url: str, resume_path: Path, dry_run: bool = True, headless: bool = False) -> dict:
    """Apply to one SAP job. Returns a structured result dict; never raises for
    website-side outcomes (those are in result['errors']). Raises only for
    local setup problems (missing config/resume) or unexpected automation faults."""
    resume_path = _validate_resume_path(resume_path)
    email, password = _require_env_credentials()
    job_id = _job_id(job_url)
    started_tick = time.perf_counter()

    result: dict = {
        "jobId": job_id,
        "jobUrl": job_url,
        "resume": str(resume_path),
        "status": "NEEDS_ATTENTION",
        "dryRun": dry_run,
        "startedAt": _now(),
        "finishedAt": None,
        "beforeSubmitUrl": None,
        "afterSubmitUrl": None,
        "beforeSubmitTitle": None,
        "afterSubmitTitle": None,
        "successIndicators": {
            "confirmationMessage": False,
            "urlChanged": False,
            "formChanged": False,
            "networkResponses": [],
        },
        "fields": {"filled": {}, "leftEmpty": LEAVE_EMPTY_FIELDS, "problems": []},
        "errors": [],
        "screenshots": {},
        "notes": [],
    }

    def _shot(page, name: str) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / name
        try:
            page.screenshot(path=str(path), full_page=True)
            result["screenshots"][name.removesuffix(".png")] = str(path.relative_to(ROOT)).replace("\\", "/")
        except Exception as exc:  # noqa: BLE001
            result["notes"].append(f"Could not save screenshot {name}: {exc}")

    def _save() -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result["finishedAt"] = _now()
        result["durationSeconds"] = round(time.perf_counter() - started_tick, 1)
        path = RESULTS_DIR / f"sap-{job_id}-result.json"
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Result saved to results/sap-{job_id}-result.json", flush=True)

    def _wait_networkidle(timeout_ms: int) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeoutError:
            pass

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    network_responses: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        def _on_response(response):
            request = response.request
            try:
                if request.method != "GET":
                    network_responses.append({
                        "timestamp": int(time.time() * 1000),
                        "url": response.url,
                        "method": request.method,
                        "status": response.status,
                    })
            except Exception:  # noqa: BLE001
                pass

        context.on("response", _on_response)
        submit_started_at = None
        try:
            _log("1/8", "Opening job page...")
            _open_job_and_click_apply(page, job_url)
            _log("2/8", "Apply clicked - handling login...")
            email_field = page.locator("#username")
            if email_field.count() and email_field.first.is_visible():
                _login(page, email, password)
            else:
                _log("3/8", "Already signed in - skipping login form.")
            if _detect_human_verification(page):
                raise RuntimeError("BLOCKED: Human verification required.")
            _shot(page, f"sap-{job_id}-application-page.png")

            if _detect_already_applied(page):
                result["status"] = "SUCCESS"
                result["notes"].append(
                    "SAP reports an existing application for this requisition "
                    "(status link visible). Nothing was re-submitted."
                )
                _shot(page, f"sap-{job_id}-already-applied.png")
                _save()
                print("\nAlready applied - skipping (treated as SUCCESS).", flush=True)
                return result

            _log("4/8", "Opening My Documents...")
            _expand_all_sections(page)
            _expand_my_documents(page)
            page.wait_for_timeout(1_000)

            _log("5/8", "Replacing resume...")
            upload_info = _replace_resume(page, resume_path)
            result["fields"]["filled"]["resume"] = upload_info
            _shot(page, f"sap-{job_id}-after-resume-upload.png")
            _log("5/8", f"Resume now shows: {upload_info['now']!r}")

            _log("5/8", f"Enforcing skills cap (max {SKILLS_MAX})...")
            removed_skills = _trim_skills_to_cap(page)
            if removed_skills:
                result["fields"]["filled"]["skillsRemoved"] = removed_skills
                _log("5/8", f"Removed {removed_skills} skill chips (DOM order) to satisfy the cap.")

            _log("6/8", "Filling application fields...")

            _log("6/8", "Filling application fields...")
            values = _fill_application_fields(page)
            result["fields"]["filled"].update(values)

            unknown = _scan_unknown_required(page)
            if unknown:
                result["status"] = "NEEDS_ATTENTION"
                _shot(page, f"sap-{job_id}-unknown-required.png")
                raise RuntimeError(
                    f"ERROR: Required fields this script does not know are empty: {unknown}. "
                    "Not guessing - the application was not submitted."
                )

            # Late skills gate: the async resume-skill parse can raise the count
            # again after the early trim; enforce the cap immediately pre-submit.
            late_removed = _trim_skills_to_cap(page)
            if late_removed:
                result["fields"]["filled"]["skillsRemoved"] = (
                    result["fields"]["filled"].get("skillsRemoved", 0) + late_removed
                )
                _log("7/8", f"Late trim: removed {late_removed} more skill chips before submit.")
                _settle(page)

            _log("7/8", "Validating application...")
            verification = _verify_application(page, resume_path.name)
            result["fields"]["problems"] = verification["problems"]
            if not verification["passed"]:
                result["status"] = "FAILED"
                _shot(page, f"sap-{job_id}-validation-failed.png")
                raise RuntimeError(
                    f"ERROR: Pre-submit validation failed: {verification['problems']} "
                    "The application was not submitted."
                )
            result["beforeSubmitUrl"] = page.url
            result["beforeSubmitTitle"] = page.title()
            _shot(page, f"sap-{job_id}-before-submit.png")

            if dry_run:
                result["status"] = "DRY_RUN"
                result["notes"].append("DRY RUN: final submission was intentionally skipped.")
                _log("8/8", "DRY RUN: final Apply button was NOT clicked.")
                _save()
                print("\nDRY RUN COMPLETE\nApplication was NOT submitted.", flush=True)
                return result

            _log("8/8", "Submitting application...")
            submit_button = _find_submit_button(page)
            submit_started_at = int(time.time() * 1000)
            submit_button.scroll_into_view_if_needed()
            submit_button.click()
            _wait_networkidle(25_000)

            _log("8/8", "Verifying submission...")
            after_text = _visible_body_text(page)
            for _attempt in range(15):
                page.wait_for_timeout(1_000)
                after_text = _visible_body_text(page)
                if SUCCESS_TEXT.search(after_text) or ALREADY_APPLIED_TEXT.search(after_text):
                    break

            result["afterSubmitUrl"] = page.url
            result["afterSubmitTitle"] = page.title()

            # SAP rejects client-side with an error banner instead of navigating.
            banner = page.locator("text=/Please correct the errors below/i")
            if banner.count() and banner.first.is_visible():
                section_errors = [
                    _norm(el.text_content(timeout=1_000) or "")
                    for el in page.locator(".rcmValidationMsgArea:not(.displayNone)").all()
                ]
                section_errors = [e for e in section_errors if e]
                result["status"] = "FAILED"
                result["errors"].append({
                    "type": "form-rejected",
                    "message": f"SAP showed 'Please correct the errors below'. Details: {section_errors}",
                })
                _shot(page, f"sap-{job_id}-form-rejected.png")
                _save()
                print(f"\nSAP rejected the form: {section_errors}", flush=True)
                return result
            result["successIndicators"]["urlChanged"] = result["afterSubmitUrl"] != result["beforeSubmitUrl"]
            result["successIndicators"]["confirmationMessage"] = bool(
                SUCCESS_TEXT.search(after_text) or ALREADY_APPLIED_TEXT.search(after_text)
            )
            result["successIndicators"]["formChanged"] = (
                not page.locator("[id$=':_submitBtn']").count()
            )
            result["successIndicators"]["statusLinkAppeared"] = bool(
                page.locator("a[id*='statusLink']").count()
            )
            result["successIndicators"]["networkResponses"] = [
                r for r in network_responses if r["timestamp"] >= submit_started_at
            ][-20:]
            _shot(page, f"sap-{job_id}-after-submit.png")

            network_success = any(
                200 <= r["status"] < 300 for r in result["successIndicators"]["networkResponses"]
            )
            state_changed = (
                result["successIndicators"]["urlChanged"]
                or result["successIndicators"]["formChanged"]
                or result["successIndicators"]["statusLinkAppeared"]
            )
            if result["successIndicators"]["confirmationMessage"] and state_changed and network_success:
                result["status"] = "SUCCESS"
            else:
                result["status"] = "NEEDS_ATTENTION"
                result["notes"].append(
                    "The observed signals did not meet the strong-evidence threshold for SUCCESS."
                )
            _save()
            print(f"\nFinal status: {result['status']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if message.startswith("BLOCKED:"):
                result["status"] = "BLOCKED"
            elif result["status"] not in {"FAILED"}:
                result["status"] = "NEEDS_ATTENTION"
            result["errors"].append({"type": "automation", "message": message})
            try:
                result["afterSubmitUrl"] = page.url
                result["afterSubmitTitle"] = page.title()
                _shot(page, f"sap-{job_id}-error.png")
            except Exception:  # noqa: BLE001
                pass
            _save()
            print(f"\n{message}", flush=True)
        finally:
            context.close()
            browser.close()

    return result


def _load_batch_jobs() -> list[dict]:
    """job_url + resume pairs straight from step 5's resume_report.json."""
    report_path = ROOT / "program_files" / "output_sap" / "resume_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    jobs = []
    for entry in report.get("results", []):
        if entry.get("error"):
            continue
        jobs.append({"job_url": entry["job_url"], "resume": entry["pdf"], "title": entry.get("title", "")})
    if not jobs:
        raise RuntimeError(f"ERROR: No successful resume builds in {report_path}.")
    return jobs


def _run_batch(dry_run: bool, only_job_id: str | None = None) -> int:
    jobs = _load_batch_jobs()
    if only_job_id:
        jobs = [j for j in jobs if _job_id(j["job_url"]) == only_job_id]
        if not jobs:
            print(f"No job with id {only_job_id!r} in resume_report.json")
            return 1
    mode = "DRY-RUN" if dry_run else "SUBMIT"
    print(f"=== Batch {mode}: {len(jobs)} job(s) ===", flush=True)
    batch_statuses: dict[str, str] = {}
    for index, job in enumerate(jobs, 1):
        resume = Path(job["resume"])
        if not resume.exists():
            print(f"[batch] SKIP (resume missing): {job['title']}", flush=True)
            continue
        print(
            f"\n[batch {index}/{len(jobs)}] {job['title']}\n"
            f"  url: {job['job_url']}\n  resume: {resume.name}",
            flush=True,
        )
        try:
            outcome = apply_to_sap_job(job["job_url"], resume, dry_run=dry_run, headless=False)
            batch_statuses[_job_id(job["job_url"])] = outcome["status"]
        except Exception as exc:  # noqa: BLE001
            batch_statuses[_job_id(job["job_url"])] = f"LOCAL_ERROR: {exc}"
            print(f"[batch] LOCAL ERROR: {exc}", flush=True)
            continue
        if index < len(jobs):
            print("[batch] pausing 10s between jobs...", flush=True)
            page_wait(10)

    print("\n=== Batch summary ===", flush=True)
    for job_id, status in batch_statuses.items():
        print(f"  {job_id}: {status}", flush=True)
    counts: dict[str, int] = {}
    for status in batch_statuses.values():
        key = status.split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    print(json.dumps(counts, indent=2), flush=True)
    return 0


def page_wait(seconds: float) -> None:
    time.sleep(seconds)


def main() -> int:
    args = sys.argv[1:]
    real_submit = "--submit" in args
    dry_run = not real_submit
    run_all = "--all" in args
    pre_confirmed = "--yes" in args  # for unattended runs; the operator confirms separately
    run_single_test = not (run_all or ("--job-id" in args))
    only_job_id = args[args.index("--job-id") + 1] if "--job-id" in args else None

    if run_all or only_job_id:
        if real_submit and not pre_confirmed:
            answer = input("Really SUBMIT applications for the selected job(s)? Type YES: ")
            if answer.strip() != "YES":
                sys.exit("Aborted.")
        return _run_batch(dry_run, only_job_id)

    if real_submit and not pre_confirmed:
        answer = input(f"Really submit the application to {JOB_URL}? Type YES: ")
        if answer.strip() != "YES":
            sys.exit("Aborted.")
    outcome = apply_to_sap_job(JOB_URL, RESUME_PATH, dry_run=dry_run, headless=False)
    print(json.dumps({k: outcome[k] for k in ("status", "fields", "screenshots", "notes")}, indent=2, default=str))
    return 0 if outcome["status"] in {"SUCCESS", "DRY_RUN"} else 1


if __name__ == "__main__":
    sys.exit(main())
