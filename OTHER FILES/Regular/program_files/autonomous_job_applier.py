import os
import sys
import json
import time
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, BrowserContext

JEV_API_KEY = "apikey_22119f2073a492064ccfa7b608e441af56d0_fb26c19638f1443a52585ad39336b2e3953e0cb9b5f8a6dcb23d843d98fc78d1"
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"

def query_jev(state_desc: str, instructions: str, criteria: dict[str, str]) -> str:
    """Use JEV System One fast decision layer to select the optimal action."""
    headers = {
        "Authorization": f"Bearer {JEV_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "jev-latest",
        "state": state_desc[:1500],
        "questions": {
            "selected_action": {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria
            }
        }
    }
    try:
        resp = requests.post(JEV_ENDPOINT, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            choice = data.get("answers", {}).get("selected_action", {}).get("choice")
            return choice
        else:
            print(f"[JEV] Warning HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[JEV] Error querying JEV: {e}")
    # Fallback: pick first option
    return list(criteria.keys())[0] if criteria else ""


class AutonomousJobApplier:
    def __init__(self, profile_path: str = "profile.json", screenshot_dir: str = "program_files/output_v2/screenshots"):
        with open(profile_path, "r", encoding="utf-8") as f:
            self.profile = json.load(f)
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def handle_cookie_banners(self, page: Page):
        """Detect and click common cookie consent dialogs."""
        cookie_selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Alle akzeptieren')",
            "button:has-text('Alles akzeptieren')",
            "button:has-text('Einverstanden')",
            "button:has-text('Zulassen')",
            "button:has-text('Zustimmen')",
            "button:has-text('Accept Cookies')",
            "button:has-text('Accept')",
            "button[data-testid*='cookie-accept']",
            "button#onetrust-accept-btn-handler",
            "button.cmp-intro_acceptAll"
        ]
        for sel in cookie_selectors:
            try:
                el = page.locator(sel).first
                if el and el.is_visible():
                    print(f"  [Cookie] Dismissing banner via: {sel}")
                    el.click(timeout=2000)
                    page.wait_for_timeout(1000)
                    return True
            except:
                pass
        return False

    def detect_stop_conditions(self, page: Page, current_url: str) -> dict:
        """Detect CAPTCHA, MFA/OTP, Account Login, or Final Submit."""
        content = page.content().lower()
        title = page.title().lower()
        url_lower = current_url.lower()

        # 1. CAPTCHA
        captcha_indicators = ["hcaptcha", "recaptcha", "cf-turnstile", "g-recaptcha", "geetest", "arkoselabs"]
        for ind in captcha_indicators:
            if ind in content or page.locator(f"iframe[src*='{ind}'], div[class*='{ind}']").count() > 0:
                return {
                    "stop": True,
                    "reason": "CAPTCHA_DETECTED",
                    "detail": f"Captcha detected ({ind}). Requires manual human solve."
                }

        # 2. MFA / OTP
        if any(term in content for term in ["verification code", "bestätigungscode", "security code", "one-time password", "enter the code sent"]):
            return {
                "stop": True,
                "reason": "MFA_OTP_REQUIRED",
                "detail": "Two-factor authentication / OTP required."
            }

        # 3. Login / Password required before continuing
        if "login" in url_lower or "signin" in url_lower or "anmelden" in url_lower:
            # Check if there is an active password input
            if page.locator("input[type='password']").count() > 0:
                # Check if it is a sign-in or account creation wall
                return {
                    "stop": True,
                    "reason": "LOGIN_REQUIRED",
                    "detail": f"Login / account wall reached on {current_url}. User credentials required."
                }

        return {"stop": False, "reason": None}

    def fill_semantic_field(self, page: Page, el, field_name: str, field_type: str, bundle: dict) -> bool:
        """Fill an input field based on semantic matching with candidate profile."""
        name_attr = (el.get_attribute("name") or "").lower()
        id_attr = (el.get_attribute("id") or "").lower()
        label_text = ""
        try:
            # Find associated label
            if id_attr:
                lbl = page.locator(f"label[for='{id_attr}']")
                if lbl.count() > 0:
                    label_text = lbl.inner_text().lower()
            if not label_text:
                # Parent label
                parent = el.locator("xpath=..")
                label_text = parent.inner_text().lower()
        except:
            pass

        combined = f"{name_attr} {id_attr} {label_text}".strip()

        # First name
        if any(w in combined for w in ["firstname", "first_name", "first-name", "vorname", "givenname"]):
            el.fill(self.profile["personal"]["first_name"])
            print(f"    Filled First Name: {self.profile['personal']['first_name']}")
            return True

        # Last name
        if any(w in combined for w in ["lastname", "last_name", "last-name", "nachname", "surname", "familyname"]):
            el.fill(self.profile["personal"]["last_name"])
            print(f"    Filled Last Name: {self.profile['personal']['last_name']}")
            return True

        # Full name
        if any(w in combined for w in ["fullname", "full_name", "your-name", "name"]) and not any(w in combined for w in ["user", "file", "company"]):
            el.fill(self.profile["personal"]["full_name"])
            print(f"    Filled Full Name: {self.profile['personal']['full_name']}")
            return True

        # Email
        if any(w in combined for w in ["email", "e-mail", "mail"]) or field_type == "email":
            el.fill(self.profile["personal"]["email"])
            print(f"    Filled Email: {self.profile['personal']['email']}")
            return True

        # Phone
        if any(w in combined for w in ["phone", "tel", "mobile", "handy", "telefon"]):
            el.fill(self.profile["personal"]["phone"])
            print(f"    Filled Phone: {self.profile['personal']['phone']}")
            return True

        # Street / Address
        if any(w in combined for w in ["street", "straße", "strasse", "address", "anschrift", "adresse"]) and not any(w in combined for w in ["email", "mail"]):
            el.fill(self.profile["personal"]["address"]["street"])
            print(f"    Filled Street: {self.profile['personal']['address']['street']}")
            return True

        # Postal code / Zip
        if any(w in combined for w in ["postal", "zip", "plz", "postleitzahl"]):
            el.fill(self.profile["personal"]["address"]["postal_code"])
            print(f"    Filled Postal Code: {self.profile['personal']['address']['postal_code']}")
            return True

        # City
        if any(w in combined for w in ["city", "ort", "stadt", "wohnort"]):
            el.fill(self.profile["personal"]["address"]["city"])
            print(f"    Filled City: {self.profile['personal']['address']['city']}")
            return True

        # Country
        if any(w in combined for w in ["country", "land", "staat"]):
            if el.evaluate("el => el.tagName") == "SELECT":
                try:
                    el.select_option(label="Germany")
                except:
                    try: el.select_option(value="DE")
                    except: pass
            else:
                el.fill(self.profile["personal"]["address"]["country"])
            print(f"    Filled Country: Germany")
            return True

        # LinkedIn
        if "linkedin" in combined:
            el.fill(self.profile["personal"]["links"]["linkedin"])
            print(f"    Filled LinkedIn URL")
            return True

        # GitHub
        if "github" in combined:
            el.fill(self.profile["personal"]["links"]["github"])
            print(f"    Filled GitHub URL")
            return True

        # Portfolio / Website
        if any(w in combined for w in ["portfolio", "website", "homepage", "url"]):
            el.fill(self.profile["personal"]["links"]["portfolio"])
            print(f"    Filled Portfolio URL")
            return True

        return False

    def handle_form_page(self, page: Page, bundle: dict) -> dict:
        """Fill all detected form inputs on the current page."""
        questions_answered = []
        
        # 1. Text / Email / Tel inputs
        inputs = page.locator("input:not([type='hidden']):not([type='submit']):not([type='button'])").all()
        for inp in inputs:
            try:
                if not inp.is_visible():
                    continue
                ftype = (inp.get_attribute("type") or "text").lower()
                if ftype == "file":
                    continue
                val = inp.input_value()
                if not val:
                    filled = self.fill_semantic_field(page, inp, "input", ftype, bundle)
                    if filled:
                        questions_answered.append(inp.get_attribute("name") or ftype)
            except Exception as e:
                pass

        # 2. Textarea (cover letter, message, motivation)
        textareas = page.locator("textarea").all()
        for ta in textareas:
            try:
                if not ta.is_visible():
                    continue
                name_attr = (ta.get_attribute("name") or "").lower()
                lbl = ""
                try: lbl = ta.locator("xpath=..").inner_text().lower()
                except: pass
                
                # Check if it's cover letter / motivation
                if any(w in f"{name_attr} {lbl}" for w in ["cover", "letter", "anschreiben", "motivation", "message", "nachricht", "note"]):
                    txt_path = bundle.get("artifacts", {}).get("letter_txt")
                    if txt_path and os.path.exists(txt_path):
                        with open(txt_path, "r", encoding="utf-8") as f:
                            letter_body = f.read()
                        ta.fill(letter_body)
                        print("    Filled Cover Letter Textarea")
                        questions_answered.append("Cover letter textarea")
            except Exception as e:
                pass

        # 3. File Uploads (Resume & Cover Letter)
        file_inputs = page.locator("input[type='file']").all()
        for fi in file_inputs:
            try:
                name_attr = (fi.get_attribute("name") or "").lower()
                lbl = ""
                try: lbl = fi.locator("xpath=..").inner_text().lower()
                except: pass
                combined = f"{name_attr} {lbl}".strip()

                r_pdf = bundle.get("artifacts", {}).get("resume_pdf")
                c_pdf = bundle.get("artifacts", {}).get("letter_pdf")

                if any(w in combined for w in ["cover", "anschreiben", "motivation"]):
                    if c_pdf and os.path.exists(c_pdf):
                        fi.set_input_files(c_pdf)
                        print(f"    Uploaded Cover Letter PDF: {os.path.basename(c_pdf)}")
                        questions_answered.append("Cover Letter Upload")
                else:
                    if r_pdf and os.path.exists(r_pdf):
                        fi.set_input_files(r_pdf)
                        print(f"    Uploaded Resume PDF: {os.path.basename(r_pdf)}")
                        questions_answered.append("Resume Upload")
            except Exception as e:
                pass

        # 4. Checkboxes (Privacy policy / Consent)
        checkboxes = page.locator("input[type='checkbox']").all()
        for cb in checkboxes:
            try:
                if not cb.is_visible():
                    continue
                lbl = ""
                try: lbl = cb.locator("xpath=..").inner_text().lower()
                except: pass
                if any(w in lbl for w in ["privacy", "datenschutz", "terms", "agree", "accept", "einverstanden", "consent"]) and not cb.is_checked():
                    cb.check()
                    print("    Checked Privacy / Terms consent checkbox")
                    questions_answered.append("Privacy policy consent")
            except Exception as e:
                pass

        return {"answered": questions_answered}

    def process_application(self, bundle: dict) -> dict:
        """Complete application workflow for a single job bundle using Playwright + JEV."""
        job_url = bundle["job_url"]
        title = bundle["title"]
        company = bundle["company"]
        file_stem = Path(bundle.get("artifacts", {}).get("resume_pdf", "app")).stem
        print(f"\n=======================================================")
        print(f"Target Job: {title} @ {company}")
        print(f"Job URL: {job_url}")
        print(f"=======================================================")

        report = {
            "title": title,
            "company": company,
            "job_url": job_url,
            "application_status": "PENDING",
            "steps_completed": [],
            "questions_answered": [],
            "problems_encountered": [],
            "final_confirmation_required": False,
            "submitted": False,
            "screenshot": ""
        }

        with sync_playwright() as p:
            # Launch Chromium
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                locale="de-DE"
            )
            page = context.new_page()

            try:
                # Step 1: Open Job URL
                print("Step 1: Navigating to Job URL...")
                page.goto(job_url, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                report["steps_completed"].append("Opened Job Posting")
                self.handle_cookie_banners(page)

                # Step 2: Confirm Position & Locate Application CTA
                print("Step 2: Analyzing page and locating application CTA...")
                page_text = page.inner_text("body")[:1000].replace("\n", " ")
                
                # Check for Apply / Bewerben CTA buttons
                cta_candidates = []
                for el in page.locator("a, button").all():
                    try:
                        if not el.is_visible():
                            continue
                        txt = (el.inner_text() or "").strip()
                        href = el.get_attribute("href") or ""
                        if any(w in txt.lower() for w in ["apply", "bewerben", "stellenangebot", "jetzt bewerben", "quick apply"]) and len(txt) < 60:
                            cta_candidates.append((el, txt, href))
                    except:
                        pass

                if not cta_candidates:
                    # Let JEV choose next action
                    report["problems_encountered"].append("No direct Apply CTA found on initial page.")
                    print("  No obvious apply CTA found.")
                else:
                    # Use JEV to select the best CTA button
                    options = {}
                    for idx, (el, txt, href) in enumerate(cta_candidates[:5]):
                        options[f"action_{idx}"] = f"Click '{txt}' (links to {href[:40]})"
                    options["scroll"] = "Scroll down to inspect more details"

                    jev_decision = query_jev(
                        state_desc=f"On job page for {title} at {company}. Found buttons: {options}",
                        instructions="Select the action that begins the official job application.",
                        criteria=options
                    )
                    print(f"  [JEV Decision] Selected: {jev_decision}")

                    # Execute selected action
                    target_idx = 0
                    if jev_decision.startswith("action_"):
                        target_idx = int(jev_decision.split("_")[1])
                    
                    target_el, target_txt, target_href = cta_candidates[target_idx]
                    print(f"  Executing CTA: Clicking '{target_txt}'")
                    
                    # Watch for new tab/page
                    with context.expect_page(timeout=5000) as new_page_info:
                        try:
                            target_el.click()
                        except:
                            if target_href.startswith("http"):
                                page.goto(target_href)
                    
                    try:
                        app_page = new_page_info.value
                        app_page.wait_for_load_state("domcontentloaded")
                    except:
                        app_page = page

                    app_page.wait_for_timeout(3000)
                    self.handle_cookie_banners(app_page)
                    report["steps_completed"].append(f"Navigated to application portal ({app_page.url[:60]})")

                    # Step 3: Check Stop Conditions (Captcha, MFA, Login Wall)
                    stop_check = self.detect_stop_conditions(app_page, app_page.url)
                    if stop_check["stop"]:
                        print(f"  [STOP CONDITION TRIGGERED]: {stop_check['reason']} - {stop_check['detail']}")
                        report["application_status"] = f"STOPPED_{stop_check['reason']}"
                        report["problems_encountered"].append(stop_check["detail"])
                        
                        # Take screenshot
                        ss_path = str(self.screenshot_dir / f"{file_stem}_stop.png")
                        app_page.screenshot(path=ss_path)
                        report["screenshot"] = ss_path
                        browser.close()
                        return report

                    # Step 4: Explore and Fill Application Form
                    print("Step 4: Filling application form elements...")
                    fill_res = self.handle_form_page(app_page, bundle)
                    report["questions_answered"].extend(fill_res["answered"])
                    report["steps_completed"].append(f"Filled {len(fill_res['answered'])} form fields")

                    # Step 5: Check for Final Submission Button / Confirmation Gate
                    print("Step 5: Verifying submission status...")
                    submit_buttons = app_page.locator("button:has-text('Submit'), button:has-text('Absenden'), button:has-text('Bewerbung absenden'), input[type='submit']").all()
                    
                    if submit_buttons:
                        print("  [FINAL SUBMISSION GATE REACHED]: Ready for final submission.")
                        report["application_status"] = "READY_FOR_CONFIRMATION"
                        report["final_confirmation_required"] = True
                        report["steps_completed"].append("Reached final review & submission screen")
                    else:
                        report["application_status"] = "IN_PROGRESS_OR_PORTAL_REDIRECT"

                    # Take screenshot of final application state
                    ss_path = str(self.screenshot_dir / f"{file_stem}_status.png")
                    app_page.screenshot(path=ss_path)
                    report["screenshot"] = ss_path

            except Exception as e:
                print(f"  [Exception encountered]: {e}")
                report["problems_encountered"].append(str(e))
                report["application_status"] = "ERROR_ENCOUNTERED"
            finally:
                browser.close()

        return report
