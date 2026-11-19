"""campaign.py — automated cold-outreach rounds (Phase 1 + 2 + 3 wired).

One round completes full cycles (research -> contacts -> email) in batches
of 3 agencies, with DISCOVERY FIRST so unfinished cycles from a previous run
are finished before any new research quota is spent:

  1. SEND QUEUED  — email everything already in contacts_to_send.csv
                    (state + daily cap aware).
  2. DISCOVER     — Phase 2 contact discovery for pending companies
                    (researched but no usable contacts yet; ERROR retried).
  3. RESEARCH     — Phase 1 discovery ONLY for the deficit needed to fill
                    the batch (never researches ahead of discovery).
  4. DISCOVER     — Phase 2 contact discovery for the newly researched.
  5. BUILD        — rebuild contacts_to_send.csv from Phase 1 + 2 output.
  6. HOOKS        — Gemini hooks for companies that still lack one.
  7. AUDIT        — personalization gate (every company hooked, no placeholders).
  8. SEND NEW     — email the newly added companies (cap aware).

--loop chains rounds back-to-back and stops when today's agency cap
(MAX_AGENCIES_PER_DAY=20, each agency up to MAX_PER_COMPANY=6 emails,
MAX_PER_DAY=120) is reached, or when the Gemini pipeline stops producing
(quota exhausted / pool empty). Each round discovers 10 NEW agencies, finds
their contacts, and emails them automatically. Pass --research-ahead to
keep researching/discovering past the email cap (e.g. to prepare tomorrow's
batch) — the loop then stops only at the Gemini limit.

Gemini usage is counted per phase in data/gemini_usage.json (every client
call appends a record when GEMINI_USAGE_FILE is set) and reported in the
round log, so the phase-1 / phase-2 / hooks split is measurable.

WHERE/WHEN records:
  - every email        -> sent_history.csv (timestamp, from, to, company,
                          subject, status, body)
  - every round step   -> data/campaign_log.csv (round id, timestamp, action,
                          detail)

Usage (from phase_3):
  python campaign.py --dry-run              # plan only
  python campaign.py                        # single round: 10 agencies
  python campaign.py --loop                 # keep going until 20 agencies/day / API limit
  python campaign.py --loop --research-ahead  # keep discovering past the email cap
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
PHASE1 = os.path.join(ROOT, "phase_1")
PHASE2 = os.path.join(ROOT, "phase_2")

RESEARCH_CSV = os.path.join(PHASE1, "data", "discovered_companies.csv")
POOL_CSV = os.path.join(PHASE1, "data", "company_names.csv")
CONTACTS_CSV = os.path.join(PHASE2, "data", "contact_discovery_results.csv")
OUTCOMES_CSV = os.path.join(PHASE2, "data", "contact_discovery_outcomes.csv")
QUEUED_CSV = os.path.join(HERE, "contacts_to_send.csv")
BATCH_CSV = os.path.join(PHASE2, "data", "_campaign_batch.csv")
CAMPAIGN_LOG = os.path.join(HERE, "data", "campaign_log.csv")
TRACKING_CSV = os.path.join(HERE, "data", "tracking.csv")
USAGE_FILE = os.path.join(HERE, "data", "gemini_usage.json")
LIVE_STATUS_FILE = os.path.join(HERE, "data", "live_status.json")
LIVE_LOG_FILE = os.path.join(HERE, "data", "live_process.log")


def _venv_py(phase_dir: str) -> str:
    for cand in ("Scripts/python.exe", "bin/python"):
        p = os.path.join(phase_dir, ".venv", cand)
        if os.path.exists(p):
            return p
    return sys.executable


PHASE1_PY = _venv_py(PHASE1)
PHASE2_PY = _venv_py(PHASE2)


def _read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _names(path: str) -> set[str]:
    rows = _read_csv(path)
    key = "company_name" if rows and "company_name" in rows[0] else "Company"
    return {str(r.get(key, "")).strip() for r in rows if str(r.get(key, "")).strip()}


def researched() -> set[str]:
    return _names(RESEARCH_CSV)


def with_contacts() -> set[str]:
    return _names(CONTACTS_CSV)


def queued() -> set[str]:
    return _names(QUEUED_CSV)


def pool() -> set[str]:
    return _names(POOL_CSV)


def pending_researched() -> list[str]:
    """Researched companies with no usable contacts yet (Phase 2 to run)."""
    done = with_contacts()
    return sorted(r for r in researched() if r not in done)


SETTINGS_PATH = os.path.join(ROOT, "streamlit_app", "settings.json")
GEMINI_KEYS_FILE = os.path.join(ROOT, "gemini_keys.json")
PROMPTS_FILE = os.path.join(ROOT, "prompts.md")
_PROBE_CACHE: tuple[str, str] | None = None


def _probe_key_model() -> tuple[str, str] | None:
    """(api_key, working_model) — first key x model that responds, or None.

    Free-tier Gemini quotas are per key AND per model (e.g. key 1 may have
    spent its gemini-3.7/3.6 daily budget while key 2 is fresh), so the
    campaign probes all keys x models and uses what still responds.
    """
    global _PROBE_CACHE
    if _PROBE_CACHE is not None:
        return _PROBE_CACHE
    # Prefer the best model that still has quota: try gemini-3.7-flash on
    # every key, then 3.6, then 3.5 (free-tier quotas are per key AND model).
    script = (
        "import json,sys,os\n"
        "from google import genai\n"
        "for _p in [%r,%r]:\n"
        "    if os.path.exists(_p):\n"
        "        try:\n"
        "            s=json.load(open(_p,encoding='utf-8')); break\n"
        "        except Exception: pass\n"
        "else:\n"
        "    sys.exit(1)\n"
        "ks=[k for k in s.get('api_keys',[]) if k.get('enabled',True) "
        "and str(k.get('provider','')).lower()=='gemini']\n"
        "ms=['gemini-3.6-flash','gemini-3.5-flash','gemini-3.7-flash']\n"
        "def try_k(key,model):\n"
        "    try:\n"
        "        c=genai.Client(api_key=key,http_options={'timeout':20000})\n"
        "        c.interactions.create(model=model,system_instruction="
        "'Reply OK',input='ping',store=False)\n"
        "        print(model); print(key); return True\n"
        "    except Exception: return False\n"
        "for m in ms:\n"
        "    for k in ks:\n"
        "        if try_k(k['value'],m): sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    try:
        proc = subprocess.run(
            [PHASE1_PY, "-c", script % (GEMINI_KEYS_FILE, SETTINGS_PATH)],
            capture_output=True, text=True, timeout=120,
        )
        lines = [l for l in (proc.stdout or "").splitlines() if l.strip()]
        if proc.returncode == 0 and len(lines) >= 2:
            _PROBE_CACHE = (lines[1].strip(), lines[0].strip())
    except Exception:
        pass
    return _PROBE_CACHE


_PROMPT_PATHS: dict[str, str] | None = None


def _extract_prompts() -> dict[str, str]:
    """Split the project-root prompts.md into {section: text}.

    Sections are delimited by lines matching ``# SECTION: <name>``. The
    prompts themselves contain many '# ...' lines, so this delimiter is
    unambiguous. Returns {} when the file is missing (phases then use
    their own defaults).
    """
    if not os.path.exists(PROMPTS_FILE):
        print(f"WARNING: {PROMPTS_FILE} not found - phases fall back to their built-in prompts.")
        return {}
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    with open(PROMPTS_FILE, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^# SECTION:\s*(.+?)\s*$", line.strip())
            if m:
                if current:
                    sections[current] = "".join(buf).strip()
                current = m.group(1)
                buf = []
            else:
                buf.append(line)
    if current:
        sections[current] = "".join(buf).strip()
    return sections


def _prompt_paths() -> dict[str, str]:
    """Extract prompts.md sections into phase_3/data/prompts/*.md (once per run).

    Returns {section: file_path}. The phase CLIs receive these paths via
    their DISCOVERY_PROMPT / CONTACT_PROMPT / CONTACT_REPEAT_PROMPT env
    vars, and generate_hooks.py via HOOK_PROMPT_PATH — so editing the one
    root file changes every Gemini prompt in the campaign.
    """
    global _PROMPT_PATHS
    if _PROMPT_PATHS is not None:
        return _PROMPT_PATHS
    out_dir = os.path.join(HERE, "data", "prompts")
    os.makedirs(out_dir, exist_ok=True)
    mapping = {
        "PHASE 1 - COMPANY DISCOVERY PROMPT": "discovery_prompt.md",
        "PHASE 2 - CONTACT DISCOVERY PROMPT (FIRST PASS)": "contact_discovery_prompt.md",
        "PHASE 2 - CONTACT DISCOVERY PROMPT (REPEAT PASS)": "contact_discovery_repeat_prompt.md",
        "PHASE 3 - COMPANY HOOK PROMPT": "hook_prompt.txt",
    }
    sections = _extract_prompts()
    paths: dict[str, str] = {}
    for section, fname in mapping.items():
        if section not in sections or not sections[section].strip():
            print(f"WARNING: prompts.md is missing or empty section {section!r} - using phase default.")
            continue
        path = os.path.join(out_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(sections[section] + "\n")
        paths[section] = path
    _PROMPT_PATHS = paths
    return paths


def _gemini_env() -> dict[str, str]:
    """Subprocess env: a Gemini key that still has quota + model chain + usage tracking + prompts."""
    env = dict(os.environ)
    env["GEMINI_USAGE_FILE"] = USAGE_FILE
    prompts = _prompt_paths()
    for section, var in (
        ("PHASE 1 - COMPANY DISCOVERY PROMPT", "DISCOVERY_PROMPT"),
        ("PHASE 2 - CONTACT DISCOVERY PROMPT (FIRST PASS)", "CONTACT_PROMPT"),
        ("PHASE 2 - CONTACT DISCOVERY PROMPT (REPEAT PASS)", "CONTACT_REPEAT_PROMPT"),
    ):
        if section in prompts:
            env[var] = prompts[section]
    if "PHASE 3 - COMPANY HOOK PROMPT" in prompts:
        env["HOOK_PROMPT_PATH"] = prompts["PHASE 3 - COMPANY HOOK PROMPT"]
    picked = _probe_key_model()
    if picked:
        key, model = picked
        env["GEMINI_API_KEY"] = key
        env["GEMINI_MODEL"] = model
    else:
        # Fall back to the first configured key if the probe failed.
        try:
            import generate_hooks

            keys = generate_hooks.find_keys(os.environ)
        except Exception:
            keys = []
        if keys:
            env["GEMINI_API_KEY"] = str(keys[0]["value"])
        env.setdefault("GEMINI_MODEL", "gemini-3.7-flash")
    env.setdefault("GEMINI_FALLBACK_MODELS", "gemini-3.6-flash, gemini-3.5-flash")
    return env


def _append_live_log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LIVE_LOG_FILE), exist_ok=True)
        with open(LIVE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _publish_live_status(
    step: int,
    step_name: str,
    status: str = "running",
    detail: str = "",
    round_id: str = "",
    batch: list[str] | None = None,
    step_result: str = "",
) -> None:
    try:
        os.makedirs(os.path.dirname(LIVE_STATUS_FILE), exist_ok=True)
        now_iso = datetime.now().isoformat()
        metrics = {
            "today_sent": _today_sent(),
            "max_per_day": int(_env_value("MAX_PER_DAY", "120") or 0),
            "agencies_today": _agencies_today(),
            "max_agencies_per_day": int(_env_value("MAX_AGENCIES_PER_DAY", "20") or 0),
            "researched_count": len(researched()),
            "contacts_count": len(with_contacts()),
            "queued_count": len(queued()),
            "hooks_count": len(_names(os.path.join(HERE, "data", "email_hooks.csv"))),
        }
        data = {
            "step": step,
            "total_steps": 8,
            "step_name": step_name,
            "status": status,
            "detail": detail,
            "round_id": round_id,
            "current_batch": batch or [],
            "step_result": step_result,
            "updated_at": now_iso,
            "pid": os.getpid(),
            "metrics": metrics,
        }
        tmp = LIVE_STATUS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, LIVE_STATUS_FILE)
    except Exception:
        pass


def _run(cmd: list[str], cwd: str, env: dict | None = None, timeout: int = 3600) -> int:
    cmd_str = f">>> {' '.join(os.path.basename(c) if os.sep in c else c for c in cmd)}"
    print(f"\n{cmd_str}")
    print(f"    (cwd: {os.path.relpath(cwd, ROOT)})")
    _append_live_log(f"[{datetime.now():%H:%M:%S}] {cmd_str}")

    clean_cmd = list(cmd)
    if clean_cmd and ("python" in clean_cmd[0].lower()) and "-u" not in clean_cmd:
        clean_cmd.insert(1, "-u")

    rc = 1
    proc = None
    try:
        proc = subprocess.Popen(
            clean_cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if proc.stdout:
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                _append_live_log(line.rstrip())
        proc.wait(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        print("!!! step timed out")
        _append_live_log(f"[{datetime.now():%H:%M:%S}] !!! step timed out")
        if proc:
            proc.kill()
        return 1
    except Exception as e:
        rc = getattr(proc, "returncode", 1) if proc else 1
        _append_live_log(f"[{datetime.now():%H:%M:%S}] Step error: {e}")

    if rc != 0:
        print(f"!!! step exited with code {rc}")
        _append_live_log(f"[{datetime.now():%H:%M:%S}] !!! step exited with code {rc}")
    return rc


def _log_round(round_id: str, action: str, detail: str) -> None:
    os.makedirs(os.path.dirname(CAMPAIGN_LOG), exist_ok=True)
    new = not os.path.exists(CAMPAIGN_LOG)
    with open(CAMPAIGN_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["round", "timestamp", "action", "detail"])
        w.writerow([round_id, datetime.now().isoformat(timespec="seconds"), action, detail])


TRACKING_COLUMNS = ["company", "date_applied", "time_applied", "emails_sent", "contact_emails", "round"]

def _log_tracking(company: str, emails_sent: int, contact_emails: str, round_id: str) -> None:
    """Append one row per company to data/tracking.csv."""
    os.makedirs(os.path.dirname(TRACKING_CSV), exist_ok=True)
    new = not os.path.exists(TRACKING_CSV)
    with open(TRACKING_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRACKING_COLUMNS)
        if new:
            w.writeheader()
        now = datetime.now()
        w.writerow({
            "company": company,
            "date_applied": now.strftime("%Y-%m-%d"),
            "time_applied": now.strftime("%H:%M:%S"),
            "emails_sent": emails_sent,
            "contact_emails": contact_emails,
            "round": round_id,
        })

def _usage_counts() -> dict[str, int]:
    """Gemini calls per phase recorded in USAGE_FILE (campaign runs only)."""
    counts = {"phase1": 0, "phase2": 0, "hooks": 0}
    if not os.path.exists(USAGE_FILE):
        return counts
    try:
        with open(USAGE_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    phase = json.loads(line).get("phase")
                except Exception:
                    continue
                if phase in counts:
                    counts[phase] += 1
    except OSError:
        pass
    return counts


def _usage_delta(before: dict[str, int]) -> dict[str, int]:
    now = _usage_counts()
    return {k: now.get(k, 0) - before.get(k, 0) for k in before}


def _env_value(name: str, default: str = "") -> str:
    """Value of NAME in phase_3/.env (values only — never printed)."""
    path = os.path.join(HERE, ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return default


def _today_sent() -> int:
    """Emails recorded as sent today (state.json daily_counts)."""
    try:
        with open(os.path.join(HERE, "state.json"), encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    return int(state.get("daily_counts", {}).get(today, 0) or 0)


def _email_cap_reached() -> bool:
    """True when today's sent count already fills MAX_PER_DAY (sends no-op)."""
    count = _today_sent()
    cap = int(_env_value("MAX_PER_DAY", "120") or 0)
    return cap > 0 and count >= cap


def _agencies_today() -> int:
    """Distinct agencies recorded in tracking.csv today (processed today)."""
    today = datetime.now().strftime("%Y-%m-%d")
    names = set()
    for row in _read_csv(TRACKING_CSV):
        if row.get("date_applied", "").strip() == today:
            c = row.get("company", "").strip()
            if c:
                names.add(c)
    return len(names)


def _agencies_cap_reached() -> bool:
    """True when today's processed agencies already fill MAX_AGENCIES_PER_DAY."""
    count = _agencies_today()
    cap = int(_env_value("MAX_AGENCIES_PER_DAY", "20") or 0)
    return cap > 0 and count >= cap


def _write_batch_csv(names: list[str]) -> str:
    """Subset of the Phase 1 research CSV for exactly the batch companies."""
    rows = _read_csv(RESEARCH_CSV)
    wanted = set(names)
    subset = [r for r in rows if r.get("company_name", "").strip() in wanted]
    with open(BATCH_CSV, "w", newline="", encoding="utf-8") as f:
        if subset:
            w = csv.DictWriter(f, fieldnames=list(subset[0].keys()))
            w.writeheader()
            w.writerows(subset)
    return BATCH_CSV


def _run_round(batch_size: int, skip_send: bool, round_id: str) -> dict:
    """One full round: complete cycles first, research only the deficit.

    Order: send queued -> discover pending -> research deficit -> discover
    the newly researched -> build -> hooks -> audit -> send new. Discovery
    ALWAYS runs before research, so unfinished cycles from a previous run
    (quota outage, crash) are completed before any new research quota is
    spent, and research never runs ahead of discovery by more than one batch.
    Returns {researched, contacts_found, batch}.
    """
    result = {"researched": 0, "contacts_found": 0, "batch": []}
    usage0 = _usage_counts()

    # 1) Send everything already queued (no-op once the daily cap is reached).
    if not skip_send:
        print("\n=== STEP 1/8: send already-queued companies ===")
        _publish_live_status(
            step=1,
            step_name="Step 1/8: Send Already-Queued Companies",
            status="running",
            detail="Dispatching emails to verified companies already queued in contacts_to_send.csv...",
            round_id=round_id,
        )
        _run([sys.executable, "send_emails.py", "--mode", "all"], cwd=HERE)

    # 2) Discovery first: complete unfinished cycles before new research.
    pending = pending_researched()
    batch = pending[:batch_size]
    if batch:
        print(f"\n=== STEP 2/8: Phase 2 discovery for {len(batch)} pending company/ies ===")
        _publish_live_status(
            step=2,
            step_name=f"Step 2/8: Phase 2 Discovery for Pending ({len(batch)} companies)",
            status="running",
            detail=f"Searching leadership contacts (CTO, VP Eng) for {', '.join(batch)}...",
            round_id=round_id,
            batch=batch,
        )
        before = len(with_contacts())
        rc = _run(
            [PHASE2_PY, "-m", "contact_discovery.cli",
             "--companies", _write_batch_csv(batch),
             "--csv", CONTACTS_CSV,
             "--outcomes", OUTCOMES_CSV,
             "--limit", str(len(batch))],
            cwd=PHASE2, env=_gemini_env(), timeout=3600,
        )
        found = len(with_contacts()) - before
        result["contacts_found"] += found
        _log_round(round_id, "phase2_discovery",
                   f"companies={', '.join(batch)} rc={rc} contacts_found={found}")

    # 3) Research ONLY the deficit needed to fill the batch.
    pending = pending_researched()
    deficit = max(0, batch_size - len(pending))
    if deficit:
        print(f"\n=== STEP 3/8: Phase 1 discovery for {deficit} new company/ies ===")
        _publish_live_status(
            step=3,
            step_name=f"Step 3/8: Phase 1 Startup Discovery ({deficit} companies)",
            status="running",
            detail=f"Discovering {deficit} German tech startups with 15-150 employees...",
            round_id=round_id,
        )
        before = len(researched())
        # --cap is the TOTAL stored target (already-stored companies count),
        # so target current + deficit to add exactly the needed new batch.
        rc = _run(
            [PHASE1_PY, "-m", "startup_discovery.cli",
             "--cap", str(before + deficit), "--cities", "Germany", "--min-score", "50"],
            cwd=PHASE1, env=_gemini_env(), timeout=3600,
        )
        new_researched = len(researched()) - before
        result["researched"] += new_researched
        _log_round(round_id, "phase1_discovery",
                   f"targeted={deficit} rc={rc} new={new_researched}")
    else:
        print(f"\nNo research needed - {len(pending)} company/ies already pending (batch full).")

    # 4) Discovery for the newly researched (idempotent: companies already in
    #    the outcomes tracker are skipped, ERROR ones are retried).
    pending = pending_researched()
    batch = pending[:batch_size]
    if batch:
        print(f"\n=== STEP 4/8: Phase 2 discovery for {len(batch)} company/ies (new research) ===")
        _publish_live_status(
            step=4,
            step_name=f"Step 4/8: Phase 2 Discovery for New Startups ({len(batch)})",
            status="running",
            detail=f"Finding verified contacts for newly discovered startups: {', '.join(batch)}...",
            round_id=round_id,
            batch=batch,
        )
        before = len(with_contacts())
        rc = _run(
            [PHASE2_PY, "-m", "contact_discovery.cli",
             "--companies", _write_batch_csv(batch),
             "--csv", CONTACTS_CSV,
             "--outcomes", OUTCOMES_CSV,
             "--limit", str(len(batch))],
            cwd=PHASE2, env=_gemini_env(), timeout=3600,
        )
        found = len(with_contacts()) - before
        result["contacts_found"] += found
        _log_round(round_id, "phase2_discovery",
                   f"companies={', '.join(batch)} rc={rc} contacts_found={found}")

    result["batch"] = batch
    if not batch and result["researched"] == 0:
        print("\nNothing new to process this round — everything researched has contacts.")
        usage = _usage_delta(usage0)
        _log_round(round_id, "gemini_usage",
                   f"phase1={usage['phase1']} phase2={usage['phase2']} hooks={usage['hooks']}")
        _publish_live_status(
            step=0,
            step_name="Round Idle (Everything Researched)",
            status="idle",
            detail="Nothing new to process — all researched companies have contacts.",
            round_id=round_id,
        )
        return result

    # 5) Rebuild the send list from Phase 1 + 2 output.
    print("\n=== STEP 5/8: rebuild contacts_to_send.csv ===")
    _publish_live_status(
        step=5,
        step_name="Step 5/8: Rebuild Recipient List & DNS MX Check",
        status="running",
        detail="Deduplicating contacts, filtering blacklists, and validating DNS MX records...",
        round_id=round_id,
        batch=batch,
    )
    _run([sys.executable, "build_email_list.py"], cwd=HERE)

    # 6) Gemini hooks for companies that still lack one (incremental merge).
    print("\n=== STEP 6/8: Gemini hooks for new companies ===")
    _publish_live_status(
        step=6,
        step_name="Step 6/8: Generate Gemini Product Hooks",
        status="running",
        detail="Crafting 2-sentence technical hooks tailored to each company's product stack...",
        round_id=round_id,
        batch=batch,
    )
    _run([PHASE1_PY, "generate_hooks.py"], cwd=HERE, env=_gemini_env(), timeout=3600)

    # 7) Audit gate.
    print("\n=== STEP 7/8: audit ===")
    _publish_live_status(
        step=7,
        step_name="Step 7/8: Audit Personalization Quality Gate",
        status="running",
        detail="Validating 100% tag resolution, brand name match, and tech focus coverage...",
        round_id=round_id,
        batch=batch,
    )
    _run([sys.executable, "audit_personalization.py"], cwd=HERE)

    # 8) Send the newly queued companies (no-op once the daily cap is reached).
    if not skip_send:
        print("\n=== STEP 8/8: send newly queued companies ===")
        _publish_live_status(
            step=8,
            step_name="Step 8/8: Send Newly Queued Companies",
            status="running",
            detail="Dispatching personalized emails to new decision-makers during optimal window...",
            round_id=round_id,
            batch=batch,
        )
        _run([sys.executable, "send_emails.py", "--mode", "all"], cwd=HERE)

    _publish_live_status(
        step=8,
        step_name="Round Completed",
        status="completed",
        detail=f"Completed round {round_id}. Researched: {result['researched']}, Contacts: {result['contacts_found']}.",
        round_id=round_id,
        batch=batch,
        step_result=f"Researched: {result['researched']} new | Contacts: {result['contacts_found']} found",
    )

    usage = _usage_delta(usage0)
    _log_round(round_id, "gemini_usage",
               f"phase1={usage['phase1']} phase2={usage['phase2']} hooks={usage['hooks']}")
    _log_round(round_id, "round_end",
               f"companies_with_contacts={len(with_contacts())} queued={len(queued())}")

    # --- TRACKING: record each company in this batch ---
    if batch:
        # Count emails sent per company from sent_history.csv
        email_counts: dict[str, int] = {}
        email_addrs: dict[str, list[str]] = {}
        hist_path = os.path.join(HERE, "sent_history.csv")
        if os.path.exists(hist_path):
            with open(hist_path, encoding="utf-8-sig", newline="") as hf:
                for row in csv.DictReader(hf):
                    cname = row.get("company", "")
                    if cname in set(batch):
                        email_counts[cname] = email_counts.get(cname, 0) + 1
                        email_addrs.setdefault(cname, []).append(row.get("to", ""))
        for company in batch:
            _log_tracking(
                company,
                email_counts.get(company, 0),
                "; ".join(email_addrs.get(company, [])),
                round_id,
            )

    return result


def _plan(batch_size: int) -> dict:
    pending = pending_researched()
    return {
        "queued_companies": sorted(queued()),
        "pending": pending[:batch_size],
        "deficit": max(0, batch_size - len(pending)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Automated outreach rounds.")
    ap.add_argument("--dry-run", action="store_true", help="plan only; nothing sent or discovered")
    ap.add_argument("--batch", type=int, default=10, help="agencies per round (default 10)")
    ap.add_argument("--research-ahead", action="store_true",
                    help="keep researching/discovering after today's email cap (prepare future batches)")
    ap.add_argument("--skip-send", action="store_true", help="research/discover/build only, no emails")
    ap.add_argument("--loop", action="store_true", help="chain rounds until the Gemini pipeline stops producing")
    ap.add_argument("--max-rounds", type=int, default=10, help="safety cap on loop iterations (default 10)")
    args = ap.parse_args()

    plan = _plan(args.batch)
    print("=== CAMPAIGN ROUND PLAN ===")
    print(f"queued agencies: {len(plan['queued_companies'])} -> {', '.join(plan['queued_companies']) or '-'}")
    print(f"pending batch   : {len(plan['pending'])} -> {', '.join(plan['pending']) or '-'}")
    print(f"new discovery   : {plan['deficit']} agency/ies (Phase 1) to keep the batch at {args.batch}")
    print(f"pool remaining  : {len(pool() - researched())} unused names in phase_1/data/company_names.csv")
    print(f"target          : Germany software companies & startups (Werkstudent & Internships in Software/AI)")
    print(f"agency cap      : {_env_value('MAX_AGENCIES_PER_DAY', '20')}/day - {_agencies_today()} processed today")
    print(f"email cap       : {_env_value('MAX_PER_DAY', '120')}/day - {_today_sent()} sent today")
    print(f"prompts file    : prompts.md at project root (edit to change all Gemini prompts)")

    if args.dry_run:
        _publish_live_status(
            step=0,
            step_name="Dry-Run Plan Complete",
            status="completed",
            detail=f"Dry run plan completed. Queued: {len(plan['queued_companies'])}, Pending: {len(plan['pending'])}, Deficit: {plan['deficit']}.",
        )
        print("\n[dry-run] No emails sent, no research or discovery run.")
        return 0

    rounds_run = 0
    empty_phase1 = 0
    empty_phase2 = 0
    while True:
        rounds_run += 1
        round_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        print(f"\n########## ROUND {rounds_run} (id {round_id}) ##########")
        _log_round(round_id, "round_start", f"batch={args.batch} loop={args.loop}")
        _publish_live_status(
            step=1,
            step_name=f"Starting Round {rounds_run}",
            status="running",
            detail=f"Round {round_id} started (batch size {args.batch}).",
            round_id=round_id,
        )

        result = _run_round(args.batch, args.skip_send, round_id)

        if result["researched"] == 0 and not result["batch"]:
            empty_phase1 += 1
        else:
            empty_phase1 = 0
        if result["contacts_found"] == 0:
            empty_phase2 += 1
        else:
            empty_phase2 = 0

        if not args.loop:
            _publish_live_status(
                step=8,
                step_name="Single Round Finished",
                status="completed",
                detail=f"Round {round_id} finished successfully.",
                round_id=round_id,
            )
            break
        # Loop-stop conditions: safety cap, today's email cap (unless
        # --research-ahead), or Gemini stopped producing (quota exhausted /
        # pool empty).
        if rounds_run >= args.max_rounds:
            print(f"\n[loop] reached --max-rounds {args.max_rounds}; stopping.")
            _log_round(round_id, "loop_stop", "max_rounds")
            _publish_live_status(
                step=0,
                step_name="Safety Cap Reached",
                status="completed",
                detail=f"Reached --max-rounds {args.max_rounds}; loop stopped.",
                round_id=round_id,
            )
            break
        if not args.research_ahead and _email_cap_reached():
            print("\n[loop] today's email cap is reached; stopping "
                  "(use --research-ahead to keep discovering for future batches).")
            _log_round(round_id, "loop_stop", "email_cap_reached")
            _publish_live_status(
                step=0,
                step_name="Daily Email Cap Reached",
                status="cap_reached",
                detail="Today's email cap reached. Outreach paused until tomorrow.",
                round_id=round_id,
            )
            break
        if _agencies_cap_reached():
            print(f"\n[loop] today's agency cap ({_env_value('MAX_AGENCIES_PER_DAY', '20')}) is reached; stopping.")
            _log_round(round_id, "loop_stop", "agencies_per_day_reached")
            _publish_live_status(
                step=0,
                step_name="Daily Company Cap Reached",
                status="cap_reached",
                detail="Today's company cap reached. Outreach paused until tomorrow.",
                round_id=round_id,
            )
            break
        if empty_phase1 >= 2 and not result["batch"]:
            print("\n[loop] Phase 1 produced nothing new twice — API limit reached or pool empty; stopping.")
            _log_round(round_id, "loop_stop", "phase1_empty_x2")
            _publish_live_status(
                step=0,
                step_name="Phase 1 Discovery Exhausted",
                status="completed",
                detail="Phase 1 produced nothing new twice. Pausing loop.",
                round_id=round_id,
            )
            break
        if empty_phase2 >= 3:
            print("\n[loop] Phase 2 found no contacts 3 rounds in a row — API limit reached; stopping.")
            _log_round(round_id, "loop_stop", "phase2_empty_x3")
            _publish_live_status(
                step=0,
                step_name="Phase 2 Discovery Exhausted",
                status="completed",
                detail="Phase 2 found no new contacts 3 rounds in a row. Pausing loop.",
                round_id=round_id,
            )
            break

        _publish_live_status(
            step=0,
            step_name="Cooldown Between Rounds",
            status="sleeping",
            detail=f"Round {rounds_run} complete. Sleeping before round {rounds_run + 1}...",
            round_id=round_id,
        )

    print("\n=== CAMPAIGN SUMMARY ===")
    print(f"rounds run            : {rounds_run}")
    print(f"researched agencies   : {len(researched())}")
    print(f"agencies w/ contacts  : {len(with_contacts())}")
    print(f"queued for sending    : {len(queued())}")
    print(f"agencies today        : {_agencies_today()}/{_env_value('MAX_AGENCIES_PER_DAY', '20')}")
    print(f"log                 : data/campaign_log.csv")
    usage = _usage_counts()
    print(f"gemini calls        : phase1={usage['phase1']} phase2={usage['phase2']} "
          f"hooks={usage['hooks']} (data/gemini_usage.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
