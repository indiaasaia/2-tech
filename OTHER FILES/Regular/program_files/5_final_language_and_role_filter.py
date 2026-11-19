import re
import json
from pathlib import Path
import pandas as pd

INPUT_CSV = Path("program_files/output/stepstone_werkstudent_internship_final.csv")
OUTPUT_REPORT_JSON = Path("program_files/output/verified_language_filter_report.json")
OUTPUT_REPORT_CSV = Path("program_files/output/verified_language_filter_results.csv")
OUTPUT_QUALIFIED_CSV = Path("program_files/output/2_filted_jobs.csv")

MANDATORY_PATTERNS = [
    (r"fluent in both (?:spoken and written )?german and english", "Fluent in both German and English required"),
    (r"fluent in both (?:spoken and written )?english and german", "Fluent in both English and German required"),
    (r"fluent in english and german", "Fluent in English and German required"),
    (r"fluent in german and english", "Fluent in German and English required"),
    (r"professional fluency in english and german", "Professional fluency in English and German mandatory"),
    (r"(?:very good|fluent|excellent|native|business[- ]fluent|sehr gute|flie[ßs]ende|verhandlungssichere)\s+(?:in\s+)?(?:german|deutsch)", "Fluent/Very good German required"),
    (r"deutsch\s*(?:auf\s*)?(?:c1|c2|b2|verhandlungssicher|flie[ßs]end|sehr gut|muttersprachlich)", "German C1/C2/B2/fluent required"),
    (r"german\s*(?:level|skills|proficiency)?\s*(?:is\s*)?(?:fluent|native|proficient|excellent|very good|business[- ]fluent|c1|c2|b2)", "German level C1/C2/fluent/very good required"),
    (r"mindestens\s+b2\s+deutsch", "Minimum B2 German required"),
    (r"deutschkenntnisse\s+auf\s+(?:b2|c1)", "German B2/C1 required"),
    (r"sufficient german language skills", "Sufficient German language skills required"),
    (r"sehr\s+gute\s+deutsch[- ]\s*und\s+englischkenntnisse", "Sehr gute Deutschkenntnisse required"),
    (r"flie[ßs]end\s+in\s+wort\s+und\s+schrift", "Fließend Deutsch in Wort und Schrift required")
]

OPTIONAL_PATTERNS = [
    r"german\s+is\s+(?:a\s+plus|an\s+advantage|beneficial|optional|bonus)",
    r"deutschkenntnisse\s+(?:sind\s+von\s+vorteil|w[äa]ren\s+ein\s+plus|optional|vorteilhaft)",
    r"german\s+language\s+skills\s+(?:would\s+be\s+a\s+bonus|are\s+beneficial|are\s+a\s+plus|an\s+advantage)",
    r"german\s+is\s+useful\s+but\s+not\s+required",
    r"basic\s+german",
    r"german\s+(?:a1|a2)"
]

def evaluate_job(row: pd.Series) -> dict:
    title = str(row.get("title", ""))
    company = str(row.get("company", ""))
    full_text = " ".join([
        str(row.get("title", "")),
        str(row.get("applicant_profile", "")),
        str(row.get("requirements", "")),
        str(row.get("job_description", "")),
        str(row.get("your_tasks", "")),
        str(row.get("snippet", ""))
    ])

    title_lower = title.lower()
    text_lower = full_text.lower()

    # 1. Title explicit flags
    if "german required" in title_lower:
        return {
            "decision": "INELIGIBLE",
            "category": "Mandatory German (Title flags German Required)",
            "evidence": "Job Title explicitly specifies 'German Required'"
        }
    if "dutch-speaking" in title_lower or "niederländisch" in text_lower:
        return {
            "decision": "INELIGIBLE",
            "category": "Non-Matching Language (Dutch Required)",
            "evidence": "Requires Dutch language proficiency"
        }

    # 2. Check Mandatory German
    for pat, desc in MANDATORY_PATTERNS:
        m = re.search(pat, text_lower, re.I)
        if m:
            # Check surrounding context for plus / optional
            start_pos = max(0, m.start() - 40)
            end_pos = min(len(text_lower), m.end() + 40)
            surrounding = text_lower[start_pos:end_pos]
            if any(w in surrounding for w in ["plus", "advantage", "vorteil", "optional", "bonus", "beneficial", "not mandatory", "not required"]):
                continue
            return {
                "decision": "INELIGIBLE",
                "category": f"Mandatory German ({desc})",
                "evidence": m.group(0)
            }

    # 3. Check Optional German
    for pat in OPTIONAL_PATTERNS:
        m = re.search(pat, text_lower, re.I)
        if m:
            return {
                "decision": "ELIGIBLE",
                "category": "German Optional / Advantage / Plus (Candidate A2 is compatible)",
                "evidence": m.group(0)
            }

    # 4. Check English requirements
    m_eng = re.search(r"(?:very good|fluent|excellent|good|advanced)\s+english", text_lower, re.I)
    if m_eng:
        return {
            "decision": "ELIGIBLE",
            "category": "English Required / Compatible (No mandatory German blocker)",
            "evidence": m_eng.group(0)
        }

    return {
        "decision": "ELIGIBLE",
        "category": "Implicit English Posting (Zero German requirement)",
        "evidence": "Entire posting in English with no German language requirement"
    }

def main():
    df = pd.read_csv(INPUT_CSV)
    print(f"Auditing language requirements on {len(df)} student/intern jobs...")

    report = []
    eligible_rows = []

    for idx, row in df.iterrows():
        res = evaluate_job(row)
        report_entry = {
            "job_id": idx + 1,
            "source": row.get("source"),
            "company": row.get("company"),
            "title": row.get("title"),
            "location": row.get("location"),
            "decision": res["decision"],
            "category": res["category"],
            "evidence": res["evidence"],
            "url": row.get("job_url")
        }
        report.append(report_entry)
        if res["decision"] == "ELIGIBLE":
            eligible_rows.append(row)

    with open(OUTPUT_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    df_rep = pd.DataFrame(report)
    df_rep.to_csv(OUTPUT_REPORT_CSV, index=False, encoding="utf-8")

    df_eligible = pd.DataFrame(eligible_rows).reset_index(drop=True)
    df_eligible.to_csv(OUTPUT_QUALIFIED_CSV, index=False, encoding="utf-8")

    print(f"\nFinal Audited Student/Intern Jobs:")
    print(f"  Total Evaluated: {len(df)}")
    print(f"  Eligible (English C2 / German A2 Compatible): {len(df_eligible)}")
    print(f"  Ineligible (Mandatory German / Non-Matching): {len(df) - len(df_eligible)}")
    print(f"  Saved qualified job pool to: {OUTPUT_QUALIFIED_CSV}")

if __name__ == "__main__":
    main()
