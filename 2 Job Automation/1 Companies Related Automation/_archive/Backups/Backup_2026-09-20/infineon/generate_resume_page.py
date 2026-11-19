"""Generate resumes.html: a simple index of all built Infineon resumes.

Same method as the Mercedes twin. Data sources (single source of truth,
never hand-typed):
  program_files/output_infineon/resume_report.json      -> which resumes were built
  program_files/output_infineon/todays_overall_jobs.csv -> job_url, location, posted date

Every link in the page is verified against the filesystem before the page is
written: the script fails loudly (exit 1) if any PDF/DOCX is missing, while
still writing the page so problems are visible. Regenerate any time with:

    python generate_resume_page.py
"""
from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_JSON = PROJECT_ROOT / "program_files" / "output_infineon" / "resume_report.json"
MASTER_CSV = PROJECT_ROOT / "program_files" / "output_infineon" / "todays_overall_jobs.csv"
OUTPUT_HTML = PROJECT_ROOT / "resumes.html"


def rel_posix(path_str: str) -> str:
    """Filesystem path relative to the project root, as forward-slash href."""
    return Path(path_str).resolve().relative_to(PROJECT_ROOT).as_posix()


def main() -> int:
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    master = pd.read_csv(MASTER_CSV, keep_default_na=False)
    meta = {str(r["job_url"]): r for _, r in master.iterrows()}

    rows: list[dict] = []
    problems: list[str] = []

    for record in sorted(report["results"], key=lambda r: r["title"].lower()):
        title = str(record.get("title") or "(untitled)")
        url = str(record.get("job_url") or "")
        info = meta.get(url, {})
        location = str(info.get("location") or "")
        posted = str(info.get("posted_time") or "")
        apply_url = str(info.get("apply_url") or url)

        pdf_href = rel_posix(record["pdf"]) if record.get("pdf") else ""
        docx_href = rel_posix(record["docx"]) if record.get("docx") else ""

        pdf_ok = bool(pdf_href) and (PROJECT_ROOT / pdf_href).is_file()
        docx_ok = bool(docx_href) and (PROJECT_ROOT / docx_href).is_file()
        if record.get("error"):
            problems.append(f"{title}: {record['error']}")
        if not pdf_ok:
            problems.append(f"{title}: PDF missing ({record.get('pdf') or 'no path'})")
        if not docx_ok:
            problems.append(f"{title}: DOCX missing ({record.get('docx') or 'no path'})")

        rows.append({
            "title": title, "location": location, "posted": posted,
            "pdf_href": pdf_href, "docx_href": docx_href,
            "pdf_ok": pdf_ok, "docx_ok": docx_ok, "apply_url": apply_url,
        })

    ready = sum(1 for r in rows if r["pdf_ok"] and r["docx_ok"])
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    cards = []
    for r in rows:
        status = "ready" if (r["pdf_ok"] and r["docx_ok"]) else "PROBLEM"
        links = []
        if r["pdf_ok"]:
            links.append(f'<a href="{html.escape(r["pdf_href"])}">PDF</a>')
        if r["docx_ok"]:
            links.append(f'<a href="{html.escape(r["docx_href"])}">DOCX</a>')
        links.append(f'<a href="{html.escape(r["apply_url"])}">Job posting</a>')
        cards.append(f"""
    <div class="card {status}">
      <h3>{html.escape(r["title"])}</h3>
      <p class="meta">{html.escape(r["location"])} &middot; {html.escape(r["posted"][:10])}</p>
      <p>{' &middot; '.join(links)}</p>
      <span class="badge {status}">{status}</span>
    </div>""")

    problem_html = ""
    if problems:
        items = "".join(f"<li>{html.escape(p)}</li>" for p in problems)
        problem_html = f"<div class='problems'><h2>Problems ({len(problems)})</h2><ul>{items}</ul></div>"

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Infineon tailored resumes ({ready}/{len(rows)} ready)</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f5f6f8; }}
 h1 {{ margin-bottom: .2rem; }}
 .sub {{ color: #555; margin-top: 0; }}
 .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; }}
 .card {{ background: #fff; border-radius: 10px; padding: 1rem 1.2rem; box-shadow: 0 1px 4px rgba(0,0,0,.08); position: relative; }}
 .card h3 {{ margin: .2rem 0; font-size: 1rem; }}
 .meta {{ color: #666; font-size: .85rem; margin: .2rem 0 .6rem; }}
 .badge {{ position: absolute; top: .8rem; right: .8rem; font-size: .7rem; padding: .15rem .5rem; border-radius: 999px; }}
 .badge.ready {{ background: #d9f2e3; color: #14713d; }}
 .badge.PROBLEM {{ background: #fde2e1; color: #a02020; }}
 a {{ color: #0b62a4; text-decoration: none; margin-right: .4rem; }}
 a:hover {{ text-decoration: underline; }}
 .problems {{ background: #fff3f3; border: 1px solid #f3c2c2; border-radius: 10px; padding: 1rem 1.2rem; margin: 1.5rem 0; }}
</style>
</head>
<body>
<h1>Infineon tailored resumes</h1>
<p class="sub">{ready}/{len(rows)} ready &middot; generated {generated}</p>
<div class="grid">{''.join(cards)}
</div>
{problem_html}
</body>
</html>
"""
    OUTPUT_HTML.write_text(page, encoding="utf-8")
    print(f"[PAGE] {ready}/{len(rows)} resume(s) ready -> {OUTPUT_HTML}")
    for problem in problems:
        print(f"[PAGE] PROBLEM: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
