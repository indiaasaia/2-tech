# Resume Content Generation — Complete Current-Reality Documentation

**Purpose:** This document describes *exactly* how the pipeline generates resume content today —
every API endpoint, every prompt, what is static vs. dynamic, what freedom the model gets, what
is validated, and what is never generated. It is the baseline reference for improving resume
quality / ATS match rate / selection probability later.

**Last verified against code:** September 2026 (steps 4 and 5 as currently in the repo).

---

## Table of contents

1. [Pipeline position and data flow](#1-pipeline-position-and-data-flow)
2. [The LLM API used](#2-the-llm-api-used)
3. [Static vs. dynamic resume components](#3-static-vs-dynamic-resume-components)
4. [What is sent to the model (inputs)](#4-what-is-sent-to-the-model-inputs)
5. [Component 1 — Career Objective](#5-component-1--career-objective)
6. [Component 2 — Experience (two stints)](#6-component-2--experience-two-stints)
7. [Component 3 — Projects (two slots)](#7-component-3--projects-two-slots)
8. [Component 4 — Skills section (four rows)](#8-component-4--skills-section-four-rows)
9. [Freedom the model gets vs. hard truth boundaries](#9-freedom-the-model-gets-vs-hard-truth-boundaries)
10. [Response parsing, auto-correction, and validation](#10-response-parsing-auto-correction-and-validation)
11. [Assembly into PDF/DOCX (Step 5)](#11-assembly-into-pdfdocx-step-5)
12. [Known weaknesses / improvement opportunities](#12-known-weaknesses--improvement-opportunities)

---

## 1. Pipeline position and data flow

Resume content generation is **Step 4** of the 5-step pipeline, followed by **Step 5** which
assembles and compiles the resumes.

```
Step 1  1_fetch_jobs.py          scrape Stepstone + workingstudentjobs.de
                                 -> program_files/output/todays_overall_jobs.csv
Step 2  2_filter_jobs.py         keep only jobs posted yesterday or today
                                 -> program_files/output/2_filted_jobs.csv
Step 3  3_test_ollama_keys.py    validate Ollama API keys
                                 -> sub_program_files/active_ollama_keys.json
Step 4  4_create_resume_components.py     <-- THIS DOCUMENT
        │  runs 4 sub-stages in sub_program_files/resume_content/:
        │    1_career_objective.py -> program_files/output/career_objective.json
        │    2_experience.py       -> program_files/output/experience.json
        │    3_projects.py         -> program_files/output/projects.json
        │    4_skills.py           -> program_files/output/skills.json
Step 5  5_create_resume.py       fill LaTeX template + compile
                                 -> output/resume/tex|pdf|docx/<Job-Title>.{tex,pdf,docx}
                                 -> program_files/output/resume_report.json
```

Step 4 is an orchestrator (`program_files/4_create_resume_components.py`) that imports and runs
the four stage modules. Each stage manages its own `TEST_JOB_LIMIT` constant (`None` = full run).
One stage failing never stops the other stages. Each stage exits 0 only when **zero records are
flagged for review** — a nonzero exit means at least one job's output was flagged.

**Matching key:** all component stores are joined by `job_url` in Step 5. A job gets a resume
only if it has all four components **and** none of them are flagged with an error.

**User manual curation:** after Step 2, the user edits `2_filted_jobs.csv` and deletes rows for
roles they don't want. Step 4 runs only on what remains in that CSV.

---

## 2. The LLM API used

Defined in `sub_program_files/ollama_request_response.py`:

| Setting | Value | Override |
|---|---|---|
| **Endpoint** | `POST https://ollama.com/v1/chat/completions` (OpenAI-compatible chat API) | env `OLLAMA_HOST` |
| **Model** | `gpt-oss:120b` | env `OLLAMA_MODEL` |
| **Auth** | `Authorization: Bearer <token>` | token from key files |
| **Timeout** | 120 seconds per request | — |
| **Payload** | single user message: `{"model": ..., "messages": [{"role": "user", "content": prompt}]}` | — |

Key loading (`load_first_key`): takes the **first key** from
`sub_program_files/active_ollama_keys.json`, falling back to `sub_program_files/ollama_keys.json`.
No rotation — one key is used for the entire run. Keys are produced/validated by Step 3.

Request characteristics:

- **Temperature / sampling:** not set — defaults of the API are used (not configurable from code today).
- **No system message** — everything (role instructions + job data) is in one user message.
- **No conversation history** — every call is stateless; slot-2 prompts receive slot-1 output only
  via a text placeholder (see §7).
- **Retries:** stages 3 (projects) and 4 (skills) retry transient request failures up to 3 times
  with a 3s/6s/9s backoff. Stage 1 (objective) has **no retry**. Stage 2 (experience) has **no retry**.
- **Response size limits are not set** (`max_tokens` absent).

---

## 3. Static vs. dynamic resume components

### STATIC — hard-coded, never generated (in `core_resume_template.tex` and `5_create_resume.py`)

| Resume section | Static content |
|---|---|
| Header | Name **RAVAL MEETKUMAR**, phone +49 15565 468731, email ravalmeett@gmail.com, LinkedIn `meetraval`, GitHub `ravalmeet` |
| Experience 1 header | Company location/date line: `Gujarat, India | Dec'23 -- Jan'25` |
| Experience 2 header | `- Pantechelearning`, `Chennai, India | Dec'21 -- Feb'22` |
| Education | MSc AI, BTU Cottbus-Senftenberg, Germany (April 2025 – Current); BE Computer Engineering, GTU, India (June 2020 – May 2024) |
| Research & Publications | Sarcasm-detection study text (fixed two bullets) |
| Achievements | Smart India Hackathon 2021/2022 runner-up, Azadi ka Amrit Mahotsav 2023, AI Guild Hackathon 2025 Winner |
| Certifications | All Coursera/Udemy/HackerRank certificate links (fixed list) |
| Additional Projects | TradingView-Data Fetch, Nirvana-Food-Managment, Select-Your-Tutor, Shivshivay Himalaya (fixed list) |
| Languages | English C2, German A2, Hindi C2, Gujarati C2 |
| Declaration | Fixed declaration text |
| Fonts/layout | Palatino (`headerfontiii`), A4, 11pt, fixed margins, tcolorbox section headers |

### DYNAMIC — generated per job by the model (four stores)

| Store | File | What is generated |
|---|---|---|
| Career objective | `career_objective.json` | 1 paragraph |
| Experience | `experience.json` | 2 × (role, one-line description, 5–8 skills) |
| Projects | `projects.json` | 2 × (project title, one-line description, 5–8 skills) |
| Skills | `skills.json` | 4 rows (see §8) |

### SEMI-STATIC — static anchor with dynamic text

- Experience 1's role: template line is `\textbf{ROLE-1 - Software Engineer}`; Step 5 replaces the
  whole `ROLE-1 - Software Engineer` token with `"<generated role> - Soham Infotech"`. Company is
  static; the role word is generated.
- Experience 2's role: only `ROLE-2` is replaced; `- Pantechelearning` is already static in the template.
- Skills rows 3 & 4 labels ("SKILLS AREA") are generated category names; rows 1 & 2 labels
  ("Programming Languages", "Specialized Area") are fixed.

---

## 4. What is sent to the model (inputs)

Every prompt (all 4 stages) receives exactly **three job fields** as placeholder substitutions:

| Placeholder | Source | Truncation |
|---|---|---|
| `{{JOB_TITLE}}` | `title` CSV column | none |
| `{{JOB_DESCRIPTION}}` | `job_description` CSV column | first **6,000** chars (`DESCRIPTION_LIMIT`) |
| `{{KEY_REQUIREMENTS}}` | `requirements` + `your_tasks` columns **merged with a space** | first **4,000** chars (`REQUIREMENTS_LIMIT`) |

If `job_description` is empty, the job is **skipped** for that component (recorded with
`skipped: empty job_description`), never retried with less data.

**Notably NOT sent to the model:** the candidate's structured profile file, education details,
company names, dates, location — everything static is baked into the prompt files themselves as
"fixed facts" prose (see §5–8). There is no separate profile JSON consumed by the generators.

**Prompt storage:** `sub_program_files/prompt/` contains 6 markdown files:

- `career_objective_prompt.md` — has a `## PROMPT` marker; only text below it is sent (the top is
  human documentation). Stage 1 requires this marker.
- `experience_1_prompt.md`, `experience_2_prompt.md`, `projects_1_prompt.md`, `projects_2_prompt.md`,
  `skills_prompt.md` — no marker; **the whole file** is sent as the prompt. (Stages 2–4 use
  `load_template`, which sends the entire file when no `## PROMPT` marker exists.)

---

## 5. Component 1 — Career objective

**Stage:** `sub_program_files/resume_content/1_career_objective.py`
**Prompt:** `prompt/career_objective_prompt.md` · **Output:** `career_objective.json`

**Call pattern:** 1 request per job. Output = one plain-text paragraph. The reply is "cleaned":
flattened to one line, Unicode punctuation normalized (en/em dashes → `-`, curly quotes → straight,
non-breaking spaces → space), surrounding quotes stripped.

**What the prompt tells the model:**

- Fixed candidate facts it may use: MSc AI at BTU (Apr 2025–present), BE Computer Engineering GTU
  (2020–2024), ~1 year professional software engineering in India (backend), ongoing LLM sarcasm
  detection research, hackathon wins, Germany-based working-student job search.
- 2–4 sentences, **max 60 words**, no labels/markdown/LaTeX chars/line breaks.
- **Keyword targeting procedure:** silently extract 8–15 ATS keywords from the posting, place the
  4–8 most important naturally; never more than 3 skills in a row; never repeat a keyword more than twice.
- **Exact phrase mirroring:** use the posting's verbatim wording (no paraphrasing keywords);
  spelled-out form with abbreviation in parentheses on first mention.
- **Title usage:** posting's core role title verbatim exactly once, never as the literal first
  words, strip (m/f/d) style suffixes, German titles kept verbatim.
- **Anti-stuffing:** no keyword lists, no filler words (passionate, hardworking, dynamic, results-driven).
- **Truthfulness:** only profile facts; never invent experience years/employers/tools; never claim
  employment at the hiring company; never mention the hiring company's name.
- Style: implied first person (no "I"/"my"), active voice, English, plain ASCII punctuation.
- One worked example of the target *structure* is included (content must not be copied).

**Validation of the output:** NONE beyond the text cleaning. No word-count check (60-word cap is
prompt-only), no keyword verification, no truthfulness check. Any parseable text becomes the objective.

**Exit code:** 1 only if a request *failed* (network/HTTP). Skips don't fail the stage.

---

## 6. Component 2 — Experience (two stints)

**Stage:** `sub_program_files/resume_content/2_experience.py`
**Prompts:** `prompt/experience_1_prompt.md` (Soham Infotech stint) + `prompt/experience_2_prompt.md`
(Pantechelearning internship) · **Output:** `experience.json`

**Call pattern:** **2 requests per job** (one per stint), independent of each other. After both:
if the two stints produced the *same role* → flagged for review ("differentiation"); if the two
skill *sets* are identical → flagged ("authenticity"). **No retry on transient failures** (single attempt).

### Fixed facts the prompt embeds

Stint 1 (Soham Infotech, Gujarat, Dec 2023 – Jan 2025, ~1 year):
backend engineering in a cross-functional team — integrating backend systems, servers, databases to
improve latency, data management, performance. Supported areas: backend/software engineering,
server-side systems, system integration, database work, data management, latency & performance
improvement. **Explicitly not established:** any specific language, framework, tool, DB, cloud,
metric, achievement, project name. The prompt lists "Python/Java/Docker/Kubernetes/AWS/TensorFlow…
are NOT established" and forbids claiming them.

Stint 2 (Pantechelearning, Chennai, Dec 2021 – Feb 2022, 3-month internship):
MySQL for data management/storage supporting ML workflows; backend infrastructure for web apps with
Django and Flask. Supported: MySQL, Django, Flask, database/data management, backend development,
web app development, ML workflow support. Everything else (other DBs, cloud, frontend, DevOps, ML
model engineering, REST API development…) explicitly forbidden. **"Intern" must be in the role.**

### Freedom given to the model (both stints)

- **ROLE: complete freedom** — explicitly "NOT restricted to any predefined list of titles"; may be
  highly specific when the posting's core function genuinely overlaps the documented work.
- Selection procedure mandated: analyze what the employer is actually hiring for (not just
  keywords), then pick the title maximizing ATS alignment + employer terminology + overlap with real
  work + truthful defensibility + professional naturalness.
- **Target title preference:** use the employer's exact title when truthful; otherwise the closest
  truthful ATS-aligned title; never copy an unsupported title just for keywords.
- **Truthful title gate:** "Could this candidate honestly have this title?" must be YES.
- **Forbidden titles:** anything Senior/Lead/Principal/Staff/Manager/Architect/Director/Head; and
  roles whose core is frontend, UI/UX, mobile, data science, ML model engineering, DevOps, cloud,
  cybersecurity, embedded, robotics, hardware.
- **No artificial variation:** do not change wording just to differ between applications; identical
  output for identical postings is acceptable.
- **DESCRIPTION:** max 25 words, one line, active voice, implied first person, no ending period,
  employer's terminology where truthfully supported, never copy a posting sentence.
- **SKILLS:** exactly 5–8, comma-separated, ranked by (1) posting keywords directly supported →
  (2) supported competency phrases → (3) close matches → (4) other genuine competencies. No fixed
  universal skill list; no keyword without support. Stint 2: MySQL/Django/Flask are genuine and
  should be *considered* every time but not forced in.
- **LaTeX character ban:** never output `\ { } ^ ~ $ % _ &`.
- **Output format:** exactly three lines — `ROLE: …` / `DESCRIPTION: …` / `SKILLS: …` — nothing else.

### Validation (code-side, in `parse_entry`)

- Regex parse of the three labeled fields (case-insensitive, whitespace-flattened); unparseable → error.
- Code fences, `**bold**`, and Unicode punctuation stripped first.
- ROLE: word count must be 1–4 (separator symbols like `&` don't count). **Auto-correction:** a
  trailing qualifier after a dash is trimmed (e.g. "Software Development Intern - Backend" →
  "Software Development Intern") *before* failing.
- DESCRIPTION: max 25 words. SKILLS: 5–8 items. Violations → the record is flagged with
  `experience_error` and **excluded from resume assembly** by Step 5 (flagged records never reach it).
- Cross-stint checks: same role or identical skill sets → flagged.
- There is **no semantic truthfulness check** — truthfulness is enforced only via the prompt.

---

## 7. Component 3 — Projects (two slots)

**Stage:** `sub_program_files/resume_content/3_projects.py`
**Prompts:** `prompt/projects_1_prompt.md`, `prompt/projects_2_prompt.md` · **Output:** `projects.json`

**Call pattern:** 2 requests per job, **sequential** — slot 2's template gets `{{SLOT1_PROJECT}}`
replaced with slot 1's generated title, so slot 2 knows what to avoid. If slot 2 still returns the
same project title, one extra retry happens. Transient failures retried up to 3 times (3/6/9s).

**⚠️ Important current reality:** the candidate has **two real projects** per the stage's docstring
("The candidate has exactly two real projects; each call picks and tailors one"), **but the prompt
files contain no project facts at all** — no names, technologies, or outcomes of the real projects.
Instead the prompts instruct the model to **invent** a project concept per slot:

- Slot 1: "Create ONE project that reads as direct evidence for THIS posting's core function" — a
  believable professional-sounding title (3–8 words, Title Case) mirroring the posting's domain
  (examples given: "Real-Time Market Data Analytics Platform", "Intelligent Document Processing with
  LLMs"), sounding like real end-to-end engineering work, not coursework.
- Slot 2: complementary, clearly different from slot 1 (different title, focus, primary technologies),
  covering posting keywords slot 1 didn't cover.
- DESCRIPTION: max 50 words, strong action verb start, mirrors the posting's vocabulary verbatim,
  **may include at most ONE plausible, modest, role-consistent metric** ("believable for a student
  project, never exaggerated") — i.e., the pipeline explicitly permits the model to fabricate a metric.
- SKILLS: 5–8, primarily the posting's own technology keywords verbatim, most-relevant first,
  named tech capitalized, practice skills lowercase.
- Never mention a company, university, or person. Same LaTeX character ban. Format: `PROJECT:` /
  `DESCRIPTION:` / `SKILLS:` lines only.

This is the **only component where the model invents content without a fixed factual basis** —
projects are fictional constructions around each posting. The only real-project constraint is the
docstring comment, which is not enforced anywhere in code or prompts.

### Validation (`parse_entry`)

- Regex parse of the three fields; unparseable → error.
- TITLE: 3–8 words; **auto-corrections**: a trailing "for …" clause is trimmed, then hard truncation
  to 8 words — corrections are recorded in `auto_corrections` but don't fail the record.
- DESCRIPTION: max 50 words. SKILLS: 5–8.
- Cross-slot check: both slots chose the same project → flagged (after the retry).

---

## 8. Component 4 — Skills section (four rows)

**Stage:** `sub_program_files/resume_content/4_skills.py`
**Prompt:** `prompt/skills_prompt.md` · **Output:** `skills.json`

**Call pattern:** 1 request per job. Transient failures retried up to 3 times.

**Prompt structure — the model must return four rows:**

| Row | Label | Content freedom |
|---|---|---|
| `LANGUAGES:` | fixed: "Programming Languages" | 4–6 programming languages the posting names/expects; for non-coding roles, may fill with the role's main technical tools as single-word names (must then not repeat in rows 3–4) |
| `SPECIALIZED-AREAS:` | fixed: "Specialized Area" | 4–5 specialized domains, in the employer's own terminology |
| `SKILLS-AREA-1: <label> :: <skills>` | **model invents** the label (2–5 words, e.g. "Databases and Data Technologies") | 4–8 posting keywords fitting that category |
| `SKILLS-AREA-2: <label> :: <skills>` | **model invents**, different from row 3 | 4–8 remaining posting keywords not used in rows 1–3 |

Quality rules: minimum fill of 4 per row (extend with role-standard entries when the posting is
thin); verbatim mirroring of posting keywords; implied basics allowed but nothing the posting gives
no hint of; no bare generic words; **no duplicates anywhere (case-insensitive)**; exact tech
capitalization; German posting terminology translated to standard English skill names; realistic
total (don't dump every keyword); no company/university/person names. Same LaTeX character ban.
Format: exactly the four lines, nothing else.

### Validation + mechanical auto-repair (`parse_section` + `auto_correct`)

The skills stage has the **most aggressive code-side repair** of all stages:

1. Regex parse of the four labeled rows; `label :: skills` split for rows 3–4. Unparseable → error.
2. **Auto-corrections (silent, recorded in `auto_corrections`, not failures):**
   - Languages row: entries not in a `KNOWN_LANGUAGES` set (a ~40-language allowlist) and not
     single-word are dropped ("removed non-language entries").
   - Duplicates dropped across the **entire section** (first occurrence wins, case-insensitive).
   - Over-max lists trimmed back to their caps.
   - **Thin languages row borrow:** if fewer than 4 languages remain, technical names are *popped
     out of skills_area_1* and moved into the languages row until the minimum is met.
3. **Hard validation (flags the record):** label empty or >5 words; stray `::` inside labels/skills;
  both skill areas with the same label; empty specialized-areas row; languages count outside 4–6
  *after* cleaning; specialized areas outside 4–5; a skill area below 4 skills *after* borrowing.
  Any hit → `skills_error` set → record excluded from Step 5 assembly.

---

## 9. Freedom the model gets vs. hard truth boundaries

Summary of the freedom landscape across all four components:

| Component | Model freedom | Hard boundary (in prompt) |
|---|---|---|
| Career objective | Sentence flow, keyword selection/placement, rhythm | Fixed candidate facts only; ≤60 words; no company name; no invention |
| Experience role | **Any professional title** (no list) | Must be truthfully defensible from the stint's fixed facts; no senior titles; "Intern" for stint 2 |
| Experience description | Which facet of real work to emphasize, employer terminology | Only documented work; no invented tech/metrics |
| Experience skills | Any set of 5–8 | Only skills supported by the stint; posting keywords must be genuinely supported |
| Project title | **Invented** (3–8 words) | Believable, no trademarks, no company names |
| Project description | **Invented**, incl. up to 1 metric | "Plausible, modest, role-consistent" — a *soft* boundary |
| Project skills | Any 5–8 from the posting | Must fit the (invented) project |
| Skills rows 3–4 labels | **Invented** (2–5 words) | Professional, Title Case, no colons |
| All skills rows | Any keywords | Posting-derived; no duplicates; realistic total |

**Key insight for improvement work:** truthfulness is enforced *exclusively through prompt text*
for all components; the only code-enforced constraints are structural (word counts, counts,
duplicates, parseability, character bans). The model could violate truthfulness (especially on
projects/metrics) and the pipeline would still ship it — there is no fact-grounding check anywhere.

---

## 10. Response parsing, auto-correction, and validation

Common machinery (duplicated in each stage file — not shared):

- **Text flattening:** all whitespace collapsed to single spaces before regex parsing; the model is
  expected to return labeled lines but often emits them on one line.
- **`strip_fences` / `clean_response`:** removes ``` fences and `**` bold, then applies the Unicode
  fix table (`–—` → `-`, curly quotes → straight, NBSP variants → space).
- **LaTeX safety:** prompts forbid `\ { } ^ ~ $ % _ &`; Step 5 additionally runs
  `escape_latex()` on every value as a second layer (also handles `#`), so even violations can't
  break compilation.
- **Flagging model:** each record carries `<component>_error` (empty = clean). Flagged records:
  - remain in the JSON stores with the reason,
  - are counted in the stage summary ("N clean, M need review") and make the stage exit 1,
  - are **silently excluded** by Step 5's `load_components()`.
- **Progress survival:** every stage rewrites its output JSON after **each job**, so a crash keeps
  all completed jobs.
- **Per-job errors never stop the loop** — in both Step 4 stages and Step 5.

Current remediation practice: when a stage flags records, the fix applied so far has been a one-off
regeneration script that re-prompts the model for just the flagged records and patches the JSON.

---

## 11. Assembly into PDF/DOCX (Step 5)

`program_files/5_create_resume.py`:

1. **Load:** the four component stores (keyed by `job_url`, flagged records dropped), the master
   `todays_overall_jobs.csv` (title/company metadata), and the template.
2. **Intersect:** keep jobs present in all four stores with no flags.
3. **File naming:** `safe_name(title)` — strips `(m/f/d)`-style suffixes, keeps `\w -`, joins spaces
   with `-`, max 80 chars. **Collision handling:** identical stems get `-2`, `-3`, … suffixes
   (added after a real bug where "Working Student" and "Working Student (m/f/d)" overwrote each other).
4. **Fill (`fill_template`):** string-replaces the placeholders in `core_resume_template.tex`.
   Placeholders: `CAREER-OBJECTIVE`, `ROLE-1` (whole token incl. "- Software Engineer"),
   `DESCRIPTION-1/2`, `SKILLS-1/2`, `PROJECT-1/2`, `PROJECT-DESCRIPTION-1/2`, `PROJECT-SKILLS-1/2`,
   `LANGUAGES`, `SPECIALIZED-AREAS`, two `SKILLS AREA` labels (positional replacement), two `{SKILLS}`.
   Every value is LaTeX-escaped first. Sanity checks: no leftover placeholders, both SKILLS AREA
   labels replaced — a violation aborts that job.
5. **PDF:** compile with the bundled `tools/tectonic.exe` (fallbacks: `./tools/tectonic.exe`,
   `tectonic`/`pdflatex` on PATH). 300s timeout; the PDF is moved to `output/resume/pdf/`.
6. **DOCX:** a **separately hand-built** mirror via python-docx (Calibri 10.5pt, bold headings,
   bullet lists) — same content, different rendering; a DOCX failure doesn't invalidate the PDF.
   The DOCX header/contact/education text is hard-coded again in this function (duplicate of the
   template's static facts).
7. **Report:** `resume_report.json` with `total_jobs` and per-job `job_url/title/tex/pdf/docx/error`.
8. Exit 0 only when every job produced both PDF and DOCX with no error.

---

## 12. Known weaknesses / improvement opportunities

Baseline observations to guide future quality work:

1. **No fact grounding for projects.** Projects are invented per posting (title + description +
   optionally a fabricated metric). Highest ATS-risk area and highest authenticity risk with
   recruiters. *Opportunity: ground both project slots in the candidate's two real projects with a
   facts file, and have the model only tailor emphasis/keywords.*
2. **Truthfulness is prompt-only everywhere.** No code checks that generated skills/roles/metrics
   appear in any allowlist of the candidate's real capabilities. *Opportunity: a fact-grounding
   validator pass, or keyword cross-check against a candidate skill inventory.*
3. **Static sections never adapt.** Research, Achievements, Certifications, Additional Projects,
   spoken Languages are identical on every resume — no keyword targeting there, and the fixed
   sections eat prime half-page space. *Opportunity: selective section reordering/trimming per job.*
4. **Single model, single attempt for 2 of 4 stages.** Objective and experience have no retry;
   a transient failure flags the whole job out of the run. Temperature/`max_tokens`/system role
   are unused. *Opportunity: unify retry policy, add system prompts, tune temperature per stage.*
5. **60-word objective is not enforced in code** — only experience (25 words), projects (50),
   and counts are code-checked. An over-long objective goes to print unchecked.
6. **No objective-quality measurement.** Nothing scores the output (keyword coverage vs. posting,
   similarity, ATS simulation). *Opportunity: an automatic scorer comparing resume text against the
   job description to rank/select the best of N generations per section.*
7. **No self-consistency or best-of-N.** Each component is one sample; there is no generate-3-pick-1.
8. **Massive code duplication.** `load_jobs`, `load_template`, `build_prompt`, `strip_fences`,
   `_UNICODE_FIXES`, `save_output` are copy-pasted across the four stage files; drift risk when
   editing. *Opportunity: extract a shared `common.py`.*
9. **Prompt marker inconsistency.** Only the objective prompt uses `## PROMPT`; the other five send
   their documentation headers to the model too (wasted tokens, model confusion risk).
10. **DOCX duplicates static facts in code** (name, contact, education) — a third place to update
    alongside the .tex template and prompts when facts change.
11. **One API key, no rotation or concurrency** — sequential requests only; a 100-job run takes
    ~700+ requests serially. *Opportunity: parallelism and key rotation for speed.*
12. **No German-language resumes.** Everything is generated in English; German postings are
    keyword-mirrored but the resume stays English (the objective prompt translates skill names).
13. **Header name truncation risk:** the template shows "RAVAL MEETKUMAR" without the surname
    ("RITESHKUMAR" appears only in the DOCX builder) — verify this is intentional.

---

### File reference (quick map)

| File | Role |
|---|---|
| `program_files/4_create_resume_components.py` | Step 4 orchestrator (runs the 4 stages) |
| `sub_program_files/resume_content/1_career_objective.py` | objective stage |
| `sub_program_files/resume_content/2_experience.py` | experience stage |
| `sub_program_files/resume_content/3_projects.py` | projects stage |
| `sub_program_files/resume_content/4_skills.py` | skills stage |
| `sub_program_files/ollama_request_response.py` | API client (endpoint, model, key loading) |
| `sub_program_files/prompt/*.md` | the 6 prompt files (the actual "brain" of the content) |
| `sub_program_files/resume_content/core_resume_template.tex` | static resume layout + placeholders |
| `program_files/5_create_resume.py` | assembly, escaping, PDF/DOCX build, report |
| `program_files/output/*.json` | component stores + `resume_report.json` |
