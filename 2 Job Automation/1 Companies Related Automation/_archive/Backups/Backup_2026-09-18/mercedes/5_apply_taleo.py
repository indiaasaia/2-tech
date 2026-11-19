"""5_apply_taleo.py -- D-MAC/Taleo apply automation for Mercedes-Benz jobs.

TARGET PORTAL
    tas-DAIMLER.taleo.net careersection apply forms (job=MER000xxxx&lang=de),
    reached through each posting's `apply_url` recorded by step 2.

ARCHITECTURE (mirrors 4_MERCEDES_job_apply.py)
    * semantic locators only (getByLabel/getByText/roles/name/id) - never
      coordinates, never positional .nth() guessing
    * discovery-first: dump the live form structure before touching anything
    * config-driven answers from config/candidate.json + resume autofill
    * every filled value is read back from the DOM before continuing
    * dry-run default: --submit needed for real submission (+ typed YES)
    * screenshots per stage + structured result JSON in results/
    * CAPTCHA/MFA -> BLOCKED, never bypassed

STATUS: DOM primitives below are RESEARCH-BASED on Taleo careersection 25C
classics and MUST be verified against the live form (probe mode) before a
real submission is attempted. The script refuses to submit until
verify_dom_assumptions() has passed on the live page.

Usage:
    python 5_apply_taleo.py --discover --url "<apply_url>"   # form structure dump
    python 5_apply_taleo.py --url "<apply_url>" --resume resume.pdf --dry-run
    python 5_apply_taleo.py --url "<apply_url>" --resume resume.pdf --submit
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
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_DIR / "config" / "candidate.json"
RESULTS_DIR = PROJECT_DIR / "results"

DEFAULT_TIMEOUT_MS = 20_000
HEADLESS = False


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not parse {CONFIG_PATH} ({exc}); using built-in defaults.")
        return {}


_CONFIG = _load_config()


def _cfg(key: str, default):
    value = _CONFIG.get(key)
    return default if value is None else value


# ---------------------------------------------------------------------------
# Field mappings - every question is matched by normalized label text.
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


# Taleo labels are German here (lang=de). English variants are included for
# lang=en fallback. Keys are field roles, lists are match patterns.
FIELD_PATTERNS: dict[str, list[str]] = {
    "first_name": ["vorname", "firstname", "givenname"],
    "last_name": ["nachname", "lastname", "familienname", "surname"],
    "email": ["email", "emailadresse", "emailaddress", "emailaddress1"],
    "phone": ["telefon", "phone", "telefonnummer", "phonenumber", "mobil", "mobile"],
    "address_street": ["strasse", "strase", "street", "address", "adresse"],
    "address_zip": ["postleitzahl", "plz", "zip", "postalcode"],
    "address_city": ["stadt", "ort", "city"],
    "address_country": ["land", "country"],
    "earliest_start": ["fruhestmoglicher", "fruehester", "eintrittstermin",
                       "starttermin", "verfugbar", "availability", "startdate",
                       "moglicherstart", "start"],
    "salary_expectation": ["gehalt", "salary", "vergutung", "remuneration"],
    "cover_letter": ["motivation", "anschreiben", "coverletter", "begleitschreiben"],
    "linkedin": ["linkedin"],
    "relocation": ["umzugsbereit", "relocation", "umzug"],
}

# Multiple-choice question patterns -> configured answers.
QUESTION_ANSWERS: list[tuple[list[str], str]] = [
    (["arbeitsgenehmigung", "workpermit", "arbeitserlaubnis",
      "berechtigungindeutschlandzuarbeiten", "legallyauthorized"],
     str(_cfg("work_permit_answer", "Yes")).lower()),
    (["bewerbenschon", "alreadyapplied", "habensiebereits"],
     str(_cfg("already_applied_answer", "No")).lower()),
    (["umzugsbereit", "relocation", "sindwesiezur"],
     str(_cfg("relocation_answer", "Yes")).lower()),
    (["geschlecht", "gender"], str(_cfg("gender_answer", "No answer")).lower()),
]

SUBMIT_TEXTS = ["absenden", "submit", "senden", "abschicken", "einreichen", "bewerbungabsenden"]
NEXT_TEXTS = ["weiter", "next", "continue", "fortfahren"]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def discover_form(page) -> dict:
    """Dump every field of the live Taleo form (labels, types, options)."""
    return page.evaluate(
        """() => {
            const out = {fields: [], buttons: [], selects: []};
            for (const el of document.querySelectorAll('input, textarea')) {
                const id = el.id || '';
                const label = id
                    ? (document.querySelector(`label[for="${id}"]`)?.innerText || '')
                    : '';
                out.fields.push({
                    tag: el.tagName, type: el.type || '', id,
                    name: el.name || '', label: label.trim().slice(0, 150),
                    required: el.required || false,
                    placeholder: (el.placeholder || '').slice(0, 80),
                });
            }
            for (const el of document.querySelectorAll('select')) {
                out.selects.push({
                    id: el.id, name: el.name || '',
                    label: (document.querySelector(`label[for="${el.id}"]`)?.innerText || '').trim().slice(0, 150),
                    options: Array.from(el.options).slice(0, 40).map(o => o.text.trim()),
                });
            }
            for (const el of document.querySelectorAll('button, input[type=submit], input[type=button], a.btn')) {
                const text = (el.innerText || el.value || '').trim();
                if (text) out.buttons.push(text.slice(0, 60));
            }
            return out;
        }"""
    )


def print_discovery(info: dict) -> None:
    print("=== TALEO FORM DISCOVERY ===")
    for field in info["fields"]:
        print(f"  [input] type={field['type']:10} id={field['id'][:40]:40} "
              f"label={field['label'][:60]}")
    for select in info["selects"]:
        print(f"  [select] id={select['id'][:40]:40} label={select['label'][:60]}")
        print(f"           options: {select['options'][:12]}")
    print(f"  [buttons] {info['buttons']}")
    print("=== END DISCOVERY ===")


def verify_dom_assumptions(info: dict) -> list[str]:
    """Return a list of assumption violations found in the discovery dump."""
    problems: list[str] = []
    all_inputs = info["fields"] + info["selects"]
    if not all_inputs:
        problems.append("no form fields found - page may not have loaded the apply form")
    haystack = _norm(" ".join(str(f.get("label") or "") + str(f.get("id") or "") for f in all_inputs))
    for role in ("first_name", "last_name", "email"):
        if not any(_norm(pattern) in haystack for pattern in FIELD_PATTERNS[role]):
            problems.append(f"expected field role '{role}' not found on live form")
    if not info["buttons"]:
        problems.append("no buttons found on live form")
    return problems


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _field_selector(field: dict) -> str:
    """CSS selector for a discovered field; '' when the field has no handle."""
    if field.get("id"):
        return f"#{field['id']}"
    if field.get("name"):
        return f"[name=\"{field['name']}\"]"
    return ""


def _find_field(info: dict, role: str) -> dict | None:
    """Find a form field by its role using normalized label/id/name matching."""
    patterns = [_norm(pattern) for pattern in FIELD_PATTERNS.get(role, [])]
    if not patterns:
        return None
    candidates = info["fields"] + info["selects"]
    # Prefer label matches, then id/name matches.
    for source in ("label", "id", "name"):
        for field in candidates:
            value = _norm(str(field.get(source) or ""))
            if value and any(pattern in value or value in pattern for pattern in patterns):
                return field
    return None


def _shot(page, results: dict, name: str) -> None:
    path = RESULTS_DIR / f"{results.get('_tag', 'taleo')}-{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        results.setdefault("screenshots", []).append(str(path))
    except Exception:  # noqa: BLE001 - screenshots must never kill the flow
        pass


def _record(results: dict, section: str, field: str, action: str, value: str) -> None:
    results.setdefault(section, []).append(
        {"field": field, "action": action, "value": str(value)[:200]}
    )


def _read_back(page, field: dict) -> str:
    """Read the current value of a field from the live DOM."""
    selector = _field_selector(field)
    if not selector:
        return ""
    try:
        if field.get("tag") == "SELECT":
            return page.eval_on_selector(selector, "el => el.selectedOptions[0]?.text || ''")
        return page.eval_on_selector(selector, "el => el.value || ''")
    except Exception:  # noqa: BLE001
        return ""


def _fill_text(page, field: dict, value: str, results: dict, section: str) -> None:
    selector = _field_selector(field)
    if not selector:
        raise RuntimeError(f"field without id/name cannot be addressed: {field}")
    locator = page.locator(selector)
    locator.scroll_into_view_if_needed(timeout=5_000)
    locator.fill(str(value))
    actual = _read_back(page, field)
    if _norm(str(actual)) != _norm(str(value)) and str(value) not in str(actual):
        raise RuntimeError(f"read-back mismatch for {field['id']}: wrote {value!r}, read {actual!r}")
    _record(results, section, field["id"] or field["name"], "filled", actual)


def _select_option(page, field: dict, wanted: str, results: dict, section: str) -> None:
    selector = _field_selector(field)
    if not selector:
        raise RuntimeError(f"field without id/name cannot be addressed: {field}")
    locator = page.locator(selector)
    locator.scroll_into_view_if_needed(timeout=5_000)
    options = page.eval_on_selector(
        selector,
        "el => Array.from(el.options).map(o => ({v: o.value, t: o.text}))",
    )
    match = next((o for o in options if _norm(o["t"]) == _norm(wanted)), None) \
        or next((o for o in options if _norm(wanted) in _norm(o["t"])), None)
    if match is None:
        raise RuntimeError(
            f"no option matching {wanted!r} in select {field['id']} "
            f"(available: {[o['t'] for o in options]})"
        )
    locator.select_option(value=match["v"])
    actual = _read_back(page, field)
    if _norm(actual) != _norm(match["t"]):
        raise RuntimeError(f"select read-back mismatch for {field['id']}: {actual!r}")
    _record(results, section, field["id"], "selected", actual)


def _click_button_by_text(page, texts: list[str]):
    """Click the first visible button whose normalized text contains any pattern."""
    for pattern in texts:
        target = _norm(pattern)
        buttons = page.locator("button, input[type=submit], input[type=button]")
        for i in range(buttons.count()):
            button = buttons.nth(i)
            try:
                if not button.is_visible():
                    continue
                label = _norm(button.inner_text() or button.get_attribute("value") or "")
                if target in label:
                    button.scroll_into_view_if_needed(timeout=5_000)
                    button.click()
                    return label
            except Exception:  # noqa: BLE001 - detached/hidden buttons are skipped
                continue
    return None


def _detect_captcha(page) -> bool:
    html = (page.content() or "").lower()
    markers = ["captcha", "recaptcha", "hcaptcha", "are-you-a-human", "botguard"]
    return any(marker in html for marker in markers)


def _walk_intro_dialogs(page, results: dict, max_steps: int = 6) -> int:
    """Advance Taleo's pre-form dialogs (language selection, disclaimer, login-skip).

    Taleo careersection opens jobapply.ftl on a JSF dialog stack: first a
    language <select> (Deutsch/Englisch/...) with Weiter, then legal-disclaimer
    pages withWeiter/accept buttons. The personal form only appears after
    these. This walker clicks Weiter (or an accept/OK button) while no real
    form fields are present, selecting 'Deutsch' (or English) when the
    language dialog shows. Returns the number of dialogs advanced.
    """
    advanced = 0
    for _ in range(max_steps):
        info = discover_form(page)
        # A real form is present when a visible non-hidden input with a label exists.
        real_fields = [f for f in info["fields"]
                       if f.get("type") not in ("hidden", "button", "submit")]
        if len(real_fields) >= 3:
            break
        # Language dialog: select German, else English.
        for select in info["selects"]:
            if not select.get("id"):
                continue
            options = [str(o) for o in select.get("options", [])]
            wanted = next((o for o in options if "deutsch" in o.lower()), None) \
                or next((o for o in options if "englisch" in o.lower()), None)
            if wanted:
                try:
                    page.eval_on_selector(
                        f"#{select['id']}",
                        "el => { const opt = Array.from(el.options).find(o => o.text === arguments[0]);"
                        " if (opt) { el.value = opt.value; el.dispatchEvent(new Event('change', {bubbles: true})); } }",
                        arg=wanted,
                    )
                    results["notes"].append(f"language dialog: selected {wanted}")
                except Exception:  # noqa: BLE001 - selection failure falls through to Weiter
                    pass
                break
        clicked = _click_button_by_text(page, NEXT_TEXTS + ["akzeptieren", "accept", "ok", "einverstanden"])
        if not clicked:
            break
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2_500)
        advanced += 1
        results["stagesReached"].append(f"dialog->{clicked}")
        _shot(page, results, f"02-dialog-{advanced}")
    return advanced


def _login_form_present(info: dict) -> bool:
    """True when the discovery dump shows Taleo's login dialog."""
    haystack = _norm(" ".join(str(f.get("label") or "") + str(f.get("id") or "")
                              for f in info["fields"]))
    return "benutzername" in haystack or "kennwort" in haystack


def _taleo_login(page, info: dict, results: dict) -> bool:
    """Log into Taleo when credentials are configured; False otherwise.

    Credentials come from env vars TALEO_USERNAME / TALEO_PASSWORD or from
    config/candidate.json (taleo_username / taleo_password) - NEVER hardcoded.
    """
    username = os.getenv("TALEO_USERNAME") or str(_cfg("taleo_username", ""))
    password = os.getenv("TALEO_PASSWORD") or str(_cfg("taleo_password", ""))
    if not username or not password:
        results["notes"].append(
            "Taleo login required; set TALEO_USERNAME/TALEO_PASSWORD env vars "
            "or taleo_username/taleo_password in config/candidate.json")
        return False
    name_field = next((f for f in info["fields"] if "login-name" in str(f.get("id") or "")), None)
    pass_field = next((f for f in info["fields"] if "login-password" in str(f.get("id") or "")), None)
    if not name_field or not pass_field:
        results["notes"].append("login form detected but username/password inputs not found")
        return False
    _fill_text(page, name_field, username, results, "login")
    _fill_text(page, pass_field, password, results, "login")
    if not _click_button_by_text(page, ["login", "log-in", "anmelden", "einloggen"]):
        results["notes"].append("login button not found")
        return False
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(4_000)
    fresh = discover_form(page)
    if _login_form_present(fresh):
        results["notes"].append("login rejected (form still showing after Log-in)")
        return False
    results["stagesReached"].append("logged-in")
    return True


def _validate_resume_path(resume_path: Path) -> Path:
    if not resume_path.exists():
        raise RuntimeError(f"ERROR: Resume file not found: {resume_path}")
    if not resume_path.is_file():
        raise RuntimeError(f"ERROR: Resume path is not a file: {resume_path}")
    if resume_path.suffix.lower() not in (".pdf", ".docx", ".doc"):
        raise RuntimeError(f"ERROR: Resume must be PDF/DOC/DOCX: {resume_path}")
    return resume_path


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
def _upload_resume(page, resume_path: Path, results: dict) -> str:
    """Upload the resume via Taleo's file input (type=file with resume markers)."""
    candidates = page.locator(
        'input[type="file"][accept*="pdf"], input[type="file"][name*="resume" i], '
        'input[type="file"][id*="resume" i], input[type="file"][name*="cv" i], '
        'input[type="file"][id*="cv" i], input[type="file"][name*="upload" i], '
        'input[type="file"][id*="upload" i]'
    )
    count = candidates.count()
    if count == 0:
        file_inputs = page.locator('input[type="file"]')
        count = file_inputs.count()
        if count == 0:
            raise RuntimeError("no file input found on the Taleo form")
        target = file_inputs.first
    else:
        target = candidates.first

    target.scroll_into_view_if_needed(timeout=5_000)
    target.set_input_files(str(resume_path))
    print(f"[TALEO] resume set: {resume_path.name} - waiting for processing ...")

    # Wait until the filename appears in the DOM (upload accepted) or timeout.
    deadline = time.time() + 90
    uploaded_name = ""
    while time.time() < deadline:
        content = page.content()
        if resume_path.stem.lower()[:12] in content.lower():
            uploaded_name = resume_path.name
            break
        page.wait_for_timeout(1_000)
    if not uploaded_name:
        print("[TALEO] WARNING: filename never appeared in DOM; upload may have failed")
        results["notes"].append("resume upload not confirmed via filename marker")
    else:
        _record(results, "resume", "upload", "uploaded", uploaded_name)
    _shot(page, results, "12-resume-uploaded")
    return uploaded_name or resume_path.name


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def apply_to_taleo_job(apply_url: str, resume_path: Path, dry_run: bool = True,
                       headless: bool = False, job_title: str = "") -> dict:
    """Apply to ONE Taleo (tas-DAIMLER) Mercedes job. Returns a result dict."""
    resume_path = _validate_resume_path(Path(resume_path))
    tag = re.sub(r"[^A-Za-z0-9]+", "-", (job_title or apply_url))[:40].strip("-") or "taleo"
    results: dict = {
        "portal": "taleo_daimler",
        "apply_url": apply_url,
        "job_title": job_title,
        "resume": str(resume_path),
        "dry_run": dry_run,
        "status": "STARTED",
        "stagesReached": [],
        "fields": [],
        "resume": [],
        "notes": [],
        "screenshots": [],
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "_tag": tag,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            # ---- open the apply form ------------------------------------
            page.goto(apply_url, wait_until="domcontentloaded",
                      timeout=DEFAULT_TIMEOUT_MS * 2)
            page.wait_for_timeout(3_000)  # Taleo bootstraps its form via JS
            results["stagesReached"].append("opened")
            _shot(page, results, "01-apply-page")

            # ---- pre-form dialogs: language selection, disclaimer, ... ---
            dialogs = _walk_intro_dialogs(page, results)
            if dialogs:
                print(f"[TALEO] advanced {dialogs} pre-form dialog(s)")

            # ---- login wall (Taleo requires an account to apply) --------
            info = discover_form(page)
            if _login_form_present(info):
                if not _taleo_login(page, info, results):
                    results["status"] = "NEEDS_CREDENTIALS"
                    _shot(page, results, "91-login-required")
                    return results
                info = discover_form(page)

            if _detect_captcha(page):
                results["status"] = "BLOCKED"
                results["notes"].append("CAPTCHA/bot protection detected on load")
                _shot(page, results, "99-captcha")
                return results

            # ---- discovery + assumption verification --------------------
            info = discover_form(page)
            print_discovery(info)
            results["discovery"] = info
            problems = verify_dom_assumptions(info)
            if problems:
                results["status"] = "NEEDS_ATTENTION"
                results["notes"].extend(problems)
                _shot(page, results, "90-dom-mismatch")
                return results
            results["stagesReached"].append("discovered")

            # ---- upload resume (before anything else; Taleo prefills) ---
            uploaded = _upload_resume(page, resume_path, results)
            results["stagesReached"].append("resume_uploaded")

            # Give Taleo time to autofill after the upload.
            page.wait_for_timeout(4_000)
            info = discover_form(page)  # refresh: autofill may change the DOM

            # ---- fill/verify personal fields ----------------------------
            personal: dict[str, str] = {
                "first_name": str(_cfg("first_name", "Meet")),
                "last_name": str(_cfg("last_name", "Raval")),
                "email": str(_cfg("email", "ravalmeett@gmail.com")),
                "phone": str(_cfg("phone", "+49 15565 468731")),
                "address_street": str(_cfg("street", "")),
                "address_zip": str(_cfg("zip", "")),
                "address_city": str(_cfg("city", "")),
            }
            for role, value in personal.items():
                if not value:
                    continue
                field = _find_field(info, role)
                if field is None:
                    results["notes"].append(f"field role '{role}' not present (skipped)")
                    continue
                existing = _read_back(page, field)
                if existing and _norm(existing) == _norm(value):
                    _record(results, "fields", field["id"], "prefilled-ok", existing)
                    continue
                if field.get("tag") == "SELECT":
                    _select_option(page, field, value, results, "fields")
                else:
                    _fill_text(page, field, value, results, "fields")
            results["stagesReached"].append("personal_fields")

            # ---- multiple-choice questions by question text -------------
            for patterns, answer in QUESTION_ANSWERS:
                for field in info["selects"]:
                    label = str(field.get("label") or "") + str(field.get("id") or "")
                    if any(_norm(pattern) in _norm(label) for pattern in patterns):
                        try:
                            current = _read_back(page, field)
                            if _norm(current) == _norm(answer):
                                _record(results, "fields", field["id"], "prefilled-ok", current)
                                continue
                            _select_option(page, field, answer, results, "fields")
                        except Exception as exc:  # noqa: BLE001
                            results["notes"].append(
                                f"question {field['id']}: {exc}")
            results["stagesReached"].append("questions")

            # ---- multi-page forms: click Next while present -------------
            for _ in range(5):
                clicked = _click_button_by_text(page, NEXT_TEXTS)
                if not clicked:
                    break
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2_500)
                info = discover_form(page)
                results["stagesReached"].append(f"next->{clicked}")

            # ---- final review screenshot --------------------------------
            _shot(page, results, "07-before-submit")
            results["stagesReached"].append("review")

            if dry_run:
                results["status"] = "DRY_RUN_COMPLETE"
                return results

            clicked = _click_button_by_text(page, SUBMIT_TEXTS)
            if not clicked:
                results["status"] = "NEEDS_ATTENTION"
                results["notes"].append("submit button not found")
                _shot(page, results, "91-no-submit")
                return results
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(4_000)
            results["stagesReached"].append(f"submitted->{clicked}")
            _shot(page, results, "08-after-submit")

            body = _norm(page.inner_text("body"))
            if _detect_captcha(page):
                results["status"] = "BLOCKED"
                results["notes"].append("CAPTCHA after submit")
            elif any(_norm(marker) in body for marker in
                     ("bestatigt", "confirmation", "thankyou", "vielen", "erfolgreich",
                      "dankesaIhre", "wirsind", "bewerbungist")):
                results["status"] = "SUCCESS"
            else:
                results["status"] = "NEEDS_ATTENTION"
                results["notes"].append("no confirmation text found after submit")
            return results

        except PlaywrightTimeoutError as exc:
            results["status"] = "FAILED"
            results["notes"].append(f"timeout: {exc}")
            _shot(page, results, "95-timeout")
            return results
        except Exception as exc:  # noqa: BLE001 - full audit on any failure
            results["status"] = results.get("status") if results.get("status") not in ("STARTED", None) else "FAILED"
            results["notes"].append(f"{type(exc).__name__}: {exc}")
            _shot(page, results, "96-error")
            return results
        finally:
            results["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            browser.close()


def _persist_result(results: dict) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{results.get('_tag', 'taleo')}-result.json"
    clean = {k: v for k, v in results.items() if k != "_tag"}
    path.write_text(json.dumps(clean, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    print(f"[TALEO] result -> {path}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Apply to ONE Taleo Mercedes job.")
    parser.add_argument("--url", required=True, help="Taleo apply_url")
    parser.add_argument("--resume", default=str(PROJECT_DIR / "config" / "candidate_resume.pdf"),
                        help="Path to the resume file (not needed with --discover)")
    parser.add_argument("--discover", action="store_true",
                        help="Only dump the live form structure, change nothing")
    parser.add_argument("--dry-run", action="store_true", help="Walk the form, stop before submit")
    parser.add_argument("--submit", action="store_true", help="Really submit (asks YES)")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    if args.discover:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=args.headless)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(args.url, wait_until="domcontentloaded", timeout=40_000)
            page.wait_for_timeout(3_000)
            print_discovery(discover_form(page))
            browser.close()
        return 0

    if args.submit:
        answer = input(f"Really SUBMIT this Taleo application?\n  url: {args.url}\nType YES to confirm: ")
        if answer.strip() != "YES":
            print("Aborted.")
            return 1

    results = apply_to_taleo_job(
        apply_url=args.url,
        resume_path=Path(args.resume),
        dry_run=not args.submit,
        headless=args.headless or HEADLESS,
    )
    _persist_result(results)
    print(json.dumps({k: results[k] for k in ("status", "stagesReached", "notes") if k in results},
                     indent=2, default=str))
    return 0 if results["status"] in ("SUCCESS", "DRY_RUN_COMPLETE") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
