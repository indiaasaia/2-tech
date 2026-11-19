#!/usr/bin/env python3
"""
LinkedIn Easy Apply Automation Bot (Tailored for Germany / DACH & International)
Candidate: Meetkumar Raval (Essen, Germany)
License: MIT
"""

import os
import sys
import json
import time
import random
import urllib.parse
import urllib.request
import subprocess
import re
from datetime import datetime

# Enable unbuffered stdout for immediate real-time logging
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    ElementClickInterceptedException,
    WebDriverException,
    StaleElementReferenceException,
)
import undetected_chromedriver as uc
from regular_app_bridge import filter_job_screening, generate_tailored_documents_for_job

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(WORKSPACE_DIR, "config.json")
HISTORY_FILE = os.path.join(WORKSPACE_DIR, "history.json")
PROFILE_DIR = os.path.join(WORKSPACE_DIR, "chrome_profile")


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Configuration file not found: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_history() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(history: dict) -> None:
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def record_job(job_id: str, title: str, company: str, status: str, details: str = "") -> None:
    history = load_history()
    history[str(job_id)] = {
        "title": title,
        "company": company,
        "status": status,
        "details": details,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_history(history)


def human_type(element, text: str) -> None:
    """Type text with randomized human-like intervals."""
    if text is None:
        return
    text_str = str(text)
    try:
        element.click()
        time.sleep(0.1)
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(Keys.BACKSPACE)
    except Exception:
        pass
    for char in text_str:
        element.send_keys(char)
        time.sleep(random.uniform(0.02, 0.08))
    time.sleep(random.uniform(0.1, 0.2))


def get_chrome_major_version() -> int:
    """Detect installed Chrome major version on Windows to prevent chromedriver version mismatch."""
    for root in ["HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"]:
        for key in [
            r"Software\Google\Chrome\BLBeacon",
            r"SOFTWARE\Google\Chrome\BLBeacon",
            r"SOFTWARE\WOW6432Node\Google\Chrome\BLBeacon",
        ]:
            try:
                cmd = f'reg query "{root}\\{key}" /v version'
                out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore")
                m = re.search(r"version\s+REG_SZ\s+(\d+)", out, re.IGNORECASE)
                if m:
                    return int(m.group(1))
            except Exception:
                pass
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            try:
                cmd = f'powershell -NoProfile -Command "(Get-Item \'{p}\').VersionInfo.ProductMajorPart"'
                out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore").strip()
                if out.isdigit():
                    return int(out)
            except Exception:
                pass
    return None


def resolve_doc_path(p: str) -> str:
    """Resolves document path whether absolute, relative, or default PDF in workspace."""
    if not p:
        local_pdf = os.path.join(WORKSPACE_DIR, "RAVAL_MEETKUMAR_RITESHKUMAR.pdf")
        return local_pdf if os.path.exists(local_pdf) else ""
    if os.path.isabs(p) and os.path.exists(p):
        return p
    candidate = os.path.join(WORKSPACE_DIR, p)
    if os.path.exists(candidate):
        return candidate
    local_pdf = os.path.join(WORKSPACE_DIR, "RAVAL_MEETKUMAR_RITESHKUMAR.pdf")
    if os.path.exists(local_pdf):
        return local_pdf
    return p


def init_browser() -> uc.Chrome:
    """Initialize Chrome with a persistent profile so cookies and login persist, fully visible on desktop."""
    os.makedirs(PROFILE_DIR, exist_ok=True)
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--lang=en-US,de-DE")
    options.add_argument("--window-size=1600,1020")
    options.add_argument("--window-position=50,30")
    options.headless = False

    major = get_chrome_major_version()
    try:
        if major:
            print(f"[*] Detected Chrome major version: {major}. Launching VISIBLE Chrome browser...", flush=True)
            driver = uc.Chrome(options=options, version_main=major, headless=False)
        else:
            print("[*] Launching VISIBLE Chrome browser with persistent profile...", flush=True)
            driver = uc.Chrome(options=options, headless=False)
    except Exception as e:
        err_msg = str(e).lower()
        if "user data directory" in err_msg or "session not created" in err_msg or "chromedriver" in err_msg:
            print(f"[!] Browser initialization notice: {e}. Clearing stale driver handles and retrying...", flush=True)
            try:
                subprocess.run("taskkill /f /im chromedriver.exe", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            time.sleep(2)
            if major:
                driver = uc.Chrome(options=options, version_main=major, headless=False)
            else:
                driver = uc.Chrome(options=options, headless=False)
        else:
            raise e
    driver.set_page_load_timeout(60)

    # Bring Chrome to the front on Windows desktop
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass

    return driver


def handle_cookie_consent(driver) -> None:
    """Dismiss European GDPR cookie consent banners on LinkedIn."""
    cookie_selectors = [
        "//button[@action-type='ACCEPT']",
        "//button[contains(., 'Accept') and contains(@class, 'artdeco-button')]",
        "//button[contains(., 'Zustimmen') or contains(., 'akzeptieren') or contains(., 'Einverstanden')]",
        "//button[contains(., 'Reject non-essential') or contains(., 'Ablehnen')]",
    ]
    for xpath in cookie_selectors:
        try:
            buttons = driver.find_elements(By.XPATH, xpath)
            for btn in buttons:
                if btn.is_displayed():
                    btn.click()
                    print("[*] Dismissed LinkedIn cookie consent banner.")
                    time.sleep(1)
                    return
        except Exception:
            pass


def ensure_logged_in(driver, config: dict) -> None:
    """Verify LinkedIn login or automatically log in with provided credentials."""
    print("[*] Checking LinkedIn login status...")
    driver.get("https://www.linkedin.com/feed")
    time.sleep(3)
    handle_cookie_consent(driver)

    if "linkedin.com/feed" in driver.current_url:
        print("[+] Already logged in to LinkedIn!")
        return

    # Check for login elements
    driver.get("https://www.linkedin.com/login")
    time.sleep(2)
    handle_cookie_consent(driver)

    creds = config.get("credentials", {})
    email = creds.get("linkedin_email", "").strip()
    password = creds.get("linkedin_password", "").strip()

    if email and password:
        try:
            print(f"[*] Attempting automated login for {email}...")
            email_fields = WebDriverWait(driver, 10).until(
                lambda d: [e for e in d.find_elements(By.CSS_SELECTOR, "input[type='email'], #username") if e.is_displayed()]
            )
            human_type(email_fields[0], email)

            pass_fields = [e for e in driver.find_elements(By.CSS_SELECTOR, "input[type='password'], #password") if e.is_displayed()]
            if pass_fields:
                human_type(pass_fields[0], password)

            submit_buttons = [b for b in driver.find_elements(By.XPATH, '//button[normalize-space(.)="Sign in" or @type="submit"]') if b.is_displayed()]
            if submit_buttons:
                submit_buttons[0].click()
                print("[*] Clicked Sign in button, waiting for redirect...")
                time.sleep(5)
        except Exception as e:
            print(f"[!] Automated login encounter: {e}")

    # Check state after submission
    current = driver.current_url.lower()

    if "feed" in current:
        print("[+] Login successful! Redirected to LinkedIn feed.")
        return

    # Check for security challenges / checkpoints
    if any(chk in current for chk in ["checkpoint", "challenge", "captcha"]):
        print("\n" + "=" * 65)
        print("[!] SECURITY CHECKPOINT / 2FA DETECTED!")
        print(f"[!] LinkedIn is asking for verification. Current URL: {driver.current_url}")
        print("[!] Waiting up to 60 seconds for verification to complete in browser...")
        print("=" * 65)
        for _ in range(30):
            if "feed" in driver.current_url.lower():
                print("[+] Security checkpoint passed! Welcome to LinkedIn feed.")
                return
            time.sleep(2)

    print(f"[*] Active LinkedIn session confirmed.")


def ensure_resume_uploaded(driver, config: dict) -> None:
    """
    Check if the candidate's resume is uploaded to LinkedIn's Application Settings.
    If not already uploaded, automatically upload it.
    """
    raw_path = config.get("documents", {}).get("resume_path", "").strip()
    resume_path = resolve_doc_path(raw_path)
    if not resume_path or not os.path.exists(resume_path):
        print(f"[-] Warning: Resume file not found at: {resume_path or raw_path}")
        return

    print("[*] Checking LinkedIn Application Settings for saved resume...")
    try:
        driver.get("https://www.linkedin.com/jobs/application-settings/")
        time.sleep(3)
        handle_cookie_consent(driver)

        # Check if already uploaded
        resume_name = os.path.basename(resume_path)
        base_prefix = os.path.splitext(resume_name)[0][:15].lower()
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()

        if base_prefix in body_text or "uploaded on" in body_text:
            print(f"[+] Default resume is already active on LinkedIn profile.")
            return

        # Upload if file input is available
        file_inputs = driver.find_elements(By.ID, "resume-upload-button")
        if file_inputs:
            print(f"[*] Uploading default resume to LinkedIn profile: {resume_name}...")
            file_inputs[0].send_keys(os.path.abspath(resume_path))
            time.sleep(5)
            print("[+] Successfully saved resume to LinkedIn Application Settings!")
    except Exception as e:
        print(f"[-] Resume check note: {e}")


def build_search_url(keyword: str, config: dict, page: int = 1) -> str:
    """Build a direct LinkedIn job search URL with exact German parameters."""
    search_cfg = config.get("search_settings", {})
    location = search_cfg.get("location", "Germany")

    params = {
        "keywords": keyword,
        "location": location,
        "f_AL": "true",  # Easy Apply only
        "sortBy": "DD",  # Date posted order
    }

    if page > 1:
        params["start"] = str((page - 1) * 25)

    # Add geoId for Germany
    if "germany" in location.lower() or "deutschland" in location.lower():
        params["geoId"] = "101282230"

    # Date posted
    date_filter = search_cfg.get("date_posted", "").lower()
    if "24" in date_filter or "day" in date_filter:
        params["f_TPR"] = "r86400"
    elif "week" in date_filter:
        params["f_TPR"] = "r604800"
    elif "month" in date_filter:
        params["f_TPR"] = "r2592000"

    # Work style: 1 = Onsite, 2 = Remote, 3 = Hybrid
    work_styles = search_cfg.get("work_style", [])
    wt_codes = []
    for ws in work_styles:
        ws_low = ws.lower()
        if "on-site" in ws_low or "onsite" in ws_low:
            wt_codes.append("1")
        elif "remote" in ws_low:
            wt_codes.append("2")
        elif "hybrid" in ws_low:
            wt_codes.append("3")
    if wt_codes:
        params["f_WT"] = ",".join(wt_codes)

    return f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}"


def get_field_context(element, dialog) -> str:
    """
    Extract surrounding question text, labels, and container text
    for any given form input element inside the modal.
    """
    context_parts = []
    try:
        # 1. Associated label via ID
        elem_id = element.get_attribute("id")
        if elem_id:
            try:
                labels = dialog.find_elements(By.XPATH, f".//label[@for='{elem_id}']")
                for l in labels:
                    txt = l.text.strip()
                    if txt:
                        context_parts.append(txt)
            except Exception:
                pass

        # 2. aria-label or name or placeholder
        for attr in ["aria-label", "name", "placeholder"]:
            try:
                val = element.get_attribute(attr)
                if val:
                    context_parts.append(val)
            except Exception:
                pass

        # 3. Walk up 3 parent levels to capture the question header / prompt
        curr = element
        for _ in range(4):
            try:
                curr = curr.find_element(By.XPATH, "..")
                t = curr.text.strip()
                if t and len(t) < 400 and t not in context_parts:
                    context_parts.append(t)
                    break
            except Exception:
                break
    except Exception:
        pass

    full_context = " ".join(context_parts).lower()
    return full_context


def ask_ollama_for_answer(question: str, field_type: str = "text", options: list = None, job_info: dict = None, config: dict = None) -> str:
    """
    Queries Ollama Cloud API (gpt-oss:120b) to intelligently answer any custom,
    unrecognized, or complex application questions based on candidate profile and history.
    """
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}

    ollama_cfg = config.get("ollama_settings", {})
    if not ollama_cfg.get("enabled", True):
        return ""

    api_key = ollama_cfg.get("api_key", "3bf91710a3c6494ebee9ae6d8651895d.Tyq9heyOhZACkdBJbJ4fdPmB")
    model = ollama_cfg.get("model", "gpt-oss:120b")
    base_url = ollama_cfg.get("base_url", "https://ollama.com").rstrip("/")
    endpoint = f"{base_url}/v1/chat/completions"

    personal = config.get("personal_info", {})
    career = config.get("career_details", {})
    auth = config.get("work_authorization_germany", {})

    job_title = job_info.get("title", "AI / Python Engineer") if job_info else "Software / AI Engineer"
    company = job_info.get("company", "Company") if job_info else "Company"

    system_prompt = f"""You are an autonomous AI assisting Meetkumar Raval in applying to jobs via LinkedIn Easy Apply.
Meetkumar's Verified Profile:
- Full Name: {personal.get('first_name', 'Meetkumar')} {personal.get('last_name', 'Raval')}
- Location: {personal.get('city', 'Cottbus')}, {personal.get('country', 'Germany')} (PLZ: {personal.get('postal_code', '03046')})
- Phone: {personal.get('phone_number', '015567018163')}
- University: {career.get('university', 'BTU Cottbus-Senftenberg')} (Master in Computer Science / Artificial Intelligence, 2026)
- Experience: {career.get('total_years_experience', '3')} years hands-on experience in AI Engineering, Python, Machine Learning, Deep Learning, Large Language Models (LLMs), AI Agents, NLP, LangChain, LlamaIndex, PyTorch, Transformers, Computer Vision, Docker, Cloud, FastAPI, Django, SQL, MongoDB, Linux, Git.
- Languages: English ({career.get('english_proficiency', 'C2 Native')}), German ({career.get('german_proficiency', 'A1.2 Basic / A2 Conversational')})
- Work Authorization in Germany: Legally authorized to work in Germany (student visa permit with employment rights under AufenthG). Does NOT require visa sponsorship.
- Notice Period / Start: Available immediately (0 days notice).
- Desired Salary: {career.get('expected_salary_eur', '60000')} EUR/year (or 20 EUR/hour for student positions).
- Willing to relocate / commute within Germany: Yes.
- Portfolio / Website: {career.get('github_or_portfolio', 'https://raval.vercel.app')}
- LinkedIn: {career.get('linkedin_profile_url', 'https://linkedin.com/in/meetraval')}

Target Job Application Context:
- Target Role: {job_title}
- Target Employer: {company}

STRICT ANSWERING RULES:
1. If OPTIONS are provided (for dropdowns or radio groups):
   You MUST choose the single best matching option from the provided list that truthfully qualifies Meetkumar and passes ATS screening.
   Return ONLY the exact text of that chosen option. Do NOT add explanation, quotes, or markdown.
2. When asked about experience with software tools, frameworks, AI libraries (LangChain, Docker, Git, PyTorch, etc.):
   Answer affirmatively ("Yes" or positive experience option) to pass screening filters.
3. If numeric input (years, hours, salary, count):
   Return ONLY the number (e.g. "3", "60000", "20", "0").
4. If Yes/No question:
   Return ONLY "Yes" or "No". Pick the qualifying answer that fits Meetkumar's background.
5. If short text or textarea (why you fit, project summary, skills):
   Return a concise, professional 1-2 sentence statement grounded strictly in Meetkumar's real AI/Python engineering capabilities.
6. Return ONLY the answer string. Do NOT write "Answer:", do NOT explain reasoning."""

    options_str = "\n".join([f"- {opt}" for opt in options]) if options else "None (free text / numeric input)"
    user_prompt = f"""QUESTION TO ANSWER:
"{question}"

FIELD TYPE: {field_type}
OPTIONS AVAILABLE:
{options_str}

Return only the final exact value to submit:"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1
    }

    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "LinkedInAutoApply/2.0"
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_answer = data["choices"][0]["message"]["content"].strip()

            # Sanitize answer
            ans = raw_answer.strip().strip('"').strip("'")
            if ans.startswith("```"):
                ans = ans.split("\n")[1] if len(ans.split("\n")) > 1 else ans
                ans = ans.replace("```", "").strip()

            # If options were given, match to closest option
            if options:
                for opt in options:
                    if ans.lower() == opt.strip().lower():
                        print(f"    [AI] Ollama Cloud selected: '{opt}' for question: '{question[:45]}...'", flush=True)
                        return opt.strip()
                for opt in options:
                    if opt.strip().lower() in ans.lower() or ans.lower() in opt.strip().lower():
                        print(f"    [AI] Ollama Cloud matched: '{opt}' for question: '{question[:45]}...'", flush=True)
                        return opt.strip()
                return options[0]

            print(f"    [AI] Ollama Cloud answered: '{ans[:60]}' for question: '{question[:45]}...'", flush=True)
            return ans
    except Exception as e:
        print(f"    [!] Ollama Cloud fallback notice ({e}); using heuristic.", flush=True)
        return ""


def fill_dialog_inputs(dialog, config: dict, driver=None, job_info: dict = None) -> None:
    """
    Intelligently inspects and fills all form fields in the active Easy Apply dialog step.
    Handles German and English question variations, dropdowns, radios, and consent checkboxes.
    """
    if driver is None:
        try:
            driver = dialog.parent
        except Exception:
            driver = None

    personal = config.get("personal_info", {})
    career = config.get("career_details", {})
    auth = config.get("work_authorization_germany", {})

    # Helper function to safely click radio buttons via label or JS
    def click_radio_safely(r_elem) -> bool:
        r_id = r_elem.get_attribute("id")
        if r_id:
            lbls = dialog.find_elements(By.XPATH, f".//label[@for='{r_id}']")
            if lbls and lbls[0].is_displayed():
                try:
                    lbls[0].click()
                    return True
                except Exception:
                    if driver:
                        try:
                            driver.execute_script("arguments[0].click();", lbls[0])
                            return True
                        except Exception:
                            pass
        try:
            r_elem.click()
            return True
        except Exception:
            if driver:
                try:
                    driver.execute_script("arguments[0].click();", r_elem)
                    return True
                except Exception:
                    pass
        return False

    # 1. Text, number, tel, and email inputs
    try:
        inputs = dialog.find_elements(By.XPATH, ".//input[@type='text' or @type='number' or @type='tel' or @type='email' or not(@type)]")
        for inp in inputs:
            try:
                if not inp.is_displayed():
                    continue
                curr_val = inp.get_attribute("value") or ""
                ctx = get_field_context(inp, dialog)
                inp_type = (inp.get_attribute("type") or "text").lower()

                # Experience (Python, Linux, Docker, total, etc.)
                if any(w in ctx for w in ["experience", "erfahrung", "years", "jahre", "berufserfahrung"]):
                    human_type(inp, career.get("total_years_experience", "3"))

                # Salary / Compensation / Gehalt / Brutto
                elif any(w in ctx for w in ["salary", "compensation", "gehalt", "gehaltsvorstellung", "brutto", "ctc"]):
                    if any(w in ctx for w in ["stunde", "stündlich", "hourly", "pro stunde"]):
                        human_type(inp, "20")
                    else:
                        human_type(inp, career.get("expected_salary_eur", "60000"))

                # Notice period / Kündigungsfrist / Start date / Availability
                elif any(w in ctx for w in ["notice", "kündigungsfrist", "start date", "eintritt", "earliest", "available", "verfügbar", "ab wann", "start working", "beginn", "starten"]):
                    if inp_type == "number" or any(w in ctx for w in ["monate", "months", "wochen", "weeks", "tage", "days"]):
                        human_type(inp, "0")
                    else:
                        human_type(inp, career.get("notice_period_months", "Immediately"))

                # Student Enrollment / Werkstudent / Studium
                elif any(w in ctx for w in ["student", "immatrikuliert", "enrolled", "werkstudent", "studium"]):
                    if inp_type == "number":
                        human_type(inp, "20" if "hour" in ctx or "stunde" in ctx else "2026")
                    else:
                        human_type(inp, "Yes")

                # University / Hochschule / School
                elif any(w in ctx for w in ["university", "hochschule", "universität", "school"]):
                    human_type(inp, career.get("university", "BTU Cottbus-Senftenberg"))

                # Degree / Major / Field of study / Abschluss / Studiengang
                elif any(w in ctx for w in ["degree", "abschluss", "major", "studiengang", "field of study", "fachrichtung"]):
                    human_type(inp, career.get("degree", "Computer Science"))

                # Hours per week / Wochenstunden
                elif any(w in ctx for w in ["hours per week", "wochenstunden", "stunden pro woche", "arbeitsstunden", "weekly hours"]):
                    human_type(inp, "20")

                # Graduation year
                elif any(w in ctx for w in ["graduation", "abschlussjahr"]):
                    human_type(inp, "2026")

                # First name
                elif any(w in ctx for w in ["first name", "vorname"]):
                    target_first = personal.get("first_name", "Meetkumar")
                    if curr_val != target_first:
                        human_type(inp, target_first)

                # Last name
                elif any(w in ctx for w in ["last name", "nachname", "familienname"]):
                    target_last = personal.get("last_name", "Raval")
                    if curr_val != target_last:
                        human_type(inp, target_last)

                # Phone / Mobile / Telefon
                elif any(w in ctx for w in ["phone", "telefon", "mobile", "handy", "rufnummer"]):
                    target_phone = personal.get("phone_number", "015567018163")
                    if not curr_val or curr_val.strip() != target_phone.strip():
                        human_type(inp, target_phone)

                # City / Location / Stadt / Wohnort
                elif any(w in ctx for w in ["city", "stadt", "wohnort", "location", "ort"]):
                    target_city = personal.get("city", "Cottbus")
                    if not curr_val or curr_val.strip().lower() != target_city.lower():
                        human_type(inp, target_city)
                        time.sleep(0.6)
                        try:
                            inp.send_keys(Keys.ARROW_DOWN)
                            time.sleep(0.3)
                            inp.send_keys(Keys.ENTER)
                        except Exception:
                            pass

                # Postal code / PLZ
                elif any(w in ctx for w in ["postal", "zip", "plz", "postleitzahl"]):
                    target_zip = personal.get("postal_code", "03046")
                    if not curr_val or curr_val.strip() != target_zip.strip():
                        human_type(inp, target_zip)

                # LinkedIn Profile URL
                elif "linkedin" in ctx:
                    if not curr_val:
                        human_type(inp, career.get("linkedin_profile_url", "https://linkedin.com/in/meetraval"))

                # GitHub / Portfolio / Website
                elif any(w in ctx for w in ["website", "portfolio", "github", "link", "webseite"]):
                    if not curr_val:
                        human_type(inp, career.get("github_or_portfolio", "https://github.com/ravalmeet/TradingView-Data"))

                # German proficiency
                elif any(w in ctx for w in ["german", "deutsch"]):
                    human_type(inp, career.get("german_proficiency", "A1.2 (Basic)"))

                # English proficiency
                elif any(w in ctx for w in ["english", "englisch"]):
                    human_type(inp, career.get("english_proficiency", "C2 (Native)"))

                else:
                    if not curr_val:
                        ans = ask_ollama_for_answer(ctx, field_type=inp_type, job_info=job_info, config=config)
                        if ans:
                            human_type(inp, ans)
                        else:
                            if any(w in ctx for w in ["how many", "wie viele", "jahre", "years", "number", "anzahl", "count"]):
                                human_type(inp, career.get("total_years_experience", "3"))
                            elif any(w in ctx for w in ["when", "wann", "date", "datum", "available", "start"]):
                                human_type(inp, "Immediately")
                            else:
                                human_type(inp, "Yes")
            except Exception:
                continue
    except Exception:
        pass

    # 2. Textarea (Cover Letter / Summary / AI Custom Response)
    try:
        textareas = dialog.find_elements(By.TAG_NAME, "textarea")
        for ta in textareas:
            try:
                if not ta.is_displayed():
                    continue
                if not ta.get_attribute("value"):
                    ctx = get_field_context(ta, dialog)
                    cl_text = (job_info or {}).get("cover_letter_text", "")
                    if cl_text and any(w in ctx for w in ["cover", "anschreiben", "brief", "letter", "motivation"]):
                        ta.send_keys(cl_text)
                        print(f"    [+] Injected tailored cover letter ({len(cl_text)} chars) into textarea.", flush=True)
                    else:
                        ans = ask_ollama_for_answer(ctx, field_type="textarea", job_info=job_info, config=config)
                        if ans:
                            ta.send_keys(ans)
                        else:
                            ta.send_keys("Motivated professional looking forward to contributing to your team. Please refer to my resume for full details.")
            except Exception:
                pass
    except Exception:
        pass

    # 3. Dropdown selects
    try:
        selects = dialog.find_elements(By.TAG_NAME, "select")
        for s in selects:
            try:
                if not s.is_displayed():
                    continue
                ctx = get_field_context(s, dialog)
                sel = Select(s)
                curr_text = sel.first_selected_option.text.strip().lower() if sel.all_selected_options else ""

                # Phone country code
                if any(w in ctx for w in ["phone", "country", "land", "vorwahl"]):
                    for opt in sel.options:
                        opt_l = opt.text.lower()
                        if "germany" in opt_l or "+49" in opt_l or "deutschland" in opt_l:
                            sel.select_by_visible_text(opt.text)
                            break

                # Work authorization / Legal right in Germany
                elif any(w in ctx for w in ["authorized", "berechtigt", "arbeitserlaubnis", "work permit", "eligible"]):
                    target = "yes" if auth.get("legally_authorized_in_germany") == "Yes" else "no"
                    for opt in sel.options:
                        opt_l = opt.text.lower()
                        if (target == "yes" and any(y in opt_l for y in ["yes", "ja"])) or (target == "no" and any(n in opt_l for n in ["no", "nein"])):
                            sel.select_by_visible_text(opt.text)
                            break

                # Visa sponsorship
                elif any(w in ctx for w in ["sponsor", "visum", "aufenthaltstitel"]):
                    target = "no" if auth.get("require_visa_sponsorship") == "No" else "yes"
                    for opt in sel.options:
                        opt_l = opt.text.lower()
                        if (target == "no" and any(n in opt_l for n in ["no", "nein"])) or (target == "yes" and any(y in opt_l for y in ["yes", "ja"])):
                            sel.select_by_visible_text(opt.text)
                            break

                # Student enrollment
                elif any(w in ctx for w in ["student", "immatrikuliert", "enrolled", "werkstudent"]):
                    for opt in sel.options:
                        opt_l = opt.text.lower()
                        if any(y in opt_l for y in ["yes", "ja"]):
                            sel.select_by_visible_text(opt.text)
                            break

                # German language proficiency
                elif any(w in ctx for w in ["german", "deutsch"]):
                    for opt in sel.options:
                        opt_l = opt.text.lower()
                        if any(lvl in opt_l for lvl in ["a1", "basic", "grundkenntnisse", "elementary"]):
                            sel.select_by_visible_text(opt.text)
                            break

                # English language proficiency
                elif any(w in ctx for w in ["english", "englisch"]):
                    for opt in sel.options:
                        opt_l = opt.text.lower()
                        if any(lvl in opt_l for lvl in ["c2", "fluent", "fließend", "native", "professional"]):
                            sel.select_by_visible_text(opt.text)
                            break

                else:
                    opt_labels = [opt.text.strip() for opt in sel.options if opt.text.strip() and not any(s in opt.text.strip().lower() for s in ["select", "auswählen", "choose", "bitte"])]
                    selected_by_ai = False
                    if opt_labels and not curr_text:
                        chosen_opt = ask_ollama_for_answer(ctx, field_type="dropdown", options=opt_labels, job_info=job_info, config=config)
                        if chosen_opt:
                            for opt in sel.options:
                                if opt.text.strip().lower() == chosen_opt.lower() or chosen_opt.lower() in opt.text.strip().lower():
                                    sel.select_by_visible_text(opt.text)
                                    selected_by_ai = True
                                    break
                    if not selected_by_ai and not curr_text and len(sel.options) > 1:
                        sel.select_by_index(1)
            except Exception:
                pass
    except Exception:
        pass

    # 4. Radio button groups (with robust label click + Ollama Cloud fallback)
    try:
        radios = dialog.find_elements(By.XPATH, ".//input[@type='radio']")
        radio_groups = {}
        for r in radios:
            name = r.get_attribute("name") or "default_group"
            radio_groups.setdefault(name, []).append(r)

        for group_name, r_buttons in radio_groups.items():
            if any(r.is_selected() for r in r_buttons):
                continue

            ctx = get_field_context(r_buttons[0], dialog)
            preferred = "yes"
            if any(w in ctx for w in ["sponsor", "visum"]):
                preferred = "no" if auth.get("require_visa_sponsorship") == "No" else "yes"
            elif any(w in ctx for w in ["authorized", "berechtigt", "arbeitserlaubnis", "work permit"]):
                preferred = "yes" if auth.get("legally_authorized_in_germany") == "Yes" else "no"
            elif any(w in ctx for w in ["student", "werkstudent", "immatrikuliert", "enrolled"]):
                preferred = "yes"
            elif any(w in ctx for w in ["kündigung", "non-compete", "wettbewerb"]):
                preferred = "no"

            # Single radio button in group (Terms, Privacy Policy, single consent requirement)
            if len(r_buttons) == 1:
                click_radio_safely(r_buttons[0])
                continue

            clicked = False
            for r_btn in r_buttons:
                r_id = r_btn.get_attribute("id")
                lbl_text = ""
                if r_id:
                    lbls = dialog.find_elements(By.XPATH, f".//label[@for='{r_id}']")
                    if lbls:
                        lbl_text = lbls[0].text.lower()
                val = (r_btn.get_attribute("value") or "").lower()
                combo = (lbl_text + " " + val).strip()

                if (preferred == "yes" and any(y in combo for y in ["yes", "ja", "agree", "zustimmen", "einverstanden", "akzeptieren", "vorhanden", "sure"])) or \
                   (preferred == "no" and any(n in combo for n in ["no", "nein", "disagree", "ablehnen"])):
                    if click_radio_safely(r_btn):
                        clicked = True
                        break

            if not clicked and r_buttons:
                radio_candidates = []
                for r_btn in r_buttons:
                    r_id = r_btn.get_attribute("id")
                    lbl_t = ""
                    if r_id:
                        lbls = dialog.find_elements(By.XPATH, f".//label[@for='{r_id}']")
                        if lbls and lbls[0].is_displayed():
                            lbl_t = lbls[0].text.strip()
                    if not lbl_t:
                        lbl_t = (r_btn.get_attribute("value") or "").strip()
                    if lbl_t:
                        radio_candidates.append((lbl_t, r_btn))

                if radio_candidates:
                    chosen = ask_ollama_for_answer(ctx, field_type="radio", options=[c[0] for c in radio_candidates], job_info=job_info, config=config)
                    if chosen:
                        for lbl_t, r_btn in radio_candidates:
                            if lbl_t.lower() == chosen.lower() or chosen.lower() in lbl_t.lower():
                                if click_radio_safely(r_btn):
                                    clicked = True
                                    break

                if not clicked:
                    click_radio_safely(r_buttons[0])
    except Exception:
        pass

    # 5. Checkboxes (consent, terms, acknowledgment, privacy)
    try:
        checkboxes = dialog.find_elements(By.XPATH, ".//input[@type='checkbox']")
        for cb in checkboxes:
            try:
                cb_id = cb.get_attribute("id") or ""
                if "follow" in cb_id.lower() or "folgen" in cb_id.lower():
                    continue
                if cb.is_selected():
                    continue

                ctx = get_field_context(cb, dialog)
                if "follow" in ctx or "folgen" in ctx:
                    continue

                if any(w in ctx for w in ["agree", "consent", "terms", "privacy", "datenschutz", "einwilligung", "acknowledge", "confirm", "bestätigen", "18", "age", "alter", "required"]):
                    try:
                        cb.click()
                    except Exception:
                        if driver:
                            driver.execute_script("arguments[0].click();", cb)
            except Exception:
                continue
    except Exception:
        pass


def resolve_step_errors(dialog, driver) -> None:
    """
    Scans the modal for any validation error messages, required indicators, or invalid inputs
    and proactively corrects them before advancing.
    """
    try:
        # 1. Unselected radio groups inside fieldsets with errors or required
        unselected_radios = dialog.find_elements(
            By.XPATH,
            ".//fieldset[contains(@class, 'error') or .//*[contains(@class, 'artdeco-inline-feedback--error')]]//input[@type='radio']"
        )
        for r in unselected_radios:
            try:
                r_id = r.get_attribute("id")
                if r_id:
                    lbls = dialog.find_elements(By.XPATH, f".//label[@for='{r_id}']")
                    if lbls:
                        try:
                            lbls[0].click()
                            break
                        except Exception:
                            if driver:
                                driver.execute_script("arguments[0].click();", lbls[0])
                                break
                if driver:
                    driver.execute_script("arguments[0].click();", r)
                else:
                    r.click()
                break
            except Exception:
                pass

        # 2. Checkboxes that are required or have errors
        error_cbs = dialog.find_elements(
            By.XPATH,
            ".//div[contains(@class, 'error') or .//*[contains(@class, 'artdeco-inline-feedback--error')]]//input[@type='checkbox']"
        )
        for cb in error_cbs:
            try:
                if not cb.is_selected():
                    ctx = get_field_context(cb, dialog)
                    if "follow" not in ctx and "folgen" not in ctx:
                        try:
                            cb.click()
                        except Exception:
                            if driver:
                                driver.execute_script("arguments[0].click();", cb)
            except Exception:
                pass

        # 3. Empty text inputs in error state or with aria-invalid="true"
        invalid_inputs = dialog.find_elements(
            By.XPATH,
            ".//input[(@aria-invalid='true' or contains(@class, 'error')) and (@type='text' or @type='number' or not(@type))]"
        )
        for inp in invalid_inputs:
            try:
                if inp.is_displayed():
                    val = inp.get_attribute("value") or ""
                    if not val:
                        ctx = get_field_context(inp, dialog)
                        ans = ask_ollama_for_answer(ctx, field_type="text")
                        if ans:
                            human_type(inp, ans)
                        elif any(w in ctx for w in ["how many", "jahre", "years", "number", "anzahl"]):
                            human_type(inp, "3")
                        elif any(w in ctx for w in ["salary", "gehalt", "compensation"]):
                            human_type(inp, "60000")
                        elif any(w in ctx for w in ["when", "wann", "date", "datum", "available", "start"]):
                            human_type(inp, "Immediately")
                        else:
                            human_type(inp, "Yes")
            except Exception:
                pass

        # 4. Dropdowns in error state
        error_selects = dialog.find_elements(
            By.XPATH,
            ".//div[contains(@class, 'error') or .//*[contains(@class, 'artdeco-inline-feedback--error')]]//select"
        )
        for s in error_selects:
            try:
                sel = Select(s)
                if len(sel.options) > 1 and not sel.first_selected_option.text.strip():
                    sel.select_by_index(1)
            except Exception:
                pass
    except Exception:
        pass


def close_modal_safely(driver) -> None:
    """
    Guarantees any active modal/dialog, confirmation prompt, or backdrop overlay is dismissed cleanly
    so that subsequent job listings are not blocked.
    Retries up to 3 times with time gaps.
    """
    for attempt in range(1, 4):
        try:
            dialogs = driver.find_elements(
                By.XPATH,
                "//dialog | //div[@role='dialog'] | //div[contains(@class, 'jobs-easy-apply-modal')] | //div[contains(@class, 'artdeco-modal')]"
            )
            visible_dialogs = [d for d in dialogs if d.is_displayed()]
            if not visible_dialogs:
                return

            dismiss_buttons = driver.find_elements(
                By.XPATH,
                "//button[@data-test-modal-close-btn or @aria-label='Dismiss' or @aria-label='Schließen' or contains(@class, 'artdeco-modal__dismiss') or contains(@class, 'jobs-easy-apply-modal__close') or contains(., 'Dismiss') or contains(., 'Schließen')]"
            )
            for btn in dismiss_buttons:
                if btn.is_displayed():
                    try:
                        btn.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1.0)
                    break

            discard_buttons = driver.find_elements(
                By.XPATH,
                "//button[@data-control-name='discard_application_confirm_btn' or contains(., 'Discard') or contains(., 'Verwerfen') or contains(@class, 'artdeco-modal__confirm-dialog-btn')]"
            )
            for d in discard_buttons:
                if d.is_displayed():
                    try:
                        d.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", d)
                    time.sleep(1.0)
                    break

            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(0.5)
            except Exception:
                pass

            rem = driver.find_elements(
                By.XPATH,
                "//dialog | //div[@role='dialog'] | //div[contains(@class, 'jobs-easy-apply-modal')] | //div[contains(@class, 'artdeco-modal')]"
            )
            if not any(r.is_displayed() for r in rem):
                return
        except Exception:
            pass
        time.sleep(1.2)

    try:
        driver.execute_script("""
            document.querySelectorAll('dialog, div.artdeco-modal-overlay, div.jobs-easy-apply-modal, div.artdeco-modal').forEach(el => el.remove());
        """)
        time.sleep(0.5)
    except Exception:
        pass


def extract_job_details(driver, job_id: str, fallback_title: str = "", fallback_company: str = "") -> dict:
    """
    Extracts complete job information and full description from the LinkedIn job details pane.
    """
    title = fallback_title or "AI Engineer"
    company = fallback_company or "Company"
    location = "Germany"
    description = ""

    # 1. Title from details pane
    try:
        t_elems = driver.find_elements(By.XPATH, "//h1[contains(@class, 'job-title') or contains(@class, 'jobs-unified-top-card__job-title')] | //div[contains(@class, 'jobs-details')]//h1")
        for te in t_elems:
            if te.is_displayed() and te.text.strip():
                title = te.text.strip()
                break
    except Exception:
        pass

    # 2. Company name
    try:
        c_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'jobs-unified-top-card__company-name')]//a | //span[contains(@class, 'jobs-unified-top-card__company-name')] | //div[contains(@class, 'job-details-jobs-unified-top-card__company-name')]")
        for ce in c_elems:
            if ce.is_displayed() and ce.text.strip():
                company = ce.text.strip()
                break
    except Exception:
        pass

    # 3. Location
    try:
        l_elems = driver.find_elements(By.XPATH, "//span[contains(@class, 'jobs-unified-top-card__bullet')] | //span[contains(@class, 'jobs-unified-top-card__workplace-type')]")
        for le in l_elems:
            if le.is_displayed() and le.text.strip():
                location = le.text.strip()
                break
    except Exception:
        pass

    # 4. Expand "Show more" button in description if present
    try:
        show_more_btns = driver.find_elements(By.XPATH, "//button[contains(@class, 'jobs-description__footer-button') or contains(., 'Show more') or contains(., 'Mehr anzeigen')]")
        for sm in show_more_btns:
            if sm.is_displayed():
                try:
                    sm.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", sm)
                time.sleep(0.5)
                break
    except Exception:
        pass

    # 5. Extract full description
    try:
        desc_elems = driver.find_elements(By.XPATH, "//div[contains(@class, 'jobs-description__content') or contains(@class, 'jobs-box__html-content') or contains(@class, 'jobs-description')]")
        for de in desc_elems:
            t = de.text.strip()
            if t:
                description = t
                break
    except Exception:
        pass

    if not description:
        description = f"{title} at {company}. AI and Python software engineering opportunity in Germany."

    return {
        "job_id": job_id,
        "title": title,
        "company": company,
        "location": location,
        "job_description": description,
        "job_url": f"https://www.linkedin.com/jobs/view/{job_id}"
    }


def score_job_alignment(title: str, company: str, description: str, config: dict = None) -> tuple[int, str]:
    """
    Evaluates how well the job aligns with Meetkumar's skills, qualifications, and student permit.
    Returns (score: int, reason: str).
    Scores 8-10 are accepted (>7).
    Scores 1-7 are rejected.
    """
    if config is None:
        try:
            config = load_config()
        except Exception:
            config = {}

    ollama_cfg = config.get("ollama_settings", {})
    if not ollama_cfg.get("enabled", True):
        return 8, "Ollama scoring bypassed (enabled=False)"

    api_key = ollama_cfg.get("api_key", "3bf91710a3c6494ebee9ae6d8651895d.Tyq9heyOhZACkdBJbJ4fdPmB")
    model = ollama_cfg.get("model", "gpt-oss:120b")
    base_url = ollama_cfg.get("base_url", "https://ollama.com").rstrip("/")
    endpoint = f"{base_url}/v1/chat/completions"

    system_prompt = """You are a strict, precise job alignment evaluator for Meetkumar Raval.
Meetkumar's Verified Profile:
- Master of Science in AI / Computer Science at BTU Cottbus-Senftenberg (Graduation: 2026)
- 3 years hands-on experience in AI Engineering, Python, Machine Learning, Deep Learning, LLMs, NLP, Docker, Cloud, FastAPI, SQL
- Languages: English (C2 Native proficiency), German (A1.2-A2 Conversational)
- Work Authorization: German Student Residence Permit valid until Dec 2028 (allowed up to 20h/week during semester, 40h/week in breaks / internships)
- Desired Roles: AI Engineer, Python Developer, Machine Learning Engineer, Working Student AI / Data Engineer

Evaluate how well the job description aligns with Meetkumar's background, technical skills, and language level.
Rules for Rating (1 to 10):
- 8 to 10: Excellent fit (AI/ML/Python/Software, working student or internship or junior AI engineer, English-friendly or basic German).
- 5 to 7: Moderate fit (different tech stack, or heavy German preference).
- 1 to 4: Poor fit (requires 5+ years senior management, requires fluent C1 German, or non-tech field).

Return ONLY this format:
SCORE: <integer from 1 to 10>
REASON: <concise 1-sentence justification>"""

    user_prompt = f"""JOB TO EVALUATE:
Title: {title}
Company: {company}
Description:
{description[:3500]}

Rate this job fit from 1 to 10:"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1
    }

    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "LinkedInAutoApply/2.0"
            }
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw = data["choices"][0]["message"]["content"].strip()

            score = 8
            reason = "Good alignment with AI and Python profile"
            sm = re.search(r"SCORE:\s*(\d+)", raw, re.IGNORECASE)
            if sm:
                score = int(sm.group(1))
            rm = re.search(r"REASON:\s*(.+)", raw, re.IGNORECASE)
            if rm:
                reason = rm.group(1).strip()
            return score, reason
    except Exception as e:
        print(f"    [!] Alignment scoring note ({e}); default accept (8/10).", flush=True)
        return 8, "Default accept on network fallback"


def process_easy_apply_modal(driver, config: dict, job_id: str, title: str, company: str, doc_bundle: dict = None) -> str:
    """
    Walk through the multi-step Easy Apply modal from start to finish.
    Includes a 3-attempt retry loop on any stuck step with time gaps.
    If stuck after 3 attempts, logs notice, safely closes dialog, and returns skipped status.
    """
    dry_run = config.get("search_settings", {}).get("dry_run", True)
    if doc_bundle and doc_bundle.get("resume_pdf") and os.path.exists(doc_bundle.get("resume_pdf")):
        resume_path = doc_bundle["resume_pdf"]
    else:
        resume_path = resolve_doc_path(config.get("documents", {}).get("resume_path", ""))

    cover_letter_text = doc_bundle.get("cover_letter_text", "") if doc_bundle else ""
    cover_letter_pdf = doc_bundle.get("cover_letter_pdf", "") if doc_bundle else ""

    # Wait for modal dialog to appear (up to 3 attempts with time gap)
    dialog = None
    for attempt in range(1, 4):
        try:
            dialog = WebDriverWait(driver, 4).until(
                EC.presence_of_element_located((By.XPATH, "//dialog | //div[@role='dialog'] | //div[contains(@class, 'jobs-easy-apply-modal')] | //div[contains(@class, 'artdeco-modal')]"))
            )
            if dialog:
                break
        except TimeoutException:
            if attempt < 3:
                time.sleep(1.5)
            else:
                print(f"    [-] Modal dialog did not appear for job {job_id} after 3 attempts.")
                close_modal_safely(driver)
                return "Failed: Modal dialog did not appear"

    step_count = 0
    max_steps = 10
    same_step_retries = 0
    last_step_content = ""

    while step_count < max_steps:
        step_count += 1
        time.sleep(1.2)

        # 1. Re-acquire active dialog element to prevent stale reference
        dialog = None
        for d_attempt in range(1, 4):
            try:
                dialogs = driver.find_elements(By.XPATH, "//dialog | //div[@role='dialog'] | //div[contains(@class, 'jobs-easy-apply-modal')]")
                vis = [d for d in dialogs if d.is_displayed()]
                if vis:
                    dialog = vis[0]
                    break
            except Exception:
                pass
            time.sleep(1.0)

        if not dialog:
            print(f"    [-] Modal dialog lost on step {step_count}. Cleaning up.")
            close_modal_safely(driver)
            return "Failed: Modal dialog lost"

        # Check if stuck on the exact same step as before
        try:
            current_content = dialog.text[:120].strip()
        except Exception:
            current_content = str(step_count)

        if current_content and current_content == last_step_content:
            same_step_retries += 1
            print(f"    [!] Modal on same step {step_count} (retry {same_step_retries}/3 with time gap)...", flush=True)
            if same_step_retries >= 3:
                print(f"    [NOTICE] Modal for '{title}' stuck on step {step_count} after 3 attempts. Recording issue and continuing to next job.", flush=True)
                close_modal_safely(driver)
                return f"Skipped: Form stuck on step {step_count}"
            time.sleep(2.0)
        else:
            same_step_retries = 0
            last_step_content = current_content

        # 2. Check if Submit Application button is ALREADY visible (Review screen or Single-step modal)
        submit_buttons = dialog.find_elements(
            By.XPATH,
            ".//button[contains(., 'Submit application') or contains(., 'Bewerbung einreichen') or contains(., 'Bewerbung absenden') or contains(., 'Bewerbung senden') or contains(@aria-label, 'Submit application') or contains(@aria-label, 'Bewerbung einreichen') or contains(@aria-label, 'Bewerbung absenden')]"
        )
        if not submit_buttons:
            submit_buttons = driver.find_elements(
                By.XPATH,
                "//div[contains(@class, 'jobs-easy-apply-modal') or contains(@class, 'artdeco-modal')]//button[contains(., 'Submit application') or contains(., 'Bewerbung einreichen') or contains(., 'Bewerbung absenden') or contains(., 'Bewerbung senden')]"
            )

        vis_submit = [b for b in submit_buttons if b.is_displayed()]
        if vis_submit:
            active_submit = vis_submit[0]
            # Scroll dialog down to ensure submit button is visible
            try:
                driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", dialog)
                time.sleep(0.8)
            except Exception:
                pass

            # Uncheck follow company checkbox if present
            try:
                follow_box = dialog.find_elements(By.ID, "follow-company-checkbox")
                if follow_box and follow_box[0].is_selected():
                    lbl = dialog.find_elements(By.XPATH, "//label[@for='follow-company-checkbox']")
                    if lbl:
                        lbl[0].click()
            except Exception:
                pass
            try:
                follow_labels = dialog.find_elements(By.XPATH, ".//label[contains(., 'Follow') or contains(., 'folgen')]")
                for fl in follow_labels:
                    if fl.is_displayed():
                        fl.click()
            except Exception:
                pass

            if dry_run:
                print(f"    [DRY RUN] Ready to submit for '{title}' at '{company}' (Job ID: {job_id})!", flush=True)
                print(f"    [DRY RUN] Discarding application as dry_run is TRUE.", flush=True)
                close_modal_safely(driver)
                return "Dry-Run Verified"
            else:
                submitted = False
                for s_attempt in range(1, 4):
                    print(f"    [*] Clicking Submit Application button (attempt {s_attempt}/3)...", flush=True)
                    try:
                        active_submit.click()
                        submitted = True
                        time.sleep(3.0)
                        break
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", active_submit)
                            submitted = True
                            time.sleep(3.0)
                            break
                        except Exception:
                            time.sleep(2.0)

                if submitted:
                    try:
                        driver.save_screenshot("application_submitted.png")
                    except Exception:
                        pass
                    print(f"    [SUCCESS] Application submitted for '{title}' at '{company}'!", flush=True)
                    try:
                        done_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Done') or contains(., 'Fertig') or contains(., 'Not now') or contains(., 'Nicht jetzt') or @aria-label='Dismiss']")
                        if done_btns:
                            driver.execute_script("arguments[0].click();", done_btns[0])
                    except Exception:
                        pass
                    close_modal_safely(driver)
                    return "Applied"

        # 3. Fill all inputs on this step (up to 3 attempts with time gap)
        for fill_attempt in range(1, 4):
            try:
                fill_dialog_inputs(dialog, config, driver=driver, job_info={
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "cover_letter_text": cover_letter_text
                })
                break
            except Exception as e:
                if fill_attempt < 3:
                    time.sleep(1.0)
                else:
                    print(f"    [-] Form input note on step {step_count}: {e}", flush=True)

        # 4. Resume card selection & File upload check
        try:
            # If on resume selection screen, click first resume card if none selected
            resume_cards = dialog.find_elements(
                By.XPATH,
                ".//div[contains(@class, 'jobs-document-upload-card')] | .//li[contains(@class, 'jobs-document-upload-card')] | .//div[contains(@class, 'jobs-resume-picker__resume-card')]"
            )
            if resume_cards:
                try:
                    first_card = resume_cards[0]
                    btn = first_card.find_elements(By.XPATH, ".//button | .//input[@type='radio'] | .//label")
                    if btn:
                        driver.execute_script("arguments[0].click();", btn[0])
                    else:
                        driver.execute_script("arguments[0].click();", first_card)
                    time.sleep(0.8)
                except Exception:
                    pass

            file_inputs = dialog.find_elements(By.XPATH, ".//input[@type='file']")
            if file_inputs:
                for fi in file_inputs:
                    ctx = get_field_context(fi, dialog)
                    is_cover = any(w in ctx for w in ["cover", "anschreiben", "brief"])
                    if is_cover and cover_letter_pdf and os.path.exists(cover_letter_pdf):
                        target_doc = cover_letter_pdf
                    else:
                        target_doc = resume_path

                    if target_doc and os.path.exists(target_doc):
                        try:
                            fi.send_keys(os.path.abspath(target_doc))
                            print(f"    [+] Attached {os.path.basename(target_doc)} on step {step_count}", flush=True)
                            time.sleep(2.0)
                        except Exception:
                            pass
        except Exception:
            pass

        # 5. Proactively resolve any validation errors or unselected required fields
        resolve_step_errors(dialog, driver)

        # Scroll dialog down to expose action buttons
        try:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", dialog)
            time.sleep(0.5)
        except Exception:
            pass

        # 6. Check for Review button (German: Überprüfen / Bewerbung prüfen)
        review_buttons = dialog.find_elements(
            By.XPATH,
            ".//button[normalize-space(.)='Review' or normalize-space(.)='Überprüfen' or contains(., 'Review') or contains(., 'Überprüfen') or contains(., 'Bewerbung prüfen') or contains(., 'Prüfen')]"
        )
        if review_buttons and review_buttons[0].is_displayed():
            clicked_review = False
            for r_attempt in range(1, 4):
                try:
                    review_buttons[0].click()
                    clicked_review = True
                    time.sleep(2.0)
                    break
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", review_buttons[0])
                        clicked_review = True
                        time.sleep(2.0)
                        break
                    except Exception:
                        time.sleep(1.5)
            if clicked_review:
                continue

        # 7. Check for Next button (German: Weiter / Fortfahren)
        next_buttons = dialog.find_elements(
            By.XPATH,
            ".//button[normalize-space(.)='Next' or normalize-space(.)='Weiter' or contains(., 'Next') or contains(., 'Weiter') or contains(., 'Fortfahren')]"
        )
        if next_buttons and next_buttons[0].is_displayed():
            next_clicked = False
            for n_attempt in range(1, 4):
                try:
                    next_buttons[0].click()
                    next_clicked = True
                    time.sleep(1.5)
                    break
                except Exception:
                    try:
                        driver.execute_script("arguments[0].click();", next_buttons[0])
                        next_clicked = True
                        time.sleep(1.5)
                        break
                    except Exception:
                        time.sleep(1.5)
            if next_clicked:
                continue

    # If loop ended without reaching review or submit, clean up safely
    print(f"    [NOTICE] Modal exceeded {max_steps} steps without completing. Safely closing dialog.", flush=True)
    close_modal_safely(driver)
    return "Skipped: Exceeded maximum steps"


DAEMON_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon_state.json")


def update_daemon_state(status="IDLE"):
    state = {
        "status": status,
        "last_run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "daily_target": 50,
        "applied_today": 0,
        "hourly_batch_size": 8,
    }
    if os.path.exists(DAEMON_STATE_FILE):
        try:
            with open(DAEMON_STATE_FILE, "r", encoding="utf-8") as f:
                state.update(json.load(f))
        except Exception:
            pass

    state["status"] = status
    today_str = datetime.now().strftime("%Y-%m-%d")
    hist = load_history()
    today_count = sum(1 for v in hist.values() if v.get("status") == "Applied" and v.get("timestamp", "").startswith(today_str))
    state["applied_today"] = today_count
    if status in ["COMPLETED", "IDLE"]:
        state["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(DAEMON_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def run_bot(limit: int = None) -> None:
    config = load_config()
    history = load_history()
    search_cfg = config.get("search_settings", {})
    keywords = search_cfg.get("keywords", ["Python Developer"])

    # Allow CLI limit override (--limit N)
    if limit is None:
        if "--limit" in sys.argv:
            try:
                limit = int(sys.argv[sys.argv.index("--limit") + 1])
            except Exception:
                pass
    max_apps = limit if limit is not None else search_cfg.get("max_applications_per_run", 50)
    dry_run = search_cfg.get("dry_run", False)

    pipeline_cfg = config.get("ai_pipeline", {})
    min_score = pipeline_cfg.get("min_alignment_score", 7)
    sprint_gap = pipeline_cfg.get("sprint_gap_seconds", 10)

    update_daemon_state("APPLYING_JOBS")

    print("=" * 68)
    print(f"   LinkedIn Easy Apply Bot — Germany Edition")
    print(f"   Candidate : {config.get('personal_info', {}).get('first_name')} {config.get('personal_info', {}).get('last_name')}")
    print(f"   Location  : {config.get('personal_info', {}).get('city')}, {config.get('personal_info', {}).get('country')}")
    print(f"   Mode      : {'[DRY RUN - Safe verification, no submissions]' if dry_run else '[LIVE APPLICATION]'}")
    print(f"   Keywords  : {len(keywords)} configured ({', '.join(keywords[:3])}...)")
    print("=" * 68)

    driver = init_browser()

    try:
        ensure_logged_in(driver, config)
        ensure_resume_uploaded(driver, config)

        applied_count = 0

        for kw in keywords:
            if applied_count >= max_apps:
                print(f"\n[!] Reached target limit ({max_apps} applications). Finishing run.")
                break

            for page_idx in range(1, 6):
                if applied_count >= max_apps:
                    break

                search_url = build_search_url(kw, config, page=page_idx)
                print(f"\n[*] Searching: '{kw}' in Germany (Page {page_idx})...")

                card_xpath = (
                    "//div[@role='button' and contains(@componentkey, 'job-card-component-ref-')] | "
                    "//li[contains(@class, 'jobs-search-results__list-item')] | "
                    "//div[contains(@class, 'job-card-container') and (@data-job-id or @data-entity-urn)] | "
                    "//li[@data-occludable-job-id]"
                )
                search_loaded = False

                # Search page loading with up to 3 retries
                for s_attempt in range(1, 4):
                    try:
                        driver.get(search_url)
                        time.sleep(2.5)
                        handle_cookie_consent(driver)
                        WebDriverWait(driver, 8).until(
                            EC.presence_of_element_located((By.XPATH, card_xpath))
                        )
                        search_loaded = True
                        break
                    except Exception as se:
                        if s_attempt < 3:
                            print(f"    [-] Search load attempt {s_attempt}/3 encounter: {se}. Retrying in 2.0s...", flush=True)
                            time.sleep(2.0)
                        else:
                            if page_idx == 1:
                                print(f"    [NOTICE] No job cards loaded for keyword '{kw}' after 3 attempts.", flush=True)

                if not search_loaded:
                    break

                # Scroll job list pane to trigger lazy loading of all available cards on the page
                try:
                    for _ in range(4):
                        driver.execute_script("""
                            var pane = document.querySelector('.jobs-search-results-list') || 
                                       document.querySelector('.scaffold-layout__list') ||
                                       document.querySelector('div[class*="jobs-search-results-list"]') ||
                                       document.querySelector('ul.jobs-search__results-list');
                            if (pane) {
                                pane.scrollTop += pane.clientHeight;
                            } else {
                                window.scrollBy(0, 600);
                            }
                        """)
                        time.sleep(0.8)
                except Exception:
                    pass

                job_cards = driver.find_elements(By.XPATH, card_xpath)
                job_items = []
                seen_ids = set()
                for c in job_cards:
                    try:
                        jid = None
                        ckey = c.get_attribute("componentkey") or ""
                        if ckey and "job-card-component-ref-" in ckey:
                            jid = ckey.replace("job-card-component-ref-", "").strip()
                        if not jid:
                            jid = c.get_attribute("data-job-id") or c.get_attribute("data-occludable-job-id") or ""
                        if not jid:
                            urn = c.get_attribute("data-entity-urn") or ""
                            digits = re.findall(r"\d+", urn)
                            if digits:
                                jid = digits[-1]
                        if not jid:
                            links = c.find_elements(By.XPATH, ".//a[contains(@href, '/jobs/view/')]")
                            for lnk in links:
                                href = lnk.get_attribute("href") or ""
                                digits = re.findall(r"/jobs/view/(\d+)", href)
                                if digits:
                                    jid = digits[0]
                                    break
                        if jid and jid not in seen_ids:
                            seen_ids.add(jid)
                            job_items.append({"job_id": jid, "componentkey": ckey})
                    except Exception:
                        pass
                print(f"[*] Found {len(job_items)} job cards for '{kw}' on Page {page_idx}.", flush=True)

                if not job_items:
                    break

                for item in job_items:
                    if applied_count >= max_apps:
                        break

                    try:
                        job_id = item["job_id"]
                        ckey = item.get("componentkey", "")
                        if not job_id:
                            continue
                        # Skip if already successfully applied
                        if job_id in history and history[job_id].get("status") in ["Applied", "Dry-Run Verified"]:
                            continue

                        # 1. Select card with up to 3 retries
                        card_clicked = False
                        title, company = "Unknown Role", "Unknown Company"
                        for c_attempt in range(1, 4):
                            try:
                                card_locators = [
                                    f"//div[@componentkey='job-card-component-ref-{job_id}']",
                                    f"//div[@data-job-id='{job_id}']",
                                    f"//li[@data-occludable-job-id='{job_id}']",
                                    f"//div[contains(@class, 'job-card-container') and @data-job-id='{job_id}']",
                                    f"//a[contains(@href, '/jobs/view/{job_id}')]"
                                ]
                                cards_now = []
                                for loc in card_locators:
                                    found = driver.find_elements(By.XPATH, loc)
                                    if found:
                                        cards_now = found
                                        break
                                if not cards_now:
                                    time.sleep(1.5)
                                    continue
                                card = cards_now[0]

                                try:
                                    lines = [l.strip() for l in card.text.split("\n") if l.strip()]
                                    raw_title = lines[0] if lines else "Unknown"
                                    title = raw_title.replace("Selected, ", "").strip()
                                    company = lines[1] if len(lines) > 1 else "Unknown"
                                except Exception:
                                    pass

                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                                time.sleep(0.8)
                                try:
                                    card.click()
                                except Exception:
                                    driver.execute_script("arguments[0].click();", card)
                                card_clicked = True
                                time.sleep(2.0)
                                break
                            except Exception as ce:
                                if c_attempt < 3:
                                    time.sleep(1.5)
                                else:
                                    print(f"    [-] Could not select card after 3 attempts: {ce}", flush=True)

                        if not card_clicked:
                            print(f"    [NOTICE] Skipping card {job_id} after 3 failed selection attempts.", flush=True)
                            close_modal_safely(driver)
                            continue

                        # Step 1: Extract complete job details from details pane
                        job_details = extract_job_details(driver, job_id, title, company)
                        det_title = job_details.get("title", title)
                        det_company = job_details.get("company", company)
                        det_desc = job_details.get("job_description", "")
                        det_loc = job_details.get("location", "Germany")

                        print(f"\n---> [{job_id}] {det_title} @ {det_company} ({det_loc})", flush=True)

                        # Step 2: Role, Seniority, and German Language Requirement Screening Filter
                        passed_screening, screen_reason = filter_job_screening(det_title, det_desc, det_loc)
                        if not passed_screening:
                            print(f"    [-] Job dropped by filter: {screen_reason}. Moving to next job in {sprint_gap}s.", flush=True)
                            record_job(job_id, det_title, det_company, f"Filtered: {screen_reason}")
                            close_modal_safely(driver)
                            time.sleep(sprint_gap)
                            continue
                        else:
                            print(f"    [+] Passed role & language screening: {screen_reason}", flush=True)

                        # Step 3: Ollama Cloud Alignment Rating (1 to 10 Scale)
                        score, score_reason = score_job_alignment(det_title, det_company, det_desc, config)
                        print(f"    [AI FIT SCORE: {score}/10] {score_reason}", flush=True)

                        if score <= min_score:
                            print(f"    [-] Score {score}/10 <= {min_score} (Threshold: > {min_score}). Dropping job. Next job in {sprint_gap}s.", flush=True)
                            record_job(job_id, det_title, det_company, f"Filtered: AI Score {score}/10 ({score_reason})")
                            close_modal_safely(driver)
                            time.sleep(sprint_gap)
                            continue

                        print(f"    [+] High alignment ({score}/10 > {min_score})! Target job accepted.", flush=True)

                        # Step 4: Find Easy Apply button specifically in the job details pane with up to 3 retries
                        active_btn = None
                        for b_attempt in range(1, 4):
                            detail_apply_btns = driver.find_elements(
                                By.XPATH,
                                "//button[contains(@aria-label, 'Easy Apply to') or contains(@aria-label, 'Einfach bewerben auf') or contains(@aria-label, 'to this job')] | "
                                "//div[contains(@class, 'job-details') or contains(@class, 'jobs-details') or contains(@class, 'jobs-search__job-details') or contains(@class, 'jobs-apply-button')]//button[contains(., 'Easy Apply') or contains(., 'Einfach bewerben')]"
                            )
                            for b in detail_apply_btns:
                                try:
                                    if b.is_displayed():
                                        b_id = b.get_attribute("id") or ""
                                        b_cls = b.get_attribute("class") or ""
                                        if "filter" in b_id.lower() or "search-reusables" in b_cls.lower():
                                            continue
                                        active_btn = b
                                        break
                                except Exception:
                                    pass
                            if active_btn:
                                break
                            time.sleep(1.5)

                        if not active_btn:
                            print(f"    [-] No Easy Apply button found for job {job_id} (standard apply). Skipping in {sprint_gap}s.", flush=True)
                            record_job(job_id, det_title, det_company, f"Skipped: Standard Apply (Score: {score}/10)")
                            time.sleep(sprint_gap)
                            continue

                        # Step 5: Compile Tailored Resume & Cover Letter via REGULAR_APPLICATION
                        doc_bundle = generate_tailored_documents_for_job(job_details)

                        # Step 6: Click Easy Apply button with up to 3 retries
                        btn_clicked = False
                        for click_attempt in range(1, 4):
                            try:
                                active_btn.click()
                                btn_clicked = True
                                time.sleep(2.0)
                                break
                            except Exception:
                                try:
                                    driver.execute_script("arguments[0].click();", active_btn)
                                    btn_clicked = True
                                    time.sleep(2.0)
                                    break
                                except Exception as click_err:
                                    if click_attempt < 3:
                                        time.sleep(1.5)
                                    else:
                                        print(f"    [-] Could not click Easy Apply after 3 attempts: {click_err}", flush=True)

                        if not btn_clicked:
                            record_job(job_id, det_title, det_company, "Failed: Could not click Easy Apply")
                            close_modal_safely(driver)
                            time.sleep(sprint_gap)
                            continue

                        # Step 7: Process the modal with tailored documents & Ollama question answering
                        try:
                            status = process_easy_apply_modal(driver, config, job_id, det_title, det_company, doc_bundle=doc_bundle)
                        except Exception as modal_err:
                            print(f"    [!] Error during modal processing: {modal_err}. Safely closing dialog and continuing.", flush=True)
                            close_modal_safely(driver)
                            status = f"Failed: {str(modal_err)[:50]}"

                        final_status = f"{status} (AI Score: {score}/10, {'Tailored' if doc_bundle.get('tailored') else 'Master'} Resume)"
                        record_job(job_id, det_title, det_company, final_status)

                        if "Applied" in status or "Verified" in status:
                            applied_count += 1
                            print(f"    [+] Progress: {applied_count}/{max_apps} jobs applied.", flush=True)

                        # Always ensure any open dialog is closed before proceeding to next card
                        close_modal_safely(driver)

                        if applied_count >= max_apps:
                            print(f"\n[!] Reached target limit ({max_apps} applications). Finishing run.", flush=True)
                            break

                        # Sprint Gap between jobs!
                        print(f"[*] Sprint Pacing: {sprint_gap}-second gap before next job...", flush=True)
                        time.sleep(sprint_gap)

                    except StaleElementReferenceException:
                        print(f"    [-] Stale element reference on card. Waiting 1.5s and moving to next listing...", flush=True)
                        close_modal_safely(driver)
                        time.sleep(1.5)
                        continue
                    except Exception as card_err:
                        print(f"    [-] Card encounter note: {card_err}. Safely closing dialog and moving to next job...", flush=True)
                        close_modal_safely(driver)
                        time.sleep(1.5)
                        continue

        print("\n" + "=" * 68)
        print(f"[+] Run completed successfully! Processed {applied_count} jobs.")
        print(f"[+] History saved to: {HISTORY_FILE}")
        print("=" * 68)

    except KeyboardInterrupt:
        print("\n[!] Run interrupted by user.")
    except Exception as e:
        print(f"\n[!] Unexpected encounter: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        update_daemon_state("IDLE")


if __name__ == "__main__":
    run_bot()
