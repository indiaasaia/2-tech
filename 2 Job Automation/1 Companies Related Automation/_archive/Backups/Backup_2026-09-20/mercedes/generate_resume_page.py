"""Generate resumes.html: a simple index of all built Mercedes resumes.

Data sources (single source of truth, never hand-typed):
  program_files/output_mercedes/resume_report.json      -> which resumes were built (paths, errors)
  program_files/output_mercedes/todays_overall_jobs.csv -> job_url, location, posted date per job

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
REPORT_JSON = PROJECT_ROOT / "program_files" / "output_mercedes" / "resume_report.json"
MASTER_CSV = PROJECT_ROOT / "program_files" / "output_mercedes" / "todays_overall_jobs.csv"
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
            "title": title, "url": url, "location": location, "posted": posted,
            "pdf": pdf_href if pdf_ok else "", "docx": docx_href if docx_ok else "",
            "error": str(record.get("error") or ""),
        })

    ready = sum(1 for r in rows if r["pdf"] and r["docx"] and not r["error"])
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    def link(href: str, label: str) -> str:
        if not href:
            return '<span class="missing">—</span>'
        return f'<a class="btn" href="{html.escape(href)}" download>{label}</a>'

    def posting_href(url: str) -> str:
        """Raw URL, byte-for-byte as scraped. Job URLs contain no quote character
        (asserted), so no HTML escaping is needed and & stays &."""
        assert '"' not in url and "<" not in url and ">" not in url, f"unexpected character in job url: {url!r}"
        return url

    body_rows = []
    for r in rows:
        title_html = (
            f'<a href="{posting_href(r["url"])}" target="_blank" rel="noopener">{html.escape(r["title"])}</a>'
            if r["url"] else html.escape(r["title"])
        )
        status = '<span class="ok">ready</span>' if (r["pdf"] and r["docx"] and not r["error"]) \
            else f'<span class="bad">{html.escape(r["error"] or "incomplete")}</span>'
        body_rows.append(
            "<tr>"
            f"<td>{title_html}</td>"
            f"<td>{html.escape(r['location'])}</td>"
            f"<td>{html.escape(r['posted'])}</td>"
            f"<td>{link(r['pdf'], 'PDF')}</td>"
            f"<td>{link(r['docx'], 'DOCX')}</td>"
            f"<td>{status}</td>"
            "</tr>"
        )

    problem_html = ""
    if problems:
        items = "".join(f"<li>{html.escape(p)}</li>" for p in problems)
        problem_html = f'<div class="problems"><strong>Verification problems:</strong><ul>{items}</ul></div>'

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mercedes Applications — Resume Index</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 24px auto; max-width: 1100px; padding: 0 16px; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  .meta {{ color: #555; font-size: .9rem; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .92rem; }}
  th, td {{ border-bottom: 1px solid #ddd; padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #f4f4f4; }}
  td a {{ color: #0a58ca; text-decoration: none; }}
  td a:hover {{ text-decoration: underline; }}
  .btn {{ display: inline-block; padding: 4px 12px; border: 1px solid #bbb; border-radius: 6px;
         background: #fafafa; color: #1a1a1a !important; text-decoration: none !important; }}
  .btn:hover {{ background: #eee; }}
  .ok {{ color: #1a7f37; font-weight: 600; }}
  .bad {{ color: #b42318; font-size: .85rem; }}
  .missing {{ color: #999; }}
  .problems {{ background: #fff4f4; border: 1px solid #f2b8b5; border-radius: 6px; padding: 10px 14px; margin: 14px 0; font-size: .88rem; }}
</style>
</head>
<body>
<h1>Mercedes-Benz Working Student Applications — Resume Index</h1>
<div class="meta">{ready}/{len(rows)} resumes ready &middot; source: jobs.mercedes-benz.com &middot; generated {generated}
&middot; click a job title to open the posting</div>
{problem_html}
<table>
<thead><tr><th>Job Title</th><th>Location</th><th>Posted</th><th>Resume PDF</th><th>Resume DOCX</th><th>Status</th></tr></thead>
<tbody>
{chr(10).join(body_rows)}
</tbody>
</table>
</body>
</html>
"""
    OUTPUT_HTML.write_text(page, encoding="utf-8")
    print(f"[PAGE] wrote {OUTPUT_HTML} ({ready}/{len(rows)} ready, {len(problems)} problem(s))")
    for problem in problems:
        print(f"[PAGE] PROBLEM: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
