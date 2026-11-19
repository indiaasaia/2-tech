#!/usr/bin/env python3
"""
Bridge between LinkedIn Easy Apply Bot and REGULAR_APPLICATION Engine.
Enables:
  1. Role & Seniority Filtering (from REGULAR_APPLICATION/steps/screen_jobs.py)
  2. German Language Level Requirement Filtering (CEFR A2 vs C1/Fluent)
  3. Single-Job LaTeX Resume & Cover Letter Compilation via Tectonic
  4. Automatic Safe Fallback to Master Resume (RAVAL_MEETKUMAR_RITESHKUMAR.pdf)
"""

import os
import sys
import re
import json
import traceback
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent

def get_reg_root() -> Path:
    # 1. Local self-contained engine
    if (WORKSPACE_DIR / "engine").exists() and (WORKSPACE_DIR / "tools" / "tectonic.exe").exists():
        return WORKSPACE_DIR
    cfg_path = WORKSPACE_DIR / "config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                c = json.load(f)
                custom = c.get("ai_pipeline", {}).get("regular_app_path")
                if custom and Path(custom).exists():
                    return Path(custom)
        except Exception:
            pass
    hardcoded = Path(r"E:\WorkSpace\2 Tech\2 Job Automation\REGULAR_APPLICATION")
    if hardcoded.exists():
        return hardcoded
    sibling = WORKSPACE_DIR.parent / "REGULAR_APPLICATION"
    if sibling.exists():
        return sibling
    return WORKSPACE_DIR

REG_ROOT = get_reg_root()
MASTER_RESUME = os.path.join(str(WORKSPACE_DIR), "RAVAL_MEETKUMAR_RITESHKUMAR.pdf")

# Setup REGULAR_APPLICATION imports if directory exists
HAS_REG_APP = False
if REG_ROOT.exists():
    if str(REG_ROOT) not in sys.path:
        sys.path.insert(0, str(REG_ROOT))
    try:
        from engine import config as reg_config
        from engine.generation import kb_loader
        from engine.generation.llm import load_first_key
        from engine import run_step4, run_step5, run_step6
        HAS_REG_APP = True
    except Exception as e:
        print(f"[-] REGULAR_APPLICATION import note: {e}")
        HAS_REG_APP = False


# ==============================================================================
# 1. SCREENING FILTERS (Strict English Werkstudent & Internship Gate)
# ==============================================================================

# Role Regexes
_STUDENT_TITLE_RE = re.compile(
    r"(?i)\b(?:werkstudent\w*|working[\s-]?student\w*|work student|student\w*\s+(?:assistant|job|trainee)|hilfskraft|\bhiwi\b)\b"
)
_INTERN_TITLE_RE = re.compile(
    r"(?i)\b(?:intern\b|internship|praktik\w*|placement|\bpraktikum)\b"
)
_SENIOR_TITLE_RE = re.compile(
    r"(?i)\b(?:senior|sr\.|lead|principal|head of|director|vp|manager|leiter)\b"
)
_AUSBILDUNG_RE = re.compile(
    r"(?i)\b(?:ausbildung|duales studium|azubi|lehrling)\b"
)

# Mandatory German Requirement Regex (rejects any mandatory German demand)
_GERMAN_MANDATORY_RE = re.compile(
    r"(?i)\b(?:german required|fluent (?:in )?german|german (?:c1|c2|b2|b1|a2|mandatory|essential)|"
    r"(?:sehr )?gute deutschkenntnisse|gute kenntnisse der deutschen sprache|"
    r"deutsch(?:kenntnisse)? (?:erforderlich|vorausgesetzt|notwendig|fließend|verhandlungssicher)|"
    r"fließend(?:e)? deutsch|verhandlungssicher\w* deutsch|business[- ]fluent german|"
    r"native german|deutsch als muttersprache|deutschkenntnisse (?:mindestens|auf) [abc][12]|"
    r"sichere deutschkenntnisse|gutes deutsch|deutsch in wort und schrift)\b"
)

# German Nice-to-Have (safe to keep if German is only optional)
_GERMAN_NICE_TO_HAVE_RE = re.compile(
    r"(?i)\b(?:german (?:is )?(?:a )?(?:plus|bonus|nice to have|advantage|beneficial)|"
    r"deutschkenntnisse (?:von vorteil|wünschenswert|ein plus)|"
    r"grundkenntnisse (?:in )?deutsch (?:von vorteil)?)\b"
)

# German Text Signals
_GERMAN_WORDS_RE = re.compile(
    r"(?i)\b(?:wir suchen|deine aufgaben|das bringst du mit|wir bieten|über uns|anforderungen|bewerbung|voraussetzungen|abgeschlossenes studium|immatrikulierter student)\b"
)
_ENGLISH_WORKING_LANG_RE = re.compile(
    r"(?i)\b(?:working language is english|english[- ]speaking (?:team|environment|company)|corporate language is english|fluent english (?:is )?required|international team|main language is english)\b"
)
_ABROAD_RE = re.compile(
    r"(?i)\b(?:united kingdom|england|scotland|wales|northern ireland|london|dublin|ireland|usa|united states|switzerland|austria)\b"
)


def filter_job_screening(title: str, text: str, location: str = "") -> tuple[bool, str]:
    """
    Applies strict screening gates:
      1. Role: MUST be Werkstudent, Working Student, or Internship (drops Senior, Regular Full-time, Ausbildung).
      2. Language: MUST be English-speaking (drops German-required roles & German-written ads without English team).
      3. Location: MUST be in Germany (student permit constraint).
    Returns (keep: bool, reason: str).
    """
    title_str = str(title or "").strip()
    text_str = f"{title_str} {str(text or '')}"
    loc_str = str(location or "").strip()

    # 1. Location Gate (Germany only)
    if _ABROAD_RE.search(loc_str) or _ABROAD_RE.search(title_str):
        return False, "Location: Outside Germany (Permit is Germany-only)"

    # 2. Role Gate: Strict Werkstudent & Internship ONLY
    if _AUSBILDUNG_RE.search(title_str):
        return False, "Role: Ausbildung / Duales Studium (Dropped)"

    if _SENIOR_TITLE_RE.search(title_str) and not (_STUDENT_TITLE_RE.search(title_str) or _INTERN_TITLE_RE.search(title_str)):
        return False, "Role: Senior / Lead / Principal / Executive (Dropped)"

    # Check title first, then first 400 chars of description
    is_student = bool(_STUDENT_TITLE_RE.search(title_str) or _INTERN_TITLE_RE.search(title_str))
    if not is_student:
        is_student = bool(_STUDENT_TITLE_RE.search(text_str[:400]) or _INTERN_TITLE_RE.search(text_str[:400]))

    if not is_student:
        return False, "Role: Not a Werkstudent or Internship role (Dropped)"

    # 3. Language Gate: Strictly English-Speaking ONLY
    # If German is explicitly required/mandatory -> DROP
    german_req_match = _GERMAN_MANDATORY_RE.search(text_str)
    if german_req_match:
        # Check if it's explicitly clarified as nice to have
        if not _GERMAN_NICE_TO_HAVE_RE.search(text_str):
            matched_phrase = german_req_match.group(0)
            return False, f"Language: German required ('{matched_phrase}') - English-only policy"

    # If the ad is heavily German without an English working-language statement -> DROP
    german_markers = len(_GERMAN_WORDS_RE.findall(text_str))
    if german_markers >= 3 and not _ENGLISH_WORKING_LANG_RE.search(text_str):
        return False, "Language: Job ad written in German without English working-language guarantee"

    return True, "Passed: English-speaking Werkstudent / Internship"


# ==============================================================================
# 2. DYNAMIC RESUME & COVER LETTER GENERATION
# ==============================================================================

def generate_tailored_documents_for_job(job_data: dict) -> dict:
    """
    Compiles a tailored 2-page LaTeX PDF resume and cover letter
    using the REGULAR_APPLICATION engine.
    Falls back safely to the master resume if anything fails.
    """
    default_result = {
        "success": True,
        "tailored": False,
        "resume_pdf": MASTER_RESUME,
        "cover_letter_pdf": "",
        "cover_letter_text": "Motivated AI & Software Engineer looking forward to contributing to your team. Please refer to my resume for full details.",
        "reason": "Default master resume",
    }

    if not HAS_REG_APP:
        print("[BRIDGE] REGULAR_APPLICATION engine not available; using master resume.")
        return default_result

    title = job_data.get("title", "")
    company = job_data.get("company", "")
    description = job_data.get("job_description", "")
    job_url = job_data.get("job_url", f"https://www.linkedin.com/jobs/view/{job_data.get('job_id', '0')}")

    print(f"\n[BRIDGE] Generating tailored application documents for: '{title}' at '{company}'...")

    try:
        kb = kb_loader.load_kb()
        token = load_first_key()
        tectonic_exe = str(REG_ROOT / "tools" / "tectonic.exe")

        job_payload = {
            "title": title,
            "company": company,
            "detail_company_name": company,
            "location": job_data.get("location", "Germany"),
            "detail_location": job_data.get("location", "Germany"),
            "job_url": job_url,
            "job_description": description,
            "requirements": description,
            "your_tasks": description,
            "applicant_profile": description,
            "about_us": "",
            "what_they_offer": "",
            "snippet": description[:300],
        }

        # Step 4: Analyze JD against KB & generate tailored components
        print("    [1/3] Analyzing JD keywords & generating tailored components...")
        record = run_step4.process_job(job_payload, token, kb, tailor=True)

        if record.get("status") != "gated_ok" or not record.get("components"):
            err_msg = record.get("error", "Gating rejected components")
            print(f"    [-] Step 4 gating notice: {err_msg}. Using master resume fallback.")
            default_result["reason"] = err_msg
            return default_result

        # Step 5: Compile 2-Page Tailored LaTeX Resume via Tectonic
        print("    [2/3] Compiling tailored LaTeX resume via Tectonic...")
        resume_res = run_step5.build_record(record, engine=tectonic_exe)
        resume_pdf = resume_res.get("pdf", "")

        if not resume_pdf or not os.path.exists(resume_pdf):
            print("    [-] Resume build failed; using master resume fallback.")
            return default_result

        print(f"    [+] Tailored Resume compiled: {os.path.basename(resume_pdf)}")

        # Step 6: Generate Tailored Cover Letter (Anschreiben)
        print("    [3/3] Generating tailored cover letter...")
        cl_pdf = ""
        cl_text = default_result["cover_letter_text"]

        try:
            letter_res = run_step6.build_letter(record, kb, token, engine=tectonic_exe)
            arts = letter_res.get("artifacts", {})
            cl_pdf = arts.get("letter_pdf", "")
            cl_txt_path = arts.get("letter_txt", "")

            if cl_txt_path and os.path.exists(cl_txt_path):
                with open(cl_txt_path, "r", encoding="utf-8") as f:
                    cl_text = f.read().strip()
            elif letter_res.get("letter"):
                cl_text = str(letter_res.get("letter"))

            if cl_pdf and os.path.exists(cl_pdf):
                print(f"    [+] Tailored Cover Letter compiled: {os.path.basename(cl_pdf)}")
        except Exception as cl_err:
            print(f"    [-] Cover letter note ({cl_err}); using standard cover letter text.")

        return {
            "success": True,
            "tailored": True,
            "resume_pdf": os.path.abspath(resume_pdf),
            "cover_letter_pdf": os.path.abspath(cl_pdf) if cl_pdf and os.path.exists(cl_pdf) else "",
            "cover_letter_text": cl_text,
            "title": title,
            "company": company,
            "reason": "Tailored documents successfully compiled via Tectonic",
        }

    except Exception as exc:
        print(f"    [!] Error during tailored document generation: {exc}")
        traceback.print_exc()
        default_result["reason"] = str(exc)
        return default_result


if __name__ == "__main__":
    test_job = {
        "job_id": "test_123",
        "title": "Working Student AI & Python Engineer",
        "company": "Siemens AG",
        "location": "Berlin, Germany",
        "job_description": "We are seeking a motivated Working Student in AI and Python to build ML pipelines, evaluate LLMs, and work with Docker and PyTorch. Fluency in English is required; German is a plus.",
    }

    # Test filtering
    passed, reason = filter_job_screening(test_job["title"], test_job["job_description"], test_job["location"])
    print(f"Filter Screening: Passed={passed}, Reason={reason}")

    # Test generation
    res = generate_tailored_documents_for_job(test_job)
    print("\nResult:", json.dumps({k: str(v) for k, v in res.items() if k != "cover_letter_text"}, indent=2))
