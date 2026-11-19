# Email Personalization Plan — Phase 3 (Berlin Startup Outreach)

**Goal:** make every outreach email as unique as the data allows — a reader should
feel the email was written *for their company and for them*, never a mass blast.
**Guardrail:** every field has a fallback. A missing value must produce a slightly
less personal email, **never** a broken one. We raise the floor and the ceiling together.

---

## 0. Data inventory — what we can personalize with (already in the repo)

| Data | Where it lives | What it buys you |
|---|---|---|
| `technical_focus` | Phase 1 CSV | Name their real tech stack in the hook line |
| `why_target` | Phase 1 CSV | A researched, company-specific reason you're writing |
| `current_hiring_evidence` | Phase 1 CSV | Mention active openings honestly ("I see you're hiring…") |
| `relevant_roles` | Phase 1 CSV | Mirror the role titles *they* use |
| `company_size` / `startup_stage` | Phase 1 CSV | "Growing Series B team…" flavor |
| `website` | Phase 1 + 2 CSVs | Verify tone/domain; future live checks |
| `contact_name` | Phase 2 CSV | First-name greeting instead of "Hi {company} team," |
| `sources` (careers URLs) | Phase 1 CSV | Future: link the exact role you saw |

The current email template uses **exactly one** of these (the company name). This
plan exists to use the rest.

---

## 1. Personalization layers (ranked by impact)

### Layer 1 — Greeting: per-person, not per-company
Phase 2 already found named individuals (Malte Kosub, Han Xiao, Ronnie Vuine…).
- If `contact_name` is a real person → `Hi Malte,`
- If it's a role inbox ("Recruiting Team", "General Contact", "Jobs Team") → `Hi Parloa team,`
- Rule: names containing team/contact/press/jobs/security/privacy/datenschutz etc. are treated as role inboxes.

**Impact:** high. The single most humanizing change; a real name in the greeting is
also a strong "not spam" signal for Gmail.

### Layer 2 — Hook line: per-company, research-backed
Replace the generic *"I've been following {company}'s work, and the problems you are
solving align closely with what I want to build my career around"* with a hook built
from `technical_focus` + `why_target` + `current_hiring_evidence`.

Template:
> I'm {sender_name}, an {degree} at {university}. {Company}'s work in {focus}
> — {why_short} — is exactly the space I want to build a career in, and I see you're
> actively hiring for {roles} on your careers page.

**Impact:** the biggest. It's the sentence every recipient reads first, and it's
unique per company by construction.

### Layer 3 — Skills matching: sender ∩ company
Intersect the user's skills (from `.env`) with the company's `technical_focus`.
- Match found → *"My hands-on {Python, ML} experience maps directly to your work in
  {NLP, voice AI}."*
- No match → still reference the focus, without claiming expertise: *"Your work in
  {focus} is exactly what I want to grow into."*
- `SKILLS` in `.env` becomes structured (see §5) so matching is reliable.

### Layer 4 — Role matching: what they hire ∩ what you'll do
Mirror the company's `relevant_roles` when they overlap the user's open roles.
- Overlap → *"I'd be a strong fit for a {Software Engineering Intern} role."*
- No overlap → use the user's own role list verbatim.
- Fallback → the current generic "Working Student or Internship role in AI, software
  engineering, or data".

### Layer 5 — Subject line: company + focus, short
- Current: `Working Student / Intern Application (AI & Software) at Parloa`
- New: `Working Student / Intern at Parloa — Conversational AI` (first term(s) of
  `technical_focus`). Short, specific, no spam words ("Application" can stay, it's neutral).
- Person's first name stays **out** of the subject (name-in-subject reads as spammy).

### Layer 6 — Signature & contact details (user-provided)
Name, phone, reply email, plus (optional, if provided): LinkedIn, GitHub, portfolio.
One link maximum, plain text — no link tracking.

### Layer 7 (optional, maximum ceiling) — Gemini-generated per-company hooks
One cheap API call per company that reads the Phase 1 evidence + the sender profile
and writes a 2-sentence personalized opening, stored in `phase_3/data/email_hooks.csv`.
The template injects it verbatim. Reuses the Phase 1/2 Gemini client patterns; a
`NO_HOOK` outcome falls back to Layer 2. This is the ceiling of personalization
without live-scraping each company's job board.

---

## 2. Concrete before / after (real data)

### Parloa → contact "Malte Kosub"
**Before:**
> Subject: Working Student / Intern Application (AI & Software) at Parloa
> Hi Parloa team, … I've been following Parloa's work, and the problems you are solving align closely with what I want to build my career around.

**After:**
> Subject: Working Student / Intern at Parloa — Conversational AI
> Hi Malte,
> I'm Meetkumar, an M.Sc. Artificial Intelligence student at BTU Cottbus-Senftenberg.
> Parloa's work in Conversational AI — NLP and voice AI for customer-facing teams —
> is exactly the space I want to build a career in, and I see you're actively hiring
> working students on your careers portal.
> My hands-on Python and ML experience maps directly to what your team does, and I'd
> be a strong fit for your Working Student – Conversational AI / Software Engineering
> roles.

### Micropsi Industries → contact "Ronnie Vuine"
**After:**
> Subject: Working Student / Intern at Micropsi Industries — Robotics AI
> Hi Ronnie,
> I'm Meetkumar, an M.Sc. Artificial Intelligence student at BTU Cottbus-Senftenberg.
> Micropsi's robotics-AI work — computer vision and deep reinforcement learning for
> industrial robots — is exactly the space I want to build a career in, and I see
> you're actively hiring on your careers portal.
> My Python and ML background maps directly to your engineering team, and I'd be a
> strong fit for your Working Student AI / Robotics Software Engineer roles.

### Jina AI → contact "Han Xiao"
**After:**
> Subject: Working Student / Intern at Jina AI — Multimodal AI
> Hi Han,
> I'm Meetkumar, an M.Sc. Artificial Intelligence student at BTU Cottbus-Senftenberg.
> Jina AI's work in multimodal AI and neural search — with a lean, fully English,
> open-source team — is exactly the space I want to build a career in, and I see
> you're actively hiring across engineering and AI research.
> My Python and ML experience maps directly to your stack, and I'd be a strong fit
> for your AI/ML Working Student or Open Source AI Developer roles.

Each email is unique, names the company's actual tech, and gives a specific reason —
without a single line of live scraping.

---

## 3. Data model change — sender CSV becomes one row per (company, email)

Current format loses the per-email contact name. New format (converter output):

```csv
company_name,email,contact_name,technical_focus,why_target,relevant_roles,current_hiring_evidence,website
Parloa,jobs@parloa.com,Recruiting Team,Conversational AI; Generative AI; NLP; Voice AI,<why_target>,<relevant_roles>,<hiring evidence>,https://www.parloa.com
Parloa,malte@parloa.com,Malte Kosub,<same>,<same>,<same>,<same>,<same>
```

- One row per (company, email) — Phase 2 already produces this shape.
- `contact_name` per row; company-level fields repeated per row (cheap, CSV).
- Semicolon-separated lists; empty cells allowed.
- `read_companies()` in `send_emails.py` is rewritten to read variable columns; the
  priority ordering, blocked-keyword filter, `MAX_PER_COMPANY` cap, and daily cap all
  keep working unchanged on top of the new shape.

**Converter spec** (`phase_3/build_email_list.py`):
1. Read Phase 2 `contact_discovery_results.csv` (one row per contact).
2. Join Phase 1 `discovered_companies.csv` on `company_name` (case-insensitive) →
   pull `technical_focus`, `why_target`, `relevant_roles`, `current_hiring_evidence`, `website`.
3. Drop blocked keywords (`datenschutz@`, `abuse@`, …) — already a sender-side rule;
   do it here too so the file is clean.
4. Write `phase_3/contacts_to_send.csv`.
5. CLI: `python3 build_email_list.py` (+ `--dry-run` prints per-company counts).
   Rerunnable — regenerates the whole file from the CSVs (source of truth).

---

## 4. Template engine changes (`email_text.py`)

All templates keep the same `facts` interface; `facts` gains per-row keys:
`contact_first_name`, `company_hook` (focus + why sentence), `company_roles`,
`company_hiring`, `matched_skills`.

- `subject(facts)` → `Working Student / Intern at {company} — {focus_headline}` (fallback: current subject).
- `plain_body(facts)` / `html_body(facts)` → sections, in order:
  1. Greeting (Layer 1)
  2. Intro: degree + university (user facts)
  3. Hook (Layer 2 / Layer 7 if present)
  4. Skills match line (Layer 3)
  5. Role line (Layer 4)
  6. Availability + German level (user facts)
  7. CTA: one short question + CV mention (already good)
  8. Signature (Layer 6)
- Every `{placeholder}` resolves to a value or a pre-written fallback sentence —
  no empty strings, no "TODO".

---

## 5. Configuration additions (`.env`) — the inputs you'll add

| Key | Example | Used for |
|---|---|---|
| `SKILLS` (structured) | `Python: 3y, PyTorch: 1y, SQL, FastAPI, Docker` | Layer 3 matching |
| `SENDER_ROLES` | `AI Engineering Working Student, Backend Working Student, Data Intern` | Layer 4 matching |
| `SENDER_LOCATION` | `Berlin` | Replaces hardcoded "Based in Berlin" |
| `EDUCATION_EXTRA` (optional) | `Thesis: NLP for…` | One-line depth |
| `LINKEDIN` / `GITHUB` / `PORTFOLIO` (optional) | URLs | Signature |
| `RESUME_PATH` | `phase_3/Lebenslauf_Meetkumar_AI.pdf` | Attachment (currently empty!) |
| `EMAIL_HOOKS_CSV` (optional) | `data/email_hooks.csv` | Layer 7 |

> **Note:** there is no PDF anywhere in the repo right now (`RESUME_PATH=` is empty).
> A resume file must be added before the first real send.

---

## 6. Implementation phases (each independently verifiable)

| Phase | Deliverable | Verify with |
|---|---|---|
| A | `build_email_list.py` converter + new sender CSV | `--dry-run` prints per-company contact counts |
| B | `send_emails.py` reads new schema, carries per-row facts | `--dry-run` shows each recipient + their greeting |
| C | `email_text.py` template v2 with all fallbacks | dry-run previews; audit script |
| D | Skills/roles matching (Layer 3/4) | dry-run shows match vs fallback lines |
| E | (Optional) Gemini hook generation | `email_hooks.csv` populated; `NO_HOOK` falls back |
| F | Personalization audit script | see §7 |
| G | Test send → your inbox | manual |

---

## 7. Verification / acceptance criteria

1. **Personalization audit** (`phase_3/audit_personalization.py`): reads the planned
   recipient list, renders every email via `email_text.py`, asserts:
   - no empty `{}` placeholders, no "TODO", no bare company-name boilerplate hook;
   - ≥90% of emails contain the company's focus terms;
   - all emails with a person-name contact use the first-name greeting.
2. **Dry run** over the full list — read a sample of 5 (Parloa, Micropsi, Jina AI,
   Qdrant, Taktile) and confirm each reads uniquely.
3. **Test email** to your own inbox → must arrive, land in **inbox**, render cleanly,
   attachment opens.
4. **First real batch** `--mode all --limit 5` → watch replies, then let the daily
   cap (30) take over.

## 8. Honest limits (by design)

- No live job-board scraping — `technical_focus` / `why_target` are model-researched
  (Phase 1) and can go stale; re-run Phase 1 periodically to refresh.
- No LinkedIn automation — cold outreach here is email-only.
- Follow-up emails (7 days, referencing the first) are a separate future script, not
  in this plan.
- Per-email *evidence* for Phase 2 emails is not stored (by Phase 2 design) — the
  sender relies on Phase 1's researched evidence, which *is* stored.
