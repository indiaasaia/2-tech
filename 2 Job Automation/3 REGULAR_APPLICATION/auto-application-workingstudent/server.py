"""Apple-Style Interactive Dashboard & Live Pipeline Server.

Provides:
  1. Live pipeline execution with streaming terminal logs
  2. Apple-style minimalist design (deep charcoal/black, frosted glass, zero clutter)
  3. Historical application registry with three explicit tabs:
     - Ready for Application (default status after completing process)
     - Applied (tracked applications with timestamp & undo)
     - Fetched Only (scraped positions before or outside full build)
  4. 1-Click clipboard copy of cover letters, direct PDF views, and instant status updates
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
import uvicorn

MODULE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_ROOT.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

import applied_tracker, config

config.ensure_utf8_stdout()


# ---------------------------------------------------------------------------
# Background Process Manager for Live Pipeline Execution
# ---------------------------------------------------------------------------
class PipelineProcessManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        self.is_running = False
        self.status = "idle"  # idle, running, completed, failed
        self.stage = "Idle"
        self.started_at: float | None = None
        self.logs: list[str] = []
        self._thread: threading.Thread | None = None

    def start(
        self,
        days: float = 1.0,
        pages: int = 6,
        max_jobs: int | None = None,
        skip_fetch: bool = False,
        force: bool = False,
        force_letters: bool = False,
        auto_apply: bool = False,
    ) -> bool:
        with self._lock:
            if self.is_running:
                return False

            self.logs = []
            self.status = "running"
            self.stage = "Initializing"
            self.started_at = time.time()
            self.is_running = True

            cmd = [
                sys.executable,
                "-u",  # unbuffered binary stdout/stderr
                str(MODULE_ROOT / "run.py"),
                "--days", str(days),
                "--pages", str(pages),
            ]
            if max_jobs:
                cmd.extend(["--max-jobs", str(max_jobs)])
            if skip_fetch:
                cmd.append("--skip-fetch")
            if force:
                cmd.append("--force")
            if force_letters:
                cmd.append("--force-letters")
            if auto_apply:
                cmd.append("--auto-apply")

            self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Launching command: {' '.join(cmd)}")

            try:
                self.process = subprocess.Popen(
                    cmd,
                    cwd=str(MODULE_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception as exc:
                self.status = "failed"
                self.stage = f"Launch Error: {exc}"
                self.is_running = False
                self._append_log(f"Failed to spawn process: {exc}")
                return False

            self._thread = threading.Thread(target=self._read_output, daemon=True)
            self._thread.start()
            return True

    def _read_output(self):
        assert self.process is not None
        for line in iter(self.process.stdout.readline, ""):
            clean_line = line.rstrip()
            if clean_line:
                self._append_log(clean_line)
                # Automatically detect stage transitions from output
                if "STAGE 1" in clean_line:
                    self.stage = "1. Fetching workingstudentjobs.de"
                elif "STAGE 2" in clean_line:
                    self.stage = "2. Filtering Recency (Last 24h)"
                elif "STAGE 3" in clean_line:
                    self.stage = "3. Checking Already Applied Status"
                elif "STAGE 4" in clean_line:
                    self.stage = "4. LLM Screening (Role, German <= A2, Tech)"
                elif "STAGE 5" in clean_line:
                    self.stage = "5. JD Analysis & Resume Tailoring"
                elif "STAGE 6" in clean_line:
                    self.stage = "6. LaTeX Compilation & Verification Gates"
                elif "STAGE 7" in clean_line:
                    self.stage = "7. Cover Letter Generation & Gates"
                elif "STAGE 8" in clean_line:
                    self.stage = "8. Building Dashboard"
                elif "STAGE 9" in clean_line:
                    self.stage = "9. Auto Application Staging"

        self.process.stdout.close()
        returncode = self.process.wait()

        with self._lock:
            self.is_running = False
            if returncode == 0:
                self.status = "completed"
                self.stage = "Completed Successfully"
                self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Pipeline execution finished cleanly.")
            else:
                self.status = "failed"
                self.stage = f"Exited with code {returncode}"
                self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Process exited with error code {returncode}")

    def stop(self) -> bool:
        with self._lock:
            if not self.is_running or not self.process:
                return False
            try:
                self.process.terminate()
                self._append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Termination signal sent.")
                self.status = "failed"
                self.stage = "Stopped by user"
                self.is_running = False
                return True
            except Exception as exc:
                self._append_log(f"Error terminating process: {exc}")
                return False

    def _append_log(self, line: str):
        self.logs.append(line)
        if len(self.logs) > 8000:
            self.logs = self.logs[-6000:]

    def get_state(self, offset: int = 0) -> dict[str, Any]:
        uptime = 0
        if self.started_at:
            uptime = int(time.time() - self.started_at)
        return {
            "status": self.status,
            "stage": self.stage,
            "is_running": self.is_running,
            "uptime_seconds": uptime,
            "offset": len(self.logs),
            "logs": self.logs[offset:],
        }


runner = PipelineProcessManager()

# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------
app = FastAPI(title="Working Student Job Applications Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
def get_status():
    return {
        "status": runner.status,
        "stage": runner.stage,
        "is_running": runner.is_running,
        "uptime_seconds": int(time.time() - runner.started_at) if runner.started_at else 0,
    }


@app.get("/api/logs")
def get_logs(offset: int = 0):
    return runner.get_state(offset=offset)


@app.post("/api/run")
def trigger_run(payload: dict[str, Any] = Body(default={})):
    days = float(payload.get("days", 1.0))
    pages = int(payload.get("pages", 6))
    max_jobs = payload.get("max_jobs")
    max_jobs = int(max_jobs) if max_jobs else None
    skip_fetch = bool(payload.get("skip_fetch", False))
    force = bool(payload.get("force", False))
    auto_apply = bool(payload.get("auto_apply", False))

    started = runner.start(
        days=days,
        pages=pages,
        max_jobs=max_jobs,
        skip_fetch=skip_fetch,
        force=force,
        auto_apply=auto_apply,
    )
    if not started:
        raise HTTPException(status_code=400, detail="Pipeline is already running.")
    return {"ok": True, "message": "Pipeline started"}


@app.post("/api/stop")
def trigger_stop():
    stopped = runner.stop()
    return {"ok": stopped, "message": "Pipeline stopped" if stopped else "No pipeline currently running"}


@app.get("/api/jobs")
def get_jobs():
    return applied_tracker.get_categorized_jobs()


@app.post("/api/jobs/status")
def update_job_status(payload: dict[str, Any] = Body(...)):
    url = str(payload.get("job_url", "")).strip()
    status = str(payload.get("status", "")).strip()
    notes = str(payload.get("notes", "")).strip()
    method = str(payload.get("method", "manual")).strip()

    if not url:
        raise HTTPException(status_code=400, detail="Missing job_url")
    if status not in applied_tracker.VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if status == applied_tracker.STATUS_APPLIED:
        rec = applied_tracker.mark_applied(
            job_url=url,
            company=payload.get("company", ""),
            title=payload.get("title", ""),
            location=payload.get("location", ""),
            method=method,
            notes=notes,
        )
    elif status == applied_tracker.STATUS_READY_TO_APPLY:
        rec = applied_tracker.mark_ready(
            job_url=url,
            company=payload.get("company", ""),
            title=payload.get("title", ""),
            location=payload.get("location", ""),
            notes=notes,
            force=True,
        )
    else:
        applied_tracker.mark_status(url, status, notes=notes)
        rec = applied_tracker.get_job_record(url) or {}

    return {"ok": True, "record": rec}


@app.get("/files/{file_path:path}")
def serve_file(file_path: str):
    """Safely serve generated PDFs, DOCX, text cover letters, and certificates."""
    clean_p = Path(file_path.replace("\\", "/"))
    # Check within project root
    target = (PROJECT_ROOT / clean_p).resolve()

    # Prevent directory traversal outside PROJECT_ROOT
    if not str(target).startswith(str(PROJECT_ROOT)):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "application/octet-stream"
    if target.suffix.lower() == ".pdf":
        media_type = "application/pdf"
    elif target.suffix.lower() == ".txt":
        media_type = "text/plain; charset=utf-8"
    elif target.suffix.lower() == ".docx":
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return FileResponse(target, media_type=media_type, filename=target.name)


# ---------------------------------------------------------------------------
# Minimalist Apple-Style Single Page Application UI
# ---------------------------------------------------------------------------
HTML_UI = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Applications &bull; Working Student Jobs</title>
<style>
:root {
  --bg-canvas: #000000;
  --bg-elevated: #161618;
  --bg-card: #1c1c1e;
  --bg-card-hover: #242426;
  --border-subtle: rgba(255, 255, 255, 0.08);
  --border-active: rgba(255, 255, 255, 0.2);
  --text-primary: #f5f5f7;
  --text-secondary: #86868b;
  --text-muted: #6e6e73;
  --apple-blue: #0071e3;
  --apple-blue-hover: #0077ed;
  --apple-green: #30d158;
  --apple-amber: #ffd60a;
  --apple-red: #ff453a;
  --apple-purple: #bf5af2;
  --font-system: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Segoe UI", Roboto, Helvetica, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; font-family: var(--font-system); }
body { background: var(--bg-canvas); color: var(--text-primary); -webkit-font-smoothing: antialiased; line-height: 1.45; }

/* Sticky Glass Topbar */
.nav-bar {
  position: sticky; top: 0; z-index: 100;
  background: rgba(18, 18, 20, 0.8);
  backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px);
  border-bottom: 1px solid var(--border-subtle);
  padding: 14px 28px; display: flex; justify-content: space-between; align-items: center;
}
.brand-group { display: flex; align-items: center; gap: 12px; }
.brand-title { font-size: 1.05rem; font-weight: 600; color: #fff; letter-spacing: -0.2px; }
.badge-source { font-size: 0.72rem; color: var(--apple-blue); background: rgba(0, 113, 227, 0.12); padding: 3px 8px; border-radius: 6px; font-weight: 500; }

.status-indicator {
  display: flex; align-items: center; gap: 8px;
  background: rgba(255, 255, 255, 0.05); padding: 5px 12px; border-radius: 20px;
  font-size: 0.8rem; font-weight: 500; color: var(--text-secondary);
}
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #6e6e73; }
.status-dot.active { background: var(--apple-green); box-shadow: 0 0 10px var(--apple-green); animation: pulse 2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

/* Main Container */
.main-wrap { max-width: 1180px; margin: 0 auto; padding: 24px 20px 80px 20px; }

/* Pipeline Control Strip */
.control-panel {
  background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: 14px;
  padding: 16px 20px; margin-bottom: 24px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px;
}
.control-group { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.btn-toggle-grp { display: inline-flex; background: rgba(255, 255, 255, 0.06); padding: 3px; border-radius: 8px; }
.btn-toggle-item {
  border: none; background: transparent; color: var(--text-secondary); font-size: 0.8rem; font-weight: 500;
  padding: 5px 12px; border-radius: 6px; cursor: pointer; transition: all 0.15s ease;
}
.btn-toggle-item.selected { background: var(--bg-card); color: #fff; box-shadow: 0 2px 6px rgba(0,0,0,0.4); }

.chk-label { display: flex; align-items: center; gap: 6px; font-size: 0.82rem; color: var(--text-secondary); cursor: pointer; }
.chk-label input { accent-color: var(--apple-blue); }

.action-buttons { display: flex; gap: 10px; }
.btn-apple {
  background: var(--apple-blue); color: #fff; border: none; padding: 7px 18px; border-radius: 8px;
  font-size: 0.85rem; font-weight: 600; cursor: pointer; transition: background 0.15s ease;
  display: inline-flex; align-items: center; gap: 6px;
}
.btn-apple:hover { background: var(--apple-blue-hover); }
.btn-apple.btn-stop { background: var(--apple-red); }
.btn-secondary {
  background: rgba(255, 255, 255, 0.08); color: var(--text-primary); border: 1px solid var(--border-subtle);
  padding: 7px 14px; border-radius: 8px; font-size: 0.85rem; font-weight: 500; cursor: pointer;
}
.btn-secondary:hover { background: rgba(255, 255, 255, 0.12); }

/* Collapsible Live Terminal */
.terminal-card {
  background: #09090b; border: 1px solid var(--border-subtle); border-radius: 12px;
  margin-bottom: 28px; overflow: hidden; display: none;
}
.terminal-card.visible { display: block; }
.terminal-header {
  padding: 10px 16px; background: #121214; border-bottom: 1px solid var(--border-subtle);
  display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem; color: var(--text-muted);
}
.terminal-body {
  padding: 14px 16px; font-family: var(--font-mono); font-size: 0.78rem; line-height: 1.55;
  color: #d1d5db; max-height: 280px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;
}

/* Tabs: Apple Segmented Control */
.tab-container {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; flex-wrap: wrap; gap: 12px;
}
.segmented-control {
  display: inline-flex; background: rgba(255, 255, 255, 0.06); padding: 4px; border-radius: 10px;
}
.seg-btn {
  border: none; background: transparent; color: var(--text-secondary); font-size: 0.85rem; font-weight: 500;
  padding: 7px 18px; border-radius: 8px; cursor: pointer; transition: all 0.15s ease; display: inline-flex; align-items: center; gap: 8px;
}
.seg-btn.active { background: #2c2c2e; color: #fff; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5); }
.seg-count {
  font-size: 0.72rem; padding: 2px 7px; border-radius: 12px; background: rgba(255, 255, 255, 0.1); color: #fff;
}
.seg-btn.active .seg-count { background: var(--apple-blue); }

.search-box {
  background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 8px;
  padding: 7px 14px; color: #fff; font-size: 0.82rem; outline: none; width: 220px; transition: border-color 0.15s ease;
}
.search-box:focus { border-color: var(--apple-blue); }

/* Job Cards Grid */
.job-list { display: grid; gap: 12px; }
.job-item {
  background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 12px;
  padding: 18px 20px; transition: border-color 0.15s ease, background 0.15s ease;
}
.job-item:hover { border-color: var(--border-active); background: var(--bg-card-hover); }

.job-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 8px; }
.job-heading { flex: 1; }
.job-title { font-size: 1.05rem; font-weight: 600; color: #fff; text-decoration: none; letter-spacing: -0.2px; }
.job-title:hover { color: var(--apple-blue); }
.job-company { color: var(--apple-blue); font-size: 0.88rem; font-weight: 600; margin-top: 2px; }

.pill { font-size: 0.72rem; font-weight: 600; padding: 4px 10px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.4px; }
.pill-ready { background: rgba(48, 209, 88, 0.15); color: var(--apple-green); border: 1px solid rgba(48, 209, 88, 0.3); }
.pill-applied { background: rgba(0, 113, 227, 0.15); color: var(--apple-blue); border: 1px solid rgba(0, 113, 227, 0.3); }
.pill-fetched { background: rgba(255, 214, 10, 0.15); color: var(--apple-amber); border: 1px solid rgba(255, 214, 10, 0.3); }

.job-meta { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 14px 0; font-size: 0.78rem; }
.meta-tag { background: rgba(255, 255, 255, 0.05); color: var(--text-secondary); padding: 3px 8px; border-radius: 6px; }

.job-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; border-top: 1px solid rgba(255, 255, 255, 0.06); padding-top: 12px; }
.act-btn {
  background: rgba(255, 255, 255, 0.06); color: var(--text-primary); border: 1px solid var(--border-subtle);
  padding: 5px 12px; border-radius: 6px; font-size: 0.8rem; font-weight: 500; text-decoration: none; cursor: pointer;
  display: inline-flex; align-items: center; gap: 5px; transition: background 0.15s ease;
}
.act-btn:hover { background: rgba(255, 255, 255, 0.12); }
.act-btn-applied { background: rgba(48, 209, 88, 0.12); color: #34d399; border-color: rgba(48, 209, 88, 0.3); }
.act-btn-applied:hover { background: rgba(48, 209, 88, 0.22); }
.act-btn-revert { color: var(--text-muted); }
.act-btn-revert:hover { color: #fff; }

.empty-state { text-align: center; padding: 60px 20px; color: var(--text-muted); font-size: 0.95rem; }

/* Toast */
.toast {
  position: fixed; bottom: 28px; right: 28px; z-index: 999;
  background: #1c1c1e; border: 1px solid var(--apple-blue); color: #fff;
  padding: 10px 18px; border-radius: 10px; font-size: 0.85rem; font-weight: 500;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5); opacity: 0; pointer-events: none; transition: opacity 0.2s ease;
}
</style>
</head>
<body>

<div class="nav-bar">
  <div class="brand-group">
    <div class="brand-title">Working Student Applications</div>
    <div class="badge-source">workingstudentjobs.de</div>
  </div>
  <div class="status-indicator">
    <div id="statusDot" class="status-dot"></div>
    <span id="statusText">Idle</span>
  </div>
</div>

<div class="main-wrap">

  <!-- Control Strip -->
  <div class="control-panel">
    <div class="control-group">
      <div class="btn-toggle-grp">
        <button class="btn-toggle-item selected" onclick="setDays(1, this)">24 Hours</button>
        <button class="btn-toggle-item" onclick="setDays(2, this)">48 Hours</button>
        <button class="btn-toggle-item" onclick="setDays(3, this)">3 Days</button>
      </div>

      <label class="chk-label">
        <input type="checkbox" id="chkSkipFetch"/> Reuse Scraped Data
      </label>
      <label class="chk-label">
        <input type="checkbox" id="chkAutoApply"/> Live Auto-Apply
      </label>
    </div>

    <div class="action-buttons">
      <button id="btnRun" class="btn-apple" onclick="toggleRun()">
        <span>&#9654;</span> Run Program
      </button>
      <button class="btn-secondary" onclick="toggleTerminal()">Terminal Logs</button>
    </div>
  </div>

  <!-- Terminal Live Viewer -->
  <div id="terminalCard" class="terminal-card">
    <div class="terminal-header">
      <div><span id="termStage">Idle</span> &bull; <span id="termElapsed">0s</span></div>
      <div style="display:flex; gap:10px;">
        <label style="cursor:pointer;"><input type="checkbox" id="chkAutoScroll" checked/> Auto-scroll</label>
        <span style="cursor:pointer;" onclick="clearLogs()">Clear</span>
      </div>
    </div>
    <div id="terminalBody" class="terminal-body">Waiting for pipeline run...</div>
  </div>

  <!-- Segmented Tabs -->
  <div class="tab-container">
    <div class="segmented-control">
      <button id="tabReady" class="seg-btn active" onclick="switchTab('ready')">
        Ready for Application <span id="countReady" class="seg-count">0</span>
      </button>
      <button id="tabApplied" class="seg-btn" onclick="switchTab('applied')">
        Applied <span id="countApplied" class="seg-count">0</span>
      </button>
      <button id="tabFetched" class="seg-btn" onclick="switchTab('fetched')">
        Fetched Only <span id="countFetched" class="seg-count">0</span>
      </button>
    </div>
    <div>
      <input type="text" id="searchBox" class="search-box" placeholder="Search company or title..." oninput="filterJobs()"/>
    </div>
  </div>

  <!-- Cards List -->
  <div id="jobList" class="job-list"></div>

</div>

<div id="toast" class="toast">Cover letter copied to clipboard!</div>

<script>
let activeTab = 'ready';
let selectedDays = 1.0;
let isPipelineRunning = false;
let logOffset = 0;
let cachedData = { ready_for_application: [], applied: [], fetched_only: [] };

function setDays(days, btn) {
  selectedDays = days;
  document.querySelectorAll('.btn-toggle-item').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
}

function switchTab(tab) {
  activeTab = tab;
  document.getElementById('tabReady').classList.toggle('active', tab === 'ready');
  document.getElementById('tabApplied').classList.toggle('active', tab === 'applied');
  document.getElementById('tabFetched').classList.toggle('active', tab === 'fetched');
  renderJobs();
}

function toggleTerminal() {
  const card = document.getElementById('terminalCard');
  card.classList.toggle('visible');
}

function clearLogs() {
  document.getElementById('terminalBody').innerText = '';
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.innerText = msg;
  t.style.opacity = '1';
  setTimeout(() => { t.style.opacity = '0'; }, 2200);
}

function copyLetterText(text) {
  if (!text) {
    showToast('No plain-text cover letter available.');
    return;
  }
  navigator.clipboard.writeText(text).then(() => {
    showToast('Cover letter copied to clipboard!');
  });
}

async function markStatus(url, status, company='', title='') {
  try {
    const res = await fetch('/api/jobs/status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_url: url, status: status, company: company, title: title })
    });
    if (res.ok) {
      showToast(status === 'applied' ? 'Marked as APPLIED' : 'Moved to READY FOR APPLICATION');
      fetchJobs();
    }
  } catch (err) {
    console.error(err);
  }
}

async function toggleRun() {
  if (isPipelineRunning) {
    // Stop
    await fetch('/api/stop', { method: 'POST' });
    return;
  }
  // Start
  const skip = document.getElementById('chkSkipFetch').checked;
  const auto = document.getElementById('chkAutoApply').checked;
  document.getElementById('terminalCard').classList.add('visible');
  document.getElementById('terminalBody').innerText = 'Starting pipeline...\\n';
  logOffset = 0;

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        days: selectedDays,
        pages: 6,
        skip_fetch: skip,
        auto_apply: auto
      })
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || 'Could not start pipeline');
    }
  } catch (err) {
    console.error(err);
  }
}

async function pollStatusAndLogs() {
  try {
    const res = await fetch(`/api/logs?offset=${logOffset}`);
    if (res.ok) {
      const data = await res.json();
      isPipelineRunning = data.is_running;

      // Update Header
      const dot = document.getElementById('statusDot');
      const txt = document.getElementById('statusText');
      const btn = document.getElementById('btnRun');

      if (data.is_running) {
        dot.classList.add('active');
        txt.innerText = data.stage;
        btn.innerHTML = '&#9632; Stop Program';
        btn.classList.add('btn-stop');
      } else {
        dot.classList.remove('active');
        txt.innerText = data.status === 'completed' ? 'Completed' : (data.status === 'failed' ? 'Failed' : 'Idle');
        btn.innerHTML = '&#9654; Run Program';
        btn.classList.remove('btn-stop');
      }

      document.getElementById('termStage').innerText = data.stage;
      document.getElementById('termElapsed').innerText = `${data.uptime_seconds}s`;

      // Append logs
      if (data.logs && data.logs.length > 0) {
        const body = document.getElementById('terminalBody');
        body.innerText += data.logs.join('\\n') + '\\n';
        logOffset = data.offset;
        if (document.getElementById('chkAutoScroll').checked) {
          body.scrollTop = body.scrollHeight;
        }
      }
    }
  } catch (e) {
    console.error(e);
  }
}

async function fetchJobs() {
  try {
    const res = await fetch('/api/jobs');
    if (res.ok) {
      cachedData = await res.json();
      document.getElementById('countReady').innerText = cachedData.counts.ready_for_application;
      document.getElementById('countApplied').innerText = cachedData.counts.applied;
      document.getElementById('countFetched').innerText = cachedData.counts.fetched_only;
      renderJobs();
    }
  } catch (err) {
    console.error(err);
  }
}

function filterJobs() {
  renderJobs();
}

function renderJobs() {
  const container = document.getElementById('jobList');
  const query = document.getElementById('searchBox').value.trim().toLowerCase();

  let list = [];
  if (activeTab === 'ready') list = cachedData.ready_for_application || [];
  else if (activeTab === 'applied') list = cachedData.applied || [];
  else list = cachedData.fetched_only || [];

  if (query) {
    list = list.filter(j => 
      (j.title && j.title.toLowerCase().includes(query)) ||
      (j.company && j.company.toLowerCase().includes(query)) ||
      (j.location && j.location.toLowerCase().includes(query))
    );
  }

  if (list.length === 0) {
    container.innerHTML = `<div class="empty-state">No jobs found in this category.</div>`;
    return;
  }

  container.innerHTML = list.map((item, idx) => {
    const cleanUrl = item.job_url || '#';
    const company = item.company || 'Company';
    const title = item.title || 'Role';
    const loc = item.location || 'Germany';
    const roleType = (item.role_type || 'working_student').replace('_', ' ');
    const domain = item.tech_domain || 'Tech';
    const german = item.german_req === 'none' ? 'No German Req' : (item.german_req === 'nice_to_have' ? 'German Optional' : item.german_req);

    // Pill
    let pillHtml = '';
    if (activeTab === 'ready') pillHtml = `<span class="pill pill-ready">Ready to Apply</span>`;
    else if (activeTab === 'applied') pillHtml = `<span class="pill pill-applied">Applied</span>`;
    else pillHtml = `<span class="pill pill-fetched">Fetched</span>`;

    // Action buttons
    let actionButtons = '';
    if (activeTab === 'ready') {
      const resLink = item.resume_path ? `<a class="act-btn" href="/files/${item.resume_path}" target="_blank">&darr; Resume PDF</a>` : '';
      const letLink = item.cover_letter_path ? `<a class="act-btn" href="/files/${item.cover_letter_path}" target="_blank">&darr; Cover Letter PDF</a>` : '';
      const copyBtn = item.cover_letter_text ? `<button class="act-btn" onclick="copyLetterText(decodeURIComponent('${encodeURIComponent(item.cover_letter_text)}'))">&#128203; Copy Letter</button>` : '';
      const markBtn = `<button class="act-btn act-btn-applied" onclick="markStatus('${item.job_url}', 'applied', '${company.replace(/'/g, "")}', '${title.replace(/'/g, "")}')">&#10003; Mark as Applied</button>`;
      actionButtons = `
        <a class="act-btn" href="${cleanUrl}" target="_blank">&rarr; Job Portal</a>
        ${resLink}
        ${letLink}
        ${copyBtn}
        ${markBtn}
      `;
    } else if (activeTab === 'applied') {
      const resLink = item.resume_path ? `<a class="act-btn" href="/files/${item.resume_path}" target="_blank">&darr; Resume PDF</a>` : '';
      const letLink = item.cover_letter_path ? `<a class="act-btn" href="/files/${item.cover_letter_path}" target="_blank">&darr; Cover Letter PDF</a>` : '';
      const copyBtn = item.cover_letter_text ? `<button class="act-btn" onclick="copyLetterText(decodeURIComponent('${encodeURIComponent(item.cover_letter_text)}'))">&#128203; Copy Letter</button>` : '';
      const revertBtn = `<button class="act-btn act-btn-revert" onclick="markStatus('${item.job_url}', 'ready_to_apply')">&#8634; Revert to Ready</button>`;
      actionButtons = `
        <a class="act-btn" href="${cleanUrl}" target="_blank">&rarr; View Ad</a>
        ${resLink}
        ${letLink}
        ${copyBtn}
        ${revertBtn}
      `;
    } else {
      actionButtons = `
        <a class="act-btn" href="${cleanUrl}" target="_blank">&rarr; View Job Ad</a>
        <button class="act-btn" onclick="markStatus('${item.job_url}', 'ready_to_apply', '${company.replace(/'/g, "")}', '${title.replace(/'/g, "")}')">+ Move to Ready</button>
      `;
    }

    return `
      <div class="job-item">
        <div class="job-top">
          <div class="job-heading">
            <a class="job-title" href="${cleanUrl}" target="_blank">${title}</a>
            <div class="job-company">${company}</div>
          </div>
          <div>${pillHtml}</div>
        </div>
        <div class="job-meta">
          <span class="meta-tag">&#128205; ${loc}</span>
          <span class="meta-tag">&#128188; ${roleType}</span>
          <span class="meta-tag">&#9881; ${domain}</span>
          <span class="meta-tag">&#127760; ${german}</span>
          ${item.applied_at ? `<span class="meta-tag">&#128340; Applied: ${item.applied_at.slice(0,10)}</span>` : ''}
          ${item.notes ? `<span class="meta-tag" style="color:var(--apple-amber);">&#8505; ${item.notes}</span>` : ''}
        </div>
        <div class="job-actions">
          ${actionButtons}
        </div>
      </div>
    `;
  }).join('');
}

// Initial boot
fetchJobs();
setInterval(pollStatusAndLogs, 1000);
// Refresh jobs every 10 seconds if running
setInterval(() => { if (isPipelineRunning) fetchJobs(); }, 8000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=HTML_UI, status_code=200)


def _find_free_port(start_port: int = 8080, host: str = "127.0.0.1") -> int:
    import socket
    for port in range(start_port, start_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return start_port


def main():
    parser = argparse.ArgumentParser(description="Start Working Student Dashboard Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port (default: automatic free port starting at 8080)")
    args = parser.parse_args()

    port = args.port or _find_free_port(8080, args.host)
    print("=" * 60)
    print(f"Working Student Live Dashboard: http://{args.host}:{port}")
    print("=" * 60)
    uvicorn.run(app, host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
