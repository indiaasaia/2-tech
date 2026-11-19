import re
import json
from pathlib import Path
import pandas as pd

INPUT_CSV = Path("program_files/output/2_filted_jobs.csv")
OUTPUT_REPORT_JSON = Path("program_files/output/verified_language_filter_report.json")
OUTPUT_REPORT_CSV = Path("program_files/output/verified_language_filter_results.csv")
OUTPUT_ELIGIBLE_CSV = Path("program_files/output/language_eligible_jobs.csv")

# Regular expressions for German requirements
MANDATORY_GERMAN_PATTERNS = [
    r"(?:sehr gute|flie[ßs]ende|verhandlungssichere|hervorragende|exzellente|perfekte|muttersprachliche)\s+Deutschkenntnisse",
    r"Deutsch\s*(?:auf\s*)?(?:C1|C2|B2|verhandlungssicher|flie[ßs]end|sehr gut|muttersprachlich)",
    r"(?:fluent|native|proficient|excellent|business[- ]fluent|very good)\s+(?:in\s+)?German",
    r"German\s*(?:level|skills|proficiency)?\s*(?:is\s*)?(?:fluent|native|proficient|excellent|very good|business[- ]fluent|C1|C2|B2)",
    r"gute\s+bis\s+sehr\s+gute\s+Deutschkenntnisse",
    r"Deutsch\s+in\s+Wort\s+und\s+Schrift",
    r"German\s+(?:and\s+English\s+)?(?:level\s+should\s+be\s+C1|fluent)",
    r"mindestens\s+B2\s+Deutsch",
    r"Deutschkenntnisse\s+auf\s+B2",
    r"Deutschkenntnisse\s+auf\s+C1"
]

OPTIONAL_GERMAN_PATTERNS = [
    r"German\s+is\s+(?:a\s+plus|an\s+advantage|beneficial|optional)",
    r"Deutschkenntnisse\s+(?:sind\s+von\s+Vorteil|w[äa]ren\s+ein\s+Plus|optional)",
    r"basic\s+German",
    r"grundlegende\s+Deutschkenntnisse",
    r"German\s+A1|German\s+A2"
]

ENGLISH_PATTERNS = [
    r"(?:very good|fluent|excellent|good|proficient|business[- ]fluent)\s+(?:English|command of English)",
    r"English\s*(?:skills)?\s*(?:is\s*)?(?:fluent|excellent|very good|good|required|B2|C1|C2)",
    r"sehr\s+gute\s+Englischkenntnisse",
    r"Englisch\s+in\s+Wort\s+und\s+Schrift"
]

def extract_language_sentences(text: str) -> list[str]:
    """Find sentences mentioning languages."""
    if not text or pd.isna(text):
        return []
    sentences = re.split(r"(?<=[.!?\n])\s+", str(text))
    matches = []
    for s in sentences:
        s_clean = s.strip()
        if re.search(r"\b(deutsch|german|englisch|english|sprache|sprachen|languages?)\b", s_clean, re.I):
            if len(s_clean) > 5 and len(s_clean) < 300:
                matches.append(s_clean)
    return matches

def classify_language(row: pd.Series) -> dict:
    full_text = " ".join([
        str(row.get("title", "")),
        str(row.get("applicant_profile", "")),
        str(row.get("requirements", "")),
        str(row.get("job_description", "")),
        str(row.get("your_tasks", "")),
        str(row.get("snippet", ""))
    ])

    lang_sentences = extract_language_sentences(full_text)
    combined_lang_text = " ".join(lang_sentences)

    # 1. Check Mandatory German
    mandatory_hits = []
    for pat in MANDATORY_GERMAN_PATTERNS:
        m = re.search(pat, combined_lang_text, re.I)
        if m:
            mandatory_hits.append(m.group(0))

    # Also check if text is 100% German with German language requirements
    is_german_text = bool(re.search(r"\b(wir suchen|deine aufgaben|dein profil|das bringst du mit|wir bieten|qualifikationen)\b", full_text, re.I))

    # 2. Check Optional German
    optional_hits = []
    for pat in OPTIONAL_GERMAN_PATTERNS:
        m = re.search(pat, combined_lang_text, re.I)
        if m:
            optional_hits.append(m.group(0))

    if mandatory_hits:
        # Check if overridden by optional (rare)
        return {
            "decision": "INELIGIBLE",
            "category": "Mandatory German (Requires fluent/C1/B2/good German beyond candidate A2)",
            "evidence": "; ".join(mandatory_hits[:2]),
            "all_lang_mentions": lang_sentences[:5]
        }

    if optional_hits:
        return {
            "decision": "ELIGIBLE",
            "category": "German Optional / Advantage / Plus (Candidate A2 is compatible)",
            "evidence": "; ".join(optional_hits[:2]),
            "all_lang_mentions": lang_sentences[:5]
        }

    # If mostly German text and requires "gute Deutschkenntnisse"
    if is_german_text and re.search(r"Deutsch(?:kenntnisse)?", combined_lang_text, re.I):
        if re.search(r"(?:gute|sehr gute|flie[ßs]ende|sichere)\s+Deutsch", combined_lang_text, re.I):
            return {
                "decision": "INELIGIBLE",
                "category": "Mandatory German (Requires fluent/C1/B2/good German beyond candidate A2)",
                "evidence": "German posting requiring gute/sehr gute Deutschkenntnisse",
                "all_lang_mentions": lang_sentences[:5]
            }

    # English posting or no strict German requirement
    if lang_sentences:
        english_evidence = [s for s in lang_sentences if re.search(r"english|englisch", s, re.I)]
        ev = english_evidence[0] if english_evidence else lang_sentences[0]
        return {
            "decision": "ELIGIBLE",
            "category": "English-Dominant / Compatible (No mandatory German blocker)",
            "evidence": ev,
            "all_lang_mentions": lang_sentences[:5]
        }

    return {
        "decision": "ELIGIBLE",
        "category": "Implicit English / No Language Mentioned",
        "evidence": "Posting written in English with zero German requirements",
        "all_lang_mentions": []
    }

def main():
    df = pd.read_csv(INPUT_CSV)
    print(f"Auditing language requirements for {len(df)} jobs...")

    report = []
    eligible_indices = []

    for idx, row in df.iterrows():
        res = classify_language(row)
        res_entry = {
            "job_id": idx + 1,
            "source": row.get("source"),
            "title": row.get("title"),
            "company": row.get("company"),
            "location": row.get("location"),
            "decision": res["decision"],
            "category": res["category"],
            "evidence": res["evidence"],
            "all_lang_mentions": res["all_lang_mentions"],
            "url": row.get("job_url")
        }
        report.append(res_entry)
        if res["decision"] == "ELIGIBLE":
            eligible_indices.append(idx)

    # Save outputs
    with open(OUTPUT_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    df_rep = pd.DataFrame(report)
    df_rep.to_csv(OUTPUT_REPORT_CSV, index=False, encoding="utf-8")

    df_eligible = df.loc[eligible_indices].reset_index(drop=True)
    df_eligible.to_csv(OUTPUT_ELIGIBLE_CSV, index=False, encoding="utf-8")

    eligible_count = len(df_eligible)
    ineligible_count = len(df) - eligible_count
    print(f"Language Audit Completed:")
    print(f"  Total Jobs: {len(df)}")
    print(f"  Eligible: {eligible_count}")
    print(f"  Ineligible (Mandatory German): {ineligible_count}")
    print(f"  Outputs saved to:\n    {OUTPUT_REPORT_JSON}\n    {OUTPUT_REPORT_CSV}\n    {OUTPUT_ELIGIBLE_CSV}")

if __name__ == "__main__":
    main()
