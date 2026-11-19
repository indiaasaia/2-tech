#!/usr/bin/env python3
"""
LinkedIn Easy Apply - Apple Minimalist Command Center & Real-Time Monitor
Candidate: Meetkumar Raval (Cottbus, Germany)
Clean, modern, uncluttered UI built to Apple Human Interface Guidelines.
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(WORKSPACE_DIR, "config.json")
HISTORY_FILE = os.path.join(WORKSPACE_DIR, "history.json")
DAEMON_STATE_FILE = os.path.join(WORKSPACE_DIR, "daemon_state.json")
STATIC_DASHBOARD_FILE = os.path.join(WORKSPACE_DIR, "dashboard.html")

app = Flask(__name__)
CORS(app)


def load_json(filepath: str, default=None):
    if not os.path.exists(filepath):
        return default if default is not None else {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def get_easy_apply_data():
    config = load_json(CONFIG_FILE, {})
    history = load_json(HISTORY_FILE, {})
    daemon_state = load_json(DAEMON_STATE_FILE, {})

    today_str = datetime.now().strftime("%Y-%m-%d")
    applied_today = 0
    all_jobs = []

    for jid, info in list(history.items())[::-1]:
        ts = info.get("timestamp", "")
        status = info.get("status", "")
        if ts.startswith(today_str) and ("Applied" in status or "Verified" in status):
            applied_today += 1

        all_jobs.append({
            "job_id": jid,
            "title": info.get("title", "Unknown Role"),
            "company": info.get("company", "Unknown Company"),
            "status": status,
            "timestamp": ts,
            "url": f"https://www.linkedin.com/jobs/view/{jid}",
        })

    total_applied = sum(1 for v in history.values() if "Applied" in v.get("status", "") or "Verified" in v.get("status", ""))
    total_filtered = sum(1 for v in history.values() if "Filtered" in v.get("status", ""))

    sched_cfg = config.get("scheduler_settings", {})
    ollama_cfg = config.get("ollama_settings", {})
    pipeline_cfg = config.get("ai_pipeline", {})

    daily_target = sched_cfg.get("daily_target", 50)
    batch_size = sched_cfg.get("applications_per_run", 50)
    sprint_gap = pipeline_cfg.get("sprint_gap_seconds", 10)
    min_score = pipeline_cfg.get("min_alignment_score", 7)

    return {
        "candidate_name": f"{config.get('personal_info', {}).get('first_name', 'Meetkumar')} {config.get('personal_info', {}).get('last_name', 'Raval')}",
        "city": config.get("personal_info", {}).get("city", "Cottbus"),
        "country": config.get("personal_info", {}).get("country", "Germany"),
        "status": daemon_state.get("status", "IDLE"),
        "applied_today": applied_today,
        "total_applied": total_applied,
        "total_filtered": total_filtered,
        "total_recorded": len(all_jobs),
        "daily_target": daily_target,
        "batch_size": batch_size,
        "sprint_gap": sprint_gap,
        "min_score": min_score,
        "cycle_count": daemon_state.get("cycle_count", 0),
        "last_cycle_at": daemon_state.get("last_cycle_at", ""),
        "next_run_at": daemon_state.get("next_run_at", ""),
        "ai_engine": {
            "enabled": ollama_cfg.get("enabled", True),
            "model": ollama_cfg.get("model", "gpt-oss:120b"),
            "provider": "Ollama Cloud API"
        },
        "recent_jobs": all_jobs[:150],
    }


APPLE_DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Easy Apply - Command Center</title>
  <style>
    :root {
      --bg: #F5F5F7;
      --card-bg: #FFFFFF;
      --card-border: rgba(0, 0, 0, 0.06);
      --card-shadow: 0 2px 8px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
      --text-primary: #1D1D1F;
      --text-secondary: #86868B;
      --text-tertiary: #A1A1A6;
      --accent: #0071E3;
      --accent-hover: #0077ED;
      --accent-subtle: rgba(0, 113, 227, 0.08);
      --green: #34C759;
      --green-subtle: rgba(52, 199, 89, 0.12);
      --orange: #FF9500;
      --orange-subtle: rgba(255, 149, 0, 0.12);
      --red: #FF3B30;
      --red-subtle: rgba(255, 59, 48, 0.12);
      --gray-subtle: rgba(142, 142, 147, 0.12);
      --divider: rgba(0, 0, 0, 0.06);
      --row-hover: rgba(0, 0, 0, 0.025);
      --seg-bg: rgba(118, 118, 128, 0.08);
      --seg-active: #FFFFFF;
      --input-bg: rgba(118, 118, 128, 0.08);
    }

    [data-theme="dark"] {
      --bg: #000000;
      --card-bg: #1C1C1E;
      --card-border: rgba(255, 255, 255, 0.08);
      --card-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
      --text-primary: #F5F5F7;
      --text-secondary: #8E8E93;
      --text-tertiary: #636366;
      --accent: #0A84FF;
      --accent-hover: #0077ED;
      --accent-subtle: rgba(10, 132, 255, 0.15);
      --green: #30D158;
      --green-subtle: rgba(48, 209, 88, 0.15);
      --orange: #FF9F0A;
      --orange-subtle: rgba(255, 159, 10, 0.15);
      --red: #FF453A;
      --red-subtle: rgba(255, 69, 58, 0.15);
      --gray-subtle: rgba(142, 142, 147, 0.18);
      --divider: rgba(255, 255, 255, 0.08);
      --row-hover: rgba(255, 255, 255, 0.035);
      --seg-bg: rgba(118, 118, 128, 0.24);
      --seg-active: #2C2C2E;
      --input-bg: rgba(118, 118, 128, 0.18);
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
      -webkit-font-smoothing: antialiased;
    }

    body {
      background-color: var(--bg);
      color: var(--text-primary);
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Helvetica Neue", Helvetica, Arial, sans-serif;
      min-height: 100vh;
      padding: 32px 24px;
      transition: background-color 0.3s ease, color 0.3s ease;
    }

    .container {
      max-width: 1180px;
      margin: 0 auto;
    }

    /* Header */
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 28px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .brand-icon {
      width: 38px;
      height: 38px;
      background: var(--text-primary);
      color: var(--card-bg);
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 1.1rem;
      letter-spacing: -0.03em;
    }

    .brand-details h1 {
      font-size: 1.35rem;
      font-weight: 600;
      letter-spacing: -0.02em;
      line-height: 1.2;
    }

    .brand-details p {
      font-size: 0.85rem;
      color: var(--text-secondary);
      font-weight: 400;
      margin-top: 2px;
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 6px 14px;
      border-radius: 980px;
      font-size: 0.82rem;
      font-weight: 500;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      color: var(--text-secondary);
      box-shadow: var(--card-shadow);
    }

    .status-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--green);
    }

    .status-dot.pulse {
      box-shadow: 0 0 0 0 rgba(52, 199, 89, 0.7);
      animation: pulseGreen 2s infinite;
    }

    @keyframes pulseGreen {
      0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(52, 199, 89, 0.7); }
      70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(52, 199, 89, 0); }
      100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(52, 199, 89, 0); }
    }

    .btn-icon {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      border: 1px solid var(--card-border);
      background: var(--card-bg);
      color: var(--text-primary);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: var(--card-shadow);
      transition: transform 0.15s ease, background 0.2s ease;
    }

    .btn-icon:hover {
      transform: scale(1.04);
    }

    .btn-primary {
      background: var(--accent);
      color: #FFFFFF;
      border: none;
      padding: 8px 18px;
      border-radius: 980px;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: background 0.2s ease, transform 0.15s ease;
    }

    .btn-primary:hover {
      background: var(--accent-hover);
      transform: scale(1.02);
    }

    .btn-primary:active {
      transform: scale(0.98);
    }

    /* Metrics Grid */
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 16px;
      margin-bottom: 24px;
    }

    .metric-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 20px 22px;
      box-shadow: var(--card-shadow);
      transition: box-shadow 0.2s ease, border-color 0.2s ease;
    }

    .metric-label {
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-weight: 600;
      color: var(--text-secondary);
      margin-bottom: 8px;
    }

    .metric-value {
      font-size: 1.95rem;
      font-weight: 600;
      letter-spacing: -0.03em;
      color: var(--text-primary);
      line-height: 1.1;
      font-feature-settings: "tnum";
    }

    .metric-sub {
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin-top: 8px;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .progress-track {
      width: 100%;
      height: 4px;
      background: var(--divider);
      border-radius: 2px;
      overflow: hidden;
      margin-top: 12px;
    }

    .progress-fill {
      height: 100%;
      background: var(--accent);
      border-radius: 2px;
      transition: width 0.4s ease;
    }

    .tag-badge {
      display: inline-flex;
      align-items: center;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 0.72rem;
      font-weight: 600;
      background: var(--accent-subtle);
      color: var(--accent);
    }

    /* Main Table Panel */
    .panel {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 18px;
      box-shadow: var(--card-shadow);
      overflow: hidden;
    }

    .panel-header {
      padding: 18px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--divider);
      flex-wrap: wrap;
      gap: 14px;
    }

    .panel-title-area {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .panel-title {
      font-size: 1.05rem;
      font-weight: 600;
      letter-spacing: -0.01em;
    }

    .panel-count {
      font-size: 0.78rem;
      font-weight: 500;
      padding: 2px 8px;
      border-radius: 980px;
      background: var(--seg-bg);
      color: var(--text-secondary);
    }

    .panel-controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    /* Apple Segmented Control */
    .segmented-control {
      display: flex;
      background: var(--seg-bg);
      padding: 3px;
      border-radius: 980px;
      gap: 2px;
    }

    .segment-btn {
      background: transparent;
      border: none;
      padding: 5px 14px;
      font-size: 0.8rem;
      font-weight: 500;
      color: var(--text-secondary);
      border-radius: 980px;
      cursor: pointer;
      transition: all 0.15s ease;
    }

    .segment-btn.active {
      background: var(--seg-active);
      color: var(--text-primary);
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
      font-weight: 600;
    }

    /* Search Box */
    .search-box {
      position: relative;
      display: flex;
      align-items: center;
    }

    .search-input {
      background: var(--input-bg);
      border: 1px solid transparent;
      padding: 6px 12px 6px 32px;
      border-radius: 980px;
      font-size: 0.82rem;
      color: var(--text-primary);
      width: 220px;
      outline: none;
      transition: width 0.2s ease, border-color 0.2s ease, background 0.2s ease;
      font-family: inherit;
    }

    .search-input:focus {
      width: 260px;
      border-color: var(--accent);
      background: var(--card-bg);
    }

    .search-icon {
      position: absolute;
      left: 10px;
      width: 14px;
      height: 14px;
      color: var(--text-tertiary);
      pointer-events: none;
    }

    /* Table */
    .table-responsive {
      overflow-x: auto;
      max-height: 580px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.88rem;
    }

    th {
      padding: 12px 24px;
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-weight: 600;
      color: var(--text-tertiary);
      border-bottom: 1px solid var(--divider);
      position: sticky;
      top: 0;
      background: var(--card-bg);
      z-index: 2;
    }

    td {
      padding: 14px 24px;
      border-bottom: 1px solid var(--divider);
      color: var(--text-primary);
      vertical-align: middle;
    }

    tbody tr {
      transition: background-color 0.1s ease;
    }

    tbody tr:hover {
      background-color: var(--row-hover);
    }

    .job-title {
      font-weight: 600;
      color: var(--text-primary);
      text-decoration: none;
      transition: color 0.15s ease;
      display: inline-block;
      max-width: 440px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .job-title:hover {
      color: var(--accent);
    }

    .company-cell {
      color: var(--text-secondary);
      font-weight: 400;
      max-width: 200px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* Badges */
    .badge {
      display: inline-flex;
      align-items: center;
      padding: 4px 10px;
      border-radius: 980px;
      font-size: 0.75rem;
      font-weight: 500;
      letter-spacing: -0.01em;
      white-space: nowrap;
    }

    .badge-applied {
      background: var(--green-subtle);
      color: var(--green);
    }

    .badge-verified {
      background: var(--accent-subtle);
      color: var(--accent);
    }

    .badge-filtered {
      background: var(--gray-subtle);
      color: var(--text-secondary);
    }

    .badge-failed {
      background: var(--red-subtle);
      color: var(--red);
    }

    .time-cell {
      font-size: 0.8rem;
      color: var(--text-tertiary);
      white-space: nowrap;
      font-feature-settings: "tnum";
    }

    .link-cell {
      text-align: right;
    }

    .btn-link {
      color: var(--text-tertiary);
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border-radius: 6px;
      transition: color 0.15s ease, background 0.15s ease;
    }

    .btn-link:hover {
      color: var(--accent);
      background: var(--accent-subtle);
    }

    /* Toast Notification */
    .toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
      border-radius: 12px;
      padding: 12px 18px;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 0.85rem;
      color: var(--text-primary);
      opacity: 0;
      transform: translateY(10px);
      transition: opacity 0.25s ease, transform 0.25s ease;
      pointer-events: none;
      z-index: 100;
    }

    .toast.show {
      opacity: 1;
      transform: translateY(0);
    }

    /* Responsive */
    @media (max-width: 960px) {
      .metrics-grid {
        grid-template-columns: repeat(2, 1fr);
      }
    }

    @media (max-width: 600px) {
      .metrics-grid {
        grid-template-columns: 1fr;
      }
      header {
        flex-direction: column;
        align-items: flex-start;
        gap: 16px;
      }
      .panel-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 12px;
      }
      .panel-controls {
        width: 100%;
        flex-direction: column;
        align-items: stretch;
      }
      .search-input {
        width: 100%;
      }
      .search-input:focus {
        width: 100%;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <header>
      <div class="brand">
        <div class="brand-icon"></div>
        <div class="brand-details">
          <h1 id="app-title">Easy Apply</h1>
          <p id="candidate-caption">Meetkumar Raval · Cottbus, Germany</p>
        </div>
      </div>
      <div class="header-actions">
        <div class="status-pill">
          <span class="status-dot pulse" id="status-dot"></span>
          <span id="bot-status-text">Active</span>
        </div>
        <button class="btn-icon" id="theme-toggle" title="Toggle appearance">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="5"></circle>
            <line x1="12" y1="1" x2="12" y2="3"></line>
            <line x1="12" y1="21" x2="12" y2="23"></line>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
            <line x1="1" y1="12" x2="3" y2="12"></line>
            <line x1="21" y1="12" x2="23" y2="12"></line>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
          </svg>
        </button>
        <button class="btn-primary" onclick="triggerRunNow()" id="btn-run">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          Run Batch
        </button>
      </div>
    </header>

    <!-- Metrics Grid -->
    <div class="metrics-grid">
      <!-- 1. Daily Progress -->
      <div class="metric-card">
        <div class="metric-label">Applications Today</div>
        <div class="metric-value" id="val-today">0 / 50</div>
        <div class="progress-track">
          <div class="progress-fill" id="progress-today" style="width: 0%;"></div>
        </div>
        <div class="metric-sub" id="sub-today">Daily Safety Goal</div>
      </div>

      <!-- 2. Total Submissions -->
      <div class="metric-card">
        <div class="metric-label">Total Applied</div>
        <div class="metric-value" id="val-total">0</div>
        <div class="metric-sub">
          <span class="tag-badge">Live Submissions</span>
        </div>
      </div>

      <!-- 3. AI Pipeline -->
      <div class="metric-card">
        <div class="metric-label">AI Engine</div>
        <div class="metric-value" style="font-size: 1.45rem;" id="val-ai-model">gpt-oss:120b</div>
        <div class="metric-sub">
          <span>Fit Score > 7 · Tectonic ATS CV</span>
        </div>
      </div>

      <!-- 4. Pacing & Rhythm -->
      <div class="metric-card">
        <div class="metric-label">Pacing & Interval</div>
        <div class="metric-value" style="font-size: 1.45rem;" id="val-pacing">10s Sprint</div>
        <div class="metric-sub" id="val-next-cycle">Continuous loop</div>
      </div>
    </div>

    <!-- Recent Applications Panel -->
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title-area">
          <h2 class="panel-title">Applications</h2>
          <span class="panel-count" id="count-listings">0 listings</span>
        </div>
        <div class="panel-controls">
          <!-- Segmented Filter -->
          <div class="segmented-control">
            <button class="segment-btn active" onclick="setFilter('all', this)">All</button>
            <button class="segment-btn" onclick="setFilter('applied', this)">Applied</button>
            <button class="segment-btn" onclick="setFilter('filtered', this)">Filtered</button>
            <button class="segment-btn" onclick="setFilter('other', this)">Other</button>
          </div>
          <!-- Search -->
          <div class="search-box">
            <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input type="text" class="search-input" id="search-input" placeholder="Search role, company..." oninput="handleSearch()">
          </div>
        </div>
      </div>

      <div class="table-responsive">
        <table>
          <thead>
            <tr>
              <th style="width: 44%;">Role</th>
              <th style="width: 24%;">Company</th>
              <th style="width: 16%;">Status</th>
              <th style="width: 12%;">Recorded</th>
              <th style="width: 4%; text-align: right;"></th>
            </tr>
          </thead>
          <tbody id="table-body">
            <tr>
              <td colspan="5" style="text-align: center; padding: 40px; color: var(--text-tertiary);">
                Loading applications...
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="toast" id="toast">
    <span id="toast-text">Message</span>
  </div>

  <script>
    let currentFilter = 'all';
    let searchQuery = '';
    let cachedJobs = [];

    // Theme Management
    const themeToggle = document.getElementById('theme-toggle');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)');
    
    function applyTheme(isDark) {
      if (isDark) {
        document.documentElement.setAttribute('data-theme', 'dark');
      } else {
        document.documentElement.removeAttribute('data-theme');
      }
      localStorage.setItem('theme', isDark ? 'dark' : 'light');
    }

    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
      applyTheme(savedTheme === 'dark');
    } else {
      applyTheme(prefersDark.matches);
    }

    themeToggle.addEventListener('click', () => {
      const isCurrentlyDark = document.documentElement.getAttribute('data-theme') === 'dark';
      applyTheme(!isCurrentlyDark);
    });

    // Toast
    function showToast(msg) {
      const t = document.getElementById('toast');
      document.getElementById('toast-text').innerText = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 3200);
    }

    // Filter & Search Controls
    function setFilter(filter, btn) {
      currentFilter = filter;
      document.querySelectorAll('.segment-btn').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      renderTable();
    }

    function handleSearch() {
      searchQuery = document.getElementById('search-input').value.toLowerCase().trim();
      renderTable();
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function formatTime(ts) {
      if (!ts) return 'N/A';
      try {
        const parts = ts.split(' ');
        if (parts.length === 2) {
          const date = parts[0];
          const time = parts[1].slice(0, 5);
          const today = new Date().toISOString().slice(0, 10);
          if (date === today) return `Today, ${time}`;
          return `${date.slice(5)}, ${time}`;
        }
      } catch (e) {}
      return ts;
    }

    function renderTable() {
      const tbody = document.getElementById('table-body');
      let filtered = cachedJobs;

      // Filter by segment
      if (currentFilter === 'applied') {
        filtered = filtered.filter(j => j.status.includes('Applied') || j.status.includes('Verified'));
      } else if (currentFilter === 'filtered') {
        filtered = filtered.filter(j => j.status.includes('Filtered'));
      } else if (currentFilter === 'other') {
        filtered = filtered.filter(j => !j.status.includes('Applied') && !j.status.includes('Verified') && !j.status.includes('Filtered'));
      }

      // Filter by search query
      if (searchQuery) {
        filtered = filtered.filter(j => 
          (j.title && j.title.toLowerCase().includes(searchQuery)) ||
          (j.company && j.company.toLowerCase().includes(searchQuery)) ||
          (j.status && j.status.toLowerCase().includes(searchQuery))
        );
      }

      document.getElementById('count-listings').innerText = `${filtered.length} listings`;

      if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding: 48px; color: var(--text-tertiary);">No listings found matching criteria.</td></tr>`;
        return;
      }

      tbody.innerHTML = filtered.map(j => {
        let badgeClass = 'badge-filtered';
        let statusText = j.status || 'Processed';
        
        if (statusText.includes('Applied')) {
          badgeClass = 'badge-applied';
        } else if (statusText.includes('Verified')) {
          badgeClass = 'badge-verified';
        } else if (statusText.includes('Filtered')) {
          badgeClass = 'badge-filtered';
        } else if (statusText.includes('Failed')) {
          badgeClass = 'badge-failed';
        }

        // Clean status text for concise display
        let displayStatus = statusText;
        if (displayStatus.length > 32) {
          displayStatus = displayStatus.slice(0, 30) + '...';
        }

        return `
          <tr>
            <td>
              <a href="${j.url}" target="_blank" class="job-title" title="${escapeHtml(j.title)}">${escapeHtml(j.title)}</a>
            </td>
            <td class="company-cell" title="${escapeHtml(j.company)}">${escapeHtml(j.company)}</td>
            <td>
              <span class="badge ${badgeClass}" title="${escapeHtml(statusText)}">${escapeHtml(displayStatus)}</span>
            </td>
            <td class="time-cell">${escapeHtml(formatTime(j.timestamp))}</td>
            <td class="link-cell">
              <a href="${j.url}" target="_blank" class="btn-link" title="Open job on LinkedIn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                  <polyline points="15 3 21 3 21 9"></polyline>
                  <line x1="10" y1="14" x2="21" y2="3"></line>
                </svg>
              </a>
            </td>
          </tr>
        `;
      }).join('');
    }

    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const json = await res.json();
        const data = json.easy_apply;
        if (!data) return;

        // Update metrics
        const appliedToday = data.applied_today || 0;
        const dailyTarget = data.daily_target || 50;
        document.getElementById('val-today').innerText = `${appliedToday} / ${dailyTarget}`;
        
        const pct = Math.min(100, Math.round((appliedToday / dailyTarget) * 100));
        document.getElementById('progress-today').style.width = `${pct}%`;
        
        document.getElementById('val-total').innerText = String(data.total_applied || 0);

        if (data.ai_engine && data.ai_engine.model) {
          document.getElementById('val-ai-model').innerText = data.ai_engine.model;
        }

        // Status pill
        const status = (data.status || 'IDLE').toUpperCase();
        const botStatusText = document.getElementById('bot-status-text');
        const statusDot = document.getElementById('status-dot');

        if (status === 'APPLYING_JOBS') {
          botStatusText.innerText = 'Applying';
          statusDot.style.background = 'var(--accent)';
          statusDot.className = 'status-dot pulse';
        } else if (status === 'RESTING_DAILY_LIMIT') {
          botStatusText.innerText = 'Goal Reached';
          statusDot.style.background = 'var(--orange)';
          statusDot.className = 'status-dot';
        } else if (status === 'STOPPED') {
          botStatusText.innerText = 'Stopped';
          statusDot.style.background = 'var(--red)';
          statusDot.className = 'status-dot';
        } else {
          botStatusText.innerText = 'Active';
          statusDot.style.background = 'var(--green)';
          statusDot.className = 'status-dot pulse';
        }

        // Update jobs table
        cachedJobs = data.recent_jobs || [];
        renderTable();

      } catch (err) {
        // Silently retry on next tick
      }
    }

    async function triggerRunNow() {
      const btn = document.getElementById('btn-run');
      btn.disabled = true;
      btn.style.opacity = '0.6';
      showToast('Launching LinkedIn Easy Apply batch...');

      try {
        const res = await fetch('/api/trigger', { method: 'POST' });
        const json = await res.json();
        showToast(json.message || 'Batch launched in background.');
      } catch (err) {
        showToast('Error triggering batch: ' + err.message);
      } finally {
        setTimeout(() => {
          btn.disabled = false;
          btn.style.opacity = '1';
        }, 3000);
      }
    }

    // Auto poll every 2.5 seconds
    fetchStatus();
    setInterval(fetchStatus, 2500);
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(APPLE_DASHBOARD_TEMPLATE)


@app.route("/api/status")
def api_status():
    easy = get_easy_apply_data()
    return jsonify({
        "easy_apply": easy,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route("/api/trigger", methods=["POST"])
def api_trigger():
    config = load_json(CONFIG_FILE, {})
    sched_cfg = config.get("scheduler_settings", {})
    apps_limit = sched_cfg.get("applications_per_run", 50)
    python_exe = os.path.join(WORKSPACE_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable
    cmd = f'start "LinkedIn Easy Apply Batch" cmd.exe /c "cd /d {WORKSPACE_DIR} && {python_exe} -u apply_bot.py --limit {apps_limit}"'
    subprocess.Popen(cmd, shell=True)
    return jsonify({"success": True, "message": f"Launched visible Chrome batch: {apps_limit} Job Applications"})


def export_static_html():
    try:
        with open(STATIC_DASHBOARD_FILE, "w", encoding="utf-8") as f:
            f.write(APPLE_DASHBOARD_TEMPLATE)
    except Exception:
        pass


if __name__ == "__main__":
    export_static_html()
    port = 5050
    print("\n" + "=" * 60)
    print("   LinkedIn Easy Apply - Apple Minimalist Dashboard")
    print(f"   Dashboard Live at: http://localhost:{port}")
    print("=" * 60 + "\n")
    app.run(host="127.0.0.1", port=port, debug=False)
