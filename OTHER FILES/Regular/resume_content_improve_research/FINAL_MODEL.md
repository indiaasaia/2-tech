# THE FINAL MODEL — Consolidated Result of 7 Research Rounds (V1–V7)

This is the single source of truth. It merges everything discovered across the seven research
rounds in this folder, shows the journey from the original 7 research topics to the final
validated architecture, and records every change, rejection, and correction made along the way.
Nothing here is assumed — every load-bearing claim was measured, prototyped, or A/B-tested
(scripts + raw results live in `experiment/` and `empirical_parser_results.json`).

---

## PART 1 — The Journey: 7 initial research topics → what each produced

| # | Original research topic | V1 finding | What later rounds did to it |
|---|---|---|---|
| 1 | **Current-system baseline** (`RESUME_GENERATION_DOCUMENTATION.md`) | Single model (`gpt-oss:120b` via Ollama Cloud), 6 prompts, raw-JD truncation into prompt text, regex-only validation, no verification of any kind | V4 audited the real data: truncation is a non-issue (0/21), tailoring is real (0 duplicate descriptions), but **35 fabricated metrics** ship across 42 project slots |
| 2 | **Open-source resume/document parsers** | Docling (MIT) primary + pdfplumber second extractor; OpenResume's published parser = best public model of ATS behavior | V3 ran the parser test on all 21 real PDFs → found **3 real defects** desk research never predicted; V4 A/B-validated the fixes |
| 3 | **Skill taxonomies + open matching projects** | ESCO best fit (EU, multilingual incl. German, free CSV dump); don't adopt any GitHub project wholesale | V5 confirmed the lexicon floor fails alone on German JDs (5/21 scored near-zero); ESCO + LLM analyst both required |
| 4 | **Keyword extraction + semantic matching** | "Taxonomy-first, LLM-assisted, embedding-verified"; e5-small with τ=0.72 | **V5 KILLED the semantic layer by measurement**: e5 cosine on short phrases compresses into 0.80–0.84 ("Kubernetes ↔ cooking recipes" = 0.818 > τ). Synonyms come from the alias/ESCO map only; the cross-encoder survives only as an advisory suggestion tool |
| 5 | **ATS platforms' real behavior + myths** | "75% auto-rejected" = likely myth; knockout questions = the only real auto-rejection; parse fidelity is the real, measurable KPI | V3 reframed: no RCT supports keyword-stuffing; truthful mirroring + machine readability is the defensible strategy |
| 6 | **Datasets + benchmarking + German market** | Own frozen 50-job benchmark primary; HF fit-dataset only as class-separation sanity (AUC ≥ 0.75 gate) | V4 quantified the German need: **7/21 JDs are German** → Lebenslauf variant priority |
| 7 | **Recommended architecture (V1 report)** | Strategy E: LLM + deterministic NLP + embeddings + rule validators, 5–7 LLM calls/job | Rebuilt through V2 (primary sources), V5 (embeddings removed, calls reduced to 3–5), V6 (gates prototyped: 294 findings, 0/21 clean jobs), V7 (constrained generation tested: gate→regenerate is **mandatory**) |

---

## PART 2 — The challenge journey: every major correction

### V2 — Primary sources killed three V1 assumptions
1. **Gemini free tier ≠ JD analyst.** Slashed to ~20 req/day → demoted to fallback-only.
2. **NVIDIA NIM ≠ free critic forever.** ~1,000 credits *total* → budget-capped to ≤1 sampled call/job.
3. **"3–4 parallel workers" impossible** — Ollama Cloud free tier runs **1 request at a time** → redesign as pipelining (deterministic work during LLM waits).
4. Found the real parsing risks in our own template: `Dec'23` breaks the universal `(19|20)\d{2}` date regex; German phone numbers fail US regexes.

### V3 — Measurement beat prediction (3 defects found, 1 prediction wrong)
| Defect (measured in 21/21 PDFs) | Root cause | Fix |
|---|---|---|
| Section titles corrupt ("AREER BJECTIVE", "E XPERIENCE") — **even the NAME corrupts** | `\scshape` small-caps font loses uppercase Unicode mapping | `\scshape` → `\bfseries`, normal case |
| Experience dates invisible to every standard date regex (0 matches in 21/21) | `Dec'23` apostrophe 2-digit year | → `Dec 2023 – Jan 2025` |
| Ligatures corrupt skill words ("efﬁciency", U+FB01/FB02) | Palatino ligature glyphs | fontspec `Ligatures=NoCommon` |
| V2's ALL-CAPS prediction was wrong — the real risk was *font corruption*, worse and different. Lesson: template risks must be measured, not derived. | | |
| Bonus: LLM is *over*-conservative — `python` absent in 12/21, `sql` in 16/21, `llm` in 20/21 despite real MySQL work | prompt over-caution | coverage metric detects (deterministic validators can't) |

### V4 — Fixes proven by A/B build + a hidden shipping bug found
1. **All 4 template fixes validated** on the project's own tectonic toolchain (`experiment/original.pdf` vs `fixed.pdf`): titles clean, dates parseable, ligatures 18→6, full name extracts. Note: the two most-recommended online ligature fixes **fail on this stack** (`glyphtounicode` is pdfTeX-only; Latin Modern not findable by name) — validated recipe is `\setmainfont{texgyrepagella}[Ligatures=NoCommon, Extension=.otf, ...]`.
2. **THE BIGGEST FIND OF ALL 7 ROUNDS:** every shipped PDF (21/21) shows the *experience* content inside "Main Projects" with a literal `PROJECT-` prefix. Root cause: in `5_create_resume.py`, `replace("SKILLS-1", …)` runs before `replace("PROJECT-SKILLS-1", …)` — the latter *contains* the former, so the placeholder is consumed. Survived every run because the sanity check only looks for *leftover* placeholders. Fix: longest-first replacement order + `assert "PROJECT-" not in filled_text` (would have blocked all 21).
3. Data audit: 7/21 German JDs; 0/21 truncated; 21/21 objectives within 60 words; real tailoring confirmed; **35 fabricated metrics** confirmed pervasive.

### V5 — Assumptions tested: one design rejected, one confirmed
1. **Semantic layer REJECTED by measurement** (see topic 4 above). Cross-encoder ranks perfectly but its absolute scores are uncalibrated (sigmoid ≈ 0.01) and it judges *relevance*, not *sufficiency* ("German B2 required" vs "German A2" ranks as relevant).
2. **Coverage scorer CONFIRMED:** intent 0.72 vs artifact 0.73 (+0.01) — the model's words genuinely land in the PDF. Blind spot: German JDs defeat an English-only lexicon (5/21 near-zero) → DE+EN lexicon + LLM analyst both mandatory.
3. **New gate:** word-segmentation sanity — pdfplumber finds only 154 "words" in the original PDF vs 622 in the fixed one; a corrupt resume can look fine by char count. Healthy = 200–800 words/page.

### V6 — The verifier itself, tested
1. **Gate bake-off:** prototype ran on all 21 jobs → **294 issues, 0 clean jobs** (G1 parse 21, G2 hallucination 201, G3 artifact 72). Every known defect class re-caught automatically.
2. **False-positive triage:** the feared regex FP ("rest" as word) = 0 occurrences; but 201/201 sampled G2 hits = **true positives, systemic**: ~9.6 unlicensed tool claims per job ("strong expertise in Python, SQL, and rexx", SAP/CRM/Jira/GCP claims). Root cause: the projects prompt *instructs* mirroring posting tools — fabrication is the design working as written. **The KB redesign is THE central fix.**
3. **Digit-rule evasion hole** found adversarially: "thirty percent" spelled out slips through → patch specified (map spelled-out numbers through the same check).
4. **JD-analyst prototype:** 2/2 valid JSON, 5.4 s/call, found `rexx` (an HRIS no lexicon contains) — but missed a stated language requirement and returned sentence-length "required" items → 3-point prompt patch list.

### V7 — The proposed central fix, built and measured
1. **Constrained generation (claimable set = KB ∪ JD-mirrorable tools) reduces fabrication ~4× but does NOT eliminate it by prompting alone** — first attempt still claimed "strong expertise in … rexx" and GCP twice. → **gate → regenerate is mandatory**, "just write a better prompt" is dead by measurement.
2. **Honesty/coverage trade-off quantified:** current coverage 0.73 (partly *purchased with fabrication*) vs honest 0.27–0.54. Missing terms are the tools genuinely lacked. Policy: honest ceiling set by KB expansion + alias-map surface mirroring; genuinely-missing requirements → **gap report to the user**, never fake claims.
3. **Analyst prompt patches also failed** (still returned `languages_required: []` on a JD literally saying "ideally english and german") → deterministic regex post-check forces language requirements into the JSON. Generalized philosophy: **LLM proposes, deterministic code disposes — everywhere.**

---

## PART 3 — THE FINAL MODEL (complete specification)

### 3.1 Architecture

```
JOB DESCRIPTION
   │
   ▼
[1] JD ANALYST — 1 LLM call (gpt-oss:120b, temp 0.1, strict JSON)
    required / preferred / nice / tools / languages / years / knockouts
   │
   ▼
[2] DETERMINISTIC POST-CHECK (LLM proposes, code disposes)
    regex language sweep → force-insert missed language requirements
    tier sanity (≤4-word items), tool list dedupe
   │
   ▼
[3] SKILL NORMALIZATION (deterministic, free)
    ESCO local CSV dump (EN+DE) + private alias map (~100 entries)
    normalized exact → rapidfuzz token_set_ratio ≥ 92 → ESCO alt-labels
   │
   ▼
[4] CLAIMABLE SET (deterministic)
    = KB-licensed skills (with evidence ids) ∪ JD tools (mirrorable, never ownable)
   │
   ▼
[5] CONSTRAINED GENERATION — 1–3 LLM calls (was 6)
    one call: objective + skills; one call: both experience stints; one call: both REAL projects
    rules: only listed tools mentionable, real projects only, no invented numbers
   │
   ▼
[6] GATES (deterministic, <1 s) — fail → regenerate with violations listed (≤2 iterations)
    G1 parse sanity: extracts, word-count 200–800/page, name/contact/sections intact
    G2 hallucination: every tech token KB-licensed; every digit (incl. spelled-out) in KB evidence
    G3 artifact integrity: no placeholders, no "PROJECT-" prefix, titles extract clean, dates parse
   │
   ▼
[7] DOCUMENT BUILD — tectonic PDF + python-docx DOCX (existing step 5, fixed)
    template fixes: \scshape→\bfseries, Dec yyyy dates, Ligatures=NoCommon (texgyrepagella),
    longest-first placeholder replacement
   │
   ▼
[8] ARTIFACT VERIFICATION — parse the PDF back (pdfplumber + second extractor)
    coverage over the *extracted* text (not the JSON intent)
    per-job missing-keyword list + GAP REPORT (missing requirements reported to user, never fabricated)
   │
   ▼
[9] SCORECARD + optional sampled critic (NVIDIA ≤1 call, budget-capped)
```

### 3.2 The gates (fail = never ship)

| Gate | Checks | Measured justification |
|---|---|---|
| G1 | text extracts; 200–800 words/page; name/email/phone (EU regex) extract; sections detectable | V3: 0/21 clean titles; V5: 154-word segmentation collapse |
| G2 | tech tokens ⊆ KB ∪ mirrorable-JD-tools; digits + spelled-out numbers ∈ KB evidence | V6: 201 true-positive hits, 35 fabricated metrics, "thirty percent" evasion |
| G3 | no leftover placeholders; `"PROJECT-" not in text`; dates match `\d{4}` regexes; titles not corrupted | V4: 21/21 collision bug; V3: date invisibility |

### 3.3 The scorecard (0–100, no embedding term)

```
GATES G1–G3: pass = mandatory precondition (fail → score 0 / regenerate)

  40  required-keyword coverage   (exact + alias/ESCO-fuzzy ≥ 92, over parsed artifact)
  20  preferred-keyword coverage
  15  parse fidelity              (extracted fields exact vs intent)
  10  format checks               (dates parse, reading order, section detection)
  10  experience relevance        (LLM analyst verdict, 1 call)
   5  naturalness                 (critic verdict, sampled)
```

Iteration rule: regenerate only if `score < 70` OR `required_coverage < 0.8`; max 2 iterations;
accept v2 only if `score(v2) > score(v1) + 2` AND G2 clean both times; else revert.
Coverage targets are **honest-calibrated** (V7): expect 0.5–0.7, not 0.73+ — chasing higher
re-creates fabrication. Missing requirements go to the gap report.

### 3.4 The candidate knowledge base (the central fix)

Structured JSON, schema-validated at load; every skill has ≥1 evidence id; explicit
`skills_allowed` / `skills_forbidden` lists per experience and project; projects are the **real**
ones (TradingView Data Fetch, LLM Sarcasm Detection Study) with real evidence only.
The LLM may **select, reorder, summarize, mirror surface forms** — it may never exceed the KB.
Fabrication becomes a compile error, not a prompt hope.

### 3.5 Free-tier reality (verified, the system must obey these)

| Provider | Reality | Role |
|---|---|---|
| Ollama Cloud (gpt-oss:120b) | 1 request at a time; unpublished weekly caps | the ONLY load-bearing LLM (analyst + generator) |
| NVIDIA NIM | ~1,000 credits TOTAL | sampled critic only |
| Gemini | ~20 req/day | fallback only |
| OpenRouter free | flaky | tie-breaker / emergency |

Budget: 3–5 LLM calls/job → 21 jobs ≈ 4 min wall-clock including all deterministic work.

### 3.6 Germany-specific items (quantified, not assumed)

7/21 JDs German → Lebenslauf variant: MM/YYYY dates (also parser-optimal), no DECLARATION section,
German ESCO labels in matching, German phone regex in the parser simulation, language requirements
surfaced as hard gates.

---

## PART 4 — Implementation order (every item evidence-backed, nothing left to research)

| # | Item | Evidence | Effort |
|---|---|---|---|
| 1 | Placeholder-collision fix + `"PROJECT-"` assert in `5_create_resume.py` | 21/21 PDFs affected (V4 §2) | ~30 min |
| 2 | 4 template fixes (exact LaTeX proven in `experiment/fixed.tex`) | A/B-validated (V4 §1) | ~1 h + re-run parser test |
| 3 | KB JSON + validator + digit rule incl. spelled-out numbers | 294 bake-off findings; systemic fabrication (V6) | 1–2 days |
| 4 | Constrained generation (claimable set) + mandatory gate→regenerate loop | prototype working (V7) | 1–2 days |
| 5 | Gate suite as permanent regression step (`experiment/verify_all.py` → pipeline) | prototype catches 294/294 (V6) | ~half day |
| 6 | Coverage scorer (DE+EN lexicon) + analyst call with deterministic post-check | prototyped (V5 §2, V6 §3, V7 §4) | 1–2 days |
| 7 | Gap report + scorecard + honest coverage targets | V7 §3 | 1 day |
| 8 | Lebenslauf variant | 7/21 German JDs (V4) | 1 day |
| 9 | Benchmark harness (frozen 50-job suite + adversarial cases) | V2 C10 protocol | 2 days |
| — | ~~e5 semantic scoring layer~~ | **rejected by measurement (V5)** | — |

## PART 5 — The meta-lesson (how the final model was reached)

The three most valuable findings of the entire effort — scshape corruption, date invisibility,
and the replacement-order bug — were **all found by testing artifacts**, never by reading code,
prompts, or web research. Two of the proposed designs (semantic scoring; "just constrain the prompt")
**died on contact with data**. The final model is smaller than the first proposal because measurement
removed machinery, not because challenge added it. Rule going forward: every pipeline change is
gated on **build → extract → assert → ship**.

*Full evidence chain: V1–V7 reports + `RESUME_GENERATION_DOCUMENTATION.md` +
`empirical_parser_test.py`/`.json` + `experiment/{validate_fixes,verify_all,analyst_prototype,mini_pipeline}.py`
with their JSON results, all in this folder.*
