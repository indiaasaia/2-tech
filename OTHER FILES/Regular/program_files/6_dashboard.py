"""Streamlit dashboard for the job automation pipeline.

Pages:
  Home         - what the system does and where the data stands
  Run Scanner  - runs the full pipeline (scrape, filter, key test, LLM components,
                 resume building) with per-stage progress and a live log;
                 every newly scanned job is added to the tracker as Pending
  Resumes      - browse every generated resume next to its matching job, with its
                 fit (share of job keywords your KB backs), keyword coverage, and
                 download buttons for the resume PDF/DOCX, cover letter and prep sheet
  Learn Before Interview - skills printed for the ATS but not yet in your KB,
                 ranked by how many jobs ask for them, plus every per-job prep sheet
  Job Tracker  - all scanned jobs with a status dropdown per job
                 (Applied / Not Interested / Pending); new jobs default to Pending;
                 Applied rows are light green, Not Interested light yellow,
                 Pending light red

Run:  streamlit run program_files/6_dashboard.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "program_files" / "output"
STATUS_CSV = OUTPUT_DIR / "job_status.csv"
SCANNER_LOG = OUTPUT_DIR / "dashboard_scanner.log"
SCAN_STATE_FILE = OUTPUT_DIR / "dashboard_scan_state.json"

SCANNER_STAGES = [
    ("Scraping job boards (Stepstone + workingstudentjobs.de)", [sys.executable, "program_files/1_fetch_jobs.py"]),
    ("Filtering fresh postings and saving the job list", [sys.executable, "program_files/2_filter_jobs.py"]),
    ("Testing Ollama API keys", [sys.executable, "program_files/3_test_ollama_keys.py"]),
    ("Generating and gating v2 resume components", [sys.executable, "resume_content_improve_research/run_step4.py"]),
    ("Building and verifying resumes", [sys.executable, "resume_content_improve_research/run_step5.py"]),
    ("Creating gated cover letters and application bundles", [sys.executable, "resume_content_improve_research/run_step6.py"]),
]

STATUS_OPTIONS = ["Pending", "Applied", "Not Interested"]
STATUS_COLORS = {"Applied": "#d4edda", "Not Interested": "#fff3cd", "Pending": "#f8d7da"}
# The v2 engine writes its artifacts and reports to output_v2 (the dashboard used
# to read output/resume_report.json, which v2 never writes: the Resumes page was empty).
OUTPUT_V2_DIR = PROJECT_ROOT / "program_files" / "output_v2"
RESUME_REPORT = OUTPUT_V2_DIR / "resume_report.json"
LETTERS_REPORT = OUTPUT_V2_DIR / "letters_report.json"
PREP_DIR = OUTPUT_V2_DIR / "prep"
FIT_COLORS = {"strong": "#d4edda", "good": "#e2f0fb", "stretch": "#fff3cd"}


def load_resume_report() -> list[dict]:
    """Read resume_report.json and return its per-job results (empty on any problem)."""
    if not RESUME_REPORT.exists():
        return []
    try:
        payload = json.loads(RESUME_REPORT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return list(payload.get("results") or [])


def load_letters_by_url() -> dict[str, dict]:
    """job_url -> step-6 letter result (empty when step 6 has not run)."""
    if not LETTERS_REPORT.exists():
        return {}
    try:
        payload = json.loads(LETTERS_REPORT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(r.get("job_url") or ""): r for r in payload.get("results") or [] if isinstance(r, dict)}


def fit_tier(share: object) -> str:
    """strong / good / stretch by the share of job keywords the KB backs."""
    if not isinstance(share, (int, float)):
        return ""
    return "strong" if share >= 0.6 else ("good" if share >= 0.4 else "stretch")


def job_meta_by_url() -> dict[str, dict]:
    """Map job_url -> {company, location, snippet} from the jobs database."""
    csv_path = OUTPUT_DIR / "todays_overall_jobs.csv"
    meta: dict[str, dict] = {}
    if not csv_path.exists():
        return meta
    try:
        frame = pd.read_csv(csv_path, keep_default_na=False)
    except Exception:  # noqa: BLE001 - meta is optional decoration
        return meta
    for _, row in frame.iterrows():
        meta[str(row.get("job_url") or "")] = {
            "company": clean(row.get("company")),
            "location": clean(row.get("location")),
        }
    return meta


def page_resumes() -> None:
    """Browse generated resumes next to their matching jobs, with downloads."""
    st.title("Resumes")
    results = load_resume_report()
    if not results:
        st.warning("No resumes yet - run the scanner (or steps 4-5) first.")
        return

    meta = job_meta_by_url()
    status = load_status().set_index("job_url")["status"].to_dict()
    letters = load_letters_by_url()

    failed = [r for r in results if r.get("status") != "verified"]
    if failed:
        st.warning(f"{len(failed)} resume(s) were not shipped (marked below with the reason).")

    ok_count = len(results) - len(failed)
    st.caption(f"{ok_count} resume(s) ready - newest run, best fit first. Fit = share of the job's "
               "technical keywords your knowledge base backs; every resume carries 100% of its keywords.")

    search = st.text_input("Search by title or company", "").strip().lower()
    ordered = sorted(enumerate(results), key=lambda pair: -(pair[1].get("kb_backed_share") or -1))
    shown = 0
    for index, result in ordered:
        title = clean(result.get("title")) or "(untitled)"
        info = meta.get(str(result.get("job_url") or ""), {})
        company = clean(result.get("company")) or info.get("company", "")
        location = info.get("location", "")
        if search and search not in title.lower() and search not in company.lower():
            continue
        shown += 1
        error = clean(result.get("build_error")) if result.get("status") != "verified" else ""
        color = STATUS_COLORS.get(status.get(str(result.get("job_url") or ""), ""), "#e8eaf6") if not error else "#f8d7da"
        tier = fit_tier(result.get("kb_backed_share"))
        with st.container(border=True):
            left, right = st.columns([7, 3])
            with left:
                meta_line = " - ".join(part for part in (company, location) if part)
                scores = ""
                if tier:
                    scores = (f"<br><small><span style='background:{FIT_COLORS[tier]};padding:1px 6px;"
                              f"border-radius:4px'>fit: {tier} ({result['kb_backed_share']:.0%})</span> "
                              f"&nbsp; keywords on resume: {result.get('keyword_coverage', 0):.0%} "
                              f"&nbsp; to learn: {len(result.get('prep_terms') or [])}</small>")
                st.markdown(
                    f"<div style='background:{color};padding:8px 12px;border-radius:6px'>"
                    f"<b>{title}</b>"
                    + (f"<br><small>{meta_line}</small>" if meta_line else "")
                    + scores
                    + (f"<br><small><b>not shipped:</b> {error}</small>" if error else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )
                if result.get("job_url"):
                    st.markdown(f"[Open job posting]({result['job_url']})")
                prep_path = Path(str(result.get("prep_file") or ""))
                if prep_path.is_file():
                    with st.expander("Interview prep"):
                        st.markdown(prep_path.read_text(encoding="utf-8"))
            with right:
                pdf_path = Path(str(result.get("pdf") or ""))
                docx_path = Path(str(result.get("docx") or ""))
                letter_pdf = Path(str((letters.get(str(result.get("job_url") or ""), {})
                                       .get("artifacts") or {}).get("letter_pdf") or ""))
                if not error and pdf_path.exists():
                    st.download_button(
                        "Download resume PDF",
                        data=pdf_path.read_bytes(),
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        key=f"pdf-{index}",
                        use_container_width=True,
                    )
                if not error and docx_path.exists():
                    st.download_button(
                        "Download resume DOCX",
                        data=docx_path.read_bytes(),
                        file_name=docx_path.name,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"docx-{index}",
                        use_container_width=True,
                    )
                if not error and letter_pdf.is_file():
                    st.download_button(
                        "Download cover letter",
                        data=letter_pdf.read_bytes(),
                        file_name=letter_pdf.name,
                        mime="application/pdf",
                        key=f"letter-{index}",
                        use_container_width=True,
                    )
    if not shown:
        st.info("No resumes match that search.")


def scan_read() -> dict:
    """Read the scanner state file; falls back to defaults when missing/corrupt."""
    state: dict = {"running": False, "stage": "", "success": None, "message": "", "new_jobs": 0, "pid": 0}
    if SCAN_STATE_FILE.exists():
        try:
            state.update(json.loads(SCAN_STATE_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return state


def scan_write(**changes: object) -> None:
    """Update the scanner state file (worker thread -> UI; retried for read races)."""
    state = scan_read()
    state.update(changes)
    tmp_path = SCAN_STATE_FILE.with_suffix(".tmp")
    for _ in range(3):
        try:
            tmp_path.write_text(json.dumps(state), encoding="utf-8")
            tmp_path.replace(SCAN_STATE_FILE)
            return
        except OSError:
            time.sleep(0.05)


def process_alive(pid: int) -> bool:
    """True when a process with this pid exists (Windows-safe)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def count_jobs() -> int:
    """Number of jobs currently in the pipeline database."""
    csv_path = OUTPUT_DIR / "todays_overall_jobs.csv"
    if not csv_path.exists():
        return 0
    try:
        return int(pd.read_csv(csv_path).shape[0])
    except Exception:  # noqa: BLE001 - the dashboard must not crash on a corrupt csv
        return 0


def component_counts() -> dict[str, int]:
    """Record counts from the v2 stores (step-4 components, step-6 letters)."""
    counts = {"resume components (gated_ok)": 0, "parked jobs": 0, "verified cover letters": 0}
    components = OUTPUT_V2_DIR / "components_v2.json"
    if components.exists():
        try:
            records = json.loads(components.read_text(encoding="utf-8"))
            counts["resume components (gated_ok)"] = sum(1 for r in records if r.get("status") == "gated_ok")
            counts["parked jobs"] = sum(1 for r in records if r.get("status") == "parked")
        except Exception:  # noqa: BLE001 - the dashboard must not crash on a corrupt store
            pass
    counts["verified cover letters"] = sum(1 for r in load_letters_by_url().values() if r.get("letter_gates_passed"))
    return counts


def count_resumes() -> tuple[int, int]:
    """(pdf, docx) counts in the v2 resume output folders."""
    pdf_dir = OUTPUT_V2_DIR / "resume" / "pdf"
    docx_dir = OUTPUT_V2_DIR / "resume" / "docx"
    pdfs = len(list(pdf_dir.glob("*.pdf"))) if pdf_dir.exists() else 0
    docx = len(list(docx_dir.glob("*.docx"))) if docx_dir.exists() else 0
    return pdfs, docx


def load_status() -> pd.DataFrame:
    """Load the persisted job statuses, guaranteeing the expected columns exist."""
    columns = ["job_url", "title", "company", "status"]
    if STATUS_CSV.exists():
        try:
            frame = pd.read_csv(STATUS_CSV, keep_default_na=False)
            for column in columns:
                if column not in frame.columns:
                    frame[column] = ""
            return frame
        except Exception:  # noqa: BLE001
            pass
    return pd.DataFrame(columns=columns)


def clean(value: object) -> str:
    """Render a CSV value for display ('' for missing/NaN)."""
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in {"", "nan", "none"} else text


def save_status(frame: pd.DataFrame) -> None:
    """Persist the job status table."""
    frame.to_csv(STATUS_CSV, index=False, encoding="utf-8")


def ensure_status_rows(jobs_frame: pd.DataFrame) -> pd.DataFrame:
    """Add a Pending row for every job not yet tracked, then save."""
    status = load_status()
    if not status.empty:
        # Sanitize: unknown statuses become Pending, duplicate urls collapse to one row.
        status["status"] = status["status"].where(status["status"].isin(STATUS_OPTIONS), "Pending")
        status = status.drop_duplicates(subset="job_url", keep="first")
    existing = set(status["job_url"])
    new_rows = [
        {"job_url": row["job_url"], "title": row["title"], "company": row["company"], "status": "Pending"}
        for _, row in jobs_frame.iterrows() if row["job_url"] not in existing
    ]
    if new_rows:
        status = pd.concat([status, pd.DataFrame(new_rows)], ignore_index=True)
        save_status(status)
    return status


def run_command(command: list[str], log_lines: list[str], log_handle) -> bool:
    """Run one pipeline script, streaming its output into the log."""
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in process.stdout or []:  # type: ignore[union-attr]
        log_lines.append(line.rstrip())
        log_handle.write("\n".join(log_lines[-400:]), encoding="utf-8")
    process.wait()
    return process.returncode == 0


def scanner_worker() -> None:
    """Run each dependency-ordered pipeline stage, publishing progress to the state file."""
    # Step 2 keeps only jobs posted within the rolling last 24 hours.

    scan_write(running=True, stage="starting", success=None, message="", new_jobs=0, pid=os.getpid())
    log_lines: list[str] = ["look-back window: last 24 hours"]
    try:
        log_handle = SCANNER_LOG.open("w", encoding="utf-8")
    except OSError as exc:
        scan_write(running=False, success=False, message=f"cannot open log file: {exc}")
        return

    all_ok = True
    try:
        for stage_index, (label, command) in enumerate(SCANNER_STAGES, 1):
            scan_write(stage=f"stage {stage_index}/{len(SCANNER_STAGES)}: {label}")
            log_lines.append(f"\n=== {label} ===")
            ok = run_command(command, log_lines, log_handle)
            log_lines.append(f"=== {label}: {'OK' if ok else 'FAILED'} ===")
            log_handle.write("\n".join(log_lines[-400:]), encoding="utf-8")
            all_ok = all_ok and ok
            if not ok:
                break

        jobs_csv = OUTPUT_DIR / "todays_overall_jobs.csv"
        if jobs_csv.exists():
            frame = pd.read_csv(jobs_csv, keep_default_na=False)
            ensure_status_rows(frame)
            scan_write(new_jobs=int(frame.shape[0]))
        scan_write(stage="finished")
    except Exception as exc:  # noqa: BLE001 - the thread must always release the running flag
        all_ok = False
        log_lines.append(f"SCANNER ERROR: {type(exc).__name__}: {exc}")
        log_handle.write("\n".join(log_lines[-400:]), encoding="utf-8")
    finally:
        log_handle.close()
        scan_write(
            running=False,
            success=all_ok,
            message=(
                "Scanner finished successfully - jobs added to the tracker as Pending"
                if all_ok else "Scanner finished with failures - check the log on this page"
            ),
        )


def page_home() -> None:
    """Home page: basic information and current data status."""
    st.title("Job Automation Dashboard")
    st.caption("Scrape - filter - generate ATS components - build PDF/DOCX resumes")

    jobs = count_jobs()
    pdfs, docx = count_resumes()
    counts = component_counts()
    left, middle, right = st.columns(3)
    left.metric("Jobs in database", jobs)
    middle.metric("PDF resumes", pdfs)
    right.metric("DOCX resumes", docx)

    st.subheader("Pipeline stores (per job)")
    st.table(pd.DataFrame(
        [(name, count) for name, count in counts.items()],
        columns=["store", "records"],
    ).set_index("store"))

    st.subheader("How the pipeline works")
    st.markdown(
        """
        1. **Fetch** - scrape Stepstone and workingstudentjobs.de
        2. **Filter** - keep postings from the last 24 hours
        3. **Keys** - test configured Ollama API keys
        4. **Components** - analyze jobs, build claimable facts, generate and gate content
        5. **Resumes** - compile, parse back, verify and score PDF/DOCX output
        6. **Letters** - generate and gate cover letters and portal upload bundles
        7. **Tracker** - mark each job Applied / Not Interested / Pending
        """
    )
    st.info("Open **Run Scanner** to fetch fresh jobs and build verified resumes and cover letters. "
            "New jobs appear in the **Job Tracker** as Pending.")


def page_scanner() -> None:
    """Run Scanner page: start button, live progress, full log."""
    st.title("Run Scanner")
    state = scan_read()

    # Orphan healing: a "running" state with a dead worker process can never finish.
    if state["running"] and not process_alive(int(state.get("pid") or 0)):
        scan_write(
            running=False,
            success=False,
            stage="",
            message="Scanner did not finish (server was restarted mid-scan) - start it again.",
        )
        state = scan_read()

    if state["running"]:
        st.info(f"Scanner running - {state.get('stage') or 'starting'} ...")
        st.caption("The scanner runs in the background. Click Refresh to see the newest log lines.")
        if st.button("Refresh progress"):
            st.rerun()
        if SCANNER_LOG.exists():
            st.text_area("Live log", value=SCANNER_LOG.read_text(encoding="utf-8", errors="replace")[-6000:], height=420)
        return

    if state.get("message"):
        if state.get("success"):
            st.success(state["message"])
        else:
            st.error(state["message"])

    if st.button("Run scanner", type="primary"):
        threading.Thread(target=scanner_worker, daemon=True).start()
        st.rerun()

    if state.get("new_jobs"):
        st.caption(f"{state['new_jobs']} job(s) now in the database")

    if SCANNER_LOG.exists():
        st.subheader("Last scan log")
        st.text_area("Log", value=SCANNER_LOG.read_text(encoding="utf-8", errors="replace")[-6000:], height=420)


def page_tracker() -> None:
    """Job tracker: dropdown per job, color-coded status rows."""
    st.title("Job Tracker")
    jobs_csv = OUTPUT_DIR / "todays_overall_jobs.csv"
    if not jobs_csv.exists():
        st.warning("No jobs yet - run the scanner first.")
        return
    frame = pd.read_csv(jobs_csv, keep_default_na=False)
    if frame.empty:
        st.warning("No jobs yet - run the scanner first.")
        return

    status = ensure_status_rows(frame)

    # The tracker must accumulate: jobs from older scans keep their status even
    # though each new scan overwrites todays_overall_jobs.csv with fresh postings.
    latest_urls = set(frame["job_url"])
    older = status[~status["job_url"].isin(latest_urls)].copy()
    older["location"] = ""
    older = older.drop(columns=["status"])  # re-merged below; keeping it would split into status_x/y
    merged = pd.concat([frame, older], ignore_index=True)
    merged = merged.drop_duplicates(subset="job_url", keep="first")
    merged = merged.merge(status[["job_url", "status"]], on="job_url", how="left")
    merged["status"] = merged["status"].where(merged["status"].isin(STATUS_OPTIONS), "Pending")

    status_filter = st.multiselect("Filter by status", STATUS_OPTIONS, default=STATUS_OPTIONS)
    st.caption(f"{len(merged)} job(s) tracked")
    for _, row in merged.iterrows():
        if row["status"] not in status_filter:
            continue
        color = STATUS_COLORS.get(row["status"], "#f8d7da")
        left, link_column, dropdown_column = st.columns([6, 2, 2])
        with left:
            meta = " - ".join(part for part in (clean(row.get("company")), clean(row.get("location")), row["status"]) if part)
            st.markdown(
                f"<div style='background:{color};padding:10px;border-radius:6px'>"
                f"<b>{clean(row['title'])}</b><br>"
                f"<small>{meta}</small></div>",
                unsafe_allow_html=True,
            )
        with link_column:
            st.markdown(f"[Open posting]({row['job_url']})")
        with dropdown_column:
            new_status = st.selectbox(
                "status",
                STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(row["status"]),
                key=f"status-{row['job_url']}",
                label_visibility="collapsed",
            )
        if new_status != row["status"]:
            status.loc[status["job_url"] == row["job_url"], "status"] = new_status
            save_status(status)
            st.rerun()


def load_learning_priorities() -> dict:
    """output_v2/prep/learning_priorities.json written by step 5 ({} when missing)."""
    path = PREP_DIR / "learning_priorities.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def page_prep() -> None:
    """Skills to learn before interviews, ranked across all jobs, plus per-job sheets."""
    st.title("Learn Before Interview")
    payload = load_learning_priorities()
    priorities = payload.get("priorities") or []
    if not payload:
        st.warning("No prep data yet - run the scanner (or step 5) first.")
        return
    st.caption(
        "These skills are on your resumes for the ATS but not yet in your knowledge base. "
        f"Ranked by how many different companies (then how many of the {payload.get('verified_jobs', 0)} "
        "verified jobs) ask for them. "
        "Learn the top ones first, then add them to candidate_kb.json with real evidence "
        "(a small project) so they become backed skills."
    )
    if priorities:
        frame = pd.DataFrame(
            [(p["term"], len(p["companies"]), p["jobs"], ", ".join(p["companies"][:6])) for p in priorities],
            columns=["skill", "companies", "jobs", "who asks"],
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)
    else:
        st.success("Every technical keyword in your verified jobs is already backed by your KB.")

    sheets = sorted(PREP_DIR.glob("*.md")) if PREP_DIR.exists() else []
    sheets = [s for s in sheets if s.name != "learning_priorities.md"]
    if sheets:
        st.subheader("Per-job prep sheets")
        choice = st.selectbox("Job", [s.stem for s in sheets])
        st.markdown((PREP_DIR / f"{choice}.md").read_text(encoding="utf-8"))


def main() -> None:
    """Streamlit entrypoint with sidebar navigation."""
    st.set_page_config(page_title="Job Automation", page_icon=":bar_chart:", layout="wide")
    page = st.sidebar.radio("Navigation", ["Home", "Run Scanner", "Resumes", "Learn Before Interview",
                                           "Job Tracker"])
    if page == "Home":
        page_home()
    elif page == "Run Scanner":
        page_scanner()
    elif page == "Resumes":
        page_resumes()
    elif page == "Learn Before Interview":
        page_prep()
    else:
        page_tracker()


if __name__ == "__main__":
    main()
