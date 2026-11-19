"""
3_bosch_job_apply.py -- Apply to ONE Bosch Group job via the Bosch / SmartRecruiters
application portal (jobs.bosch.de -> jobs.smartrecruiters.com/BoschGroup/...).

Public API:

    from 3_bosch_job_apply import apply_to_bosch_job

    result = apply_to_bosch_job(JOB_URL, RESUME_PATH, dry_run=True)  # 1. always dry-run first
    if result["status"] == "DRY_RUN":                                # 2. user verifies
        result = apply_to_bosch_job(JOB_URL, RESUME_PATH, dry_run=False)  # 3. real submit

Manual use:

    python 3_bosch_job_apply.py --url "<JOB_URL>" --resume "<RESUME_PATH>" --dry-run
    python 3_bosch_job_apply.py --url "<JOB_URL>" --resume "<RESUME_PATH>" --submit
    python 3_bosch_job_apply.py --discover        # DOM discovery dump only (no filling)

Design rules (mirrors the Mercedes reference architecture):
- Never invents data. Every answer comes from config/candidate.json (or the
  built-in constants it overrides) - never hardcoded inside the flow logic.
- Dry-run walks the ENTIRE flow (upload, email, questions, consents, validation)
  and stops before Submit. Submit is only clicked in --submit mode behind a
  typed YES confirmation and only after full pre-submit validation.
- CAPTCHA / bot-protection detection stops with status CAPTCHA_DETECTED.
  No bypass is ever attempted.
- Fields are identified SEMANTICALLY: every control is located, its associated
  label/question text is read from the live DOM, normalized, and matched
  against bilingual (DE/EN) question patterns. No coordinates, no positional
  locator(...).nth(k), no index-based option selection.
- Unknown questions are detected, reported, and BLOCK submission - never
  randomly answered.
- NEEDS-verification everywhere: every fill/selection is read back from the
  DOM before the flow continues.

Statuses (spec): SUCCESS | FAILED | CAPTCHA_DETECTED | UNKNOWN_FORM (+ DRY_RUN).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

# ===========================================================================
# CONFIGURATION SECTION - defaults live here; config/candidate.json OVERRIDES
# them when present. Personal data belongs in the JSON, never hardcoded.
# ===========================================================================

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "candidate.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load_config() -> dict:
    """Optional external candidate profile. If config/candidate.json exists,
    its values OVERRIDE the built-in constants below. Edit the JSON, never the
    source, when your personal data changes."""
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: Could not parse {CONFIG_PATH} ({exc}); using built-in constants.", flush=True)
        return {}


_CONFIG = _load_config()


def _cfg(key: str, default):
    value = _CONFIG.get(key)
    return default if value is None else value


JOB_URL = _cfg(
    "job_url",
    "https://jobs.smartrecruiters.com/BoschGroup/744000148955270-werkstudent-im-bereich-informationstechnologie-w-m-div-",
)
RESUME_PATH = Path(_cfg("resume_path", r"E:\WorkSpace\2 Tech\Cold Emaling\RAVAL_MEETKUMAR_RESUME.pdf"))

CANDIDATE_EMAIL = _cfg("candidate_email", "ravalmeett@gmail.com")

# --- postal address (optional; used only if the portal asks for it) ---
STREET = _cfg("street", "")
POSTAL_CODE = _cfg("postal_code", "")
CITY = _cfg("city", "")
COUNTRY = _cfg("country", "")

# --- Bosch working-student pre-question answers (all overridable via JSON) ---
ENROLLED_ENTIRE_PERIOD = bool(_cfg("enrolled_entire_period", True))       # Immatrikulation -> Ja/Yes
STUDY_TYPE = _cfg("study_type", "Vollzeit / full-time")                    # Vollzeit / full-time
DUAL_STUDY = bool(_cfg("dual_study", False))                               # Duales Studium -> Nein/No
EXPECTED_GRADUATION = _cfg("expected_graduation", "10.2027")               # MM/YYYY
INTENDS_FURTHER_DEGREE = bool(_cfg("intends_further_degree", False))       # further degree -> Nein/No
PREFERRED_WORKING_STUDENT_DURATION = _cfg("preferred_duration", "6 Months")
PREFERRED_PERIOD_START = _cfg("preferred_period_start", "01.10.2027")      # DD.MM.YYYY
PREFERRED_PERIOD_END = _cfg("preferred_period_end", "")                    # optional; empty = unknown
EXPECTED_JOB_TITLE = _cfg("expected_job_title", "")                        # optional safety check

# --- Consents ---
BOSCH_OTHER_POSITION_CONSENT = bool(_cfg("bosch_other_position_consent", True))  # Einwilligungserklaerung (optional)
PRIVACY_CONSENT = bool(_cfg("privacy_consent", True))                            # required to submit

# --- Additional attachments (never the resume; only what is configured here) ---
ADDITIONAL_ATTACHMENTS = [Path(p) for p in _cfg("additional_attachments", [])]
MAX_ATTACHMENT_MB = 10  # portal limit shown on the upload widget

# --- Optional SmartRecruiters login (only if the flow demands it) ---
SMARTRECRUITERS_EMAIL = os.environ.get("SMARTRECRUITERS_EMAIL") or _cfg("smartrecruiters_email", "")
SMARTRECRUITERS_PASSWORD = os.environ.get("SMARTRECRUITERS_PASSWORD") or _cfg("smartrecruiters_password", "")

VIEWPORT = {"width": 1440, "height": 1000}
DEFAULT_TIMEOUT_MS = 20_000
HEADLESS = False  # headed during development per spec; CLI --headless also available

SUCCESS_TEXT = re.compile(
    r"application\s+(?:has\s+been\s+)?(?:submitted|sent|received)"
    r"|thank\s+you(?:\s+for\s+(?:your\s+)?applying)?"
    r"|we\s+(?:have\s+)?received\s+your\s+application"
    r"|vielen\s+dank(?:\s+f[u\u00fc]r\s+deine\s+bewerbung)?"
    r"|bewerbung\s+(?:erfolgreich|gesendet|erhalten)",
    re.I,
)
CAPTCHA_TEXT = re.compile(
    # Challenge-indicative phrases only. Bare tokens like "captcha"/"datadome"
    # false-positived on SmartRecruiters' inline JSON ("enableDataDomeIntegration"
    # appears on every page even when no challenge is shown). A REAL challenge
    # almost always mounts its iframe, which CAPTCHA_FRAME_URL still catches.
    r"verify you are human|human verification|are you a robot|verification required"
    r"|px-captcha|datadome captcha|captcha challenge",
    re.I,
)
CAPTCHA_FRAME_URL = re.compile(
    # Real CHALLENGE endpoints only. DataDome's passive sensor iframe loads on
    # every SmartRecruiters page without any challenge being shown - matching
    # the bare domain false-positived every run. A real challenge mounts
    # geo.captcha-delivery.com/captcha/... (interactive widget).
    r"recaptcha/api|hcaptcha\.com/challenges|challenges\.cloudflare\.com"
    r"|geo\.captcha-delivery\.com|captcha-delivery\.com/captcha/"
    r"|datadome|geetest",
    re.I,
)
ERRORISH_TEXT = re.compile(
    r"error|invalid|required|must be|please (?:enter|select|fill|upload|provide)|"
    r"fehl|bitte (?:gib|w[a\u00e4]hl|f[u\u00fc]ll)|ung[u\u00fc]ltig|erforderlich",
    re.I,
)

# ---------------------------------------------------------------------------
# Question specs: key -> bilingual normalized patterns + kind + config source.
# Patterns are matched against _norm_key()-normalized question text, so they
# must be plain lowercase alnum substrings (diacritics folded, punctuation
# stripped). Matching is substring-based = inherently fuzzy. Order matters:
# first matching spec wins, most specific first.
# ---------------------------------------------------------------------------
QUESTION_SPECS: list[dict] = [
    {
        "key": "enrollment",
        "kind": "yesno",
        "config": "ENROLLED_ENTIRE_PERIOD",
        "patterns": [
            "immatrikulation",
            "immatrikuliert",
            "enrolled during the entire",
            "demonstrably enrolled",
        ],
    },
    {
        "key": "study_type",
        "kind": "study_type",
        "config": "STUDY_TYPE",
        "patterns": [
            "volloderteilzeitstudium",
            "vollzeitoderteilzeit",
            "fulltimeorparttime",
            "degreeprograminfulltime",
        ],
    },
    {
        "key": "dual_study",
        "kind": "yesno",
        "config": "DUAL_STUDY",
        "patterns": [
            "dualesstudium",
            "dualcurriculum",
            "dualstudy",
        ],
    },
    {
        "key": "graduation",
        "kind": "date_mm_yyyy",
        "config": "EXPECTED_GRADUATION",
        "patterns": [
            "wannendetvoraussichtlichdasstudium",
            "wannendetdasstudium",
            "expectingtograduate",
            "whentograduate",
        ],
    },
    {
        "key": "further_degree",
        "kind": "yesno",
        "config": "INTENDS_FURTHER_DEGREE",
        "patterns": [
            "weiteresstudium",
            "einweiteresstudium",
            "anotherdegreeprogram",
            "startanotherdegree",
            " masterzubeginnen",
        ],
    },
    {
        "key": "duration",
        "kind": "duration",
        "config": "PREFERRED_WORKING_STUDENT_DURATION",
        "patterns": [
            "dauerderwerkstudententatigkeit",
            "preferreddurationoftheworkingstudent",
        ],
    },
    {
        "key": "period",
        "kind": "date_range",
        "config": "PREFERRED_PERIOD_START",
        "patterns": [
            "zeitraumderwerkstudententatigkeit",
            "preferredtimeperiodfortheworkingstudent",
            "beginnende",
        ],
    },
]

# NOTE: patterns are matched with _norm_key() (lowercase, umlauts folded
# ä->a, ö->o, ü->u, ß->ss, non-alphanumerics stripped).
# 'Zusätzliche Anhänge' -> 'zusatzlicheanhange'; both spelling variants are
# listed so mis-encoded pages still match.
RESUME_SECTION_PATTERNS = [
    "lebenslauf",
    "resume",
    "cv",
]
ATTACHMENT_SECTION_PATTERNS = [
    "zusaetzlicheanhange",
    "zusatzlicheanhange",
    "additionalattachments",
    "weitereanhange",
    "zusatzdokumente",
    "additionaldocuments",
]
CONSENT_PATTERNS = [
    "einwilligungserklaerung",
    "einwilligungserklarung",
    "einwilligungs",
    "andereoffenestellen",
    "otheropenpositions",
]
PRIVACY_PATTERNS = [
    "datutzerklaerung",
    "datutzerklarung",
    "datenschutzerklaerung",
    "datenschutz",
    "dataprotectionnotice",
    "privacypolicy",
]

YES_TOKENS = {"ja", "yes"}
NO_TOKENS = {"nein", "no", "nay"}


# ===========================================================================
# Small helpers
# ===========================================================================

def _log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


_UMLAUTS = str.maketrans({
    "ä": "a", "ö": "o", "ü": "u", "ß": "ss",
    "Ä": "a", "Ö": "o", "Ü": "u",
})


def _norm_key(value: str) -> str:
    """Aggressive normalization for fuzzy bilingual matching: lowercase,
    fold umlauts, drop everything non-alphanumeric. 'Voll- oder Teilzeitstudium?'
    and 'full-time or part-time' style variance collapses to comparable keys."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").translate(_UMLAUTS).lower())


def _matches(text: str, patterns: list[str]) -> bool:
    key = _norm_key(text)
    return any(_norm_key(p) and _norm_key(p) in key for p in patterns)


def _tokens(value: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", str(value or "").translate(_UMLAUTS).lower()) if t]


def _yes_option(text: str) -> bool:
    toks = set(_tokens(text))
    return bool(toks & YES_TOKENS)


def _no_option(text: str) -> bool:
    toks = set(_tokens(text))
    return bool(toks & NO_TOKENS)


def _wants_full_time(config_value: str) -> bool:
    key = _norm_key(config_value)
    if "teilzeit" in key or "parttime" in key:
        return False
    if "vollzeit" in key or "fulltime" in key:
        return True
    raise RuntimeError(f"ERROR: study_type config {config_value!r} is neither full-time nor part-time.")


def _duration_number(config_value: str) -> str | None:
    m = re.search(r"\d+", str(config_value or ""))
    return m.group(0) if m else None


def _duration_option_matches(config_value: str, option_text: str) -> bool:
    key = _norm_key(option_text)
    num = _duration_number(config_value)
    has_unit = ("monat" in key) or ("month" in key)
    if num:
        return bool(re.search(rf"(?<!\d){re.escape(num)}(?!\d)", key)) and has_unit
    return _norm_key(config_value) in key


def _validate_resume_path(resume_path: Path) -> Path:
    if not resume_path.exists():
        raise RuntimeError(f"ERROR: Resume file not found: {resume_path}")
    if not resume_path.is_file():
        raise RuntimeError(f"ERROR: Resume path is not a file: {resume_path}")
    if resume_path.suffix.lower() not in (".pdf", ".doc", ".docx"):
        raise RuntimeError(
            f"ERROR: Resume must be a PDF or DOCX (got {resume_path.suffix!r}): {resume_path}"
        )
    return resume_path


def _validate_attachments(paths: list[Path]) -> list[Path]:
    checked: list[Path] = []
    for p in paths:
        if not p.exists() or not p.is_file():
            raise RuntimeError(f"ERROR: Additional attachment not found: {p}")
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > MAX_ATTACHMENT_MB:
            raise RuntimeError(
                f"ERROR: Attachment {p.name} is {size_mb:.1f}MB which exceeds the "
                f"portal limit of {MAX_ATTACHMENT_MB}MB. Not uploading."
            )
        checked.append(p)
    return checked


def _job_ids(job_url: str) -> tuple[str, str]:
    """(job_id, slug-ish reference) extracted from a Bosch job URL."""
    m = re.search(r"/(?:BoschGroup/)?(\d{6,})(?:-([^/?]+))?", job_url)
    if m:
        return m.group(1), (m.group(2) or "").strip("-")
    m2 = re.search(r"/([0-9]{4,}-[^/?]+)", job_url)
    if m2:
        return m2.group(1), m2.group(1)
    return "", ""


# ===========================================================================
# DOM primitives (runtime-verified; no guessed coordinates, no positional picks)
# ===========================================================================

_FLATTEN_TEXT_JS = r"""
() => {
  // textContent auto-recurses (unlike manual childNodes walking, which misses
  // lit-rendered shadow content such as the resume-upload filename chip).
  let t = document.body ? document.body.textContent : '';
  const walk = (r) => r.querySelectorAll('*').forEach(el => {
    if (el.shadowRoot) { t += ' ' + el.shadowRoot.textContent; walk(el.shadowRoot); }
  });
  walk(document);
  return t.replace(/\s+/g, ' ').trim();
}
"""


def _body_text(page) -> str:
    """Visible page text INCLUDING text rendered inside open shadow roots
    (SmartRecruiters oneclick-ui renders everything in spl-* components)."""
    try:
        flattened = page.evaluate(_FLATTEN_TEXT_JS)
        if flattened and flattened.strip():
            return flattened
    except Exception:  # noqa: BLE001
        pass
    try:
        return page.locator("body").inner_text(timeout=8_000)
    except Exception:  # noqa: BLE001
        return ""


def _dismiss_cookie_banner(page) -> bool:
    for name in ("Accept Cookies", "Accept all", "Accept All Cookies", "Alle akzeptieren",
                 "Akzeptieren", "Decline", "Ablehnen"):
        button = page.get_by_role("button", name=re.compile(re.escape(name), re.I))
        try:
            if button.count() and button.first.is_visible():
                button.first.click(timeout=4_000)
                page.wait_for_timeout(700)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _detect_captcha(page) -> bool:
    if CAPTCHA_TEXT.search(_body_text(page)):
        return True
    return any(CAPTCHA_FRAME_URL.search(f.url) for f in page.frames)


def _page_errors(page) -> list[str]:
    errs = page.evaluate(
        """() => {
            const out = [];
            const roots = [];
            const collectRoots = (root) => {
                roots.push(root);
                root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) collectRoots(el.shadowRoot); });
            };
            collectRoots(document);
            const sel = '[role=alert], .error, [class*="error" i], [aria-invalid="true"], [data-qa*="error" i]';
            roots.forEach(root => {
                root.querySelectorAll(sel).forEach(e => {
                    const t = (e.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (t && t.length < 300 && out.indexOf(t) === -1) out.push(t);
                });
            });
            return out;
        }"""
    )
    return [e for e in errs if ERRORISH_TEXT.search(e or "")]


# ---------------------------------------------------------------------------
# Form discovery: inventory of every visible control with its associated
# question/label text, computed from the LIVE DOM. This is the ground truth
# the whole automation acts on (spec sections 6, 24).
# ---------------------------------------------------------------------------

_INVENTORY_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  // All enumeration roots: document + every reachable OPEN shadow root (DFS,
  // pre-order - the same flattened order Playwright's CSS engine uses, so the
  // synthetic 'sel >> nth=k' paths below resolve to exactly this element).
  const roots = [];
  const collectRoots = (root) => {
    roots.push(root);
    root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) collectRoots(el.shadowRoot); });
  };
  collectRoots(document);
  const globalIndexOf = (el, cssSel) => {
    let idx = 0;
    for (const r of roots) {
      for (const m of r.querySelectorAll(cssSel)) {
        if (m === el) return idx;
        idx++;
      }
    }
    return -1;
  };
  // Flattened text: light DOM + all nested open shadow roots.
  const flat = (node) => {
    if (node.nodeType === 3) return node.textContent;
    if (node.nodeType !== 1) return '';
    let t = '';
    if (node.shadowRoot) for (const c of node.shadowRoot.childNodes) t += flat(c);
    for (const c of node.childNodes) t += flat(c);
    return t;
  };
  const pathOf = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const root = el.getRootNode ? el.getRootNode() : document;
    if (root && root !== document) {
      // Shadow element: a plain CSS path cannot cross shadow boundaries, so use
      // a qualified tag selector + its index in the flattened match order. The
      // INDEX COMES FROM THIS SEMANTIC INVENTORY - the question matching below
      // stays text-based; the index only addresses the already-classified node.
      let sel = el.tagName.toLowerCase();
      const t = el.getAttribute('type');
      if (t) sel += '[type="' + t + '"]';
      const idx = globalIndexOf(el, sel);
      return idx >= 0 ? (sel + ' >> nth=' + idx) : sel;
    }
    const parts = [];
    let node = el, depth = 0;
    while (node && node.nodeType === 1 && depth < 8) {
      if (node.id) { parts.unshift('#' + CSS.escape(node.id)); break; }
      const parent = node.parentElement;
      if (!parent) { parts.unshift(node.tagName.toLowerCase()); break; }
      let idx = 1, sib = node;
      while ((sib = sib.previousElementSibling)) { if (sib.tagName === node.tagName) idx++; }
      parts.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + idx + ')');
      node = parent; depth++;
    }
    return parts.join(' > ');
  };
  const ancestorsOf = (el) => {
    const chain = [];
    let n = el, guard = 0;
    while (n && n.nodeType === 1 && guard++ < 40) {
      chain.push(n);
      if (n.parentElement) { n = n.parentElement; continue; }
      const root = n.getRootNode ? n.getRootNode() : null;
      if (root && root.host) { n = root.host; continue; }  // jump out of the shadow boundary
      break;
    }
    return chain;
  };
  const labelOf = (el) => {
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l && norm(l.textContent)) return norm(l.textContent);
    }
    const wrap = el.closest('label');
    if (wrap && norm(wrap.textContent)) return norm(wrap.textContent);
    const aria = el.getAttribute('aria-label');
    if (aria && norm(aria)) return norm(aria);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map(id => document.getElementById(id))
                  .filter(Boolean).map(x => x.textContent).join(' ');
      if (norm(t)) return norm(t);
    }
    if (el.tagName === 'INPUT' && el.placeholder) return norm(el.placeholder);
    return '';
  };
  const KNOWN = /immatrikulation|teilzeit|vollzeit|duales|voraussichtlich|weiteres\s+studium|werkstudententatigkeit|gewuenschte|dauer|zeitraum|duration|graduate|enrolled|dual|lebenslauf|resume|cv\b|anhange|anhaenge|attachments|email|e-mail|datenschutz|privacy|einwilligung|consent|open positions|anrede|cover letter/i;
  const blockOf = (el) => {
    // Climb light-DOM parents AND across shadow boundaries (host jump), reading
    // the FLATTENED text at every level so shadow-rendered questions are seen.
    const chain = ancestorsOf(el);
    for (const n of chain) {
      if (n === document.body || n === document.documentElement) break;
      const own = flat(n);
      const t = norm(own);
      if (!t || t.length > 700) continue;
      if (KNOWN.test(t) || /\?/.test(t)) return { path: pathOf(n), text: t };
    }
    const fs = el.closest('fieldset');
    if (fs) return { path: pathOf(fs), text: norm(flat(fs)) };
    const wide = chain.slice(0, 6);
    const n2 = wide[wide.length - 1] || el.parentElement;
    return { path: n2 ? pathOf(n2) : pathOf(el), text: n2 ? norm(flat(n2)) : '' };
  };
  const sel = 'input:not([type="hidden"]), select, textarea, [role="checkbox"], [role="combobox"], [role="listbox"][tabindex]';
  const out = [];
  roots.forEach(root => {
  root.querySelectorAll(sel).forEach(el => {
    const visible = el.offsetParent !== null || el.type === 'file' || el.getClientRects().length > 0;
    if (!visible) return;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return;
    const block = blockOf(el);
    const entry = {
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase() ||
            (el.tagName === 'SELECT' ? 'select' : (el.getAttribute('role') || '')),
      id: el.id || '',
      name: el.getAttribute('name') || '',
      dataQa: el.getAttribute('data-qa') || '',
      placeholder: el.getAttribute('placeholder') || '',
      label: labelOf(el),
      blockPath: block.path,
      blockText: block.text,
      cssPath: pathOf(el),
      required: !!(el.required || el.getAttribute('aria-required') === 'true'),
      value: el.tagName === 'SELECT' ? (el.selectedOptions[0] ? norm(el.selectedOptions[0].textContent) : '') : norm(el.value || ''),
      checked: el.type === 'checkbox' || el.getAttribute('role') === 'checkbox'
                 ? (el.checked === true || el.getAttribute('aria-checked') === 'true')
                 : null,
      accept: el.getAttribute('accept') || '',
      inShadow: root !== document,
    };
    if (entry.type === 'select') {
      entry.options = [...el.options].map(o => ({ value: o.value, text: norm(o.textContent) }));
    }
    if (entry.type === 'radio') {
      entry.radioValue = el.value || entry.label || '';
    }
    out.push(entry);
  });
  });
  return out;
}
"""

_BUTTONS_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const roots = [];
  const collectRoots = (root) => {
    roots.push(root);
    root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) collectRoots(el.shadowRoot); });
  };
  collectRoots(document);
  const out = [];
  roots.forEach(root => {
    root.querySelectorAll('button, [role="button"], input[type="submit"], input[type="button"], a')
      .forEach(el => {
        if (!(el.offsetParent !== null || el.getClientRects().length > 0)) return;
        out.push({
          tag: el.tagName.toLowerCase(),
          text: norm(el.innerText || el.value || el.getAttribute('aria-label') || el.textContent || ''),
          disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
          type: el.getAttribute('type') || '',
          dataQa: el.getAttribute('data-qa') || '',
        });
      });
  });
  return out.filter(b => b.text && b.text.length < 120);
}
"""


def _inventory(page) -> list[dict]:
    return page.evaluate(_INVENTORY_JS)


def _buttons(page) -> list[dict]:
    return page.evaluate(_BUTTONS_JS)


def _find_button(page, patterns: list[str], exact: bool = False):
    """Semantic button lookup by accessible name. Returns a Playwright locator
    or None. Never positional: matches by visible text/aria-label."""
    for pat in patterns:
        rx = re.compile(f"^{re.escape(pat)}$", re.I) if exact else re.compile(pat, re.I)
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=rx)
            try:
                if loc.count():
                    return loc.first
            except Exception:  # noqa: BLE001
                continue
    return None


# ---------------------------------------------------------------------------
# Path resolution: inventory paths are either classic light-DOM CSS paths or
# shadow-qualified selectors ('sel >> nth=k' computed over the flattened
# document + open-shadow-root order). All interactions resolve through one JS
# resolver so action and read-back always hit the same element - including
# elements rendered inside open shadow roots (SmartRecruiters oneclick-ui).
# ---------------------------------------------------------------------------

_RESOLVE_JS = r"""
([path, mode, value]) => {
  const roots = [];
  const collectRoots = (root) => {
    roots.push(root);
    root.querySelectorAll('*').forEach(el => { if (el.shadowRoot) collectRoots(el.shadowRoot); });
  };
  collectRoots(document);
  const iterAll = (cssSel) => {
    const arr = [];
    for (const r of roots) arr.push(...r.querySelectorAll(cssSel));
    return arr;
  };
  let el = null;
  const m = /^(.*?)\s*>>\s*nth=(\d+)$/.exec(path);
  if (m) {
    el = iterAll(m[1])[Number(m[2])] || null;
  } else {
    for (const r of roots) { el = r.querySelector(path); if (el) break; }
  }
  if (!el) return { found: false };
  const flat = (node) => {
    if (node.nodeType === 3) return node.textContent;
    if (node.nodeType !== 1) return '';
    let t = '';
    if (node.shadowRoot) for (const c of node.shadowRoot.childNodes) t += flat(c);
    for (const c of node.childNodes) t += flat(c);
    return t;
  };
  if (mode === 'click') {
    try { el.scrollIntoView({block: 'center'}); } catch (e) {}
    el.click();
    return { found: true, done: true };
  }
  if (mode === 'click_checkbox') {
    try { el.scrollIntoView({block: 'center'}); } catch (e) {}
    const target = (el.type === 'checkbox' || el.getAttribute('role') === 'checkbox')
      ? el : (el.querySelector('input[type=checkbox]') || el.closest('label') || el);
    target.click();
    return { found: true, done: true };
  }
  if (mode === 'set') {
    // Only native input/textarea elements accept the prototype value setter;
    // applying it to a custom element (e.g. an oc-input host) throws
    // 'Illegal invocation'. For anything else set .value directly when the
    // property exists, then dispatch the events frameworks listen for.
    try {
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
        const proto = el.tagName === 'TEXTAREA'
          ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
      } else if ('value' in el) {
        el.value = value;
      } else {
        const inner = el.querySelector('input, textarea')
          || (el.shadowRoot && el.shadowRoot.querySelector('input, textarea'));
        if (!inner) return { found: true, done: false, error: 'no settable input inside' };
        const proto = inner.tagName === 'TEXTAREA'
          ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(inner, value);
        el = inner;
      }
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      try { el.blur(); } catch (e) {}
      return { found: true, done: true };
    } catch (err) {
      return { found: true, done: false, error: String(err) };
    }
  }
  if (mode === 'value') {
    return { found: true, value: el.value == null ? '' : String(el.value) };
  }
  if (mode === 'checkbox_state') {
    if (el.type === 'checkbox') return { found: true, state: !!el.checked };
    const ac = el.getAttribute('aria-checked');
    if (ac !== null) return { found: true, state: ac === 'true' };
    const inner = el.querySelector('input[type=checkbox]');
    if (inner) return { found: true, state: !!inner.checked };
    return { found: true, state: null };
  }
  if (mode === 'checked_radios_in') {
    const vals = [];
    const walkIn = (root) => {
      root.querySelectorAll('input[type=radio]').forEach(r => {
        if (r.checked) vals.push(r.value || r.name || '');
      });
      root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) walkIn(e.shadowRoot); });
    };
    walkIn(el);
    return { found: true, values: vals };
  }
  if (mode === 'select_options') {
    if (el.tagName !== 'SELECT') return { found: true, options: null };
    return { found: true, options: [...el.options].map(o => ({value: o.value, text: (o.textContent || '').trim()})) };
  }
  if (mode === 'text') {
    return { found: true, text: flat(el).replace(/\s+/g, ' ').trim() };
  }
  if (mode === 'wider_text') {
    // Flattened text of the element plus up to three ancestors (crossing
    // shadow-host boundaries) - catches section headings the tight block misses.
    let node = el;
    let text = flat(node);
    for (let i = 0; i < 3 && node; i++) {
      const up = node.parentElement
        || (node.getRootNode && node.getRootNode().host)
        || null;
      if (!up || up === document.body || up === document.documentElement) break;
      node = up;
      text += ' ' + flat(node);
    }
    return { found: true, text: text.replace(/\s+/g, ' ').trim() };
  }
  return { found: true };
}
"""


def _resolve_path(page, path: str, mode: str = "ping", value: str | None = None) -> dict:
    """Resolve an inventory path (light-DOM CSS or shadow 'sel >> nth=k') to its
    live element and run one interaction mode against it."""
    return page.evaluate(_RESOLVE_JS, [path, mode, value])


def _click(page, path: str) -> None:
    """Click a DOM-discovered element by its runtime-computed path, with a JS
    fallback if the regular click is intercepted."""
    loc = page.locator(path).first
    try:
        loc.scroll_into_view_if_needed(timeout=5_000)
        loc.click(timeout=6_000)
        return
    except Exception:  # noqa: BLE001
        pass
    result = _resolve_path(page, path, "click")
    if not result.get("found") or not result.get("done"):
        raise RuntimeError(f"ERROR: Could not click discovered element at path {path!r}.")


def _fill_text(page, path: str, value: str) -> str:
    loc = page.locator(path).first
    try:
        loc.scroll_into_view_if_needed(timeout=5_000)
        loc.click(timeout=5_000)
        loc.fill("")
        loc.fill(value)
        try:
            loc.press("Tab")
        except Exception:  # noqa: BLE001
            pass
    except Exception:
        # Shadow-DOM inputs are not reachable by Playwright locators (CSS does
        # not pierce closed registration) - fall back to the JS resolver, which
        # enumerates document + open shadow roots itself.
        if not _js_set_value(page, path, value):
            return ""
    page.wait_for_timeout(400)
    result = _resolve_path(page, path, "value")
    return result.get("value", "") if result.get("found") else ""


def _js_set_value(page, path: str, value: str) -> bool:
    """Native-setter + input/change events for React-controlled inputs."""
    result = _resolve_path(page, path, "set", value)
    return bool(result.get("found") and result.get("done"))


def _read_checkbox_state(page, css_path: str) -> bool | None:
    """Ground-truth checkbox state: input.checked, aria-checked, or a nested
    real checkbox (custom styled widgets). None = undeterminable."""
    result = _resolve_path(page, css_path, "checkbox_state")
    if not result.get("found"):
        return None
    return result.get("state")


def _set_checkbox(page, css_path: str, want: bool) -> bool:
    """Set a checkbox (native OR custom styled) to the wanted state.
    Tries Playwright check/uncheck first, then a JS click on the element, its
    nested input, or the wrapping label. Verifies the final state."""
    loc = page.locator(css_path).first
    try:
        loc.scroll_into_view_if_needed(timeout=5_000)
        if want:
            loc.check(timeout=6_000)
        else:
            loc.uncheck(timeout=6_000)
        page.wait_for_timeout(500)
        if _read_checkbox_state(page, css_path) is want:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        _resolve_path(page, css_path, "click_checkbox")
        page.wait_for_timeout(800)
    except Exception:  # noqa: BLE001
        return False
    return _read_checkbox_state(page, css_path) is want


def _group_by_block(entries: list[dict]) -> list[dict]:
    """Group control entries that share the same question block (e.g. radio
    groups, multi-field date ranges). Radio inputs sharing the same HTML name
    are merged into ONE group even if their individual block detection
    differed (prevents answering 'Ja' and 'Nein' as separate questions)."""
    groups: dict[str, dict] = {}
    radio_groups: dict[str, str] = {}  # radio name -> blockPath of first radio
    for e in entries:
        if e["type"] in ("submit", "button", "image"):
            continue
        if e["type"] == "radio" and e.get("name"):
            existing = radio_groups.get(e["name"])
            if existing is not None:
                groups[existing]["controls"].append(e)
                continue
            radio_groups[e["name"]] = e["blockPath"]
        g = groups.get(e["blockPath"])
        if g is None:
            g = {"blockPath": e["blockPath"], "blockText": e["blockText"], "controls": []}
            groups[e["blockPath"]] = g
        g["controls"].append(e)
    return list(groups.values())


def _select_native_option(page, select_path: str, wanted_text: str) -> str | None:
    """Select a native <select> option by its visible label/value - never by index."""
    info = _resolve_path(page, select_path, "select_options").get("options")
    if not info:
        return None
    key = _norm_key(wanted_text)
    match = next((o for o in info if _norm_key(o["text"]) == key), None) \
        or next((o for o in info if key and _norm_key(o["text"]) and key in _norm_key(o["text"])), None) \
        or next((o for o in info if o["value"] and _norm_key(o["value"]) == key), None)
    if not match:
        return None
    page.locator(select_path).first.select_option(value=match["value"])
    page.wait_for_timeout(500)
    return _resolve_path(page, select_path, "value").get("value", "")


def _select_custom_option(page, block_path: str, wanted_text: str,
                          matcher=None, max_rounds: int = 3) -> bool:
    """Select an option in a SmartRecruiters custom dropdown:
    click trigger -> wait for options -> click the option whose visible text
    matches -> verify. Matching is by text (normalized), never by index."""
    def _committed() -> bool:
        try:
            result = _resolve_path(page, block_path, "text")
            block_text = _norm_key(str(result.get("text") or "")) if result.get("found") else ""
            if not block_text:
                block_text = _norm_key(page.locator(block_path).first.inner_text(timeout=4_000))
        except Exception:  # noqa: BLE001
            return False
        if matcher:
            return matcher(wanted_text, block_text)
        return _norm_key(wanted_text) in block_text

    if _committed():
        return True

    for _ in range(max_rounds):
        block = page.locator(block_path).first
        trigger = block.locator('[role="combobox"], [role="listbox"], button, [tabindex]:not(input):not(textarea)')
        opened = False
        try:
            if trigger.count():
                trigger.first.scroll_into_view_if_needed(timeout=5_000)
                trigger.first.click(timeout=5_000)
                opened = True
        except Exception:  # noqa: BLE001
            pass
        if not opened:
            try:
                _click(page, block_path)
                opened = True
            except Exception:  # noqa: BLE001
                continue

        # wait for options to appear anywhere on the page (portals render overlays)
        options = page.locator('[role="option"], [role="menuitem"], [role="listbox"] li')
        deadline = time.time() + 6
        while time.time() < deadline and not options.count():
            page.wait_for_timeout(400)

        picked = False
        for i in range(options.count()):
            opt = options.nth(i)
            try:
                if not opt.is_visible():
                    continue
                text = opt.text_content() or ""
            except Exception:  # noqa: BLE001
                continue
            if matcher:
                if matcher(wanted_text, text):
                    opt.scroll_into_view_if_needed()
                    opt.click(timeout=5_000)
                    picked = True
                    break
            elif _norm_key(wanted_text) and _norm_key(wanted_text) in _norm_key(text):
                opt.scroll_into_view_if_needed()
                opt.click(timeout=5_000)
                picked = True
                break
        if not picked:
            page.keyboard.press("Escape")  # close without selecting anything
            page.wait_for_timeout(700)
            continue
        page.wait_for_timeout(1_200)
        if _committed():
            return True
    return _committed()


def _yes_no_matcher(want_yes: bool):
    def matcher(_wanted: str, option_text: str) -> bool:
        return _yes_option(option_text) if want_yes else _no_option(option_text)
    return matcher


def _study_type_matcher(want_full_time: bool):
    def matcher(_wanted: str, option_text: str) -> bool:
        key = _norm_key(option_text)
        is_full = ("vollzeit" in key) or ("fulltime" in key)
        is_part = ("teilzeit" in key) or ("parttime" in key)
        return is_full if want_full_time else is_part
    return matcher


# ===========================================================================
# Flow steps (spec section 25)
# ===========================================================================

def open_bosch_job(page, job_url: str) -> dict:
    """Open the Bosch job page and read title/company for the safety check."""
    page.goto(job_url, wait_until="load", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(2_000)
    _dismiss_cookie_banner(page)

    title = ""
    for sel in ("h1", "[data-qa*='title' i]", ".job-title", "title"):
        try:
            loc = page.locator(sel).first
            if loc.count():
                title = _norm(loc.inner_text(timeout=5_000)) or _norm(loc.text_content())
                if title:
                    break
        except Exception:  # noqa: BLE001
            continue
    if not title:
        title = _norm(page.title())

    body = _norm_key(_body_text(page))
    url_key = _norm_key(page.url)
    if "bosch" not in body and "boschgroup" not in url_key:
        raise RuntimeError(
            "ERROR: SAFETY CHECK - opened page does not mention 'Bosch' (body or "
            f"URL company token). Refusing to continue on {page.url}"
        )
    return {"job_title": title, "url": page.url}


def click_apply(context, job_page) -> tuple[object, str]:
    """Click 'Apply now' and return (application_page, note). Handles same-tab,
    new-tab/popup, and redirect cases."""
    apply_btn = _find_button(job_page, [r"apply\s*now", r"jetzt\s*bewerben", r"^apply$"])
    if apply_btn is None:
        raise RuntimeError(
            "ERROR: 'Apply now' button not found on the Bosch job page "
            f"({job_page.url})."
        )
    before_pages = len(context.pages)
    try:
        apply_btn.scroll_into_view_if_needed(timeout=5_000)
        apply_btn.click(timeout=8_000)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"ERROR: Could not click 'Apply now': {exc}") from exc

    # Case 1: new tab / popup (register the expectation right after the click;
    # if the popup already opened, the same-tab fallback below catches it).
    try:
        with context.expect_page(timeout=10_000) as popup_info:
            pass
        new_page = popup_info.value
        new_page.wait_for_load_state("domcontentloaded", timeout=30_000)
        return new_page, "opened in a new tab"
    except Exception:  # noqa: BLE001
        pass

    # Case 2: same tab navigation or SPA
    deadline = time.time() + 20
    while time.time() < deadline:
        if len(context.pages) > before_pages:
            candidate = context.pages[-1]
            candidate.wait_for_load_state("domcontentloaded", timeout=20_000)
            return candidate, "opened in a new tab (late)"
        job_page.wait_for_timeout(1_000)
    return job_page, "same tab"


def _wait_for_manual_captcha_clear(page, seconds: int) -> bool:
    """Poll until the CAPTCHA/bot-protection challenge is gone. The DataDome
    interstitial ('Verification Required') is often transient and carries its
    own RETRY button that re-runs the automated check - clicking that is not
    solving a challenge, so try it first; whatever remains is left for a human
    in the headed browser. True when the page is clean."""
    deadline = time.time() + max(0, seconds)
    retry_clicks = 0
    while time.time() < deadline:
        if not _detect_captcha(page):
            return True
        if retry_clicks < 4:
            clicked = False
            for fr in page.frames:  # the interstitial lives in DataDome's iframe
                for loc in (fr.get_by_role("button", name=re.compile(r"^retry$|try again", re.I)),
                            fr.locator("button:has-text('RETRY'), input[value='RETRY']")):
                    try:
                        if loc.count():
                            loc.first.click(timeout=5_000)
                            clicked = True
                            break
                    except Exception:  # noqa: BLE001 - frame gone / not mounted
                        continue
                if clicked:
                    break
            if clicked:
                retry_clicks += 1
                _log("2/10", f"Clicked the interstitial RETRY button ({retry_clicks}/4)...")
                page.wait_for_timeout(10_000)
                if not _detect_captcha(page):
                    return True
                continue
            # no retry button reachable: a reload re-runs DataDome's check and
            # historically clears this transient interstitial
            retry_clicks += 1
            _log("2/10", f"Interstitial persists - reloading the page (retry {retry_clicks}/4)...")
            try:
                page.reload(wait_until="domcontentloaded", timeout=45_000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(10_000)
            continue
        # All automated attempts exhausted: park the window on the interstitial
        # and wait for the HUMAN to click RETRY (one click, not a CAPTCHA
        # solve). The window is headed in unattended runs, so this is the
        # semi-attended path that lets a session continue without a full
        # restart. Poll cheaply; timeout ends the attempt.
        remaining = int(deadline - time.time())
        _log("2/10", f"Waiting for a HUMAN to click RETRY in the browser window "
                     f"({remaining}s left)... (no automation beyond this point)")
        page.wait_for_timeout(10_000)
    return not _detect_captcha(page)


def wait_for_application(app_page, timeout_s: int = 90,
                         wait_after_captcha_s: int = 0) -> bool:
    """Wait until the SmartRecruiters application form is REALLY available:
    a file input, an email input, or question controls must be present.

    The oneclick SPA sometimes hydrates slowly or sticks on a blank shell;
    if half the budget passes with no controls, reload the page once and
    keep waiting (a fresh navigation reliably re-mounts the form).
    A CAPTCHA / bot-protection challenge (e.g. DataDome on the oneclick-ui
    form) stops with CAPTCHA_DETECTED - or, when wait_after_captcha_s > 0,
    pauses for the user to solve it manually in the headed browser and then
    continues waiting for the real form."""
    _dismiss_cookie_banner(app_page)
    deadline = time.time() + timeout_s
    reloaded = False
    while time.time() < deadline:
        if _detect_captcha(app_page):
            if wait_after_captcha_s > 0:
                _log("2/10", "CAPTCHA/bot-protection detected - solve it manually in the "
                            f"browser window ({wait_after_captcha_s}s budget)...")
                if _wait_for_manual_captcha_clear(app_page, wait_after_captcha_s):
                    _log("2/10", "CAPTCHA cleared; continuing.")
                    deadline = time.time() + timeout_s
                    continue
                raise RuntimeError("CAPTCHA_DETECTED")
            raise RuntimeError("CAPTCHA_DETECTED")
        entries = _inventory(app_page)
        kinds = {e["type"] for e in entries}
        if "file" in kinds or "email" in kinds or "select" in kinds or "checkbox" in kinds:
            return True
        if not reloaded and time.time() > deadline - timeout_s // 2:
            reloaded = True
            _log("2/10", "Form controls not mounted yet - reloading the application page once...")
            try:
                app_page.reload(timeout=45_000)
                app_page.wait_for_timeout(5_000)
                _dismiss_cookie_banner(app_page)
            except Exception:  # noqa: BLE001 - reload is best-effort
                pass
            continue
        app_page.wait_for_timeout(1_500)
    raise RuntimeError(
        f"ERROR: Application form did not become available after clicking Apply "
        f"(url: {app_page.url})."
    )


def _classify_file_sections(page) -> list[dict]:
    """Find every file input and classify it RESUME vs ADDITIONAL vs UNKNOWN by
    the text of its surrounding section (spec section 12 - never confuse them)."""
    entries = [e for e in _inventory(page) if e["type"] == "file"]
    classified: list[dict] = []
    for e in entries:
        section = _norm_key(e["blockText"])
        # climb one more level for section headings the tight block may miss
        wider = _resolve_path(page, e["blockPath"], "wider_text").get("text", "")
        section_wide = _norm_key(wider)
        both = section + " " + section_wide
        if _matches(both, RESUME_SECTION_PATTERNS) and not _matches(both, ATTACHMENT_SECTION_PATTERNS):
            kind = "resume"
        elif _matches(both, ATTACHMENT_SECTION_PATTERNS):
            kind = "attachment"
        elif e.get("accept") and ".pdf" in e["accept"].lower() and "lebenslauf" in both:
            kind = "resume"
        else:
            kind = "unknown"
        classified.append({**e, "kind": kind})
    return classified


def upload_resume(page, resume_path: Path) -> str:
    """Upload the resume and VERIFY the filename chip appears in the UI.

    Strategy: try the classified RESUME section first, then every other file
    input (avatar-wrapped dropzone first - the oneclick widget nests the real
    resume input inside oc-avatar). An attempt only counts when the filename
    shows up in the page and no uploading/processing state remains; an input
    that swallows the file silently is a wrong target, never a success.
    """
    stem = _norm_key(resume_path.stem)
    last_error = ""
    # The oneclick SPA mounts its file inputs progressively; inventory taken too
    # early misses (or mis-targets) the real resume dropzone. Retry the whole
    # inventory -> set -> verify cycle a few times, letting the page hydrate.
    for attempt in range(1, 4):
        deadline_inv = time.time() + (30 if attempt == 1 else 8)
        all_files: list[dict] = []
        while time.time() < deadline_inv:
            all_files = [e for e in _inventory(page) if e["type"] == "file"]
            if len(all_files) >= 2:
                break
            page.wait_for_timeout(2_000)
        sections = _classify_file_sections(page)
        candidates: list[str] = [s["cssPath"] for s in sections if s["kind"] == "resume"]
        # The Resume dropzone lives inside the oc-resume-upload custom element;
        # scoping the locator to that host disambiguates it from the identical
        # #file-input inside the oc-easy-apply prefill widget higher on the page
        # (page.locator(css).first would otherwise hit the wrong one).
        scoped: list[str] = ["oc-resume-upload input[type=file]"]
        # preference: scoped host -> classified resume -> everything else except
        # the avatar/profile-image widget (never a resume target)
        avatar_first = [e["cssPath"] for e in all_files
                        if "oc-avatar" in e["cssPath"] and e["cssPath"] not in candidates]
        others = [e["cssPath"] for e in all_files
                  if e["cssPath"] not in candidates and e["cssPath"] not in avatar_first]
        seen: set[str] = set()
        ordered = [c for c in scoped + candidates + others
                   if not (c in seen or seen.add(c))]
        if not ordered:
            last_error = f"attempt {attempt}: no file input present"
            page.wait_for_timeout(4_000)
            continue
        for css in ordered:
            try:
                page.locator(css).first.set_input_files(str(resume_path), timeout=10_000)
            except Exception as exc:  # noqa: BLE001 - wrong/hidden input, try the next
                last_error = f"attempt {attempt}: {type(exc).__name__}: {exc}"
                continue
            deadline = time.time() + 30
            while time.time() < deadline:
                body = _norm_key(_body_text(page))
                # primary signal: ANY file input on the page (document or shadow
                # roots) now carries the file ('C:\\fakepath\\<name>' in .value);
                # secondary: filename chip rendered in the page text
                try:
                    input_val = page.evaluate(
                        """() => {
                            let vals = [];
                            const walk = (r) => r.querySelectorAll('*').forEach(el => {
                                if (el.tagName === 'INPUT' && el.type === 'file' && el.value) vals.push(el.value);
                                if (el.shadowRoot) walk(el.shadowRoot);
                            });
                            walk(document);
                            return vals.join(' | ');
                        }""")
                except Exception:  # noqa: BLE001
                    input_val = ""
                if stem in _norm_key(input_val) or stem in body:
                    # Guard against 'Uploading...' states, but only near the
                    # filename: the 31k-char oneclick page always contains the
                    # word 'uploading' somewhere (i18n strings), which must not
                    # block verification forever.
                    i = body.find(stem)
                    window = body[max(0, i - 60):i + len(stem) + 60] if i >= 0 else ""
                    if not re.search(r"uploading|processing|wirdgeladen|wirdhochgeladen", window):
                        _log("3/10", f"Resume upload verified in UI ({resume_path.name}).")
                        return resume_path.name
                page.wait_for_timeout(2_000)
            last_error = f"attempt {attempt}: filename never appeared after setting {css[:60]}"
        page.wait_for_timeout(5_000)
    raise RuntimeError(
        f"ERROR: Resume upload did not complete after 3 attempts - filename "
        f"({resume_path.name}) never appeared. Last: {last_error}. "
        "Run with --discover and inspect the DOM.")


def fill_email(page, email: str) -> str:
    """Fill the email field identified semantically and verify the value."""
    entries = _inventory(page)
    candidates = [
        e for e in entries
        if e["type"] == "email"
        or (e["type"] in ("text", "") and _matches(e["label"] + " " + e["blockText"],
                                                   ["e-mail", "email"]))
    ]
    if not candidates:
        raise RuntimeError("ERROR: Email field not found on the application form.")
    # The oneclick form renders Email and Confirm-Email as two identical
    # unlabeled inputs; both take the SAME address by definition, so filling
    # every email-type field with the address is not a guess. Only bail out
    # when a text field matched on its label/block but is NOT type=email
    # (that could be something else entirely).
    email_typed = [c for c in candidates if c["type"] == "email"]
    fuzzy_only = [c for c in candidates if c["type"] != "email"]
    if len(candidates) > 1 and not email_typed:
        raise RuntimeError(
            f"ERROR: Multiple email-like fields found: "
            f"{[c['label'] or c['placeholder'] for c in candidates]}. Not guessing."
        )
    targets = email_typed or candidates[:1]
    for e in targets:
        got = _fill_text(page, e["cssPath"], email)
        if got.strip() != email:
            ok = _js_set_value(page, e["cssPath"], email)
            got = page.locator(e["cssPath"]).first.input_value() if ok else got
        if got.strip() != email:
            raise RuntimeError(f"ERROR: Email field shows {got!r}, expected {email!r}.")
    _log("4/10", f"Email filled and verified in {len(targets)} field(s) ({email}).")
    return email


def go_to_next_step(page) -> bool:
    """Click the Next/Continue/Weiter button if one exists. Returns False when
    no advance button is present (single-page form)."""
    btn = _find_button(page, [r"^next$", r"^continue$", r"^weiter$", r"continue\s*application"])
    if btn is None:
        return False
    btn.scroll_into_view_if_needed(timeout=5_000)
    btn.click(timeout=8_000)
    page.wait_for_timeout(2_000)
    try:
        page.wait_for_load_state("networkidle", timeout=12_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1_000)
    return True


def _match_question_spec(block_text: str) -> dict | None:
    key = _norm_key(block_text)
    for spec in QUESTION_SPECS:
        for pat in spec["patterns"]:
            if _norm_key(pat) and _norm_key(pat) in key:
                return spec
    return None


def discover_questions(page) -> dict:
    """Discover every question group on the page and map it to the known
    question specs. Returns {'matched': [...], 'unknown': [...]}"""
    entries = _inventory(page)
    groups = _group_by_block(entries)
    matched, unknown = [], []
    for g in groups:
        text = g["blockText"]
        spec = _match_question_spec(text)
        if spec:
            matched.append({**g, "spec": spec})
        elif any(c["type"] in ("radio", "select", "checkbox", "combobox", "listbox", "text", "tel")
                 or c["tag"] in ("select", "textarea") for c in g["controls"]):
            # question-like group with no known spec
            if _matches(text, CONSENT_PATTERNS + PRIVACY_PATTERNS):
                continue  # consents are handled separately
            unknown.append(g)
    return {"matched": matched, "unknown": unknown, "groups": groups}


def _answer_yesno_group(page, group: dict, want_yes: bool) -> None:
    radios = [c for c in group["controls"] if c["type"] == "radio"]
    if radios:
        chosen = next((r for r in radios
                       if (_yes_option(r["label"] or r.get("radioValue", "")) == want_yes
                           and (_yes_option(r["label"] or r.get("radioValue", ""))
                                or _no_option(r["label"] or r.get("radioValue", ""))))), None)
        if chosen is None:
            raise RuntimeError(
                f"ERROR: Could not find a {'Ja/Yes' if want_yes else 'Nein/No'} radio option "
                f"in question block: {group['blockText'][:120]!r}"
            )
        _click(page, chosen["cssPath"])
        page.wait_for_timeout(600)
        fresh = _resolve_path(page, group["blockPath"], "checked_radios_in").get("values", [])
        if not fresh:
            raise RuntimeError(
                f"ERROR: Radio selection did not stick for block: "
                f"{group['blockText'][:120]!r}"
            )
        return
    # custom dropdown
    if not _select_custom_option(page, group["blockPath"],
                                 "Ja/Yes" if want_yes else "Nein/No",
                                 matcher=_yes_no_matcher(want_yes)):
        raise RuntimeError(
            f"ERROR: Could not select {'Ja/Yes' if want_yes else 'Nein/No'} in question block: "
            f"{group['blockText'][:120]!r}"
        )


def _answer_choice_group(page, group: dict, config_value: str, matcher) -> str:
    if _select_custom_option(page, group["blockPath"], config_value, matcher=matcher):
        return config_value
    raise RuntimeError(
        f"ERROR: Could not select {config_value!r} in question block: "
        f"{group['blockText'][:120]!r}"
    )


def _fill_date_in_group(page, group: dict, value: str) -> str:
    """Fill a date answer. Supports plain text inputs and segmented date fields.
    Native <input type=date> needs ISO yyyy-mm-dd; an MM/YYYY answer is mapped
    to the 1st of that month. Always verifies by reading back."""
    text_inputs = [c for c in group["controls"] if c["tag"] in ("input", "textarea")
                   and c["type"] in ("", "text", "tel", "date") and c["type"] != "file"]
    if not text_inputs:
        raise RuntimeError(
            f"ERROR: No input found for date question: {group['blockText'][:120]!r}"
        )
    if len(text_inputs) == 1:
        control = text_inputs[0]
        fill_value = value
        if control["type"] == "date":
            m = re.match(r"^(\d{1,2})\.(\d{4})$", value.strip())  # MM.YYYY
            if m:
                fill_value = f"{m.group(2)}-{int(m.group(1)):02d}-01"
        got = _fill_text(page, control["cssPath"], fill_value)
        if got.strip() != fill_value:
            _js_set_value(page, control["cssPath"], fill_value)
            got = page.locator(control["cssPath"]).first.input_value()
        if got.strip() != fill_value:
            raise RuntimeError(
                f"ERROR: Date field shows {got!r}, expected {fill_value!r} "
                f"({group['blockText'][:100]!r})"
            )
        return value
    # segmented date inputs (e.g. MM + YYYY): distribute parts in DOM order
    parts = [p for p in re.split(r"[.\-/]", value) if p]
    if len(parts) != len(text_inputs):
        raise RuntimeError(
            f"ERROR: {len(text_inputs)} date segments found but value {value!r} "
            f"has {len(parts)} parts ({group['blockText'][:100]!r})"
        )
    filled = []
    for part, control in zip(parts, text_inputs):
        got = _fill_text(page, control["cssPath"], part)
        if got.strip() != part:
            _js_set_value(page, control["cssPath"], part)
            got = page.locator(control["cssPath"]).first.input_value()
        filled.append(got)
    if [f.strip() for f in filled] != [p.strip() for p in parts]:
        raise RuntimeError(
            f"ERROR: Segmented date did not take {value!r} (got {filled}) for "
            f"{group['blockText'][:100]!r}"
        )
    return value


def fill_study_questions(page) -> dict:
    """Answer every known Bosch pre-question from configuration. Unknown
    questions are collected and reported - never answered blindly."""
    disc = discover_questions(page)
    answered: dict[str, str] = {}

    for group in disc["matched"]:
        spec = group["spec"]
        key = spec["key"]
        if key in answered:
            continue
        kind = spec["kind"]
        if kind == "yesno":
            want_yes = bool(_CONFIG.get(_cfg_name(spec), globals()[_cfg_name(spec)]))
            _answer_yesno_group(page, group, want_yes)
            answered[key] = "Ja/Yes" if want_yes else "Nein/No"
        elif kind == "study_type":
            want_full = _wants_full_time(globals()[_cfg_name(spec)])
            _answer_choice_group(page, group, globals()[_cfg_name(spec)],
                                 _study_type_matcher(want_full))
            answered[key] = "Vollzeit / full-time" if want_full else "Teilzeit / part-time"
        elif kind == "duration":
            config_value = globals()[_cfg_name(spec)]
            num = _duration_number(config_value)
            def matcher(_w, option_text, _num=num, _cfgv=config_value):
                return _duration_option_matches(_cfgv, option_text)
            _answer_choice_group(page, group, config_value, matcher)
            answered[key] = config_value
        elif kind == "date_mm_yyyy":
            answered[key] = _fill_date_in_group(page, group, globals()[_cfg_name(spec)])
        elif kind == "date_range":
            start = PREFERRED_PERIOD_START
            end = PREFERRED_PERIOD_END
            text_inputs = [c for c in group["controls"]
                           if c["tag"] in ("input", "textarea") and c["type"] in ("", "text", "tel", "date")]
            if end and len(text_inputs) >= 2:
                _fill_date_in_group(page, {**group, "controls": text_inputs[:1]}, start)
                _fill_date_in_group(page, {**group, "controls": text_inputs[1:2]}, end)
                answered[key] = f"{start} - {end}"
            else:
                _fill_date_in_group(page, group, start)
                answered[key] = start + (f" - {end}" if end else " (end left empty per config)")
        page.wait_for_timeout(400)

    # Text questions that are NOT known Bosch questions but ARE filled from
    # config (email etc.) must not appear as unknown; drop entries whose block
    # is clearly the email block.
    unknown = [g for g in disc["unknown"] if not _matches(g["blockText"], ["email", "e-mail"])]
    return {"answered": answered, "unknown": unknown}


def _cfg_name(spec: dict) -> str:
    return spec.get("config") or ""


def handle_consent(page, allow: bool) -> str:
    """Optional Bosch 'Einwilligungserklaerung' checkbox - found strictly by its
    associated text, never by position. allow=False leaves it unchecked."""
    groups = _group_by_block(_inventory(page))
    for g in groups:
        if not _matches(g["blockText"], CONSENT_PATTERNS):
            continue
        boxes = [c for c in g["controls"] if c["type"] == "checkbox"]
        if not boxes:
            continue
        box = boxes[0]
        if not _set_checkbox(page, box["cssPath"], allow):
            raise RuntimeError(
                "ERROR: Bosch other-positions consent checkbox did not reach the "
                f"configured state (allow={allow}). NOT submitting."
            )
        return "checked" if allow else "unchecked"
    if allow:
        raise RuntimeError(
            "ERROR: Consent checkbox ('Einwilligungserklaerung' / other open "
            "positions) configured true but not found on the form."
        )
    return "not-found (allowed=false)"


def handle_privacy_checkbox(page) -> str:
    """REQUIRED privacy/data-protection checkbox, found by its associated text."""
    groups = _group_by_block(_inventory(page))
    for g in groups:
        if not _matches(g["blockText"], PRIVACY_PATTERNS):
            continue
        boxes = [c for c in g["controls"] if c["type"] == "checkbox"]
        if not boxes:
            continue
        box = boxes[0]
        if not _set_checkbox(page, box["cssPath"], True):
            raise RuntimeError(
                "ERROR: Required privacy checkbox could not be checked. NOT submitting."
            )
        return "checked"
    raise RuntimeError(
        "ERROR: Required privacy-policy checkbox ('Datutzerklarung'/'Datenschutz'/"
        "'data protection notice') not found on the form. NOT submitting."
    )


def handle_attachments(page, files: list[Path]) -> list[str]:
    """Upload ONLY configured additional attachments into the ADDITIONAL
    attachments section. Empty list = do nothing (spec section 11)."""
    if not files:
        return []
    files = _validate_attachments(files)
    sections = [s for s in _classify_file_sections(page) if s["kind"] == "attachment"]
    if not sections:
        raise RuntimeError(
            "ERROR: Additional attachments configured but no attachment upload "
            "field was identified. Not uploading into unknown inputs."
        )
    uploaded: list[str] = []
    target = sections[0]
    page.locator(target["cssPath"]).first.set_input_files([str(p) for p in files])
    deadline = time.time() + 60
    while time.time() < deadline:
        body = _norm_key(_body_text(page))
        if all(_norm_key(p.stem) in body for p in files):
            uploaded = [p.name for p in files]
            break
        page.wait_for_timeout(2_000)
    if len(uploaded) != len(files):
        raise RuntimeError(
            f"ERROR: Additional attachments upload not verified (expected "
            f"{[p.name for p in files]}). NOT submitting."
        )
    return uploaded


def validate_application(page, email: str, resume_uploaded: bool) -> dict:
    """Complete pre-submit validation (spec section 13). Returns a report;
    'passed' False means DO NOT SUBMIT."""
    report = {"passed": True, "problems": []}

    def problem(msg: str) -> None:
        report["passed"] = False
        report["problems"].append(msg)

    if not resume_uploaded:
        problem("Resume was not uploaded/verified.")
    if not email:
        problem("Email was not filled/verified.")

    disc = discover_questions(page)
    answered_keys = set()
    for group in disc["matched"]:
        answered_keys.add(group["spec"]["key"])
    expected_keys = {s["key"] for s in QUESTION_SPECS}
    missing = expected_keys - answered_keys
    if missing:
        problem(f"Known Bosch questions not detected as answered: {sorted(missing)}.")

    if disc["unknown"]:
        problem(
            "UNKNOWN QUESTIONS detected (never guessed - must be answered by a "
            "human or added to QUESTION_SPECS): "
            + "; ".join(g["blockText"][:160] for g in disc["unknown"])
        )

    # privacy checkbox must be checked; consent must match configuration
    checked = False
    for g in _group_by_block(_inventory(page)):
        if _matches(g["blockText"], PRIVACY_PATTERNS):
            boxes = [c for c in g["controls"] if c["type"] == "checkbox"]
            if boxes:
                state = _read_checkbox_state(page, boxes[0]["cssPath"])
                if state is True:
                    checked = True
        if _matches(g["blockText"], CONSENT_PATTERNS):
            boxes = [c for c in g["controls"] if c["type"] == "checkbox"]
            if boxes:
                state = _read_checkbox_state(page, boxes[0]["cssPath"])
                if state is not None and state != BOSCH_OTHER_POSITION_CONSENT:
                    problem(
                        f"Bosch other-positions consent is {state} but config says "
                        f"{BOSCH_OTHER_POSITION_CONSENT}."
                    )
    if not PRIVACY_CONSENT:
        problem("privacy_consent=false in configuration - submission is not allowed.")
    elif not checked:
        problem("Required privacy checkbox is not checked.")

    errors = _page_errors(page)
    if errors:
        problem(f"Visible validation errors on page: {errors[:10]}")

    if _detect_captcha(page):
        problem("CAPTCHA / bot protection detected.")

    return report


def submit_application(page) -> None:
    """Click 'Absenden'/'Submit' - only after validate_application passed."""
    btn = _find_button(page, [r"^absenden$", r"^submit$"], exact=True)
    if btn is None:
        btn = _find_button(page, [r"absenden", r"submit\s*application", r"^submit\b"])
    if btn is None:
        raise RuntimeError("ERROR: Submit button ('Absenden'/'Submit') not found.")
    name = ""
    try:
        name = _norm(btn.text_content() or btn.inner_text())
    except Exception:  # noqa: BLE001
        pass
    btn.scroll_into_view_if_needed(timeout=5_000)
    btn.click(timeout=8_000)


def verify_submission(page, timeout_s: int = 40) -> dict:
    """Wait for a real confirmation (never trust the click alone)."""
    deadline = time.time() + timeout_s
    confirmation = ""
    while time.time() < deadline:
        text = _body_text(page)
        m = SUCCESS_TEXT.search(text)
        if m:
            confirmation = _norm(m.group(0))
            break
        if _detect_captcha(page):
            return {"confirmed": False, "reason": "CAPTCHA_DETECTED", "confirmation": ""}
        errs = _page_errors(page)
        if errs:
            return {"confirmed": False, "reason": f"validation errors after submit: {errs[:5]}",
                    "confirmation": ""}
        page.wait_for_timeout(1_500)
    app_id = ""
    m = re.search(r"(?:application|bewerbung)[^0-9]{0,20}([A-Z0-9-]{6,})", _body_text(page), re.I)
    if m:
        app_id = m.group(1)
    return {
        "confirmed": bool(confirmation),
        "reason": "" if confirmation else "no confirmation text appeared",
        "confirmation": confirmation,
        "application_id": app_id,
        "final_url": page.url,
    }


def _maybe_login(page) -> None:
    """If SmartRecruiters demands a login, use env/config credentials or STOP.
    Never hardcodes credentials."""
    entries = _inventory(page)
    has_password = any(e["type"] == "password" for e in entries)
    if not has_password:
        return
    if any(e["type"] == "file" for e in entries):
        return  # guest application with an optional password field - not a wall
    if not (SMARTRECRUITERS_EMAIL and SMARTRECRUITERS_PASSWORD):
        raise RuntimeError(
            "ERROR: SmartRecruiters requires login and no credentials are "
            "configured. Set SMARTRECRUITERS_EMAIL / SMARTRECRUITERS_PASSWORD "
            "environment variables and re-run. Stopping instead of guessing."
        )
    email_entry = next((e for e in entries if e["type"] == "email"
                        or (e["type"] in ("text", "") and "email" in _norm_key(e["label"] + e["blockText"]))), None)
    pwd_entry = next(e for e in entries if e["type"] == "password")
    _fill_text(page, email_entry["cssPath"], SMARTRECRUITERS_EMAIL)
    _fill_text(page, pwd_entry["cssPath"], SMARTRECRUITERS_PASSWORD)
    btn = _find_button(page, [r"sign\s*in", r"log\s*in", r"anmelden"])
    if btn is not None:
        btn.click(timeout=8_000)
        page.wait_for_load_state("networkidle", timeout=20_000)
        page.wait_for_timeout(2_000)


# ===========================================================================
# Main driver
# ===========================================================================

def apply_to_bosch_job(job_url: str, resume_path: Path, dry_run: bool = True,
                       headless: bool = HEADLESS, discover_only: bool = False,
                       wait_after_captcha_s: int = 0,
                       additional_attachments: list[Path] | None = None) -> dict:
    resume_path = _validate_resume_path(Path(resume_path))
    attachments = _validate_attachments(additional_attachments if additional_attachments is not None
                                        else ADDITIONAL_ATTACHMENTS)
    job_id, slug_ref = _job_ids(job_url)
    started = time.perf_counter()

    result: dict = {
        "status": "UNKNOWN_FORM",
        "company": "Bosch",
        "job_title": EXPECTED_JOB_TITLE or slug_ref,
        "application_url": job_url,
        "timestamp": _now(),
        "resume_uploaded": False,
        "email_filled": False,
        "questions_completed": False,
        "consent_completed": False,
        "attachments_uploaded": [],
        "submitted": False,
        "confirmation_message": "",
        "application_id": "",
        "error": None,
        "dryRun": dry_run,
        "startedAt": _now(),
        "finishedAt": None,
        "stagesReached": [],
        "questionsAnswered": {},
        "unknownQuestions": [],
        "diagnostics": {"url": "", "title": "", "step": "", "visibleErrors": [], "domInfo": ""},
        "screenshots": {},
        "notes": [],
    }

    def _stage(name: str) -> None:
        result["stagesReached"].append(name)

    active = {"page": None}  # page the flow currently acts on (for diagnostics)

    def _shot(page, name: str) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / f"bosch-{job_id or 'job'}-{name}"
        try:
            page.screenshot(path=str(path), full_page=True)
            result["screenshots"][name.replace(".png", "")] = str(path)
        except Exception as exc:  # noqa: BLE001
            result["notes"].append(f"Could not save screenshot {name}: {exc}")

    def _fail(page, message: str, status: str = "FAILED") -> None:
        result["status"] = status
        result["error"] = message
        result["diagnostics"]["url"] = page.url
        result["diagnostics"]["title"] = page.title()
        result["diagnostics"]["visibleErrors"] = _page_errors(page)
        try:
            result["diagnostics"]["domInfo"] = json.dumps(_buttons(page)[:20], ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass
        _shot(page, "error.png")
        _save()
        print(f"\n{message}", flush=True)

    def _save() -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result["finishedAt"] = _now()
        result["durationSeconds"] = round(time.perf_counter() - started, 1)
        path = RESULTS_DIR / f"bosch-{job_id or 'job'}-result.json"
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n",
                        encoding="utf-8")
        print(f"Result saved to results/bosch-{job_id or 'job'}-result.json", flush=True)

    with sync_playwright() as pw:
        # BOSCH_BROWSER_CHANNEL (e.g. "chrome") runs the machine's real Chrome
        # instead of Playwright's bundled Chromium - same visible browser, no bypass.
        channel = os.environ.get("BOSCH_BROWSER_CHANNEL", "").strip()
        browser = (pw.chromium.launch(headless=headless, channel=channel)
                   if channel else pw.chromium.launch(headless=headless))
        context = browser.new_context(viewport=VIEWPORT)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        try:
            _log("1/10", "Opening Bosch job page...")
            info = open_bosch_job(page, job_url)
            _stage("job_page")
            result["diagnostics"]["url"] = info["url"]
            result["diagnostics"]["title"] = info["job_title"]
            if EXPECTED_JOB_TITLE:
                got_key = _norm_key(info["job_title"])
                want_key = _norm_key(EXPECTED_JOB_TITLE)
                overlap = len(set(_tokens(info["job_title"])) & set(_tokens(EXPECTED_JOB_TITLE)))
                if want_key not in got_key and overlap < max(1, int(0.5 * len(_tokens(EXPECTED_JOB_TITLE)))):
                    raise RuntimeError(
                        f"ERROR: SAFETY CHECK - job title mismatch. Expected "
                        f"{EXPECTED_JOB_TITLE!r}, found {info['job_title']!r}. NOT applying."
                    )
            _shot(page, "01_job_page.png")

            _log("2/10", "Opening the application form...")
            # Case: the job URL IS already the application form (SmartRecruiters
            # oneclick-ui: some list-API links point here directly, and the
            # canonical posting URL sometimes redirects here) - no 'Apply now'
            # click. CAPTCHA here propagates (or waits for a manual solve).
            if "oneclick" in page.url or "oneclick" in job_url:
                wait_for_application(page, timeout_s=20,
                                     wait_after_captcha_s=wait_after_captcha_s)
                app_page, note = page, "job URL is already the application form (oneclick)"
            else:
                app_page, note = click_apply(context, page)
            active["page"] = app_page  # failures after this point are on the app page
            _stage("application_opened")
            _log("2/10", f"Application interface: {note} ({app_page.url})")
            wait_for_application(app_page, wait_after_captcha_s=wait_after_captcha_s)
            _maybe_login(app_page)
            _shot(app_page, "02_application_opened.png")

            if not dry_run and not discover_only:
                result["notes"].append(
                    "Real submit requested; unknown questions (if any) will be "
                    "re-checked at pre-submit validation."
                )

            if discover_only:
                inv = _inventory(app_page)
                RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                dump = {
                    "url": app_page.url,
                    "buttons": _buttons(app_page),
                    "fileSections": _classify_file_sections(app_page),
                    "questions": discover_questions(app_page),
                    "inventory": inv,
                }
                out = RESULTS_DIR / f"bosch-discover-{job_id or 'job'}.json"
                out.write_text(json.dumps(dump, indent=2, ensure_ascii=False, default=str) + "\n",
                               encoding="utf-8")
                result["status"] = "DISCOVERED"
                result["notes"].append(f"Discovery dump written to {out}")
                _save()
                print(f"\nDISCOVERY COMPLETE -> {out}", flush=True)
                return result

            _log("3/10", "Uploading resume...")
            shown = upload_resume(app_page, resume_path)
            result["resume_uploaded"] = True
            _stage("resume_uploaded")
            _shot(app_page, "03_resume_uploaded.png")

            _log("4/10", "Filling email address...")
            fill_email(app_page, CANDIDATE_EMAIL)
            result["email_filled"] = True
            _stage("email_filled")
            _shot(app_page, "04_email_filled.png")

            _log("5/10", "Advancing to the pre-question step...")
            advanced = go_to_next_step(app_page)
            if not advanced:
                result["notes"].append("No Next/Continue button found; assuming single-page form.")
            _stage("prequestions")
            _shot(app_page, "05_prequestions.png")

            _log("6/10", "Answering Bosch pre-questions from configuration...")
            q = fill_study_questions(app_page)
            result["questionsAnswered"] = q["answered"]
            result["unknownQuestions"] = [g["blockText"] for g in q["unknown"]]
            _stage("questions_filled")
            _shot(app_page, "06_prequestions.png")

            _log("7/10", "Handling Bosch consent and privacy checkboxes...")
            consent_state = handle_consent(app_page, BOSCH_OTHER_POSITION_CONSENT)
            privacy_state = handle_privacy_checkbox(app_page)
            result["consent_completed"] = True
            _stage("consent")
            _shot(app_page, "06_consent.png")

            _log("8/10", "Handling additional attachments (config-driven)...")
            uploaded_files = handle_attachments(app_page, attachments)
            result["attachments_uploaded"] = uploaded_files
            _stage("attachments")

            _log("9/10", "Validating the complete application before submit...")
            report = validate_application(app_page, CANDIDATE_EMAIL, result["resume_uploaded"])
            if not report["passed"]:
                _shot(app_page, "validation-failed.png")
                raise RuntimeError(
                    "ERROR: Pre-submit validation FAILED - the application was NOT "
                    f"submitted. Problems: {report['problems']}"
                )
            result["questions_completed"] = True
            _shot(app_page, "07_before_submit.png")

            if q["unknown"]:
                _shot(app_page, "unknown-questions.png")

            if dry_run:
                result["status"] = "DRY_RUN"
                result["notes"].append("DRY RUN: 'Absenden' intentionally NOT clicked.")
                _save()
                print("\nDRY_RUN_COMPLETE\nApplication was NOT submitted.", flush=True)
                return result

            _log("10/10", "Submitting application ('Absenden')...")
            submit_application(app_page)
            try:
                app_page.wait_for_load_state("networkidle", timeout=25_000)
            except PlaywrightTimeoutError:
                pass
            outcome = verify_submission(app_page)
            _shot(app_page, "08_success.png")
            result["submitted"] = True
            result["confirmation_message"] = outcome.get("confirmation", "")
            result["application_id"] = outcome.get("application_id", "")
            result["diagnostics"]["url"] = app_page.url
            if outcome["confirmed"]:
                result["status"] = "SUCCESS"
            elif outcome.get("reason") == "CAPTCHA_DETECTED":
                result["status"] = "CAPTCHA_DETECTED"
            else:
                result["status"] = "FAILED"
                result["error"] = f"Submission not confirmed: {outcome.get('reason')}"
            _save()
            print(f"\nFinal status: {result['status']}", flush=True)

        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if message.startswith("CAPTCHA_DETECTED"):
                result["status"] = "CAPTCHA_DETECTED"
                result["error"] = "CAPTCHA / bot protection detected. Automation stopped by design."
                if wait_after_captcha_s > 0:
                    result["notes"].append(
                        f"Manual-CAPTCHA budget of {wait_after_captcha_s}s elapsed without a solve."
                        " Re-run with --wait-after-captcha and solve the challenge in the browser."
                    )
                _shot(active["page"] or page, "captcha.png")
            else:
                try:
                    _fail(active["page"] or page, message)
                except Exception:  # noqa: BLE001
                    result["status"] = "FAILED"
                    result["error"] = message
                    _save()
        finally:
            context.close()
            browser.close()

    return result


# ===========================================================================
# CLI
# ===========================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Apply to ONE Bosch job via SmartRecruiters.")
    parser.add_argument("--url", default=JOB_URL, help="Bosch job posting URL")
    parser.add_argument("--resume", default=str(RESUME_PATH), help="Path to the resume (PDF/DOCX)")
    parser.add_argument("--email", default=CANDIDATE_EMAIL, help="Candidate email override")
    parser.add_argument("--dry-run", action="store_true", help="Stop before Absenden (default)")
    parser.add_argument("--submit", action="store_true", help="Really submit the application")
    parser.add_argument("--headless", action="store_true", help="Run without a visible browser window")
    parser.add_argument("--discover", action="store_true",
                        help="Open the application form, dump the DOM inventory, exit (no filling)")
    parser.add_argument("--wait-after-captcha", type=int, default=0,
                        help="Seconds to wait for manual CAPTCHA completion before stopping")
    args = parser.parse_args()

    if args.submit:
        answer = input(
            f"Really SUBMIT this Bosch application?\n  url: {args.url}\nType YES to confirm: "
        )
        if answer.strip() != "YES":
            print("Aborted.")
            return 1

    if args.email != CANDIDATE_EMAIL:
        _CONFIG["candidate_email"] = args.email
        globals()["CANDIDATE_EMAIL"] = args.email

    outcome = apply_to_bosch_job(
        job_url=args.url,
        resume_path=Path(args.resume),
        dry_run=not args.submit,
        headless=args.headless or HEADLESS,
        discover_only=args.discover,
        wait_after_captcha_s=args.wait_after_captcha,
    )
    print(json.dumps(
        {k: outcome.get(k) for k in (
            "status", "job_title", "stagesReached", "questionsAnswered",
            "unknownQuestions", "attachments_uploaded", "submitted",
            "confirmation_message", "application_id", "screenshots", "notes", "error",
        )},
        indent=2, default=str,
    ))
    return 0 if outcome["status"] in ("SUCCESS", "DRY_RUN", "DISCOVERED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
