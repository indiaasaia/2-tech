# ATS Research Report V2 — Challenged, Verified, Made Concrete

**What this document is:** a re-research of `ATS_RESEARCH_REPORT.md` (V1) with every major claim
re-verified against primary sources, weak points challenged and corrected, and vague recommendations
replaced with concrete schemas, algorithms, thresholds, and numbers.

**Verification method used:** primary-source reads (OpenResume's full published parser algorithm,
ESCO API page, Hugging Face dataset/model pages, Workday/SAP docs via search), plus adversarial
review of the candidate's own current resume artifacts (PDF structure inspection below).

---

## Part A — Where V1 was wrong, unverifiable, or too vague

Every challenged point, and the corrected position:

### A1. "Gemini free tier = JD analyst" — ❌ WRONG ASSUMPTION
**V1 claim:** Gemini free tier is "fast, generous daily free quota."
**Reality (verified):** Google repeatedly slashed free-tier limits; Gemini 2.5 Flash dropped to
**~20 requests/day** for many users (Dec 2025 onward; user reports of limits as low as 0 on some
models without billing). Free-tier quotas now vary per model and per project and are unstable.
**Corrected design:** Gemini can be a *fallback*, never a *load-bearing* component. The JD analyst
should run on **Ollama Cloud gpt-oss:120b** (already working, already keyed) with Gemini as fallback #2
and deterministic keyword extraction as the no-LLM fallback. Plan for **0 free Gemini calls**, be
pleased if you get some.

### A2. "NVIDIA NIM = free critic forever" — ❌ WRONG ASSUMPTION
**V1 claim:** NVIDIA NIM is a free API for the critic role.
**Reality (verified):** NIM free access = **~1,000 inference credits total (not per day)** + 40 RPM.
1,000 requests is one decent benchmark run, not an ongoing pipeline component. You can *request*
5,000, but the architecture must not assume it.
**Corrected design:** the critic role gets **at most 1 call per job** and only when the deterministic
hallucination check passes (why pay to review a document that failed compile?). Budget: 1,000 credits
≈ first 1,000 jobs verified. After that, critic calls rotate to whatever free capacity exists
(Ollama Cloud with a *different* model is acceptable independence: e.g., `gpt-oss:20b` vs `:120b` is
weak independence; OpenRouter free models are stronger but flaky).

### A3. "Ollama Cloud free tier" — ⚠️ HALF TRUE
**Verified:** free tier runs **1 request at a time** (no concurrency) with unpublished session/weekly
limits; paid tier $20/mo. So V1's "3–4 parallel workers" is impossible on the free Ollama tier.
**Corrected design:** concurrency comes from *pipelining*, not parallel LLM calls: while one job's
LLM call runs, do other jobs' deterministic work (parsing, ESCO matching, embeddings) locally. The
LLM remains serial — which is fine because it's only 3–5 calls per job now (see A6).

### A4. "multilingual-e5-small needs `query:`/`passage:` prefixes" — ✅ TRUE but underspecified
Verified from the model card family (e5 series requires input prefixes: `query: ` for the search
side, `passage: ` for the document side; using the wrong prefix measurably degrades retrieval).
Concrete usage in §C6.

### A5. The resume-JD-fit datasets — ⚠️ usable, with a caveat
`cnamuangtoun/resume-job-description-fit`: verified via secondary sources — ~6k+ resume-JD pairs,
3 labels (**Good Fit / Potential Fit / No Fit**), official train/test split; derived ATS-score
datasets already exist on top of it (e.g., `0xnbk/resume-ats-score-v1-en`). Caveat: these are
*generic* English tech resumes — none will resemble a German working-student application. Use them
to sanity-check that a scorer separates classes at all (AUC check), **not** to tune weights for the
German market. The own-benchmark (frozen local jobs) remains the primary instrument. This downgrades
V1's "calibrate weights on HF datasets" from P2 to P3-ish; class-separation check stays P1.

### A6. V1's "5–7 LLM calls per job" — ⚠️ reducible to 3–4
V1 counted: analyst (1) + generator (2: experience×1 each? actually 5 generator calls today) + critic (1).
The current generator does **6 calls per job** (1 objective + 2 experience + 2 projects + 1 skills).
Concrete new budget:
- 1 × JD analyst (JSON, one call, *replaces* the 5× re-analysis implicit in today's 6 prompts)
- 1 × experience tailor (both stints in ONE call — they share a JD; one call returning JSON with
  both stints also enables the same-role/same-skills check *inside* the model's single context)
- 1 × projects tailor (both slots in one call, with explicit "different" constraint)
- 1 × objective + skills (combined; both are short, both depend on the same analysis)
- 0–1 × critic (only if deterministic checks pass; sampled, e.g., every job first run, then ~10%)
**Total: 4 per job steady-state (down from 6), 5 with critic.** On a 1-at-a-time free tier this
matters: ~21 jobs → 84 calls ≈ 15–20 min wall-clock instead of ~35.

### A7. "ESCO dictionary matching is the primary extractor" — ⚠️ needs concrete mechanics
ESCO API v1.1.6 is real and free (verified), but calling the API per keyword at runtime is slow and
rate-limited. Concrete alternative: download the **ESCO CSV dump once** (`skills_en.csv` +
`skills_de.csv` from the ESCO download portal), build a local lookup: preferred label + alt labels →
concept URI (~14k skill concepts, tens of thousands of alt labels). Match by normalized exact +
rapidfuzz ≥ 92 threshold. Runtime cost: zero API calls, milliseconds. License: ESCO is free to reuse
with attribution (not OSI-licensed — fine for this personal pipeline; flag if commercializing).

### A8. V1's coverage metric — too vague. Made concrete in §C3.

### A9. V1's hallucination check — underspecified. Made concrete in §C4, with a real gap found:
**fuzzy matching alone cannot catch paraphrased inventions** ("built CI pipelines" when the KB says
nothing about CI). Concrete fix: claim-level extraction + entailment-style LLM check for *sentences*
that contain no KB token — see §C4 layer 2.

### A10. LaTeX template parsing risks — now verified by artifact inspection
Inspection of the actual generated PDF pipeline shows these specific, concrete risks:
- The header is a **`tabular` with a `minipage`** — many extractors emit the name fine, but the
  two-column contact block can reorder ("Phone/Email/LinkedIn/GitHub" label-value pairs are separate
  table cells).
- Section titles are `\section{\textbf{...}}` — good (real LaTeX sections), but the resume parser
  heuristics (OpenResume-style: **bold + ALL-CAPS full-line**) will NOT match, because titles render
  as "Career Objective" (title case). The fallback keyword heuristic will catch most, but "Main
  Projects" vs "Additional Projects" ambiguity is real.
- `\hfill` date lines (`Gujarat, India | Dec'23 -- Jan'25`) extract as a single line with the role —
  date regexes must handle `Dec'23` (apostrophe-year, unusual) and en-dash.
- fontawesome icons are fine (they don't extract as text), but hyperlink display text
  (`\href{...}{ravalmeett@gmail.com}`) extracts correctly — verified pattern.
- **`{}`-based placeholders like `LANGUAGES` inside `{LANGUAGES}`** are filled by string replace —
  no parsing risk after fill, but the *sanity check* in step 5 already catches leftovers. Keep.

### A11. "German ATS = international ATS" — verified nuance
German-market reality: the dominant ATS/HR systems in Germany include Workday, SAP SuccessFactors
(SAP's home turf, very common in German enterprises), Personio (Berlin, SMB powerhouse), Recruitee,
Greenhouse/Lever (startups), plus **Umantis, HRworks, softgarden, d.vinci** (DACH-specific). Almost
all embed a resume parser at application time. The Lebenslauf-specific expectations (tabular
reverse-chronological, MM/YYYY dates, photo optional-but-common, no "declaration" section, no
"objective" in the US sense) are *human/cultural* requirements layered on top of parsing — evidence
level: strong convention (multiple German recruiting guides agree), not ATS-technical requirement.

### A12. V1 weights — arbitrary. §C7 derives them properly with a defensible method.

---

## Part B — Deep primary-source findings

### B1. OpenResume parser algorithm (full algorithm published — this is the best public model of ATS parsing)
Verified in full. The 4 steps, with the exact mechanics that matter for OUR template:

1. **Text items** via pdf.js — every text run + x/y + bold + newline flags.
2. **Group into lines** — join adjacent items when horizontal gap < average character width
   (avg width = Σ item widths / Σ chars, excluding bold/newline items). *Implication: wide
   letter-spacing or gap-heavy lines fragment; our LaTeX output is normal-spaced → fine.*
3. **Group into sections** — a line is a section title iff: **single item in line AND bold AND
   ALL-CAPS**; fallback = keyword list of common section names.
   *Implication (A10): our titles are bold+TitleCase, not ALL-CAPS → the PRIMARY heuristic fails,
   the keyword fallback is doing all the work. Either accept that (keywords list covers us) or
   switch section titles to ALL-CAPS for maximal parser compatibility. Concrete recommendation:
   keep visual TitleCase but test; if the ported parser misses a section, switch to caps.*
4. **Feature scoring extraction** — per attribute, regex feature sets with +/− scores, e.g.
   Name: `/^[a-zA-Z\s.]+$/` (+3), bold (+2), all-caps (+2), contains `@` (−4, it's email), contains
   digits (−4, phone)... Date: `/(?:19|20)\d{2}/`. Subsections split on vertical gap > 1.4× typical.
   *Implications for us:*
   - **Name extraction will fail on "RAVAL MEETKUMAR RITESHKUMAR" ONLY IF** it contains non-ASCII —
     it doesn't. ✅ But the name is in a table cell together with contact labels; the +bold+all-caps
     score saves it. Verify empirically in Phase 2.
   - **Phone format** `+49 15565 468731` does NOT match their US-centric
     `\(?XXX\)?...` regex — a German parser consumer may use EU regexes, but our simulation must use
     *multiple* regex sets (US + EU) to be honest.
   - **Dates `Dec'23 -- Jan'25`** — the `(?:19|20)\d{2}` core regex FAILS on apostrophe years!
     This is a genuine, concrete finding: **change the template date format to `Dec 2023 – Jan 2025`**
     (or MM/YYYY for German style). High-confidence, zero-cost fix.

### B2. Workday / SAP parsing (verified via official docs + parser-engineering writeups)
- Workday: resume parsing **populates a structured profile the recruiter reviews and corrects**;
  accepted formats PDF/DOC/DOCX/RTF/TXT; Workday explicitly does **not** auto-fill everything —
  candidates often must correct. Published docs describe *field population*, never ranking.
  *Implication: the highest-stakes fields are name/email/phone/education/experience mapping —
  exactly what our parse-simulation must verify character-exact.*
- SAP SuccessFactors: resume parsing is a **configuration option** with permission-gated profile XML
  (verified help portal); careers-site parsing commonly powered by textkernel-class engines. Same
  lesson: structured field extraction, recruiter-visible.
- Neither publishes matching/ranking logic → V1's §23 conclusion stands: simulate parsing honestly,
  never claim to predict ranking.

### B3. ESCO (verified via EC portal)
Two APIs (web-service + local/API package), free, multilingual (EN + DE among 25+ languages).
The **downloadable CSV dump** is the practical route (A7). Coverage check for this user's domain:
ESCO contains concepts for Python, Kubernetes, Django, MySQL, NLP, LLM-class terms ("large language
model" concept exists), plus soft skills. Gaps exist for bleeding-edge terms — the alias map (§C2)
absorbs them.

### B4. Embedding models (verified via model cards / MTEB)
- `intfloat/multilingual-e5-small`: 384-dim, ~118M params, multilingual (100+ langs incl. German),
  **requires `query: `/`passage: ` prefixes**, Apache-2.0, CPU-fine (~10 ms/sentence on modern CPU).
- `cross-encoder/ms-marco-MiniLM-L-6-v2`: reranker, ~22M params, ~50–100× slower per pair than
  bi-encoder but fine for ≤40 pairs/job, English-optimized — for German pairs prefer
  `BAAI/bge-reranker-base` (multilingual).
- Honest caveat (challenged): cosine similarity on short skill phrases is **noisy** — "Kubernetes"
  vs "container orchestration" scores high (~0.7+), but so do unrelated tech pairs sometimes.
  That's why semantic similarity must only *confirm relevance*, never *grant skills* (V1 got this
  right; it survives the challenge).

### B5. Free-tier reality table (verified Sept 2026)

| Provider | Free reality | Architectural consequence |
|---|---|---|
| Ollama Cloud | 1 request at a time; unpublished weekly/session caps; gpt-oss:120b available | serial LLM calls; pipeline deterministic work around them |
| NVIDIA NIM | ~1,000 credits TOTAL + 40 RPM | critic only, ≤1 call/job, sampled |
| Gemini | ~20 req/day on popular flash models (was 250–1,500; slashed repeatedly) | fallback only, never load-bearing |
| OpenRouter free | rotating free models, per-model daily caps, flaky | tie-breaker / emergency fallback |

**Total LLM budget per 21-job run: ~84–105 calls — Ollama free tier handles this; nothing else is
load-bearing.**

### B6. German market facts (challenged and held, with sources classed)
- Photo: still common on German CVs but **legally optional** (AGG prohibits required photos);
  convention, not rule. For working-student tech roles, English CV without photo is normal.
- Date format: MM/YYYY tabular is the Lebenslauf convention — our `Dec'23` style is nonstandard
  (B1 found it also breaks parser date regexes — two independent reasons to fix).
- "DECLARATION" section: Indian-CV convention, essentially never present in German/international
  applications — remove (it also wastes prime space).
- ATS in Germany: SuccessFactors + Workday + Personio dominate; all parse → the parsing-verification
  strategy transfers fully.

---

## Part C — The concrete design (replaces V1's vague sections)

### C1. Candidate knowledge base — concrete schema (JSON Schema-validated)

```json
{
  "profile": {
    "name": "RAVAL MEETKUMAR RITESHKUMAR",
    "contact": {
      "phone": "+49 15565 468731",
      "email": "ravalmeett@gmail.com",
      "linkedin": "linkedin.com/in/meetraval",
      "github": "github.com/ravalmeet",
      "location": "Cottbus, Germany"
    },
    "work_authorization": "student residence permit; full-time work allowed 140 days/year (verifiable fact to state)"
  },
  "education": [
    {"degree": "MSc Artificial Intelligence", "school": "BTU Cottbus-Senftenberg",
     "location": "Germany", "start": "2025-04", "end": "present"}
  ],
  "experience": [
    {
      "id": "soham",
      "company": "Soham Infotech", "location": "Gujarat, India",
      "start": "2023-12", "end": "2025-01",
      "titles_allowed": ["Software Engineer", "Backend Engineer", "Software Developer"],
      "titles_forbidden_patterns": ["senior|lead|principal|staff|manager|architect|director|head"],
      "evidence": [
        "integrated backend systems, servers and databases in a cross-functional team to improve latency, data management and performance"
      ],
      "skills_allowed": ["backend engineering", "system integration", "database management",
        "data management", "performance optimization", "server-side development", "software engineering"],
      "skills_forbidden": ["docker", "kubernetes", "aws", "react", "frontend", "devops",
        "machine learning engineering", "python", "java"]
    }
  ],
  "projects": [
    {"id": "tradingview", "title": "TradingView Data Fetch",
     "evidence": ["market-data fetching tool; open source on GitHub with 40+ stars and 24+ forks"],
     "skills_allowed": ["python", "api integration", "data fetching", "automation"]},
    {"id": "sarcasm", "title": "LLM Sarcasm Detection Study",
     "evidence": ["empirical study on large language models for sarcasm detection in low-resourced Indic languages (ongoing MSc research)"],
     "skills_allowed": ["nlp", "llm", "transformers", "python", "research"]}
  ],
  "skills": [
    {"name": "MySQL", "aliases": ["mysql db"], "evidence": ["pantechelearning"]},
    {"name": "Django", "aliases": [], "evidence": ["pantechelearning"]},
    {"name": "Flask", "aliases": [], "evidence": ["pantechelearning"]},
    {"name": "NLP", "aliases": ["natural language processing"], "evidence": ["sarcasm"]},
    {"name": "LLM", "aliases": ["large language models", "large language model"], "evidence": ["sarcasm"]}
  ],
  "languages_spoken": [{"lang": "English", "level": "C2"}, {"lang": "German", "level": "A2"}],
  "certifications": [{"name": "Google Big Data and Machine Learning", "url": "..."}],
  "achievements": [{"name": "AI Guild Hackathon 2025", "result": "Winner, Berlin/Brandenburg"}]
}
```

Rules: every skill has ≥1 evidence id; `skills_forbidden` lists are explicit (the current prompts'
"not established" prose becomes machine-checkable); schema validated at load; a CI check fails if a
skill lacks evidence.

### C2. Skill normalization — concrete
1. Local ESCO lookup (A7): `skills_en.csv` + `skills_de.csv` → map `{normalized_label → concept_uri, preferred_en, preferred_de}`.
2. Private alias map for ESCO gaps: `{"k8s": "Kubernetes", "ci/cd": "CI/CD", "llm": "large language model", "ml": "machine learning", ...}` — start with ~100 entries covering the user's domain; grow from benchmark misses.
3. Matching function: normalize (casefold, strip punctuation) → exact → rapidfuzz `token_set_ratio ≥ 92` → ESCO alt-labels → else "unknown term" bucket.

### C3. Coverage metric — concrete formula
From the JD analysis (one JSON: `required[], preferred[], nice[], languages[], years_min, title`):

```
coverage_tier(tier) = Σ_{r ∈ tier} w(r) · hit(r) / Σ_{r ∈ tier} w(r)

hit(r) = 1.0  if surface(r) or alias(r) present in extracted resume text   (exact/taxonomy)
       = 0.7  if ESCO-concept(r) matches an ESCO-concept of a resume token  (normalized)
       = 0.5  if semantic(r, best_resume_sentence) ≥ τ_sem (0.72 for e5)    (semantic)
       = 0.0  otherwise

w(r): required = 1.0, preferred = 0.6, nice = 0.3
final_coverage = 0.5·coverage(required) + 0.3·coverage(preferred) + 0.2·coverage(nice)
```
- τ_sem = 0.72 chosen as e5-small's typical "related but not identical" band; **must be validated on
  the HF fit-dataset before trusting** (that's the P1 dataset check, A5).
- Text searched = **the parser-extracted text**, not the JSON sources — so coverage also measures
  machine readability implicitly.

### C4. Hallucination / fact check — two layers (concrete fix for A9)
**Layer 1 — deterministic token gate (every run, free):**
- Extract claims: split every generated value into tokens/n-grams.
- Every *technology-like* token (matched by ESCO/alias/known-tech list) must resolve to KB-allowed
  skills for that section's source, OR be a verbatim JD term AND the section is skills/projects where
  mirroring is licensed... **no** — corrected rule after challenge: JD-verbatim alone is NOT enough
  (the JD says Kubernetes; the KB doesn't → claiming it is still a lie). Final rule:
  **every technology token must be KB-licensed (KB skill ∪ KB evidence text tokens). Period.**
  A JD term that isn't in the KB is a *gap to close in the KB*, not a license.
- Metrics/numbers: every digit token in generated text must appear in the KB evidence or be a date.
  (This kills the fabricated-metric class mechanically.)
**Layer 2 — sentence entailment check (1 LLM call, sampled or on-request):**
- For each generated sentence containing NO KB token (paraphrase suspects — rare), ask the critic:
  "Is this claim supported by this evidence? yes/no" — only for the few suspect sentences, so it's
  ~200 tokens, not a full-document review.

### C5. Parse simulation — concrete port plan
Reimplement OpenResume's 4 steps in Python over **pdfplumber** (MIT; PyMuPDF optional):
1. `page.extract_words(extra_attrs=["fontname","size"])` → text items with x/y + bold flag
   (bold = font name contains "Bold").
2. Merge adjacent (gap < avg char width) → lines (group by y within tolerance).
3. Section detection: single-item + bold + ALL-CAPS primary; keyword fallback list
   (objective, experience, education, project, skill, achievement, certification, language,
   publication) — include German keywords too (berufserfahrung, ausbildung, kenntnisse...).
4. Feature scoring: port the published regexes **plus an EU/German extension set**:
   phone `(\+?\d[\d\s\-()/]{6,}\d)`, date `\b(?:Jan|Feb|...|Dez|Dezember)[a-z]*\.?\s*'?\d{2,4}\b` and
   `\d{2}/\d{4}`; name/extraction logic otherwise as published.
Then compare against intent: name ✓, email ✓, phone ✓, ≥5 sections found, every date parses,
every KB skill findable in extracted text. **Dual-extractor check:** run Docling too; flag any
field where the two disagree.

### C6. Semantic match — concrete
```python
from sentence_transformers import SentenceTransformer, CrossEncoder
m = SentenceTransformer("intfloat/multilingual-e5-small")   # Apache-2.0, CPU
rer = CrossEncoder("BAAI/bge-reranker-base")                # for top pairs only

q = m.encode("query: " + requirement, normalize_embeddings=True)
d = m.encode("passage: " + sentence, normalize_embeddings=True)   # prefixes MANDATORY (A4)
sim = float(q @ d)
# candidates = sentences with sim ≥ 0.60; reranked; covered if reranker score ≥ 0.5
```
Per requirement: best evidence sentence + score → the scorecard stores the pair, so every
"covered" verdict is auditable.

### C7. Scoring — weights derived, not asserted
Method: the score must rank the HF fit-dataset correctly (class separation) *and* respect the
priority structure (required > preferred > nice; parse failures are gates not deductions).
Derived weighting (v0, to be re-fit on the benchmark):

| Component | Weight | Gate? |
|---|---|---|
| G1 parses + name/contact extract | GATE | fail → score 0, never ship |
| G2 hallucination layer-1 clean | GATE | fail → regenerate, never ship |
| G3 all sections detected by parser | GATE | — |
| Required coverage | 30 | |
| Semantic evidence match | 20 | |
| Preferred coverage | 15 | |
| Parse fidelity (fields exact) | 15 | |
| Format checks (dates, reading order) | 10 | |
| Critic verdict (when run) | 10 | absent → redistribute proportionally |

Iteration rule (concrete): run generator again only if `score < 70` OR `required_coverage < 0.8`;
max 2 iterations; accept v2 only if `score(v2) > score(v1) + 2` AND G2 clean both times; else revert.

### C8. Generator prompt redesign — concrete structural change
One JD-analysis call produces JSON; ONE shared "claimable set" (KB ∩ JD-relevant, normalized) is
injected into each generation prompt as a closed list. Prompts change from "don't invent" (hope) to
"choose only from this list" (constraint), with the deterministic gate (C4) enforcing after the fact.
The four generation calls collapse to three (A6: experience-both, projects-both, objective+skills),
each returning strict JSON (parsed with pydantic; 1 repair retry; then deterministic fallback).

### C9. Failure handling — concrete matrix

| Failure | Detection | Action |
|---|---|---|
| Analyst JSON malformed | pydantic | 1 repair call → fallback: KeyBERT+ESCO keywords only (score flagged low-confidence) |
| Generator JSON malformed | pydantic | 1 retry → park job in `runs/failed/` with reason (visible in dashboard) |
| Ollama 429/timeout | HTTP | backoff ×3 → next provider (OpenRouter → Gemini) → park |
| Parse simulation finds nothing | empty extraction | template bug — do NOT ship; alert |
| Coverage < 0.8 | scorecard | ≤2 regeneration iterations |
| Hallucination token | C4 layer 1 | regenerate that section with violation listed (1 call) |
| Critic disagreement | C4 layer 2 | drop the suspect sentence, regenerate it, log |
| German JD | language detect (fasttext/langid) | analysis in German; generation English; verbatim DE keywords preserved where KB-licensed |

### C10. Benchmark — concrete protocol (own-data-first, per A5)
1. Freeze 50 jobs from already-fetched CSV (stratified: EN/DE × tech/non-tech × working-student/intern).
2. Version-pin: pipeline commit + KB commit + model names in `runs/benchmark_<date>/manifest.json`.
3. Metrics collected per job: required/preferred/nice coverage, parse fidelity %, hallucination count
   (MUST be 0), score, LLM calls, wall time.
4. Class-separation check: run the scorer on `cnamuangtoun/resume-job-description-fit` test split;
   report AUC Good-Fit vs No-Fit; only trust τ_sem and weights if AUC ≥ 0.75.
5. Adversarial set (12 cases, concrete): JD title `C++ & R&D Engineer (m/w/d)`; JD with only "K8s,
   CI/CD" abbreviations; German-only JD; JD demanding React (KB-forbidden → expect skill absent,
   coverage penalty, NOT hallucination); contradictory JD; empty description; 12-word title; JD with
   emoji; duplicate JD; JD with embedded tables; JD with German date formats; JD with "English C1
   required" (language gate surfaced).
6. Blind human ranking: 10 pairs old-vs-new, count wins; report alongside the metric deltas.

---

## Part D — Challenged final architecture (what I would actually build)

**Remove:** the 6-prompt raw-JD re-analysis (→ 1 analyst call); invented projects + permitted fake
metrics (→ KB real projects); prompt-only truthfulness (→ C4 layer-1 gate); `Dec'23` date format
(→ `Dec 2023`, dual-verified reason B1+A12); DECLARATION section (→ removed, German convention);
silent flag-dropping (→ visible `runs/failed/`).

**Keep:** steps 1–3 (fetch/filter/keys — they work); tectonic PDF + python-docx DOCX builders; the
manual CSV curation; gpt-oss:120b as the writer.

**Add (in build order):** KB JSON + validator → ESCO local dump + alias map → analyst call (JSON,
Ollama) → 3-call generator with claimable sets → pdfplumber parser-sim (ported OpenResume logic +
EU regexes) → C4 layer-1 gate → coverage (C3) → scorecard + iteration loop (C7) → semantic layer
(C6, after τ validation) → critic sampling (NVIDIA, budget-capped) → benchmark harness (C10).

**LLM budget:** 3–4 calls/job steady-state + ≤1 critic — fits Ollama free tier serially, with all
other providers as genuine fallbacks rather than load-bearing assumptions (the V1 error, corrected).

**The one-sentence test of the design:** every truth claim is KB-derived and machine-checked, every
ATS behavior we depend on is simulated with published algorithms, every score is computed from the
*parsed artifact* rather than intent, and every provider assumption is backed by verified 2026 free-tier
reality — so the system's quality claim is falsifiable at every layer.

*Primary sources: OpenResume parser algorithm deep-dive (open-resume.com, full algorithm); ESCO
Services/API portal (esco.ec.europa.eu); Workday "Concept: Resume Parsing" admin doc; SAP
SuccessFactors "Configuring Resume Parsing" help portal; intfloat/multilingual-e5-small + BAAI
reranker model cards; Gemini rate-limit docs + Dec-2025 slash reports; NVIDIA NIM credit/RPM forum +
pricing analyses; Ollama pricing/limits pages; cnamuangtoun/resume-job-description-fit dataset card
(via secondary confirmation of labels/splits).*
