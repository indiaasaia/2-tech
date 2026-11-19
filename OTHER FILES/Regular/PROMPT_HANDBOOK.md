# ATS Resume Automation — Prompt Handbook

Project: JOB_AUTOMATION · What each prompt is for, our purpose, and the exact prompts we use.

**The big picture:** we scrape fresh working-student jobs in Germany, filter to postings from the last few days, validate Ollama API keys, then use `gpt-oss:120b` (via ollama.com's OpenAI-compatible endpoint) to generate **one ATS-optimized resume per job**. The resume is assembled by filling placeholder slots in `sub_program_files/resume_content/core_resume_template.tex` — one generation stage per section.

---

## The shared skeleton of every prompt

Each stage ships one prompt file in `sub_program_files/` with the same anatomy:

1. **Header (not sent to the model):** which script loads it, which placeholders the script fills, which CSV columns they come from.
2. **`## PROMPT` marker:** everything below this line is what the script actually sends to the model.
3. **Fixed candidate/stint facts** — the only facts the model may use (the truthfulness anchor that prevents hallucinated years, tools, employers).
4. **`{{PLACEHOLDERS}}`** for job data: `{{JOB_TITLE}}`, `{{JOB_DESCRIPTION}}`, `{{KEY_REQUIREMENTS}}` (filled from CSV columns `title`, `job_description`, `requirements` + `your_tasks`, truncated by the script).
5. **Numbered output rules** covering: output format (plain text, no markdown), length, ATS keyword strategy, **decision procedures** (deterministic mapping rules so different postings produce different outputs), variety checks, LaTeX-safe characters, and a closing "return only the content" line.

**Runtime that executes the prompts:**
- `sub_program_files/ollama_request_response.py` — `send_prompt(prompt, token)` + `load_first_key()`; the shared transport layer.
- `sub_program_files/resume_content/1_career_objective.py`, `2_experience.py` — per-stage scripts that fill placeholders for each job row, call `send_prompt`, parse/validate responses, and save incremental JSON to `program_files/output/` (`career_objective.json`, `experience.json`).

**Pipeline context:** `1_fetch_jobs.py` (scrape Stepstone + workingstudentjobs.de) → `2_filter_jobs.py` (freshness filter) → `3_test_ollama_keys.py` (active keys) → resume-content stages (career objective → experience → projects → skills, one JSON each).

---

## Stage 1 — Career Objective

**What we write a prompt for:** generate a 3–4 sentence, max-60-word career objective per job — identity-first opening, MSc AI at BTU Cottbus-Senftenberg, posting-mirrored keywords, implied first person. Output fills the template's `CAREER-OBJECTIVE` slot.

**Purpose:** every application opens with a paragraph that mirrors the posting's vocabulary so both human recruiters and ATS parsers match it, while stating only real candidate facts.

**The prompts we use — `sub_program_files/prompt/career_objective_prompt.md`:**

- *Fixed truthful candidate profile (the only usable facts):* MSc Artificial Intelligence @ BTU Cottbus-Senftenberg (Apr 2025–present); BE Computer Engineering @ Gujarat Technological University (2020–2024); ~1 year Software Engineer experience in India (Dec 2023–Jan 2025) — backend integration of systems/servers/databases for latency, data management, performance; ongoing LLM sarcasm-detection research on low-resourced Indic languages; Smart India Hackathon runner-up ×2, AI Guild Hackathon 2025 Winner (Berlin/Brandenburg); based in Germany, seeking working-student/internship roles alongside the MSc.
- *Output rules:* single clean paragraph, no markdown/LaTeX/quotes; 2–4 sentences, ≤60 words; recommended flow (professional identity → MSc sentence → specialisations matched to the posting → sought roles) with "never produce the same sentence pattern for every job"; **keyword procedure** — silently extract the 8–15 most important ATS keywords from the posting (prioritizing requirements/tasks sections), then place the 4–8 most important naturally; **exact verbatim keyword mirroring** with abbreviation handling ("Artificial Intelligence (AI)" on first mention); the posting's role title used verbatim exactly once — never as the literal first words — with `(m/f/d)`-style suffixes stripped; no filler words (passionate/hardworking/dynamic); strict truthfulness (~1 year cap, nothing outside profile + posting, no hiring-company names); LaTeX-safe characters (`& # +` only inside verbatim keywords like R&D, C#, C++); authenticity rule (varied sentence openings, omit profile facts that don't fit, never tack skills on).

The file itself is the single source of truth for the full text.

---

## Stage 2 — Experience (two real stints → two prompts, two calls per job)

**What we write prompts for:** per job, generate the three values for each of the two fixed employment stints — ROLE (1–3 words), DESCRIPTION (one line ≤25 words), SKILLS (5–8, comma-separated) — filling `ROLE-1/DESCRIPTION-1/SKILLS-1` and `ROLE-2/DESCRIPTION-2/SKILLS-2`.

**Purpose:** keep both stints 100% truthful (company/location/dates are fixed in the .tex and never generated) while making role wording, description emphasis, and skill selection job-specific — ATS keywords come from the posting; substance never leaves the real stint facts.

**The prompts we use (all in `sub_program_files/prompt/`):**

**`prompt/experience_1_prompt.md`** — stint 1: Soham Infotech, Gujarat, Dec 2023 – Jan 2025 (~1 year, entry role; real work: backend integration of systems/servers/databases for latency, data management, performance).
- Three-line output format: `ROLE:` / `DESCRIPTION:` / `SKILLS:`.
- **Role decision procedure:** identify the posting's dominant discipline, map into the truthful family — general development/features/applications → *Software Engineer*; backend/APIs/services/databases/data → *Backend Engineer*; Entwickler/entwicklung (backend-centric) → *Backend Developer*; web/end-to-end → *Software Developer*. Only these four allowed; never the posting's domain as the title (no "Automation Engineer"), never "Intern".
- Description leads with the posting's most-emphasized facet and reuses its exact nouns only where they overlap real facts; skills PRIMARY = posting's own requirement keywords mirrored verbatim, FALLBACK = generic families the stint supports; never domain tools (PLCs, robotics, cloud, containers, ML frameworks); no bare words like "software"; American spelling; technologies capitalized, practices lowercase.

**`prompt/experience_2_prompt.md`** — stint 2: Pantechelearning, Chennai, Dec 2021 – Feb 2022 (3-month internship during the Bachelor's; real work: MySQL data management/storage supporting ML workflows; Django + Flask backend infrastructure for web apps).
- Same three-line format; internship titles allowed and preferred.
- Same role decision procedure with Intern variants of the four titles.
- **MySQL, Django, Flask mandatory** in skills (the real stack); remaining slots from posting keywords or fallback practices.
- Description must vary its opening verb — "Implemented" banned as the default (alternatives: Built/Developed/Designed/Supported/Managed, or tech-first openings) — and lead with the fact the posting cares most about.

**Shared rules in both:** LaTeX-safe characters (never backslash, braces, `^ ~ $ % _ &`; `& # +` only inside verbatim keywords), English only, no company/location/dates inside the generated lines, **VARIETY CHECK** ("if two different postings would receive the same three lines, the answer is wrong"), no invented numbers/metrics.

**Decisions you made along the way:** two prompts/two calls instead of one JSON call; internship title allowed for stint 2; stint-1 skills sourced from posting requirements (ATS-first) bounded by what the stint plausibly covers; company rendered "Soham Infotech".

---

## How we verify a prompt actually works

We measure, not guess. The loop: run a **two-job probe** first (catches edge cases cheaply), then a full 10-job run, then compute metrics — pairwise Jaccard overlap of skill sets between jobs, role distribution, distinct description openings. Results across the iterations: E1 skill overlap 68% → 27%; E2 98% → 57% (the floor is the mandatory real stack); E1 roles from one static title to a 5/5 posting-driven split; E2 description openings 8 distinct of 10. The probes caught and fixed real defects before full runs: an "Automation Engineer" title fabrication, a bare "software" skill, mixed UK/US spelling, and a Unicode non-breaking hyphen that would break LaTeX.

---

## Later stages (same pattern, not yet built)

Projects stage (PROJECT-1/2, PROJECT-DESCRIPTION-1/2, PROJECT-SKILLS-1/2), Skills stage (LANGUAGES, SPECIALIZED-AREAS, SKILLS rows), then an **assembler** that merges all stage JSONs into `core_resume_template.tex` and compiles one ATS-ready PDF per job — each will follow the same skeleton and the same measurement loop.
