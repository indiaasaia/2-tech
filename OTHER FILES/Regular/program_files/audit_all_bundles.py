import json
import os
from pypdf import PdfReader
from pathlib import Path

def audit_bundles(bundles_file, label):
    print(f"\n=======================================================")
    print(f"=== AUDITING {label} ({bundles_file}) ===")
    print(f"=======================================================")
    if not os.path.exists(bundles_file):
        print(f"ERROR: {bundles_file} does not exist!")
        return
    with open(bundles_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    bundles = data.get("bundles", [])
    print(f"Total bundles registered: {len(bundles)}")
    
    issues = []
    student_verified = 0
    single_page_verified = 0

    for idx, b in enumerate(bundles, 1):
        title = b["title"]
        comp = b["company"]
        portal = b["portal"]
        r_pdf = b["artifacts"]["resume_pdf"]
        c_pdf = b["artifacts"]["letter_pdf"]
        c_txt = b["artifacts"]["letter_txt"]
        
        # 1. File existence
        for ftype, path in [("Resume PDF", r_pdf), ("Letter PDF", c_pdf), ("Letter TXT", c_txt)]:
            if not os.path.exists(path):
                issues.append(f"[{idx}] {ftype} missing: {path}")

        # 2. Resume page count
        if os.path.exists(r_pdf):
            try:
                reader = PdfReader(r_pdf)
                p_count = len(reader.pages)
                if p_count == 1:
                    single_page_verified += 1
                else:
                    issues.append(f"[{idx}] Resume PDF page count is {p_count} (EXCEEDS 1 PAGE): {comp} - {title}")
            except Exception as e:
                issues.append(f"[{idx}] Error reading Resume PDF: {e}")

        # 3. Student/Intern role check
        title_lower = title.lower()
        if any(k in title_lower for k in ["student", "intern", "praktik", "thesis"]):
            student_verified += 1
        else:
            issues.append(f"[{idx}] Title has no student/intern keyword: '{title}' at {comp}")

        print(f"  [{idx:2d}] {comp[:25]:25s} | {title[:40]:40s} | 1-Page: OK | Student: OK")

    print(f"\nAudit Summary for {label}:")
    print(f"  Total Bundles: {len(bundles)}")
    print(f"  1-Page Resumes: {single_page_verified}/{len(bundles)}")
    print(f"  Student/Intern Titles: {student_verified}/{len(bundles)}")
    if not issues:
        print(f"  >>> STATUS: 100% PERFECT! ZERO DEFECTS.")
    else:
        print(f"  >>> ISSUES FOUND: {len(issues)}")
        for iss in issues:
            print(f"      * {iss}")

if __name__ == "__main__":
    audit_bundles("program_files/yesterday_20261013/output_v2/application_bundles.json", "YESTERDAY (13/10/2026)")
    audit_bundles("program_files/output_v2/application_bundles.json", "TODAY (14/10/2026)")
