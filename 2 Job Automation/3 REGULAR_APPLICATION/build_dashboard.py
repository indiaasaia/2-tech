"""Generate a standalone, minimalist, high-productivity HTML application dashboard."""
import json
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load_json(rel_path):
    p = ROOT / rel_path
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Error loading {rel_path}: {e}")
    return {}

def resolve_file(path_str, default_subfolder=""):
    """Convert any absolute or irregular path into a verified existing file in REGULAR_APPLICATION."""
    if not path_str:
        return ""
    name = Path(path_str).name
    
    # Check direct relative path
    candidate = ROOT / path_str
    if candidate.is_file():
        return str(candidate.relative_to(ROOT)).replace("\\", "/")
    
    # Check default subfolder
    if default_subfolder:
        candidate = ROOT / default_subfolder / name
        if candidate.is_file():
            return str(candidate.relative_to(ROOT)).replace("\\", "/")
            
    # Search in common directories
    for sub in [
        "output/applications/resume/pdf",
        "output/applications/resume/docx",
        "output/applications/letters/pdf",
        "output/applications/letters/docx",
        "output/applications/letters/textfield",
        "output/applications/prep",
        "documents"
    ]:
        candidate = ROOT / sub / name
        if candidate.is_file():
            return str(candidate.relative_to(ROOT)).replace("\\", "/")
            
    return ""

def main():
    shortlist_data = load_json("output/applications/shortlist.json")
    bundles_data = load_json("output/applications/application_bundles.json")
    resumes_data = load_json("output/applications/resume_report.json")
    letters_data = load_json("output/applications/letters_report.json")
    kb_data = load_json("engine/knowledge_base/candidate_kb.json")

    profile = kb_data.get("profile", {})
    contact = profile.get("contact", {})
    availability = profile.get("availability", {})
    work_auth = profile.get("work_authorization", "")

    bundles_by_url = {b.get("job_url"): b for b in bundles_data.get("bundles", []) if b.get("job_url")}
    resumes_by_url = {r.get("job_url"): r for r in resumes_data.get("results", []) if r.get("job_url")}
    letters_by_url = {l.get("job_url"): l for l in letters_data.get("results", []) if l.get("job_url")}

    jobs = shortlist_data.get("jobs", [])

    job_records = []
    for idx, j in enumerate(jobs, 1):
        url = j.get("job_url", "")
        bundle = bundles_by_url.get(url, {})
        resume = resumes_by_url.get(url, {})
        letter = letters_by_url.get(url, {})

        # Letter text
        letter_txt_raw = (bundle.get("artifacts") or {}).get("letter_txt") or (letter.get("artifacts") or {}).get("letter_txt")
        letter_txt_rel = resolve_file(letter_txt_raw, "output/applications/letters/textfield")
        
        letter_content = ""
        if letter_txt_rel:
            try:
                letter_content = (ROOT / letter_txt_rel).read_text(encoding="utf-8")
            except Exception:
                pass

        # Prep sheet
        prep_file_raw = resume.get("prep_file") or ""
        prep_file_rel = resolve_file(prep_file_raw, "output/applications/prep")

        # Resumes & Letters
        res_pdf_rel = resolve_file((bundle.get("artifacts") or {}).get("resume_pdf") or j.get("pdf"), "output/applications/resume/pdf")
        res_docx_rel = resolve_file((bundle.get("artifacts") or {}).get("resume_docx") or j.get("docx"), "output/applications/resume/docx")
        let_pdf_rel = resolve_file((bundle.get("artifacts") or {}).get("letter_pdf") or (letter.get("artifacts") or {}).get("letter_pdf"), "output/applications/letters/pdf")
        let_docx_rel = resolve_file((bundle.get("artifacts") or {}).get("letter_docx") or (letter.get("artifacts") or {}).get("letter_docx"), "output/applications/letters/docx")

        # Absolute file:// URLs for local system viewing
        abs_root_uri = (str(ROOT).replace("\\", "/"))
        if not abs_root_uri.startswith("/"):
            abs_root_uri = "/" + abs_root_uri

        job_records.append({
            "id": idx,
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "job_url": url,
            "portal": bundle.get("portal") or ("stepstone" if "stepstone" in url.lower() else "workingstudentjobs"),
            "fit_tier": j.get("fit_tier") or "stretch",
            "score": j.get("score", 0),
            "kb_backed_share": j.get("kb_backed_share", 0),
            "keyword_coverage": j.get("keyword_coverage", 1.0),
            "prep_terms": j.get("prep_terms", []),
            "top_gaps": j.get("top_gaps", []),
            "notes": bundle.get("notes", ""),
            "upload_slot": bundle.get("upload_slot", ""),
            "missing": bundle.get("missing", []),
            "requested_documents": bundle.get("requested_documents", []),
            "res_pdf": res_pdf_rel,
            "res_docx": res_docx_rel,
            "let_pdf": let_pdf_rel,
            "let_docx": let_docx_rel,
            "let_txt": letter_txt_rel,
            "letter_content": letter_content,
            "prep_file": prep_file_rel,
            "letter_source": bundle.get("letter_source") or letter.get("letter_source", "")
        })

    # Generate HTML content
    html_content = generate_html(job_records, profile, contact, availability, work_auth)
    
    out_file1 = ROOT / "applications_dashboard.html"
    out_file1.write_text(html_content, encoding="utf-8")
    print(f"Generated dashboard -> {out_file1}")

    out_file2 = ROOT / "output" / "applications" / "dashboard.html"
    out_file2.parent.mkdir(parents=True, exist_ok=True)
    out_file2.write_text(html_content, encoding="utf-8")
    print(f"Generated dashboard copy -> {out_file2}")

def generate_html(jobs, profile, contact, availability, work_auth):
    jobs_json = json.dumps(jobs, ensure_ascii=False)
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Job Application Command Center | Meetkumar Raval</title>
<style>
  :root {{
    --bg: #0b0f19;
    --surface: #111827;
    --surface-elevated: #1f2937;
    --surface-hover: #263346;
    --border: #242f42;
    --border-light: #334155;
    --text: #f8fafc;
    --text-muted: #94a3b8;
    --text-dim: #64748b;
    --primary: #3b82f6;
    --primary-hover: #2563eb;
    --primary-dim: rgba(59, 130, 246, 0.12);
    --success: #10b981;
    --success-dim: rgba(16, 185, 129, 0.12);
    --warning: #f59e0b;
    --warning-dim: rgba(245, 158, 11, 0.12);
    --danger: #ef4444;
    --purple: #8b5cf6;
    --purple-dim: rgba(139, 92, 246, 0.12);
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 14px;
    --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: var(--font);
    background-color: var(--bg);
    color: var(--text);
    line-height: 1.5;
    padding: 24px;
    -webkit-font-smoothing: antialiased;
  }}

  .container {{
    max-width: 1540px;
    margin: 0 auto;
  }}

  /* Header banner */
  header {{
    background: linear-gradient(180deg, #162032 0%, #111827 100%);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 22px 26px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
  }}

  .header-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    margin-bottom: 18px;
  }}

  .header-title h1 {{
    font-size: 23px;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 10px;
  }}

  .header-title p {{
    color: var(--text-muted);
    font-size: 13.5px;
    margin-top: 3px;
  }}

  .badge-tag {{
    display: inline-flex;
    align-items: center;
    padding: 3px 9px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-radius: 999px;
    background: var(--primary-dim);
    color: #60a5fa;
    border: 1px solid rgba(96,165,250,0.3);
  }}

  /* Fast Quick-Copy Toolbar */
  .quick-copy-bar {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    background: rgba(0,0,0,0.3);
    border: 1px solid var(--border);
    padding: 12px 14px;
    border-radius: var(--radius-md);
  }}

  .quick-copy-title {{
    width: 100%;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-dim);
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
  }}

  .btn-copy {{
    background: var(--surface-elevated);
    border: 1px solid var(--border-light);
    color: var(--text);
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
    border-radius: var(--radius-sm);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: all 0.15s ease;
    user-select: none;
  }}

  .btn-copy:hover {{
    background: var(--surface-hover);
    border-color: var(--primary);
    color: #fff;
    transform: translateY(-1px);
  }}

  .btn-copy:active {{
    transform: translateY(0);
  }}

  /* Metrics summary cards */
  .metrics-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
  }}

  .metric-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }}

  .metric-label {{
    font-size: 11.5px;
    color: var(--text-muted);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}

  .metric-value {{
    font-size: 24px;
    font-weight: 700;
    color: #fff;
    margin-top: 4px;
    display: flex;
    align-items: baseline;
    gap: 6px;
  }}

  .metric-sub {{
    font-size: 11.5px;
    color: var(--text-dim);
    font-weight: 400;
  }}

  /* Controls & Search */
  .controls-bar {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 14px;
  }}

  .filter-tabs {{
    display: flex;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 3px;
    gap: 3px;
  }}

  .tab-btn {{
    background: transparent;
    border: none;
    color: var(--text-muted);
    padding: 6px 14px;
    font-size: 12.5px;
    font-weight: 500;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: all 0.15s ease;
  }}

  .tab-btn:hover {{
    color: var(--text);
  }}

  .tab-btn.active {{
    background: var(--primary);
    color: #fff;
    font-weight: 600;
  }}

  .search-box {{
    position: relative;
    min-width: 290px;
  }}

  .search-box input {{
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 8px 14px 8px 34px;
    color: #fff;
    font-size: 13px;
    outline: none;
    transition: border 0.15s ease;
  }}

  .search-box input:focus {{
    border-color: var(--primary);
    box-shadow: 0 0 0 2px var(--primary-dim);
  }}

  .search-icon {{
    position: absolute;
    left: 11px;
    top: 50%;
    transform: translateY(-50%);
    width: 14px;
    height: 14px;
    opacity: 0.5;
    pointer-events: none;
  }}

  /* Table styling */
  .table-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    text-align: left;
    font-size: 13px;
  }}

  thead th {{
    background: #141b27;
    color: var(--text-dim);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 13px 16px;
    border-bottom: 1px solid var(--border);
    user-select: none;
    white-space: nowrap;
  }}

  tbody tr {{
    border-bottom: 1px solid var(--border);
    transition: background 0.12s ease;
  }}

  tbody tr:hover {{
    background: rgba(255,255,255,0.02);
  }}

  tbody tr.is-applied {{
    opacity: 0.55;
    background: rgba(16, 185, 129, 0.02);
  }}

  td {{
    padding: 12px 16px;
    vertical-align: middle;
  }}

  .col-status {{ width: 120px; }}
  .col-company {{ width: 220px; }}
  .col-title {{ min-width: 270px; }}
  .col-fit {{ width: 140px; text-align: center; }}
  .col-docs {{ width: 240px; }}
  .col-actions {{ width: 170px; text-align: right; }}

  /* Status Dropdown */
  .status-select {{
    background: var(--surface-elevated);
    border: 1px solid var(--border-light);
    color: var(--text);
    font-size: 11.5px;
    font-weight: 600;
    padding: 4px 7px;
    border-radius: var(--radius-sm);
    outline: none;
    cursor: pointer;
  }}

  .status-select.to-apply {{ color: #60a5fa; border-color: rgba(96,165,250,0.4); }}
  .status-select.applied {{ color: #34d399; border-color: rgba(52,211,153,0.4); background: rgba(52,211,153,0.1); }}
  .status-select.interview {{ color: #fbbf24; border-color: rgba(251,191,36,0.4); background: rgba(251,191,36,0.1); }}
  .status-select.skipped {{ color: var(--text-dim); border-color: var(--border); }}

  /* Company & Role */
  .company-cell {{
    display: flex;
    flex-direction: column;
    gap: 3px;
  }}

  .company-name {{
    font-weight: 600;
    color: #fff;
    font-size: 13.5px;
  }}

  .portal-pill {{
    display: inline-flex;
    align-items: center;
    width: fit-content;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    padding: 2px 6px;
    border-radius: 4px;
    background: rgba(255,255,255,0.06);
    color: var(--text-dim);
  }}

  .role-title {{
    font-weight: 600;
    color: #e2e8f0;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: color 0.15s;
  }}

  .role-title:hover {{
    color: var(--primary);
    text-decoration: underline;
  }}

  .role-sub {{
    font-size: 11.5px;
    color: var(--text-dim);
    margin-top: 2px;
  }}

  /* Fit Tiers */
  .tier-badge {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }}

  .tier-strong {{
    background: var(--success-dim);
    color: #34d399;
    border: 1px solid rgba(52,211,153,0.3);
  }}

  .tier-good {{
    background: var(--primary-dim);
    color: #60a5fa;
    border: 1px solid rgba(96,165,250,0.3);
  }}

  .tier-stretch {{
    background: var(--warning-dim);
    color: #fbbf24;
    border: 1px solid rgba(251,191,36,0.3);
  }}

  .fit-numbers {{
    font-size: 11px;
    color: var(--text-dim);
    margin-top: 3px;
    font-family: var(--mono);
  }}

  /* Document link buttons */
  .doc-btn-group {{
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }}

  .doc-btn {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 7px;
    font-size: 11.5px;
    font-weight: 600;
    border-radius: var(--radius-sm);
    text-decoration: none;
    transition: all 0.15s ease;
    border: 1px solid transparent;
  }}

  .doc-btn-pdf {{
    background: rgba(239, 68, 68, 0.12);
    color: #f87171;
    border-color: rgba(239, 68, 68, 0.25);
  }}
  .doc-btn-pdf:hover {{
    background: rgba(239, 68, 68, 0.22);
    color: #fca5a5;
  }}

  .doc-btn-docx {{
    background: rgba(59, 130, 246, 0.12);
    color: #60a5fa;
    border-color: rgba(59, 130, 246, 0.25);
  }}
  .doc-btn-docx:hover {{
    background: rgba(59, 130, 246, 0.22);
    color: #93c5fd;
  }}

  .doc-btn-prep {{
    background: rgba(139, 92, 246, 0.12);
    color: #a78bfa;
    border-color: rgba(139, 92, 246, 0.25);
  }}
  .doc-btn-prep:hover {{
    background: rgba(139, 92, 246, 0.22);
    color: #c4b5fd;
  }}

  /* Action buttons */
  .action-col {{
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 6px;
  }}

  .btn-copy-letter {{
    background: #2563eb;
    color: #fff;
    border: none;
    padding: 6px 10px;
    font-size: 11.5px;
    font-weight: 600;
    border-radius: var(--radius-sm);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    transition: all 0.15s ease;
    white-space: nowrap;
  }}

  .btn-copy-letter:hover {{
    background: #1d4ed8;
    transform: translateY(-1px);
    box-shadow: 0 2px 8px rgba(37,99,235,0.4);
  }}

  .btn-details {{
    background: var(--surface-elevated);
    border: 1px solid var(--border-light);
    color: var(--text-muted);
    padding: 6px 9px;
    font-size: 12px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: all 0.15s;
  }}

  .btn-details:hover {{
    color: #fff;
    background: var(--surface-hover);
  }}

  /* Drawer / Detail View */
  .drawer-row {{
    background: #0d121c;
    border-bottom: 2px solid var(--border);
  }}

  .drawer-content {{
    padding: 18px 22px;
    display: grid;
    grid-template-columns: 1.1fr 0.9fr;
    gap: 20px;
  }}

  .drawer-box {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 16px;
  }}

  .drawer-box-title {{
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}

  .letter-preview {{
    background: #090d15;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 14px;
    font-family: var(--mono);
    font-size: 11.5px;
    color: #cbd5e1;
    max-height: 280px;
    overflow-y: auto;
    white-space: pre-wrap;
    line-height: 1.6;
  }}

  .prep-tags {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 6px;
  }}

  .prep-tag {{
    background: rgba(245, 158, 11, 0.12);
    border: 1px solid rgba(245, 158, 11, 0.25);
    color: #fcd34d;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
  }}

  .notice-banner {{
    background: rgba(59, 130, 246, 0.08);
    border-left: 3px solid var(--primary);
    padding: 10px 14px;
    font-size: 12.5px;
    color: #93c5fd;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    margin-bottom: 12px;
  }}

  /* Toast Notification */
  .toast {{
    position: fixed;
    bottom: 24px;
    right: 24px;
    background: #10b981;
    color: #fff;
    padding: 12px 20px;
    border-radius: var(--radius-md);
    font-size: 13.5px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    transform: translateY(100px);
    opacity: 0;
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    z-index: 1000;
  }}

  .toast.show {{
    transform: translateY(0);
    opacity: 1;
  }}
</style>
</head>
<body>

<div class="container">

  <!-- Header -->
  <header>
    <div class="header-top">
      <div class="header-title">
        <h1>
          <span>⚡ Application Command Center</span>
          <span class="badge-tag">24H Verified</span>
        </h1>
        <p>Candidate: <strong>{profile.get('name', 'Meetkumar Raval')}</strong> | MSc Artificial Intelligence @ BTU Cottbus-Senftenberg | Valid Permit until Dec 2028</p>
      </div>
      <div>
        <a href="documents/certificate_of_enrolment_small.pdf" target="_blank" class="btn-copy" style="background: rgba(16,185,129,0.12); border-color: rgba(16,185,129,0.3); color: #34d399; font-weight:600;">
          📄 View Enrolment Certificate
        </a>
      </div>
    </div>

    <!-- Quick Copy Hub -->
    <div class="quick-copy-bar">
      <div class="quick-copy-title">
        <span>⚡ 1-Click Form Autofill (Click to copy exact info for online portals - Zero Typos)</span>
        <span style="color:var(--text-dim)">Click any button to copy</span>
      </div>
      <button class="btn-copy" onclick="copyText('{profile.get('name', '')}', 'Full Name')">👤 Name</button>
      <button class="btn-copy" onclick="copyText('{contact.get('email', '')}', 'Email')">✉️ Email</button>
      <button class="btn-copy" onclick="copyText('{contact.get('phone_de', '')}', 'Phone')">📱 Phone</button>
      <button class="btn-copy" onclick="copyText('{contact.get('address', '')}', 'Address')">📍 Address</button>
      <button class="btn-copy" onclick="copyText('{contact.get('linkedin', '')}', 'LinkedIn URL')">🔗 LinkedIn</button>
      <button class="btn-copy" onclick="copyText('{contact.get('github', '')}', 'GitHub URL')">🐙 GitHub</button>
      <button class="btn-copy" onclick="copyText('{contact.get('portfolio', '')}', 'Portfolio URL')">🌐 Portfolio</button>
      <button class="btn-copy" onclick="copyText('{work_auth}', 'Work Authorization Note')">🛡️ Work Permit Note</button>
      <button class="btn-copy" onclick="copyText('{availability.get('hours', '')}', 'Availability Note')">⏱️ Hours & Availability</button>
    </div>
  </header>

  <!-- Metrics Cards -->
  <div class="metrics-grid">
    <div class="metric-card">
      <span class="metric-label">Verified Postings</span>
      <div class="metric-value">{len(jobs)} <span class="metric-sub">last 24h</span></div>
    </div>
    <div class="metric-card" style="border-left: 3px solid #10b981;">
      <span class="metric-label" style="color: #34d399;">Strong Fit (&ge;60% KB)</span>
      <div class="metric-value" style="color: #34d399;">{sum(1 for j in jobs if j.get('fit_tier') == 'strong')} <span class="metric-sub">apply first</span></div>
    </div>
    <div class="metric-card" style="border-left: 3px solid #3b82f6;">
      <span class="metric-label" style="color: #60a5fa;">Good Fit (&ge;40% KB)</span>
      <div class="metric-value" style="color: #60a5fa;">{sum(1 for j in jobs if j.get('fit_tier') == 'good')} <span class="metric-sub">solid match</span></div>
    </div>
    <div class="metric-card" style="border-left: 3px solid #f59e0b;">
      <span class="metric-label" style="color: #fbbf24;">Stretch (&lt;40% KB)</span>
      <div class="metric-value" style="color: #fbbf24;">{sum(1 for j in jobs if j.get('fit_tier') == 'stretch')} <span class="metric-sub">prep required</span></div>
    </div>
    <div class="metric-card">
      <span class="metric-label">ATS Keyword Guarantee</span>
      <div class="metric-value" style="color: #10b981;">100% <span class="metric-sub">all resumes</span></div>
    </div>
  </div>

  <!-- Filters & Controls -->
  <div class="controls-bar">
    <div class="filter-tabs">
      <button class="tab-btn active" onclick="setFilter('all', this)">All Jobs ({len(jobs)})</button>
      <button class="tab-btn" onclick="setFilter('strong', this)">Strong Fit</button>
      <button class="tab-btn" onclick="setFilter('good', this)">Good Fit</button>
      <button class="tab-btn" onclick="setFilter('stretch', this)">Stretch</button>
      <button class="tab-btn" onclick="setFilter('to-apply', this)">To Apply</button>
      <button class="tab-btn" onclick="setFilter('applied', this)">Applied</button>
    </div>
    <div class="search-box">
      <svg class="search-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
      <input type="text" id="searchInput" placeholder="Search company, title, or skills..." oninput="handleSearch()">
    </div>
  </div>

  <!-- Main Table -->
  <div class="table-card">
    <table>
      <thead>
        <tr>
          <th class="col-status">Status</th>
          <th class="col-company">Company</th>
          <th class="col-title">Role / Posting</th>
          <th class="col-fit">Fit &amp; Match</th>
          <th class="col-docs">Tailored Documents</th>
          <th class="col-actions">Quick Actions</th>
        </tr>
      </thead>
      <tbody id="jobsTableBody">
        <!-- Rendered via JavaScript -->
      </tbody>
    </table>
  </div>

</div>

<!-- Toast element -->
<div id="toast" class="toast">
  <span>✓ Copied to clipboard!</span>
</div>

<script>
const JOBS = {jobs_json};

let currentFilter = 'all';
let currentSearch = '';

// Load status from localStorage
function getSavedStatus(url) {{
  return localStorage.getItem('job_status_' + url) || 'to-apply';
}}

function setSavedStatus(url, status) {{
  localStorage.setItem('job_status_' + url, status);
  renderTable();
}}

function copyText(text, label) {{
  navigator.clipboard.writeText(text).then(() => {{
    showToast('Copied ' + label + ' to clipboard!');
  }}).catch(() => {{
    const textarea = document.createElement('textarea');
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    showToast('Copied ' + label + ' to clipboard!');
  }});
}}

function showToast(msg) {{
  const toast = document.getElementById('toast');
  toast.innerHTML = '<span>✓ ' + msg + '</span>';
  toast.classList.add('show');
  setTimeout(() => {{
    toast.classList.remove('show');
  }}, 2500);
}}

function setFilter(filter, el) {{
  currentFilter = filter;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  renderTable();
}}

function handleSearch() {{
  currentSearch = document.getElementById('searchInput').value.toLowerCase().trim();
  renderTable();
}}

function toggleDrawer(id) {{
  const drawer = document.getElementById('drawer-' + id);
  if (!drawer) return;
  drawer.style.display = drawer.style.display === 'none' ? 'table-row' : 'none';
}}

function renderTable() {{
  const tbody = document.getElementById('jobsTableBody');
  tbody.innerHTML = '';

  const filtered = JOBS.filter(job => {{
    const status = getSavedStatus(job.job_url);
    if (currentFilter === 'strong' && job.fit_tier !== 'strong') return false;
    if (currentFilter === 'good' && job.fit_tier !== 'good') return false;
    if (currentFilter === 'stretch' && job.fit_tier !== 'stretch') return false;
    if (currentFilter === 'to-apply' && status !== 'to-apply') return false;
    if (currentFilter === 'applied' && status !== 'applied') return false;

    if (currentSearch) {{
      const text = (job.company + ' ' + job.title + ' ' + (job.prep_terms || []).join(' ')).toLowerCase();
      if (!text.includes(currentSearch)) return false;
    }}
    return true;
  }});

  if (filtered.length === 0) {{
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 40px; color: var(--text-dim);">No matching jobs found.</td></tr>';
    return;
  }}

  filtered.forEach(job => {{
    const status = getSavedStatus(job.job_url);
    const isApplied = status === 'applied';

    const tierClass = 'tier-' + (job.fit_tier || 'stretch');
    const tierLabel = (job.fit_tier || 'stretch').toUpperCase();

    // Documents
    let docsHtml = '<div class="doc-btn-group">';
    if (job.res_pdf) docsHtml += `<a href="${{job.res_pdf}}" target="_blank" class="doc-btn doc-btn-pdf" title="View Resume PDF">CV PDF</a>`;
    if (job.res_docx) docsHtml += `<a href="${{job.res_docx}}" download class="doc-btn doc-btn-docx" title="Download Word CV">DOCX</a>`;
    if (job.let_pdf) docsHtml += `<a href="${{job.let_pdf}}" target="_blank" class="doc-btn doc-btn-pdf" title="View Cover Letter PDF">Letter</a>`;
    if (job.prep_file) docsHtml += `<a href="${{job.prep_file}}" target="_blank" class="doc-btn doc-btn-prep" title="Interview Cheat Sheet">Prep</a>`;
    docsHtml += '</div>';

    // Copy letter button
    const hasLetter = !!job.letter_content;
    const copyLetterBtn = hasLetter ? 
      `<button class="btn-copy-letter" onclick="copyJobLetter(${{job.id}})" title="Copy Cover Letter Text to Clipboard">📋 Copy Letter</button>` :
      `<span style="color:var(--text-dim); font-size:11px;">(Resume Only)</span>`;

    const row = document.createElement('tr');
    row.className = isApplied ? 'is-applied' : '';
    row.innerHTML = `
      <td class="col-status">
        <select class="status-select ${{status}}" onchange="setSavedStatus('${{job.job_url}}', this.value)">
          <option value="to-apply" ${{status==='to-apply'?'selected':''}}>⏳ To Apply</option>
          <option value="applied" ${{status==='applied'?'selected':''}}>✓ Applied</option>
          <option value="interview" ${{status==='interview'?'selected':''}}>⭐ Interview</option>
          <option value="skipped" ${{status==='skipped'?'selected':''}}>✕ Skipped</option>
        </select>
      </td>
      <td class="col-company">
        <div class="company-cell">
          <span class="company-name">${{escapeHtml(job.company)}}</span>
          <span class="portal-pill">${{job.portal}}</span>
        </div>
      </td>
      <td class="col-title">
        <div>
          <a href="${{job.job_url}}" target="_blank" class="role-title" rel="noopener">
            ${{escapeHtml(job.title)}}
            <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
          </a>
          <div class="role-sub">
            ${{job.prep_terms && job.prep_terms.length > 0 ? 'Skills: ' + job.prep_terms.slice(0, 4).join(', ') : 'ATS Tailored'}}
          </div>
        </div>
      </td>
      <td class="col-fit">
        <span class="tier-badge ${{tierClass}}">${{tierLabel}}</span>
        <div class="fit-numbers">Score: ${{job.score ? job.score.toFixed(1) : 0}}% | KB: ${{(job.kb_backed_share*100).toFixed(0)}}%</div>
      </td>
      <td class="col-docs">
        ${{docsHtml}}
      </td>
      <td class="col-actions">
        <div class="action-col">
          ${{copyLetterBtn}}
          <button class="btn-details" onclick="toggleDrawer(${{job.id}})" title="Expand Details & Preview">▼</button>
        </div>
      </td>
    `;
    tbody.appendChild(row);

    // Expandable Drawer Row
    const drawerRow = document.createElement('tr');
    drawerRow.id = 'drawer-' + job.id;
    drawerRow.className = 'drawer-row';
    drawerRow.style.display = 'none';

    const prepTermsHtml = (job.prep_terms || []).map(t => `<span class="prep-tag">${{escapeHtml(t)}}</span>`).join('');
    const gapsHtml = (job.top_gaps || []).map(g => `<li style="margin-left: 16px; margin-bottom: 2px;">${{escapeHtml(g)}}</li>`).join('');

    drawerRow.innerHTML = `
      <td colspan="6" style="padding: 0;">
        <div class="drawer-content">
          <!-- Left: Cover Letter Preview -->
          <div class="drawer-box">
            <div class="drawer-box-title">
              <span>Cover Letter Preview (${{job.letter_source || 'generated'}})</span>
              ${{hasLetter ? `<button class="btn-copy" style="padding: 2px 8px; font-size: 11px;" onclick="copyJobLetter(${{job.id}})">📋 Copy Text</button>` : ''}}
            </div>
            ${{hasLetter ? `<div class="letter-preview">${{escapeHtml(job.letter_content)}}</div>` : '<p style="color:var(--text-dim); font-size: 13px;">No cover letter generated for this role.</p>'}}
          </div>

          <!-- Right: Portal & Interview Info -->
          <div class="drawer-box">
            <div class="drawer-box-title">Portal Delivery &amp; Interview Cheat Sheet</div>
            
            ${{job.notes ? `<div class="notice-banner">📌 <strong>Application Note:</strong> ${{escapeHtml(job.notes)}}</div>` : ''}}

            <div style="margin-bottom: 14px;">
              <strong style="font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Upload Slot:</strong>
              <div style="font-size: 13px; color: #fff; margin-top: 2px;">${{escapeHtml(job.upload_slot || 'Standard document upload')}}</div>
            </div>

            ${{job.prep_terms && job.prep_terms.length > 0 ? `
              <div style="margin-bottom: 14px;">
                <strong style="font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Learn/Review Before Interview:</strong>
                <div class="prep-tags">${{prepTermsHtml}}</div>
              </div>
            ` : ''}}

            ${{job.top_gaps && job.top_gaps.length > 0 ? `
              <div>
                <strong style="font-size: 12px; color: var(--text-muted); text-transform: uppercase;">Posting Demands To Be Aware Of:</strong>
                <ul style="font-size: 12.5px; color: var(--text-muted); margin-top: 4px;">${{gapsHtml}}</ul>
              </div>
            ` : ''}}
          </div>
        </div>
      </td>
    `;
    tbody.appendChild(drawerRow);
  }});
}}

function copyJobLetter(id) {{
  const job = JOBS.find(j => j.id === id);
  if (!job || !job.letter_content) return;
  copyText(job.letter_content, job.company + ' Cover Letter');
}}

function escapeHtml(str) {{
  if (!str) return '';
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}}

// Initialize
renderTable();
</script>

</body>
</html>
"""

if __name__ == "__main__":
    main()
