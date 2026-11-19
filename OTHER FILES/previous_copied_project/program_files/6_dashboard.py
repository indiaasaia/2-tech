"""Streamlit dashboard for the job automation pipeline.

Pages:
  Home         - what the system does and where the data stands
  Run Scanner  - runs the full pipeline (scrape, filter, key test, LLM components,
                 resume building) with per-stage progress and a live log;
                 every newly scanned job is added to the tracker as Pending
  Resumes      - browse every generated resume next to its matching job,
                 with download buttons for the PDF/DOCX and a link to the posting
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
    ("Scraping job boards (Stepstone + workingstudentjobs.de)", "program_files/1_fetch_jobs.py"),
    ("Filtering fresh postings and saving the job list", "program_files/2_filter_jobs.py"),
    ("Testing Ollama API keys", "program_files/3_test_ollama_keys.py"),
    ("Generating ATS resume components: objective, experience, projects, skills (LLM)", "program_files/4_create_resume_components.py"),
    ("Building PDF and DOCX resumes", "program_files/5_create_resume.py"),
]

STATUS_OPTIONS = ["Pending", "Applied", "Not Interested"]
STATUS_COLORS = {"Applied": "#d4edda", "Not Interested": "#fff3cd", "Pending": "#f8d7da"}
RESUME_REPORT = OUTPUT_DIR / "resume_report.json"


def load_resume_report() -> list[dict]:
    """Read resume_report.json and return its per-job results (empty on any problem)."""
    if not RESUME_REPORT.exists():
        return []
    try:
        payload = json.loads(RESUME_REPORT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return list(payload.get("results") or [])


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

    failed = [r for r in results if r.get("error")]
    if failed:
        st.warning(f"{len(failed)} resume(s) failed to build (marked below).")

    ok_count = len(results) - len(failed)
    st.caption(f"{ok_count} resume(s) ready - newest run. Download the PDF or DOCX, or open the posting.")

    search = st.text_input("Search by title or company", "").strip().lower()
    shown = 0
    for index, result in enumerate(results):
        title = clean(result.get("title")) or "(untitled)"
        info = meta.get(str(result.get("job_url") or ""), {})
        company = info.get("company", "")
        location = info.get("location", "")
        if search and search not in title.lower() and search not in company.lower():
            continue
        shown += 1
        error = clean(result.get("error"))
        color = STATUS_COLORS.get(status.get(str(result.get("job_url") or ""), ""), "#e8eaf6") if not error else "#f8d7da"
        with st.container(border=True):
            left, right = st.columns([7, 3])
            with left:
                meta_line = " - ".join(part for part in (company, location) if part)
                st.markdown(
                    f"<div style='background:{color};padding:8px 12px;border-radius:6px'>"
                    f"<b>{title}</b>"
                    + (f"<br><small>{meta_line}</small>" if meta_line else "")
                    + (f"<br><small><b>build error:</b> {error}</small>" if error else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )
                if result.get("job_url"):
                    st.markdown(f"[Open job posting]({result['job_url']})")
            with right:
                pdf_path = Path(str(result.get("pdf") or ""))
                docx_path = Path(str(result.get("docx") or ""))
                if not error and pdf_path.exists():
                    st.download_button(
                        "Download PDF",
                        data=pdf_path.read_bytes(),
                        file_name=pdf_path.name,
                        mime="application/pdf",
                        key=f"pdf-{index}",
                        use_container_width=True,
                    )
                if not error and docx_path.exists():
                    st.download_button(
                        "Download DOCX",
                        data=docx_path.read_bytes(),
                        file_name=docx_path.name,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"docx-{index}",
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
    """Record counts from the four component stores."""
    mapping = (("career_objective.json", "objectives"), ("experience.json", "experiences"),
               ("projects.json", "projects"), ("skills.json", "skills"))
    counts: dict[str, int] = {}
    for file_name, key in mapping:
        path = OUTPUT_DIR / file_name
        if path.exists():
            try:
                counts[file_name] = len(json.loads(path.read_text(encoding="utf-8")).get(key, []))
            except Exception:  # noqa: BLE001
                counts[file_name] = 0
        else:
            counts[file_name] = 0
    return counts


def count_resumes() -> tuple[int, int]:
    """(pdf, docx) counts in the resume output folders."""
    pdf_dir = OUTPUT_DIR / "resume" / "pdf"
    docx_dir = OUTPUT_DIR / "resume" / "docx"
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
    """Run every scanner stage in the background thread, publishing progress to the state file."""
    # Step 2 keeps only jobs posted yesterday or today; no look-back configuration needed.

    scan_write(running=True, stage="starting", success=None, message="", new_jobs=0, pid=os.getpid())
    log_lines: list[str] = ["look-back window: jobs posted yesterday or today (calendar dates)"]
    try:
        log_handle = SCANNER_LOG.open("w", encoding="utf-8")
    except OSError as exc:
        scan_write(running=False, success=False, message=f"cannot open log file: {exc}")
        return

    all_ok = True
    try:
        for stage_index, (label, script) in enumerate(SCANNER_STAGES, 1):
            scan_write(stage=f"stage {stage_index}/{len(SCANNER_STAGES)}: {label}")
            log_lines.append(f"\n=== {label} ===")
            ok = run_command([sys.executable, script], log_lines, log_handle)
            log_lines.append(f"=== {label}: {'OK' if ok else 'FAILED'} ===")
            log_handle.write("\n".join(log_lines[-400:]), encoding="utf-8")
            all_ok = all_ok and ok

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

    st.subheader("Component stores (LLM-generated, per job)")
    st.table(pd.DataFrame(
        [(name, count) for name, count in counts.items()],
        columns=["store", "records"],
    ).set_index("store"))

    st.subheader("How the pipeline works")
    st.markdown(
        """
        1. **Fetch** - scrape Stepstone and workingstudentjobs.de
        2. **Filter** - keep postings from the last few days
        3. **Keys** - test the Ollama API keys
        4. **Components** - career objective, experience, projects, skills (gpt-oss:120b)
        5. **Resumes** - fill the LaTeX template, compile the PDF, build the DOCX
        6. **Tracker** - mark each job Applied / Not Interested / Pending
        """
    )
    st.info("Open **Run Scanner** to fetch fresh jobs and rebuild all resumes. "
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


def main() -> None:
    """Streamlit entrypoint with sidebar navigation."""
    st.set_page_config(page_title="Job Automation", page_icon=":bar_chart:", layout="wide")
    page = st.sidebar.radio("Navigation", ["Home", "Run Scanner", "Resumes", "Job Tracker"])
    if page == "Home":
        page_home()
    elif page == "Run Scanner":
        page_scanner()
    elif page == "Resumes":
        page_resumes()
    else:
        page_tracker()


if __name__ == "__main__":
    main()
