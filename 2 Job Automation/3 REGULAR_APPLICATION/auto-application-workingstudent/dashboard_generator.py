"""Application Dashboard Generator for working student & internship postings.

Generates a standalone, minimalist HTML dashboard with:
  - Application cards & status badges (APPLIED, READY TO APPLY, NEW)
  - 1-Click copy for cover letter text (for pasting directly into web forms)
  - Direct links to generated Resume PDF and Cover Letter PDF
  - Direct links to original job postings
  - Tracking summary metrics
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from . import applied_tracker, config
except ImportError:
    import applied_tracker, config

config.ensure_utf8_stdout()


def _rel_link(path_str: str | Path) -> str:
    if not path_str:
        return ""
    p = Path(path_str)
    if not p.is_absolute():
        p = config.PROJECT_ROOT / p
    if p.exists():
        try:
            return str(p.relative_to(config.PROJECT_ROOT)).replace("\\", "/")
        except Exception:
            return str(p).replace("\\", "/")
    return ""


def build_dashboard(output_file: Path | None = None) -> Path:
    """Build the HTML dashboard for workingstudent applications."""
    config.ensure_dirs()
    target_path = output_file or config.DASHBOARD_HTML

    # Load tracker
    tracker = applied_tracker.load_tracker()
    tracked_jobs = tracker.get("jobs", {})

    # Load screened jobs
    screened_rows: list[dict[str, Any]] = []
    if config.SCREENED_CSV.exists():
        try:
            df = pd.read_csv(config.SCREENED_CSV, keep_default_na=False)
            screened_rows = df.to_dict("records")
        except Exception as exc:
            print(f"[DASHBOARD] Warning: Could not read {config.SCREENED_CSV}: {exc}")

    # Load engine reports if available
    resumes_report: dict[str, Any] = {}
    letters_report: dict[str, Any] = {}
    engine_resume_rep = config.PROJECT_ROOT / "output" / "applications" / "resume_report.json"
    engine_letter_rep = config.PROJECT_ROOT / "output" / "applications" / "letters_report.json"

    if engine_resume_rep.exists():
        try:
            data = json.loads(engine_resume_rep.read_text(encoding="utf-8"))
            for r in data.get("results", []):
                if r.get("job_url"):
                    resumes_report[r["job_url"]] = r
        except Exception:
            pass

    if engine_letter_rep.exists():
        try:
            data = json.loads(engine_letter_rep.read_text(encoding="utf-8"))
            for r in data.get("results", []):
                if r.get("job_url"):
                    letters_report[r["job_url"]] = r
        except Exception:
            pass

    # Build job list (combine screened rows and tracked jobs)
    seen_urls: set[str] = set()
    cards: list[dict[str, Any]] = []

    for row in screened_rows:
        url = str(row.get("job_url") or "").strip()
        if not url:
            continue
        seen_urls.add(url)
        tracked = tracked_jobs.get(url, {})
        res_info = resumes_report.get(url, {})
        let_info = letters_report.get(url, {})
        let_arts = let_info.get("artifacts") or {}

        # Status determination
        if tracked.get("status") == applied_tracker.STATUS_APPLIED:
            status = "APPLIED"
            badge_class = "badge-applied"
        elif res_info.get("status") == "verified" or let_arts.get("letter_pdf"):
            status = "READY TO APPLY"
            badge_class = "badge-ready"
        else:
            status = "SCREENED"
            badge_class = "badge-screened"

        # Resolve paths
        res_pdf = _rel_link(res_info.get("pdf") or tracked.get("resume_path", ""))
        let_pdf = _rel_link(let_arts.get("letter_pdf") or tracked.get("cover_letter_path", ""))
        let_txt_path = _rel_link(let_arts.get("textfield_txt", ""))
        let_text = ""
        if let_txt_path and (config.PROJECT_ROOT / let_txt_path).exists():
            try:
                let_text = (config.PROJECT_ROOT / let_txt_path).read_text(encoding="utf-8").strip()
            except Exception:
                pass

        cards.append({
            "url": url,
            "company": row.get("company", "Company"),
            "title": row.get("title", "Role"),
            "location": row.get("location", "Germany"),
            "posted_time": row.get("posted_time", ""),
            "role_type": row.get("role_type", "working_student"),
            "tech_domain": row.get("tech_domain", "tech"),
            "german_req": row.get("german_requirement", "none"),
            "status": status,
            "badge_class": badge_class,
            "resume_pdf": res_pdf,
            "letter_pdf": let_pdf,
            "letter_text": let_text,
            "requirements": row.get("requirements", ""),
            "applied_at": tracked.get("applied_at", ""),
        })

    # Stats
    total_screened = len(cards)
    ready_count = sum(1 for c in cards if c["status"] == "READY TO APPLY")
    applied_count = sum(1 for c in cards if c["status"] == "APPLIED")

    # Generate HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Working Student Job Applications Dashboard</title>
<style>
:root {{
  --bg: #0f141c;
  --card-bg: #18202c;
  --card-border: #243042;
  --text: #e2e8f0;
  --text-muted: #94a3b8;
  --accent: #38bdf8;
  --accent-hover: #0ea5e9;
  --success: #10b981;
  --warning: #f59e0b;
  --purple: #a855f7;
  --border-radius: 10px;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
body {{ background-color: var(--bg); color: var(--text); padding: 24px; line-height: 1.5; }}
header {{ max-width: 1200px; margin: 0 auto 24px auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; border-bottom: 1px solid var(--card-border); padding-bottom: 16px; }}
h1 {{ font-size: 1.5rem; font-weight: 700; color: #fff; }}
.subtitle {{ color: var(--text-muted); font-size: 0.9rem; }}
.stats-bar {{ display: flex; gap: 12px; }}
.stat-box {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 8px; padding: 8px 16px; text-align: center; }}
.stat-val {{ font-size: 1.3rem; font-weight: 700; color: var(--accent); }}
.stat-lbl {{ font-size: 0.75rem; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.5px; }}

.container {{ max-width: 1200px; margin: 0 auto; display: grid; gap: 18px; }}
.job-card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: var(--border-radius); padding: 20px; transition: transform 0.15s ease, border-color 0.15s ease; }}
.job-card:hover {{ border-color: var(--accent); transform: translateY(-2px); }}
.card-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 12px; }}
.job-title {{ font-size: 1.15rem; font-weight: 600; color: #fff; text-decoration: none; }}
.job-title:hover {{ color: var(--accent); }}
.company-name {{ color: var(--accent); font-weight: 600; font-size: 0.95rem; margin-top: 2px; }}
.meta-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; font-size: 0.8rem; }}
.tag {{ background: #222d3d; border: 1px solid var(--card-border); padding: 3px 8px; border-radius: 6px; color: var(--text-muted); }}

.badge {{ font-size: 0.75rem; font-weight: 700; padding: 4px 10px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.5px; }}
.badge-ready {{ background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #059669; }}
.badge-applied {{ background: rgba(56, 189, 248, 0.2); color: #38bdf8; border: 1px solid #0284c7; }}
.badge-screened {{ background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid #d97706; }}

.action-bar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; padding-top: 14px; border-top: 1px solid rgba(255,255,255,0.06); align-items: center; }}
.btn {{ background: #263445; color: #fff; padding: 6px 14px; border-radius: 6px; font-size: 0.85rem; font-weight: 500; text-decoration: none; border: 1px solid var(--card-border); cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }}
.btn:hover {{ background: #334458; }}
.btn-primary {{ background: #0284c7; border-color: #0284c7; }}
.btn-primary:hover {{ background: #0369a1; }}
.btn-copy {{ background: #2d224d; border-color: #4c3585; color: #c084fc; }}
.btn-copy:hover {{ background: #3b2b68; }}

.cl-snippet {{ margin-top: 12px; background: #111722; border: 1px solid #1f2937; border-radius: 6px; padding: 12px; font-size: 0.85rem; color: #cbd5e1; white-space: pre-wrap; max-height: 180px; overflow-y: auto; }}
.copied-toast {{ position: fixed; bottom: 24px; right: 24px; background: #10b981; color: #fff; padding: 10px 20px; border-radius: 8px; font-weight: 600; box-shadow: 0 4px 12px rgba(0,0,0,0.3); opacity: 0; pointer-events: none; transition: opacity 0.25s ease; }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Working Student Applications</h1>
    <div class="subtitle">Source: workingstudentjobs.de (Last 24 Hours) &bull; Tailored Resumes & Cover Letters</div>
  </div>
  <div class="stats-bar">
    <div class="stat-box">
      <div class="stat-val">{total_screened}</div>
      <div class="stat-lbl">Screened</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{ready_count}</div>
      <div class="stat-lbl">Ready</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{applied_count}</div>
      <div class="stat-lbl">Applied</div>
    </div>
  </div>
</header>

<div class="container">
"""

    if not cards:
        html_content += """
  <div class="job-card" style="text-align: center; padding: 48px;">
    <h3 style="color: #94a3b8; font-weight: 500;">No working student jobs currently staged.</h3>
    <p style="color: #64748b; font-size: 0.9rem; margin-top: 8px;">Run <code>python run.py --days 1</code> to fetch and build fresh applications.</p>
  </div>
"""

    for i, c in enumerate(cards, 1):
        clean_company = html.escape(c["company"])
        clean_title = html.escape(c["title"])
        clean_loc = html.escape(c["location"])
        clean_domain = html.escape(c["tech_domain"])
        clean_role = html.escape(c["role_type"].replace("_", " ").title())
        clean_url = html.escape(c["url"])

        resume_btn = f'<a class="btn" href="/{c["resume_pdf"]}" target="_blank">&darr; Resume PDF</a>' if c["resume_pdf"] else '<span class="tag">Resume Pending</span>'
        letter_btn = f'<a class="btn" href="/{c["letter_pdf"]}" target="_blank">&darr; Cover Letter PDF</a>' if c["letter_pdf"] else ''
        
        copy_btn = ""
        cl_box = ""
        if c["letter_text"]:
            escaped_text = html.escape(c["letter_text"])
            copy_btn = f'<button class="btn btn-copy" onclick="copyText(`copy-area-{i}`)">&#128203; Copy Letter Text</button>'
            cl_box = f'<div id="copy-area-{i}" class="cl-snippet" style="display:none;">{escaped_text}</div>'

        html_content += f"""
  <div class="job-card">
    <div class="card-header">
      <div>
        <a class="job-title" href="{clean_url}" target="_blank">{clean_title}</a>
        <div class="company-name">{clean_company}</div>
      </div>
      <div>
        <span class="badge {c['badge_class']}">{c['status']}</span>
      </div>
    </div>
    <div class="meta-row">
      <span class="tag">&#128205; {clean_loc}</span>
      <span class="tag">&#128188; {clean_role}</span>
      <span class="tag">&#9881; {clean_domain}</span>
      <span class="tag">&#127760; German: {c['german_req']}</span>
      {f'<span class="tag">&#128340; Applied: {c["applied_at"][:10]}</span>' if c['applied_at'] else ''}
    </div>
    {cl_box}
    <div class="action-bar">
      <a class="btn btn-primary" href="{clean_url}" target="_blank">&rarr; Apply on Portal</a>
      {resume_btn}
      {letter_btn}
      {copy_btn}
      {f'<button class="btn" onclick="toggleSnippet(`copy-area-{i}`)">Preview Letter</button>' if c["letter_text"] else ''}
    </div>
  </div>
"""

    html_content += """
</div>

<div id="toast" class="copied-toast">Copied to clipboard!</div>

<script>
function copyText(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const text = el.innerText || el.textContent;
  navigator.clipboard.writeText(text).then(() => {
    showToast();
  });
}
function toggleSnippet(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}
function showToast() {
  const t = document.getElementById('toast');
  t.style.opacity = '1';
  setTimeout(() => { t.style.opacity = '0'; }, 2000);
}
</script>
</body>
</html>
"""

    target_path.write_text(html_content, encoding="utf-8")
    # Also copy to DATA_DASHBOARD_HTML
    config.DATA_DASHBOARD_HTML.write_text(html_content, encoding="utf-8")
    print(f"[DASHBOARD] Generated dashboard at {target_path}")
    return target_path


def main() -> int:
    build_dashboard()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
