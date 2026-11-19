#!/usr/bin/env python3
"""
LinkedIn Easy Apply — 100% Dedicated Autonomous Application System
Powered by:
  - Undetected Chrome Engine with Human-Like Typing & Anti-Detection
  - Ollama Cloud AI Assistant (gpt-oss:120b) for Dynamic Application Questions
  - 24/7 Continuous Micro-Loop: 3 Jobs per cycle -> 5-Minute Safety Rest
  - Safety Daily Ceiling: Max 50 applications/day
  - Local Web Dashboard at http://localhost:5050

Candidate: Meetkumar Raval
Location: Cottbus, Germany
"""

import os
import sys
import json
import time
import signal
import logging
import threading
import subprocess
import webbrowser
from datetime import datetime, timedelta

# Enable UTF-8 console output for Windows cmd/powershell
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Optional colorama for clean terminal output
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    G = Fore.GREEN + Style.BRIGHT
    C = Fore.CYAN + Style.BRIGHT
    Y = Fore.YELLOW + Style.BRIGHT
    R = Fore.RED + Style.BRIGHT
    W = Fore.WHITE + Style.BRIGHT
    M = Fore.MAGENTA + Style.BRIGHT
    D = Style.RESET_ALL
except Exception:
    G = C = Y = R = W = M = D = ""

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(WORKSPACE_DIR, "config.json")
HISTORY_FILE = os.path.join(WORKSPACE_DIR, "history.json")
DAEMON_STATE_FILE = os.path.join(WORKSPACE_DIR, "daemon_state.json")

# Global stop flag for graceful Ctrl+C handling
running = True


def signal_handler(sig, frame):
    global running
    print(f"\n\n{Y}[*] Stopping LinkedIn Easy Apply Runner cleanly...{D}")
    running = False
    update_state(status="STOPPED")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_applied_today() -> int:
    today_str = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                hist = json.load(f)
                return sum(
                    1 for v in hist.values()
                    if "Applied" in v.get("status", "") and v.get("timestamp", "").startswith(today_str)
                )
        except Exception:
            pass
    return 0


def update_state(status="IDLE", next_target=None, cycle_count=0):
    applied_today = get_applied_today()
    state = {
        "status": status,
        "last_cycle_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "next_run_at": next_target.strftime("%Y-%m-%d %H:%M:%S") if next_target else "",
        "schedule": "Continuous Sprint Loop: Tailored LaTeX CV (10s pacing)",
        "loop_mode": "CONTINUOUS_SPRINT_LOOP",
        "apps_per_run": 50,
        "applied_today": applied_today,
        "daily_target": 50,
        "cycle_count": cycle_count,
        "heartbeat_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if os.path.exists(DAEMON_STATE_FILE):
        try:
            with open(DAEMON_STATE_FILE, "r", encoding="utf-8") as f:
                state.update(json.load(f))
        except Exception:
            pass

    state["status"] = status
    state["applied_today"] = applied_today
    state["heartbeat_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if next_target:
        state["next_run_at"] = next_target.strftime("%Y-%m-%d %H:%M:%S")
    if cycle_count > 0:
        state["cycle_count"] = cycle_count

    try:
        with open(DAEMON_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def run_cycle_easy_apply(limit=3, max_retries=3, retry_delay=10):
    python_exe = os.path.join(WORKSPACE_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable

    apply_script = os.path.join(WORKSPACE_DIR, "apply_bot.py")

    for attempt in range(1, max_retries + 1):
        print(f"{C}[*] Applying to up to {limit} jobs (Attempt {attempt}/{max_retries})...{D}", flush=True)
        try:
            res = subprocess.run([python_exe, "-u", apply_script, "--limit", str(limit)], check=False)
            if res.returncode == 0:
                print(f"{G}[+] Batch processed successfully!{D}", flush=True)
                return True
            else:
                print(f"{Y}[!] Easy Apply runner exited with code {res.returncode}.{D}", flush=True)
        except Exception as e:
            print(f"{Y}[!] Easy Apply encounter (attempt {attempt}/{max_retries}): {e}{D}", flush=True)

        if attempt < max_retries:
            print(f"[*] Waiting {retry_delay}s before retrying Easy Apply...", flush=True)
            time.sleep(retry_delay)

    print(f"{Y}[NOTICE] Easy Apply batch concluded after {max_retries} attempts. Continuing continuous loop.{D}", flush=True)
    return False


def start_flask_dashboard(port=5050):
    """Starts the Flask web dashboard in a background daemon thread."""
    try:
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)

        from dashboard import app, export_static_html
        export_static_html()

        def _run():
            app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)

        server_thread = threading.Thread(target=_run, daemon=True)
        server_thread.start()
        print(f"{G}[+] Web Dashboard live at: http://localhost:{port}{D}")
        return True
    except Exception as e:
        print(f"{Y}[!] Dashboard background server note: {e}{D}")
        return False


def main():
    config = load_config()
    personal = config.get("personal_info", {})
    career = config.get("career_details", {})
    sched_cfg = config.get("scheduler_settings", {})
    ollama_cfg = config.get("ollama_settings", {})
    pipeline_cfg = config.get("ai_pipeline", {})
    gap_seconds = sched_cfg.get("loop_gap_seconds", 10)
    apps_limit = sched_cfg.get("applications_per_run", 50)
    daily_target = sched_cfg.get("daily_target", 50)
    min_score = pipeline_cfg.get("min_alignment_score", 7)
    port = sched_cfg.get("dashboard_port", 5050)

    candidate_name = f"{personal.get('first_name', 'Meetkumar')} {personal.get('last_name', 'Raval')}"
    location = f"{personal.get('city', 'Cottbus')}, {personal.get('country', 'Germany')}"
    ai_status = f"Ollama Cloud ({ollama_cfg.get('model', 'gpt-oss:120b')})" if ollama_cfg.get("enabled", True) else "Disabled"

    print(f"\n{C}{'=' * 76}")
    print(f"{W}   LinkedIn Easy Apply -- Autonomous Sprint Pipeline")
    print(f"{C}{'=' * 76}{D}")
    print(f"  {C}Candidate       :{D} {candidate_name} ({location})")
    print(f"  {C}Degree / Uni    :{D} {career.get('degree', 'Computer Science')} @ {career.get('university', 'BTU Cottbus-Senftenberg')}")
    print(f"  {C}AI Assistant    :{D} {G}{ai_status}{D} (Fit scoring threshold > {min_score}/10 & Question answering)")
    print(f"  {C}Resume Tailoring:{D} {G}REGULAR_APPLICATION (Tectonic LaTeX CV + Cover Letter){D}")
    print(f"  {C}Cycle Rhythm    :{D} Non-stop Sprint (10-second gap between listings)")
    print(f"  {C}Daily Safety Cap:{D} Max {daily_target} applications/day")
    print(f"  {C}Mode            :{D} CONTINUOUS SPRINT LOOP (Runs until stopped with Ctrl+C)")
    print(f"{C}{'=' * 76}{D}\n")

    # Start Flask Web Dashboard in background thread
    start_flask_dashboard(port=port)

    # Automatically open dashboard in browser after 1.5s
    def open_browser():
        time.sleep(1.5)
        try:
            webbrowser.open(f"http://localhost:{port}")
        except Exception:
            pass

    threading.Thread(target=open_browser, daemon=True).start()

    cycle_count = 0
    while running:
        cycle_count += 1
        applied_today = get_applied_today()

        print(f"\n{C}{'=' * 76}")
        print(f"{W}>>> SPRINT CYCLE #{cycle_count} STARTING AT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} <<<{D}")
        print(f"  {W}Daily Progress: {applied_today}/{daily_target} applications submitted today{D}")
        print(f"{C}{'=' * 76}{D}\n")

        # Easy Apply Job Submissions
        if applied_today >= daily_target:
            print(f"{G}[+] Daily safety limit of {daily_target} reached today ({applied_today} submitted).{D}")
            print(f"{G}[+] Job submissions paused to protect LinkedIn account. Will resume automatically tomorrow.{D}")
            update_state("RESTING_DAILY_LIMIT", cycle_count=cycle_count)
            # Sleep 1 hour before checking date reset
            next_target = datetime.now() + timedelta(hours=1)
        else:
            remaining_for_today = daily_target - applied_today
            batch_size = min(apps_limit, remaining_for_today)
            update_state("APPLYING_JOBS", cycle_count=cycle_count)
            try:
                run_cycle_easy_apply(limit=batch_size)
            except Exception as e:
                print(f"{Y}[!] Cycle #{cycle_count} job application encounter: {e}. Continuing loop.{D}")

            next_target = datetime.now() + timedelta(seconds=gap_seconds)

        update_state("IDLE", next_target=next_target, cycle_count=cycle_count)

        print(f"\n{G}[✓] Sprint Cycle #{cycle_count} finished.{D}")
        print(f"[*] Next run at: {next_target.strftime('%H:%M:%S')} ({gap_seconds}-second sprint pacing)\n")

        # Sprint gap countdown
        while running and datetime.now() < next_target:
            remaining = int((next_target - datetime.now()).total_seconds())
            if remaining <= 0:
                break
            sys.stdout.write(
                f"\r{C}[*] Sprint Gap Countdown (Cycle #{cycle_count + 1} at {next_target.strftime('%H:%M:%S')}): {W}{remaining:02d}s{D} remaining...   "
            )
            sys.stdout.flush()
            time.sleep(1)

        sys.stdout.write("\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{G}[+] LinkedIn Continuous Runner stopped by user. Browser & sessions preserved.{D}")
        update_state("STOPPED")
        sys.exit(0)
