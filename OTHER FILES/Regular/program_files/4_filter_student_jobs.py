import re
import json
import pandas as pd
from pathlib import Path

INPUT_CSV = Path("program_files/output/2_filted_jobs.csv")
OUTPUT_STUDENT_CSV = Path("program_files/output/stepstone_werkstudent_internship_final.csv")
OUTPUT_AUDIT_CSV = Path("program_files/output/student_role_audit.csv")

def is_student_or_intern(row: pd.Series) -> tuple[bool, str]:
    title = str(row.get("title", "")).strip()
    contract = str(row.get("detail_contract_type", "")).strip().lower()
    snippet = str(row.get("snippet", "")).strip()
    source = str(row.get("source", ""))

    # Working student jobs source is inherently for students
    if source == "workingstudentjobs.de":
        return True, "Source workingstudentjobs.de (Student portal)"

    title_lower = title.lower()

    # Clear non-student markers
    disqualifying_titles = [
        "senior", "lead engineer", "team lead", "head of", "director",
        "principal", "test manager", "account executive", "legal counsel",
        "development engineer", "platform engineer", "specialist",
        "payroll and hr", "consultant", "professor", "lehrer"
    ]
    for dt in disqualifying_titles:
        if dt in title_lower and not any(st in title_lower for st in ["working student", "werkstudent", "intern", "praktik"]):
            return False, f"Non-student title: '{dt}' without student qualifier"

    # Explicit student markers in title
    student_markers = [
        "werkstudent", "working student", "intern", "internship",
        "praktikant", "praktikum", "thesis", "masterthesis",
        "bachelorthesis", "studentische", "student assistant",
        "student for thesis", "graduates", "graduate"
    ]
    for sm in student_markers:
        if re.search(r"\b" + re.escape(sm) + r"\b", title_lower):
            return True, f"Explicit student title keyword: '{sm}'"

    # Contract type checks
    if any(ct in contract for ct in ["internship", "praktikum", "student job", "industrial placement student", "werkstudent"]):
        return True, f"Contract type indicates student: '{contract}'"

    return False, "No student / internship indicator in title or contract"

def main():
    df = pd.read_csv(INPUT_CSV)
    print(f"Auditing student role qualification for {len(df)} jobs...")

    audit_records = []
    student_rows = []

    for idx, row in df.iterrows():
        is_student, reason = is_student_or_intern(row)
        audit_records.append({
            "job_id": idx + 1,
            "source": row.get("source"),
            "company": row.get("company"),
            "title": row.get("title"),
            "is_student": is_student,
            "reason": reason,
            "url": row.get("job_url")
        })
        if is_student:
            student_rows.append(row)

    df_audit = pd.DataFrame(audit_records)
    df_audit.to_csv(OUTPUT_AUDIT_CSV, index=False, encoding="utf-8")

    df_student = pd.DataFrame(student_rows).reset_index(drop=True)
    df_student.to_csv(OUTPUT_STUDENT_CSV, index=False, encoding="utf-8")

    print(f"Role Type Filter Completed:")
    print(f"  Total Input Jobs: {len(df)}")
    print(f"  Qualified Student/Intern Roles: {len(df_student)}")
    print(f"  Non-Student Roles Filtered Out: {len(df) - len(df_student)}")
    print(f"  Outputs saved to:\n    {OUTPUT_STUDENT_CSV}\n    {OUTPUT_AUDIT_CSV}")

if __name__ == "__main__":
    main()
