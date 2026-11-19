"""Background runners for the live-run UI.

Every pipeline phase runs on a **daemon thread**. The UI never blocks: the
thread writes log lines into a thread-safe buffer that the Streamlit
fragment polls every couple of seconds, and the CSV files (the source of
truth, written after every batch/company by the phases themselves) drive the
progress bars. ``request_stop()`` flips a flag the discovery loops check
between batches/companies, so stopping is clean and resumable.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import paths, settings as settings_mod
from .clients import RotatingClient, build_provider_factory, ensure_usable_keys

# Make the phase packages importable from the repo root.
if str(paths.ROOT) not in sys.path:
    sys.path.insert(0, str(paths.ROOT))

from phase_1.startup_discovery.config import Config as P1Config  # noqa: E402
from phase_1.startup_discovery.discovery import run_discovery  # noqa: E402
from phase_1.startup_discovery.gemini_client import FakeGeminiClient as P1FakeClient  # noqa: E402
from phase_2.contact_discovery.config import Config as P2Config  # noqa: E402
from phase_2.contact_discovery.discovery import run_contact_discovery  # noqa: E402
from phase_2.contact_discovery.gemini_client import FakeGeminiClient as P2FakeClient  # noqa: E402


def _reset_demo_files(handle: RunHandle, *paths_to_clear: Path) -> None:
    """Delete demo CSVs so a dry run always starts as a fresh campaign."""
    for path in paths_to_clear:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            handle.log.emit(f"[demo] could not clear {path.name}: {exc}")
    if paths_to_clear:
        handle.log.emit(f"[demo] reset {', '.join(p.name for p in paths_to_clear)} — fresh simulation.")


class LogBuffer:
    """Thread-safe, append-only log line store."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._lock = threading.Lock()

    def emit(self, line: str) -> None:
        with self._lock:
            self._lines.append(str(line))

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()


class RunHandle:
    """One background run. The UI holds it in session_state."""

    PHASE_LABELS = {
        "phase1": "Phase 1 · Startup discovery",
        "phase2": "Phase 2 · Contact discovery",
        "phase3": "Phase 3 · Email sender",
        "campaign": "Master Campaign Pipeline",
    }

    def __init__(
        self,
        phase: str,
        dry_run: bool = False,
        phase3_mode: str = "preview",
        overrides: dict[str, Any] | None = None,
    ):
        self.phase = phase
        self.dry_run = dry_run
        self.phase3_mode = phase3_mode
        self.overrides: dict[str, Any] = overrides or {}
        self.log = LogBuffer()
        self.stop_event = threading.Event()
        self.finished = threading.Event()
        self.error: str | None = None
        self.result: dict[str, Any] | None = None
        self.started_at = time.time()
        self.thread: threading.Thread | None = None

    @property
    def label(self) -> str:
        suffix = " · DRY RUN" if self.dry_run else ""
        return f"{self.PHASE_LABELS.get(self.phase, self.phase)}{suffix}"

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, target: Callable[["RunHandle", dict], None], settings: dict) -> None:
        self.thread = threading.Thread(target=target, args=(self, settings), daemon=True)
        self.thread.start()

    def request_stop(self) -> None:
        self.stop_event.set()


# --------------------------------------------------------------------------
# Phase 1 — startup discovery
# --------------------------------------------------------------------------

def _build_phase1_config(settings: dict, cities: list[str], overrides: dict) -> P1Config:
    p1 = settings.get("phase1", {})
    cfg = P1Config.from_env().with_overrides(
        model=p1.get("model"),
        batch_size=int(p1.get("batch_size", 5)),
        total_cap=int(p1.get("total_cap", 50)),
        min_hiring_score=int(p1.get("min_hiring_score", 55)),
        max_runs=int(p1.get("max_runs", 20)),
        temperature=float(p1.get("temperature", 0.2)),
        csv_path=p1.get("csv_path"),
        prompt_path=p1.get("prompt_path"),
        cities=tuple(cities),
    )
    return cfg.with_overrides(**overrides)


def run_phase1(handle: RunHandle, settings: dict) -> None:
    try:
        overrides = handle.overrides or {}
        cities = overrides.get("cities") or settings_mod.cities(settings)
        cfg = _build_phase1_config(settings, cities, overrides)

        if handle.dry_run:
            from phase_1.startup_discovery.cli import _build_fake_pool

            cfg = cfg.with_overrides(csv_path=str(paths.DEMO_COMPANIES))
            _reset_demo_files(handle, paths.DEMO_COMPANIES)
            handle.log.emit(
                f"DRY RUN — simulated client, no API calls. "
                f"Cap {cfg.total_cap}, {cfg.batch_size} per batch. Cities: {', '.join(cities) or '—'}."
            )
            client = P1FakeClient(_build_fake_pool(cfg.total_cap * 2 + 10), cfg.batch_size)
        else:
            keys = settings_mod.enabled_keys(settings)
            if not keys:
                raise RuntimeError(
                    "No enabled API keys. Open Settings → API keys and add a Gemini "
                    "(AIza…) or Yandex (AQ… + folder id) key."
                )
            ensure_usable_keys(keys, log_fn=handle.log.emit)
            handle.log.emit(
                f"Live run — model {cfg.model}, cities: {', '.join(cities) or '—'}, "
                f"{len(keys)} enabled key(s)."
            )
            client = RotatingClient(
                keys,
                build_provider_factory(cfg.model, phase=1),
                log_fn=handle.log.emit,
            )

        result = run_discovery(
            client, cfg, log_fn=handle.log.emit, should_stop=handle.stop_event.is_set
        )
        handle.result = result
        handle.log.emit(
            f"=== FINISHED: {result['total_stored']}/{result['target']} companies "
            f"across {result['runs']} run(s) ==="
        )
    except Exception as exc:
        handle.error = str(exc)
        handle.log.emit(f"!!! RUN FAILED: {exc}")
    finally:
        handle.finished.set()


# --------------------------------------------------------------------------
# Phase 2 — contact discovery
# --------------------------------------------------------------------------

def _build_phase2_config(settings: dict, overrides: dict) -> P2Config:
    p2 = settings.get("phase2", {})
    cfg = P2Config.from_env().with_overrides(
        model=p2.get("model"),
        fallback_models=tuple(p2.get("fallback_models") or []),
        max_iterations=int(p2.get("max_iterations", 3)),
        temperature=float(p2.get("temperature", 0.2)),
        limit=p2.get("limit"),
        companies_path=p2.get("companies_path"),
        csv_path=p2.get("csv_path"),
        outcomes_path=p2.get("outcomes_path"),
        prompt_path=p2.get("prompt_path"),
        repeat_prompt_path=p2.get("repeat_prompt_path"),
    )
    return cfg.with_overrides(**overrides)


def run_phase2(handle: RunHandle, settings: dict) -> None:
    try:
        overrides = handle.overrides or {}
        cfg = _build_phase2_config(settings, overrides)

        if handle.dry_run:
            cfg = cfg.with_overrides(
                companies_path=str(paths.DEMO_COMPANIES),
                csv_path=str(paths.DEMO_RESULTS),
                outcomes_path=str(paths.DEMO_OUTCOMES),
            )
            _reset_demo_files(handle, paths.DEMO_RESULTS, paths.DEMO_OUTCOMES)
            handle.log.emit(
                f"DRY RUN — simulated client, no API calls. "
                f"Up to {cfg.max_iterations} iterations per company."
            )
            client = P2FakeClient()
        else:
            keys = settings_mod.enabled_keys(settings)
            if not keys:
                raise RuntimeError(
                    "No enabled API keys. Open Settings → API keys and add a Gemini "
                    "(AIza…) or Yandex (AQ… + folder id) key."
                )
            ensure_usable_keys(keys, log_fn=handle.log.emit)
            chain = ", ".join([cfg.model, *cfg.fallback_models])
            handle.log.emit(
                f"Live run — models: {chain} (fallback on rate limits), "
                f"{len(keys)} enabled key(s)."
            )
            client = RotatingClient(
                keys,
                build_provider_factory(cfg.model, phase=2, phase2_fallback=cfg.fallback_models),
                log_fn=handle.log.emit,
            )

        result = run_contact_discovery(
            client, cfg, log_fn=handle.log.emit, should_stop=handle.stop_event.is_set
        )
        handle.result = result
        handle.log.emit(
            f"=== FINISHED: {result['companies_processed']} company/companies processed, "
            f"{result['contacts_found']} contact(s) stored ==="
        )
    except Exception as exc:
        handle.error = str(exc)
        handle.log.emit(f"!!! RUN FAILED: {exc}")
    finally:
        handle.finished.set()


# --------------------------------------------------------------------------
# Phase 3 — email sender (preview / test only from the UI)
# --------------------------------------------------------------------------

def run_phase3(handle: RunHandle, settings: dict) -> None:
    """Runs send_emails.py in a subprocess and streams its stdout live.

    The UI only ever starts this in a safe mode: ``preview`` (dry-run plan)
    or ``test`` (ONE email to TEST_RECIPIENT). Bulk ``all`` sending is left
    to the CLI on purpose.

    stdout is drained by a separate pump thread so the Stop button stays
    responsive even if the subprocess stalls without writing output.
    """
    mode = handle.phase3_mode or "preview"
    if mode == "all":
        cmd = [sys.executable, str(paths.PHASE3_SEND_SCRIPT), "--mode", "all"]
    elif mode == "test":
        cmd = [sys.executable, str(paths.PHASE3_SEND_SCRIPT), "--mode", "test"]
    else:
        cmd = [sys.executable, str(paths.PHASE3_SEND_SCRIPT), "--mode", "all", "--dry-run"]
    try:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        handle.log.emit(f"$ {' '.join(cmd)}  (cwd: {paths.PHASE3_DIR})")
        proc = subprocess.Popen(
            cmd,
            cwd=str(paths.PHASE3_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None

        def _pump() -> None:
            for line in proc.stdout:
                handle.log.emit(line.rstrip("\n"))

        pump = threading.Thread(target=_pump, daemon=True)
        pump.start()
        stopped = False
        while proc.poll() is None:
            if handle.stop_event.is_set():
                proc.terminate()
                handle.log.emit("Stopped by user.")
                stopped = True
                break
            time.sleep(0.2)
        pump.join(timeout=5)
        if not stopped and proc.returncode not in (0, None):
            handle.log.emit(f"(process exited with code {proc.returncode})")
        handle.log.emit("=== FINISHED ===")
    except Exception as exc:
        handle.error = str(exc)
        handle.log.emit(f"!!! RUN FAILED: {exc}")
    finally:
        handle.finished.set()


def run_campaign(handle: RunHandle, settings: dict) -> None:
    """Runs campaign.py in a subprocess and streams its stdout live."""
    cmd = [sys.executable, "-u", "-m", "phase_3.campaign"]
    if handle.dry_run:
        cmd.append("--dry-run")
    if handle.overrides.get("loop"):
        cmd.append("--loop")
    if handle.overrides.get("batch"):
        cmd.extend(["--batch", str(handle.overrides["batch"])])
    if handle.overrides.get("skip_send"):
        cmd.append("--skip-send")
    if handle.overrides.get("research_ahead"):
        cmd.append("--research-ahead")

    try:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        handle.log.emit(f"$ {' '.join(cmd)}  (cwd: {paths.ROOT})")
        proc = subprocess.Popen(
            cmd,
            cwd=str(paths.ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert proc.stdout is not None

        def _pump() -> None:
            for line in proc.stdout:
                handle.log.emit(line.rstrip("\n"))

        pump = threading.Thread(target=_pump, daemon=True)
        pump.start()
        stopped = False
        while proc.poll() is None:
            if handle.stop_event.is_set():
                proc.terminate()
                handle.log.emit("[campaign] Stopped by user.")
                stopped = True
                break
            time.sleep(0.3)
        pump.join(timeout=5)
        if not stopped and proc.returncode not in (0, None):
            handle.log.emit(f"(process exited with code {proc.returncode})")
        handle.log.emit("=== CAMPAIGN FINISHED ===")
    except Exception as exc:
        handle.error = str(exc)
        handle.log.emit(f"!!! CAMPAIGN RUN FAILED: {exc}")
    finally:
        handle.finished.set()


def make_handle(
    phase: str,
    dry_run: bool,
    phase3_mode: str = "preview",
    overrides: dict | None = None,
) -> RunHandle:
    """Build a handle wired to the right runner and start it."""
    target = {
        "phase1": run_phase1,
        "phase2": run_phase2,
        "phase3": run_phase3,
        "campaign": run_campaign,
    }[phase]
    handle = RunHandle(phase, dry_run=dry_run, phase3_mode=phase3_mode, overrides=overrides or {})
    handle.start(target, settings_mod.load())
    return handle
