#!/usr/bin/env python3
"""
LinkedIn Unified Master Scheduler Daemon
Executes:
  - 10 Job Applications (Easy Apply) via visible Chrome
  - 3 AI Comments (SocialCrabs)
Every hour at minute :30 (11:30, 12:30, 01:30, 02:30, ...)
Candidate: Meetkumar Raval
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(WORKSPACE_DIR, "config.json")
DAEMON_STATE_FILE = os.path.join(WORKSPACE_DIR, "daemon_state.json")


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_socialcrabs_dir() -> str:
    config = load_config()
    configured_path = config.get("scheduler_settings", {}).get("socialcrabs_path")
    if configured_path and os.path.exists(configured_path):
        return configured_path

    candidates = [
        os.path.abspath(os.path.join(WORKSPACE_DIR, "..", "Linkedin", "socialcrabs")),
        os.path.abspath(os.path.join(WORKSPACE_DIR, "..", "socialcrabs")),
        os.path.abspath(os.path.join(WORKSPACE_DIR, "socialcrabs")),
        os.path.abspath(os.path.join(WORKSPACE_DIR, "Linkedin", "socialcrabs")),
        r"C:\Users\raval\Downloads\Linkedin\socialcrabs",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


SOCIALCRABS_DIR = get_socialcrabs_dir()


def get_applied_today() -> int:
    """Calculates how many applications were successfully submitted today."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    history_file = os.path.join(WORKSPACE_DIR, "history.json")
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                hist = json.load(f)
                return sum(1 for v in hist.values() if "Applied" in v.get("status", "") and v.get("timestamp", "").startswith(today_str))
        except Exception:
            pass
    return 0


def calculate_next_target(gap_minutes: int = 5) -> datetime:
    """Calculate upcoming target time (current time + gap_minutes)."""
    return datetime.now() + timedelta(minutes=gap_minutes)


def update_state(status="IDLE", next_target: datetime = None, cycle_count: int = 0):
    applied_today = get_applied_today()
    state = {
        "status": status,
        "last_cycle_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "next_run_at": next_target.strftime("%Y-%m-%d %H:%M:%S") if next_target else "",
        "schedule": "Continuous Loop: 1 Comment + 3 Jobs (5 min gap)",
        "loop_mode": "CONTINUOUS_NON_STOP_LOOP",
        "apps_per_run": 3,
        "comments_per_run": 1,
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


def run_cycle(comments_limit=1, apps_limit=3, max_retries=3, retry_delay=10):
    """
    Executes the continuous loop cycle:
      Step 1: Take 1 post -> comment it (SocialCrabs)
      Step 2: Take 3 jobs -> submit applications (Easy Apply Bot)
    With 3 retries on errors and time gap between attempts.
    """
    config = load_config()
    daily_target = config.get("scheduler_settings", {}).get("daily_target", 50)
    applied_today = get_applied_today()

    print("\n" + "=" * 70, flush=True)
    print(f"[*] LOOP CYCLE EXECUTION AT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"[*] Workload: 1 AI Comment (SocialCrabs) + 3 Job Applications (Easy Apply)", flush=True)
    print(f"[*] Daily Progress: {applied_today}/{daily_target} applications submitted today", flush=True)
    print("=" * 70 + "\n", flush=True)

    # Step 1: Take one post -> comment it (SocialCrabs)
    update_state("RUNNING_SOCIALCRABS_COMMENTS")
    socialcrabs_success = False
    sc_dir = get_socialcrabs_dir()
    for attempt in range(1, max_retries + 1):
        print(f"[1/2] Taking 1 post and commenting via SocialCrabs (Attempt {attempt}/{max_retries})...", flush=True)
        try:
            if os.path.exists(sc_dir):
                npx_cmd = f'npx tsx src/scripts/run-24h-daemon.ts --post-live --once --no-server --batch-size {comments_limit}'
                res = subprocess.run(npx_cmd, shell=True, cwd=sc_dir, check=False)
                if res.returncode == 0:
                    print(f"[+] SocialCrabs: Comment successfully posted!", flush=True)
                    socialcrabs_success = True
                    break
                else:
                    print(f"[!] SocialCrabs exited with code {res.returncode}.", flush=True)
            else:
                print(f"[-] SocialCrabs directory not found at: {sc_dir}", flush=True)
                break
        except Exception as e:
            print(f"[!] SocialCrabs encounter on attempt {attempt}: {e}", flush=True)

        if attempt < max_retries:
            print(f"[*] Waiting {retry_delay}s before retrying SocialCrabs (attempt {attempt + 1}/{max_retries})...", flush=True)
            time.sleep(retry_delay)

    if not socialcrabs_success:
        print(f"[NOTICE] SocialCrabs concluded with warnings after {max_retries} attempts. Proceeding to job applications.", flush=True)

    time.sleep(3)

    # Step 2: Take three jobs -> send submit (Easy Apply)
    update_state("RUNNING_JOB_APPLICATIONS")
    python_exe = os.path.join(WORKSPACE_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = sys.executable
    apply_script = os.path.join(WORKSPACE_DIR, "apply_bot.py")

    applied_today = get_applied_today()
    if applied_today >= daily_target:
        print(f"\n[+] Daily safety cap of {daily_target} applications reached today ({applied_today} applied).", flush=True)
        print(f"[+] Skipping job submissions to protect your LinkedIn account. Resuming automatically at midnight.", flush=True)
        easy_apply_success = True
    else:
        remaining_today = daily_target - applied_today
        batch_to_run = min(apps_limit, remaining_today)
        easy_apply_success = False

        for attempt in range(1, max_retries + 1):
            print(f"\n[2/2] Taking {batch_to_run} jobs and submitting applications (Attempt {attempt}/{max_retries})...", flush=True)
            try:
                res = subprocess.run([python_exe, "-u", apply_script, "--limit", str(batch_to_run)], check=False)
                if res.returncode == 0:
                    print(f"[+] Easy Apply: {batch_to_run} applications batch processed successfully!", flush=True)
                    easy_apply_success = True
                    break
                else:
                    print(f"[!] Easy Apply exited with code {res.returncode}.", flush=True)
            except Exception as e:
                print(f"[!] Easy Apply encounter on attempt {attempt}: {e}", flush=True)

            if attempt < max_retries:
                print(f"[*] Waiting {retry_delay}s before retrying Easy Apply (attempt {attempt + 1}/{max_retries})...", flush=True)
                time.sleep(retry_delay)

        if not easy_apply_success:
            print(f"[NOTICE] Easy Apply concluded with warnings after {max_retries} attempts. Continuing loop.", flush=True)

    print("\n" + "=" * 70, flush=True)
    print(f"[+] CYCLE FINISHED AT {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("=" * 70 + "\n", flush=True)
    print("=" * 70 + "\n", flush=True)


def main():
    config = load_config()
    sched_cfg = config.get("scheduler_settings", {})
    gap_minutes = sched_cfg.get("loop_gap_minutes", 5)
    apps_limit = sched_cfg.get("applications_per_run", 3)
    comments_limit = sched_cfg.get("comments_per_run", 1)

    # Support single execution trigger
    if "--once" in sys.argv:
        print("[CLI] Single loop cycle requested (--once).", flush=True)
        run_cycle(comments_limit, apps_limit)
        print("[CLI] Single cycle completed successfully. Exiting.", flush=True)
        return

    print("=" * 72)
    print("   LinkedIn Continuous 2-in-1 Automation Loop")
    print(f"   Candidate       : Meetkumar Raval")
    print(f"   Loop Sequence   : 1. Post 1 AI Comment")
    print(f"                     2. Submit 3 Easy Apply Applications")
    print(f"                     3. 5-Minute Time Gap between cycles")
    print(f"   Mode            : CONTINUOUS NON-STOP LOOP")
    print("=" * 72 + "\n")

    cycle_count = 0
    while True:
        cycle_count += 1
        print(f"\n>>> STARTING CYCLE #{cycle_count} <<<", flush=True)

        try:
            run_cycle(comments_limit, apps_limit)
        except Exception as e:
            print(f"[!] Encounter in cycle #{cycle_count}: {e}. Resuming loop.", flush=True)

        next_target = calculate_next_target(gap_minutes)
        update_state("IDLE", next_target, cycle_count)
        print(f"[*] Cycle #{cycle_count} done. Next cycle scheduled for: {next_target.strftime('%Y-%m-%d %H:%M:%S')} (5-min gap)\n", flush=True)

        # 5-minute gap countdown loop
        while datetime.now() < next_target:
            remaining = int((next_target - datetime.now()).total_seconds())
            if remaining <= 0:
                break
            mins = remaining // 60
            secs = remaining % 60
            sys.stdout.write(f"\r[*] 5-Minute Gap Countdown (Cycle #{cycle_count + 1} at {next_target.strftime('%H:%M:%S')}): {mins:02d}m {secs:02d}s remaining... ")
            sys.stdout.flush()
            time.sleep(1)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
