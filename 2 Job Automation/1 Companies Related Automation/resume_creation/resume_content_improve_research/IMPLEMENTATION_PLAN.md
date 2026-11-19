# IMPLEMENTATION PLAN — Replace `resume_content/` with the Final Model

**DECISIONS CONFIRMED (user, this session):**
1. **Rollout:** parallel-run first — v2 writes to `output_v2/`, benchmarked vs v1 before cutover.
2. **Format:** English-only with the parser-safe template fixes (no Lebenslauf variant for now).
3. **ESCO:** approved — free CSV dump will be downloaded in Phase A.

Remaining open items: §5 items 1 (KB facts) and 2 (job-title truth) — see the KB questionnaire.

**FURTHER DECISIONS:**
4. **KB input mode:** drafted from the candidate's **master Academic CV** (pasted by the candidate,
   confirmed 100% correct) instead of the old template data — see the divergence table below.
5. **Job title:** "Software Engineer" is accurate for the Soham Infotech stint — `titles_allowed` fixed to it.
6. **KB status: APPROVED** — `knowledge_base/validate_kb.py` passes with 0 errors, 0 warnings:
   25 evidence-linked global skills, 2 experiences, 7 real projects (3 main + 4 additional),
   1 research entry, 10 certifications, 4 achievements.

### CRITICAL DIVERGENCE FOUND: the master CV contradicts the pipeline's static content

While drafting the KB from the master CV, several **static** facts in the current
`core_resume_template.tex` pipeline were found to be **stale or wrong** vs. the master CV:

| Fact | Current pipeline template | Master CV (candidate-confirmed) |
|---|---|---|
| Soham Infotech role | generic "integrated backend systems..." | **quant/reinforcement-learning models for trading, backend components + real-time algorithms** |
| Soham skills | backend/system-integration list | **Python, RL, DL, Mathematics, Quant, SQL, Data Analytics** |
| Pantechelearning stint | "MySQL, Django, Flask backend work" (Django+Flask+MySQL are only skills) | **Machine Learning Internship, Chennai, Dec'21–Feb'22: ML models, text-to-speech, visual-activity analysis; NLP/CV/Django** |
| Main projects | 2 slots filled with generated text | **3 real ones: High Frequency Trading Platform, Automated Resume Generation (live demo), Vehicle Sharing Application** |
| HFT metric | none | **"70% accuracy in real-time cash segment"** — KB-licensed digit |
| Education dates | mismatched in old runs | **BTU MSc AI April 2025–current; GTU BE June 2020–May 2024** |
| Address | Cottbus | **Ernestinenstraße 21, 45141 Essen** |
| Certifications | 1 ("Google Big Data and ML") | **10 (all Coursera/HackerRank/Udemy, URLs in KB)** |
| Achievements | 1 | **4 (SIH 2021/2022, Azadi ka Amrit Mahotsav 2023, AI Guild 2025 Winner)** |
| Profile photo | absent | **profile.jpg in header** |

**Consequence:** Phase B (template v2) must rebuild the static sections from the KB, not from the
old template — otherwise the resume ships stale facts. The KB is now the single source of truth
for both static and dynamic content.

**Goal:** replace the current 4-stage generation method (`sub_program_files/resume_content/`,
6 prompts, prompt-only truthfulness) with the measured architecture from `FINAL_MODEL.md`
(KB → analyst → claimable set → constrained generation → gates → verified build), implemented
in a new `resume_content_improve_research/` package.

**Everything below is evidence-backed** — each design choice cites the round that measured it
(V1–V7), and each "needs from you" item appears in one consolidated list in §5.

---

## 1. What gets replaced vs. kept

| Current (resume_content) | Final model | Evidence |
|---|---|---|
| 6 markdown prompts re-reading the raw JD | 1 analyst call → JSON + deterministic post-check | V2 A6, V6 §3, V7 §4 |
| Truthfulness only in prompt prose | KB-licensed claimable set + G2 gate | V6 §2b, V7 §2 |
| Invented projects + 35 fabricated metrics | Real projects from KB only, digit rule incl. spelled-out numbers | V4 §3-E, V6 §2c |
| `Dec'23` dates, `\scshape` titles, Palatino ligatures | Validated template fixes (exact LaTeX in `experiment/fixed.tex`) | V3/V4 A/B |
| `SKILLS-1` ⊂ `PROJECT-SKILLS-1` collision | Longest-first replacement + `assert "PROJECT-" not in text` | V4 §2 |
| No verification | G1–G3 gates + parse-back + coverage + gap report | V5, V6 |
| 6 LLM calls/job | 3–5 calls/job | V2 A6, V7 |
| Silent flag-dropping | Job parked visibly with reason | V2 C9 |

**Kept unchanged:** steps 1–3 (fetch/filter/keys), tectonic + python-docx builders,
manual CSV curation, gpt-oss:120b via Ollama Cloud, the dashboard (extended with a
new "Verification" page).

---

## 2. New package layout

```
resume_content_improve_research/
  knowledge_base/
    candidate_kb.json          ← from you (§5 item 1)
    kb_schema.json             ← JSON Schema, validated at load
    alias_map.json             ← K8s→Kubernetes etc. (~100 entries, extensible)
    esco/                      ← ESCO skills_en.csv + skills_de.csv dump (§5 item 4)
  generation/                  ← replaces sub_program_files/resume_content/
    analyst.py                 ← 1 call → strict-JSON JD analysis
    analyst_postcheck.py       ← deterministic language/tier enforcement (V7 §4)
    claimable_set.py           ← KB ∪ mirrorable JD tools (V7)
    generator.py               ← 1–3 calls, constrained prompts, strict JSON
    prompts/                   ← new analyst + generator prompts (rewritten from V6/V7 patches)
  verification/
    gates.py                   ← G1/G2/G3 (port of experiment/verify_all.py, prod-grade)
    coverage.py                ← deterministic scorer over parsed PDF text (V5 §2)
    parse_sim.py               ← ported OpenResume-style parser + EU regexes (V2 C5)
    scorecard.py               ← 0–100 score + gap report (V5 §5, V7 §3)
  templates/
    core_resume_template_v2.tex  ← template with the 4 fixes + collision-proof @@TOKENS@@
    build_docx.py                ← existing DOCX mirror, pointed at new JSON
  run_step4_v2.py            ← orchestrator: analyst → claimable → generate → gate loop → build → verify
  run_step5_v2.py            ← build pdf/docx + parse-back + scorecard + gap report per job
```

Pipeline steps 1–3 and the dashboard stay where they are; `main.py` gains two switches
(`--resume-engine v1|v2`, v2 default once validated).

---

## 3. Build order (each phase independently testable)

### Phase A — Inputs & KB (day 1) — IN PROGRESS
1. ~~Collect your inputs (§5), write `candidate_kb.json` + `kb_schema.json`.~~
   → `knowledge_base/candidate_kb.json` DRAFTED (status: `DRAFT_PENDING_REVIEW`, 14 GUESS markers)
   → `knowledge_base/validate_kb.py` written and passing (structural check + guess flagging).
   → **NEXT: you review the KB** — confirm the 14 guesses (language levels, second stint
     duties, pytorch/huggingface/git/REST-API usage, certification details, hackathon name)
     and ADD any real skills missing from the 9-entry list. Then set `status: "APPROVED"`.
2. ~~Validator~~ done (see above); kb_schema.json folded into the validator logic.
3. ESCO CSV dump → local lookup `{label → concept_uri, preferred_en, preferred_de}`.
4. Alias map v1 (~100 entries from the JD corpus we already fetched).

### Phase B — Template & build fixes (day 1–2, from V4's validated recipe)
1. `core_resume_template_v2.tex`:
   - `\scshape` → `\bfseries` (titles + header name),
   - `Dec'yy` → `Dec yyyy` (or `MM/YYYY` for the Lebenslauf variant),
   - `\setmainfont{texgyrepagella}[Ligatures=NoCommon, Extension=.otf, ...]`,
   - placeholders renamed to collision-proof `@@PROJECT_DESC_1@@`-style tokens.
2. `build_docx.py` adapted to the new component JSON.
3. Gate for the build itself: `assert "PROJECT-" not in filled_text` (V4's one-line 21/21 killer).

### Phase C — Analyst + post-check (day 2)
1. `analyst.py`: one call, strict JSON (pydantic), temperature 0.1 — includes the three
   V6 patches (language-requirement rule + worked example; preferred-tier guidance;
   ≤4-word verbatim items).
2. `analyst_postcheck.py`: regex language sweep (english|german|deutsch|fließend|B2|C1…)
   force-inserts missed language requirements; dedupes; enforces item lengths.

### Phase D — Claimable set + constrained generation (day 3)
1. `claimable_set.py`: `KB skills (with evidence ids) ∪ JD tools (mirrorable, never ownable)`
   normalized via ESCO + alias map.
2. `generator.py`: 3 calls max — (objective+skills), (both experiences), (both real projects).
   Prompts: "choose only from this list", real projects only, no invented numbers.
   Strict JSON out; 1 repair retry; then deterministic fallback.

### Phase E — Gates + regeneration loop (day 3–4)
1. `gates.py` (prod port of `experiment/verify_all.py`): G1 parse sanity (200–800 words/page,
   name/contact/sections), G2 hallucination (tech tokens ⊆ KB ∪ JD-tools; digits incl.
   spelled-out ∈ KB evidence), G3 artifact integrity (no placeholders, no `PROJECT-` prefix,
   dates parse, titles not corrupted).
2. Loop: gate fail → regenerate with violations listed → ≤2 iterations → else park job in
   `runs/failed/` with reason (visible in dashboard).

### Phase F — Verification + scorecard + gap report (day 4–5)
1. `parse_sim.py` (OpenResume-style heuristics + EU/German regex sets) over the built PDF.
2. `coverage.py`: required/preferred/nice coverage over the **extracted text**, alias-aware.
3. `scorecard.py`: G1–G3 pass mandatory; 40/20/15/10/10/5 weights; iteration rule
   (regenerate if score<70 or required<0.8, max 2, accept if +2); gap report JSON
   (missing requirements → user, never fabricated).
4. `run_step5_v2.py` wires build → parse-back → scorecard → `resume_report.json` v2.

### Phase G — Integration + dashboard + regression (day 5–6)
1. `main.py` engine switch; dashboard "Verification" page (score, gates, gap report per job).
2. Regression suite: run `empirical_parser_test.py` — must go 0/21 → 21/21 clean on the new output.
3. Benchmark on a frozen 20-job set (stratified EN/DE): compare v1 vs v2 on
   fabrication count, coverage, parse fidelity, LLM calls, wall time.
4. Cutover: v2 becomes default; v1 kept for one release as fallback.

---

## 4. Definition of "implemented perfectly"

1. `empirical_parser_test.py`: 21/21 clean titles, dates, names (from 0/21).
2. Gate bake-off on new output: **0 G2 findings** (from 201), 0 G3 findings.
3. Fabricated metrics: **0** (from 35); spelled-out numbers included in the check.
4. Coverage: honest 0.5–0.7 with a per-job gap report; no coverage achieved via unlicensed claims.
5. LLM calls ≤ 5/job; wall-clock ≤ ~5 min per 20-job run on the serial free tier.
6. Every change reproducible: build → extract → assert → ship (the V4 meta-lesson).

---

## 5. WHAT I NEED FROM YOU (consolidated — the only blockers)

| # | Item | Why | Without it |
|---|---|---|---|
| 1 | **Candidate KB confirmation**: your real, current skills/tools per experience & project, any real projects beyond the 2 known, real certifications, real achievements, honest German level, coursework tools | The KB is the source of truth; V6 proved the current prompts fabricate ~9.6 claims/job — only you can license what's true | The generator stays over-restrictive (honest coverage stuck ~0.3–0.5) or I'd have to guess truth |
| 2 | **Job-title truth**: exact title(s) you're entitled to claim for Soham Infotech (and whether "Software Engineer" is accurate) | Titles are the highest-scrutiny claim in German screening | Risk of title inflation, the #1 interview-kill class |
| 3 | ~~Lebenslauf decision~~ | **RESOLVED: English-only + parser-safe fixes** |
| 4 | ~~ESCO dump~~ | **RESOLVED: approved, Phase A downloads it** |
| 5 | ~~Rollout mode~~ | **RESOLVED: parallel-run first, cutover only after benchmark** |
| 6 | **(Optional) 5–10 real postings** you'd actually apply to, for the acceptance benchmark | Makes the v1-vs-v2 comparison concrete on your real targets | Random frozen 20-job sample |

Items 1–2 remain the hard blockers; 6 is optional.

---

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Model still violates the claimable set (V7 measured: it will) | Gate→regenerate loop is mandatory, not optional; violations fed back verbatim |
| Analyst JSON malformed | 1 repair call → deterministic lexicon-only fallback, job flagged low-confidence |
| Ollama free tier throttling mid-run | Serial design already; backoff ×3 → park job with reason; resume next run |
| ESCO terms missing for niche tools | Private alias map grows from benchmark misses; "unknown term" bucket reported |
| Template change shifts layout | Phase B measured first via `experiment/validate_fixes.py` A/B before integration |
| Overwriting good v1 outputs | v2 writes to `output_v2/` until the benchmark passes; explicit cutover |

---

*Evidence base: FINAL_MODEL.md (V1–V7), experiment/ prototypes (validate_fixes, verify_all,
analyst_prototype, mini_pipeline) — all reproducible in this folder.*
