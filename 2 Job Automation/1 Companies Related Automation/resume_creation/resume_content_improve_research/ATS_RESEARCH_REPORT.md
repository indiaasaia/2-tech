# ATS Research Report — Rebuilding the Resume-Optimization Subsystem for Reliability

**Scope:** research only. Nothing in this report has been implemented; the production pipeline is untouched.
**Baseline input:** `RESUME_GENERATION_DOCUMENTATION.md` (same folder) — exact current-reality reconstruction of the pipeline.
**Resources assumed:** Ollama Cloud (`gpt-oss:120b` class), NVIDIA NIM free API, Gemini free tier, OpenRouter free models, Python, open-source libraries, local execution.
**Sources:** cited inline; claims are kept separate from evidence level where they cannot be fully verified (see §4, §19, §27).

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [Current architecture — exact reconstruction](#2-current-architecture--exact-reconstruction)
3. [Current weaknesses — systematic gap analysis](#3-current-weaknesses--systematic-gap-analysis)
4. [How ATS systems actually work](#4-how-ats-systems-actually-work)
5. [ATS myths vs evidence](#5-ats-myths-vs-evidence)
6. [Open-source tools inventory](#6-open-source-tools-inventory)
7. [Resume parsing tools — comparison](#7-resume-parsing-tools--comparison)
8. [Job/resume matching tools — comparison](#8-jobresume-matching-tools--comparison)
9. [Keyword extraction tools — comparison](#9-keyword-extraction-tools--comparison)
10. [Semantic matching](#10-semantic-matching)
11. [Document format validation](#11-document-format-validation)
12. [ATS simulation — what is realistically possible](#12-ats-simulation--what-is-realistically-possible)
13. [Multi-model architecture with the free APIs](#13-multi-model-architecture-with-the-free-apis)
14. [The verification loop](#14-the-verification-loop)
15. [Candidate knowledge base](#15-candidate-knowledge-base)
16. [Scoring framework](#16-scoring-framework)
17. [Benchmarking framework](#17-benchmarking-framework)
18. [Recommended architecture](#18-recommended-architecture)
19. [Recommended technology stack](#19-recommended-technology-stack)
20. [Implementation roadmap](#20-implementation-roadmap)
21. [Recommendation table](#21-recommendation-table)
22. [Priorities P0–P3](#22-priorities-p0--p3)
23. [What cannot be verified](#23-what-cannot-be-verified)
24. [Final answer: the architecture I would build](#24-final-answer-the-architecture-i-would-build)

---

## 1. Executive summary

**What is wrong with the current approach:** the pipeline is a single-model, single-pass, prompt-only system.
One model (`gpt-oss:120b` via Ollama Cloud) reads a truncated job posting and *invents* resume content
against truthfulness rules that exist only inside the prompt text. There is no structured candidate
database, no fact grounding (projects are fabricated per posting, including an explicitly permitted
fabricated metric), no machine-readability verification of the produced PDF/DOCX, no keyword-coverage
measurement, no semantic matching, no independent verification of any kind, and no objective way to
know whether any change improves anything. The system optimizes for *looking tailored*, with no
measurement of whether it *is* tailored or whether a machine can even read it.

**The biggest opportunity** is not a better prompt. It is the introduction of two things the system
completely lacks:

1. **A factual candidate knowledge base** — a structured, evidence-linked source of truth that the
   LLM may select from but never exceed, enforced by deterministic checks, not prompt text.
2. **A closed verification loop** — parse the generated document like an ATS would (open-source
   parsers), measure keyword coverage against a structured job analysis, compute semantic similarity
   with local embeddings, and run an independent-model fact review. Iterate only when a score says so.

Both are buildable entirely with free models and open-source libraries running on a laptop CPU.
The research conclusion (§13, §14, §18) is that the best reliability/cost architecture is
**Strategy E: LLM + deterministic NLP + embeddings + rule validators** — not one big model, not a
ten-agent swarm. Roughly 5–7 LLM calls per job, everything else deterministic.

---

## 2. Current architecture — exact reconstruction

Reconstructed from the code and verified in detail in `RESUME_GENERATION_DOCUMENTATION.md`. Answers
to the 17 reconstruction questions:

| # | Question | Answer (current system) |
|---|---|---|
| 1 | How jobs are fetched | Step 1 (`1_fetch_jobs.py`): Python scraping of Stepstone and workingstudentjobs.de with per-job detail-page fetching; retry/backoff on read timeouts |
| 2 | Portals used | Stepstone, workingstudentjobs.de (Germany) |
| 3 | Info extracted per job | title, company, location, posted_time, job_url, job_description, requirements, your_tasks |
| 4 | JD processing | **None.** Raw text is truncated (6,000 / 4,000 chars) and poured into prompt placeholders. No parsing, no requirement classification |
| 5 | Resume structure | Static LaTeX template (`core_resume_template.tex`, Academic-CV-derived, tcolorbox headers, Palatino) + 4 dynamic slots (objective, 2 experiences, 2 projects, 4-row skills) + hand-built DOCX mirror |
| 6 | Sections modified per job | Career objective; both experience entries (role/description/skills); both main projects (title/description/skills); the whole Skills section |
| 7 | Sections kept unchanged | Header/contact, education, research & publications, achievements, certifications, additional projects, spoken languages, declaration, layout |
| 8 | Prompts used | 6 markdown files in `sub_program_files/prompt/` — career objective, experience ×2 (one per real stint), projects ×2 (no project facts!), skills |
| 9 | LLM/API used | `POST https://ollama.com/v1/chat/completions`, model `gpt-oss:120b`, Bearer key, no temperature/system/max_tokens control, single key, no rotation |
| 10 | Output validation | Regex parsing of labeled lines; word/count limits; dedupe; Unicode normalization; auto-corrections (skills stage). **No semantic or factual validation** |
| 11 | Final generation | String-replace into LaTeX → tectonic PDF; separate python-docx DOCX mirror; collision-safe filenames |
| 12 | File formats | PDF (tectonic) + DOCX (python-docx) + .tex source |
| 13 | How resume enters application process | It doesn't — pipeline stops at file generation; applications are manual |
| 14 | Historical versions | No. Each run overwrites output folders; only `resume_report.json` logs file paths. No versioning, no per-job history |
| 15 | Resume-vs-JD comparison | **None anywhere** |
| 16 | ATS simulation / independent verification | **None** |
| 17 | Deterministic vs LLM split | LLM does all content decisions; deterministic code only validates structure (counts, regex, LaTeX escaping, filenames) |

**Job-description understanding (gap §5-A):** the pipeline captures raw `requirements`/`your_tasks`
strings only. It never distinguishes required vs. preferred skills, never extracts years-of-experience,
language requirements (German/English), work-authorization constraints, certifications, or domain
terminology as structured fields. Keyword extraction is delegated entirely to the LLM *inside* each
generation prompt — there is no explicit keyword list to verify against, which makes coverage
unmeasurable.

**Skill normalization (gap §5-B):** none. "ML", "Machine Learning", "machine-learning" are treated as
unrelated strings. The only normalization is a hard-coded ~40-language allowlist in the skills stage.
Open taxonomies that could fix this: **ESCO** (European Commission, multilingual — includes German
labels, free API and bulk downloads, ideal for the German market), **O\*NET** (US DoD, CC BY 4.0),
plus research tooling: `jensjorisdecorte/Skill-Extraction-benchmark` (ESCO-based datasets), `ESCOX`
(LLM-based skill/occupation extraction to ESCO/ISCO), `nestauk/ojd_daps_skills` (extract + map to a
taxonomy of choice), `KonstantinosPetrakis/esco-skill-extractor`. ESCO is the strongest fit: EU
vocabulary, German translations included, explicitly designed for EU labor-market matching.

---

## 3. Current weaknesses — systematic gap analysis

### A. Job-description understanding — **absent**
- No structured JD analysis at all. The LLM re-analyzes the raw posting 5 times (once per prompt) with
  no shared, verifiable intermediate representation.
- No required-vs-preferred distinction, no years-of-experience extraction, no language-requirement
  detection (critical in Germany: "Deutsch fließend" vs "English fluent"), no work-authorization or
  location filtering at generation time.
- Consequence: coverage cannot be measured, and hallucination cannot be detected — there is nothing
  to compare the output against.

### B. Skill normalization — **absent**
- No taxonomy, no synonym map, no abbreviation handling beyond prompt hopes. Directly measurable loss:
  a posting asking for "K8s experience" while the resume says "Kubernetes" scores zero in any
  exact-match ATS facet.

### C. Fact grounding — **the weakest point**
- Projects are invented per posting; up to one fabricated metric is *explicitly permitted* by the prompt.
- Experience skills are constrained only by prompt text; nothing checks that a generated skill is real.
- A single hallucinated technology (e.g., "Docker" on the experience line) ships unchallenged and can
  be caught in a 2-minute recruiter phone screen. This is a **selection-destroying** risk class.

### D. Machine readability — **unverified**
- The LaTeX PDF uses a two-column `tabular` header block, `tcolorbox` section titles, fontawesome
  icons, and Palatino (`cfr-lm`). None of this has ever been tested through a text extractor.
  Text-extraction order and section detection are plausible-but-unverified assumptions.
- The DOCX mirror is clean (simple paragraphs/bullets — good), but nobody checks either file.

### E. Verification — **absent**
- No parser simulation, no coverage metric, no semantic score, no independent review, no hallucination
  detector, no regression tests. Quality claims are unfalsifiable.

### F. Process robustness
- No retries in 2 of 4 stages; a transient failure silently drops a job from the run (flag → excluded
  by Step 5). One API key, serial execution, ~6 requests/job (~10 s each) → ~1 min/job minimum, no
  concurrency. No caching: identical postings re-pay full cost.

### G. Market fit (Germany)
- Resume is English-only by construction; several German postings expect German applications (a large
  share of working-student postings in Germany are German-language). The system keyword-mirrors German
  text but produces an English resume — untested against German recruiter expectations.
- Template carries an Indian-CV convention ("DECLARATION" section) that is *not* a German Lebenslauf
  convention; German CVs are tabular reverse-chronological with MM/YYYY dates and (still commonly) a
  photo — current template uses neither date style nor photo, and its date format (`Dec'23 -- Jan'25`)
  is nonstandard for Germany.

---

## 4. How ATS systems actually work

Synthesis across vendor documentation (Workday, SAP SuccessFactors), parser engineering writeups,
the resume-parser community (OpenResume), and empirical recruiter surveys.

**Stage 1 — Ingestion.** The ATS accepts an upload (typically PDF, DOCX, DOC, RTF, TXT; some add
HTML/images-with-OCR). Workday's documented behavior is representative: the resume is parsed into a
*structured candidate profile* (name, contact, education, experience) that the recruiter reviews and
corrects; parsing failures mean the recruiter sees an empty or garbled profile — a real, observed
failure mode (Workday "Autofill with Resume" complaints are common among applicants).

**Stage 2 — Text extraction & layout reconstruction.** PDF text is extracted glyph/position-wise; the
parser must reconstruct reading order. Multi-column layouts, tables, text boxes, and header/footer
content can scramble the order in weaker parsers. DOCX extraction is structurally easier (XML source,
linear flow). This is where "ATS-safe formatting" rules actually come from.

**Stage 3 — Segmentation & field extraction.** Section headers are detected (Experience, Education,
Skills…), entries split, dates normalized (a wide variety of formats: "Jan 2024", "01/2024",
"Januar 2024", "2023-12"), job titles/companies paired, skills matched against internal or third-party
taxonomies (many vendors embed commercial skill ontologies similar in role to ESCO/O*NET).

**Stage 4 — Matching & ranking.** Three coexisting mechanisms:
1. **Knockout questions** — work authorization, degrees, licenses, location. These DO auto-disposition
   applications before human review. This is the only "automatic rejection" mechanism with strong
   evidence.
2. **Keyword/Boolean search** — recruiters search the candidate database (exact terms, Boolean AND/OR).
   Exact surface form still matters here; taxonomies/synonyms soften it in modern systems.
3. **Relevance ranking** — vendor-specific, frequently now AI-assisted; opaque. Workday, SuccessFactors
   etc. do not publish ranking algorithms. There is **no universal ATS score**; every "ATS score" a
   commercial tool sells is its own model of one or more of these stages, not an industry standard.

**Practical consequence for the design:** maximize what is verifiable — (a) flawless text extraction
and field parsing of our own output, (b) coverage of terms a recruiter would search, (c) structured,
complete profile fields — and treat vendor ranking as unknowable (§23).

## 5. ATS myths vs evidence

| Claim | Classification | Basis |
|---|---|---|
| "75% of resumes are rejected by ATS before a human sees them" | **Likely myth** | No primary source exists; multiple independent analyses (2024–2026) trace it to marketing; large-scale application analyses found no major ATS auto-rejects on content |
| "ATS auto-reject by keyword score" | **Likely myth** (modern systems), with one exception | Recruiters report they review; auto-disposition exists but via **knockout questions** (work authorization, credentials) — *strong evidence* |
| "PDFs are unreadable to ATS" | **Outdated / weak evidence** | Modern parsers handle text PDFs fine; DOCX remains the safest convention (linear XML); image/scanned PDFs fail everywhere |
| "Columns/tables always break parsing" | **Moderate evidence, overstated** | Reading-order reconstruction fails in weaker parsers, especially two-column *headers* and text boxes; single-column linear flow is universally safe |
| "Photos cause ATS rejection" | **Unverified for ATS / industry convention** | No parser evidence; photo norms are cultural (expected in Germany historically, declining post-AGG; discouraged in US/UK) |
| "You must mirror keywords exactly; synonyms score zero" | **Partially true (moderate evidence)** | Older Boolean search: exact; modern systems: taxonomy + semantic search softens it. Mirroring exact terms remains the high-EV strategy *when truthful* |
| "Keyword stuffing improves ranking" | **Myth for hiring outcome** | Ranking is opaque, recruiters read the resume, stuffing reads as dishonesty; no evidence of benefit, clear evidence of recruiter aversion |
| "One ATS score exists / '95% ATS-compatible' scores" | **Marketing claim** | Every checker scores its own model; algorithms are private and mutually inconsistent (see §26/§23) |
| "ATS can reliably detect AI-written resumes" | **Unverified** | No credible public evidence of ATS-level detection; irrelevant anyway if content is truthful |
| "Icons/graphics in headers break parsing" | **Moderate evidence** | Icons themselves are ignored, but icon-adjacent *text* (e.g., phone number inside a text box) can be dropped |

---

## 6. Open-source tools inventory

Curated for: local execution, Python integration, license, maintenance. (Inspected via docs, repos,
and the comparative literature — not full code audits; license flags must be re-verified at
implementation time.)

| Project | Where | Purpose | License | Local | Input | Output | Strength | Weakness |
|---|---|---|---|---|---|---|---|---|
| **PyMuPDF (fitz)** | PyPI | fast PDF text/layout extraction | ⚠️ AGPL-3.0 (or commercial) | ✅ | PDF | text + layout | fastest, precise positions | AGPL for a commercial future |
| **pdfplumber** | PyPI | PDF text + tables + geometry | MIT | ✅ | PDF | text/tables | precise geometry (reading order checks) | slow |
| **python-docx** | PyPI | DOCX read/write | MIT | ✅ | DOCX | XML/paras | we already generate with it; also parse | DOCX only |
| **Docling** | GitHub (IBM) | layout-aware PDF/DOCX → structured MD/JSON | MIT | ✅ | PDF, DOCX | structured | strong layout model, active, MIT — best all-rounder | heavier deps (torch) |
| **unstructured** | PyPI | multi-format partitioning | Apache-2.0 | ✅ | PDF/DOCX/HTML | elements | many formats | generic, less resume-aware |
| **Apache Tika** | Apache | universal text extraction | Apache-2.0 | ✅ (JVM) | almost anything | text+meta | bulletproof extraction | JVM dependency |
| **OpenResume parser** | GitHub (xitanggg/open-resume) | *resume-specific* PDF parser: text items → lines → sections → fields | ⚠️ AGPL-3.0 | ✅ | PDF | structured JSON | exactly the ATS-simulation logic we need (documented 4-step pipeline) | TS/Node, AGPL; port logic instead of vendoring |
| **pyresparser** | PyPI | simple resume field extraction | MIT | ✅ | PDF/DOCX | fields | trivial to use | stale, spaCy-version conflicts — avoid |
| **pyresume** | GitHub | simple Python resume parser (PDF/DOCX/TXT) | MIT | ✅ | PDF/DOCX/TXT | structured | Python-native | small community, audit needed |
| **Resume-Matcher** | GitHub (srbhr/Resume-Matcher) | resume-vs-JD analysis: parse, keywords, score | MIT | ✅ | PDF/DOCX + JD | match report | most popular OSS in this niche; good reference architecture | app-oriented; extract its scoring ideas |
| **Skill-Extraction-benchmark** | GitHub (jensjorisdecorte) | ESCO skill extraction datasets + models | open | ✅ | text | ESCO skills | *the* benchmark for skill extraction (JCD) | research-grade |
| **nestauk/ojd_daps_skills** | GitHub (Nesta) | skill phrase extraction + taxonomy mapping | MIT | ✅ | job ads | taxonomy skills | extract+map pipeline, exactly our shape | UK-centric taxonomy defaults; swap ESCO in |
| **KeyBERT** | PyPI | embedding-based keyword extraction | MIT | ✅ | text | keywords | top accuracy in comparative benchmarks (D'Agostino 7-algo benchmark; IEEE 2023 comparative assessment) | needs an embedding model |
| **spaCy** | PyPI | NLP pipeline (NER, noun phrases, matching) | MIT | ✅ | text | tokens/entities | fast, deterministic, German models exist | skills need custom patterns |
| **sentence-transformers** | PyPI | local embeddings + rerankers | Apache-2.0 | ✅ | text | vectors | core of semantic layer | model choice matters (§10) |
| **rapidfuzz** | PyPI | fuzzy string matching | MIT | ✅ | strings | scores | abbreviation/typo normalization | lexical only |
| **tectonic** | already bundled | LaTeX compile | MIT | ✅ | .tex | PDF | current engine, keep | — |
| **tiktoken / transformers tokenizers** | PyPI | token counting for free-tier budgeting | MIT/Apache | ✅ | text | counts | plan API quotas | — |

---

## 7. Resume parsing tools — comparison

The verification pipeline needs one thing: **parse our own generated PDF/DOCX the way a third party
would.** Ranking for that purpose:

1. **Docling (MIT)** — best primary parser: layout-aware, handles both PDF and DOCX, outputs
   structured Markdown/JSON, active IBM maintenance, permissive license. The 2024 arXiv comparative
   study of 10 open-source PDF parsers (`arXiv:2410.09871`) and the 2025/26 community benchmarks place
   Docling/Marker at the top of open-source layout parsing; PyMuPDF/pdfplumber lead on raw speed for
   clean text.
2. **PyMuPDF or pdfplumber** — secondary deterministic checker: extract raw text + positions to
   verify *reading order* (does the name come first? are sections in order?) and *character-level*
   correctness of every generated value (this doubles as the hallucination detector on the artifact).
   License note: PyMuPDF is AGPL — for a purely internal pipeline that's fine; if a commercial product
   is ever planned, pdfplumber (MIT) is the drop-in safe choice.
3. **OpenResume's parser logic** — not for the license, for the *blueprint*: its published 4-step
   algorithm (text items → lines → sections → field extraction) is a faithful model of how ATS parsers
   work on resumes. Reimplementing its section/field heuristics in Python over Docling/PyMuPDF output
   gives us a resume-specific parser simulation without license issues.
4. **Avoid**: pyresparser (unmaintained), any cloud "resume parser API" (defeats the free/local design).

**Recommendation:** Docling as primary extractor + PyMuPDF/pdfplumber as independent second extractor +
a ported OpenResume-style section/field heuristics layer on top. Two independent extractors agreeing
on name/contact/sections/skills is itself a strong verification signal.

## 8. Job/resume matching tools — comparison

| Tool | Algorithm | Deterministic | LLM | Embeddings | Python-integrable | Verdict |
|---|---|---|---|---|---|---|
| Resume-Matcher (srbhr) | parse + keyword extraction + similarity scoring | partly | yes (for parsing/keywords) | yes | ✅ | best *reference* for scoring design; don't adopt wholesale |
| CV-Embed / SBERT matchers (GitHub topic: job-matching) | SBERT cosine resume↔JD | yes (after embeddings) | no | yes | ✅ | good semantic-similarity baseline |
| Nesta skills library | extract + map to taxonomy | yes | no | yes (mapper) | ✅ | closest to the production shape we need |
| ESCOX (research) | LLM joint skill+occupation extraction → ESCO | no | yes | yes | research code | shows the LLM+ESCO pattern works; simpler to do LLM-candidates → ESCO-verify |
| CareerBERT (2025, ESWA) | bi-encoder trained on resume/job pairs in shared space | yes | no | yes | model available | evidence that shared-space matching is the SOTA approach; we won't train, but its eval methodology informs our benchmark |
| Commercial (Jobscan etc.) | private | — | — | — | ❌ | compare only; algorithm private (§26) |

**Conclusion:** don't adopt any project wholesale; assemble a small deterministic matcher (taxonomy +
fuzzy + coverage arithmetic) and one embedding-based scorer, and keep both auditable.

## 9. Keyword extraction tools — comparison

| Method | Accuracy on JDs | Speed | Cost | Complexity | FP/FN profile | Verdict |
|---|---|---|---|---|---|---|
| LLM extraction | high recall, decent precision | slow (~2–5 s/JD) | 1 API call | low | FP: generic phrases; FN: rare | use, but *bounded* by taxonomy |
| ESCO/taxonomy dictionary matching | high precision (only real skills), moderate recall | instant | 0 | low | FP: ~none; FN: novel skills | **primary** for the German market |
| KeyBERT (+ MMR) | top-tier among extractors in comparative benchmarks | ~1 s | 0 (local) | low | FP: mid-frequency phrases | secondary/opinion channel |
| YAKE / RAKE | mid; YAKE duplicates, RAKE noise | instant | 0 | very low | FP: frequent | skip (nothing they do that KeyBERT+taxonomy don't do better) |
| spaCy noun phrases + custom skill patterns | high precision for tech nouns | instant | 0 | medium | FN: out-of-vocab | useful for candidate-side evidence extraction |
| TF-IDF | weak (statistical, no semantics) | instant | 0 | very low | both high | skip |
| Transformer NER (skill-typed) | strong, esp. fine-tuned | ~0.1 s | 0 | medium-high | balanced | P2: only if benchmark shows taxonomy gaps |

**Recommended extraction architecture:** *taxonomy-first, LLM-assisted, embedding-verified* —
1. ESCO dictionary match (deterministic, precise, multilingual incl. German),
2. LLM proposes additional JD-specific keywords (1 call), each validated by (a) presence in JD text or
   (b) embedding similarity to a JD sentence — killing invented keywords,
3. KeyBERT as a recall net over the remainder.
Output: a structured, deduplicated, priority-ranked keyword/requirement list — the **measurable
contract** every later stage is checked against.

## 10. Semantic matching

Exact keyword matching is not enough — but semantic matching without truth-guards is dangerous.

**Models (all Apache-2.0, CPU-runnable, via sentence-transformers):**
- **`all-MiniLM-L6-v2`** — 384-dim, 5× faster than mpnet, ~90–95% relative quality; the throughput
  choice; English-only.
- **`BAAI/bge-small-en-v1.5`** — 384-dim, matches/beats MiniLM on retrieval benchmarks at same size.
- **`intfloat/multilingual-e5-small`** — **the pick**: multilingual (German postings!), strong on
  retrieval, small enough for CPU; E5 models need "query:"/"passage:" prefixes.
- **Cross-encoder rerankers** (`cross-encoder/ms-marco-MiniLM-*`, bge-reranker-base) — much better
  precision for *pair* judgments; use on the top candidates only (it's ~50–100× slower than bi-encoders).

**The "container orchestration ↔ Kubernetes" problem:** semantics must be used to *verify relevance*,
never to *grant skills*. Rule:
- Semantic similarity answers: *"does this resume line contain evidence relevant to this requirement?"*
- Granting a skill to the candidate is a **knowledge-base + taxonomy** decision only (§15). If the KB
  lacks Kubernetes, the resume may not claim it — even if "container orchestration" scores 0.9
  similarity. Conversely, when the KB *has* Kubernetes and the JD says "K8s", the taxonomy maps them
  and the resume should carry the JD's surface form where truthful.

**Concrete matcher:** requirement list × resume evidence bullets → bi-encoder cosine (multilingual-e5)
for candidate pairs → cross-encoder rerank of top pairs → thresholded matrix → per-requirement
"covered / partially covered / missing" with the *evidence sentence* attached. Fully local, ~free,
deterministic given fixed models.

## 11. Document format validation

**What to check on the generated PDF (per §4 failure modes):**
- text extraction succeeds and is non-empty in reading order (Docling + PyMuPDF both)
- name/contact strings extract intact and in the header region
- all section headers detectable (exact expected set)
- no value garbled (compare extracted text vs. component JSONs — this is also the hallucination check)
- no glyph loss: Unicode map check (current pipeline already normalizes dashes/quotes — extend the check to the final PDF text)
- header/footer text not duplicated into body (the template's fancyhdr is empty — verify)

**What to check on the DOCX:** python-docx read-back of every paragraph; simple paragraph flow (the
current mirror is already parser-friendly — keep it that way); no text boxes; no hidden content.

**Which format to generate:** keep **both**. DOCX = safest parsing; PDF = expected by German
recruiters. Test the DOCX→PDF conversion question by *not* converting (we already compile LaTeX natively,
which is cleaner than DOCX→PDF converters, which can garble fonts/spacing — a known risk in
conversion tools; native compilation sidesteps it entirely).

**Template risks found (from static analysis; to confirm empirically):** two-column `tabular` header
(currently contains name + contact — the highest-stakes fields, in the riskiest construct),
`tcolorbox`-based section headers (visual, not `\section`-marked in flow order), fontawesome icons
next to link text. Recommendation: keep visuals if the parser simulation extracts everything cleanly;
otherwise simplify the header block to single-column.

## 12. ATS simulation — what is realistically possible

| ATS stage | Can we simulate? | How |
|---|---|---|
| File ingestion & text extraction | **Yes, faithfully** | Docling + PyMuPDF double-extraction |
| Reading-order/layout robustness | **Yes** | position data from PyMuPDF; compare orders |
| Section detection & field extraction | **Yes, approximately** | ported OpenResume-style heuristics; disagreement between our parser and intent = red flag |
| Date/title/company normalization | **Yes** | regex suites incl. German formats (MM/YYYY, "Januar 2024") |
| Skill extraction | **Yes, approximately** | ESCO dictionary + NER over extracted text |
| Keyword/Boolean search behavior | **Yes, as a model** | exact + fuzzy + taxonomy-expanded coverage counts |
| Semantic recruiter search | **Partially** | local embeddings approximate; vendor models unknown |
| Knockout questions | **No** (they live in application forms, not resumes) | out of scope — but *detect* the JD's knockout requirements (work auth, German level) and surface them to the user |
| Vendor ranking algorithms | **No** | private; multi-parser agreement is the honest proxy |

**Honest framing for the report card:** our score is a *lower bound robustness indicator* across N
parsers, not a prediction of any vendor's number.

## 13. Multi-model architecture with the free APIs

Available: Ollama Cloud (gpt-oss:120b — current), NVIDIA NIM free API (large model endpoints, free
credits/rate-limited), Gemini free tier (fast, generous daily free quota, structured-JSON output mode),
OpenRouter free models (rotating free-tier models, variable reliability).

**Responsibility split (each role → model choice rationale):**

| Role | Model | Why |
|---|---|---|
| A — JD analyst (structured JSON) | **Gemini free tier** (or gpt-oss:120b) | needs instruction-following + JSON mode; fast; free quota fits daily volume |
| B — Content generator (the writer) | **gpt-oss:120b** (Ollama Cloud) | current prose quality is acceptable; keep one constant here to limit variables |
| C — Independent critic/fact-checker | **NVIDIA NIM model** (different family from B) | independence is the point — same-family models share biases |
| D — Optional tie-breaker (disagreements) | **OpenRouter free model** | only on conflict; costless standby |

**Strategies compared (reliability/cost):**
- A: one large model — cheapest, zero verification. Rejected.
- B: one model + deterministic validation — big win per cost (catches structure + coverage + hallucination-by-lookup). Strong baseline.
- C: two independent models — catches prompt-blindspots of B; ~2× LLM cost.
- D: multi-agent swarm — no evidence of benefit at this task size; rate limits and latency explode. Rejected.
- **E (recommended): LLM + NLP + embeddings + deterministic validators + 1 independent LLM review** —
  the deterministic layers do the measurable work; LLMs do language tasks; a single cross-model review
  adds an independent pair of eyes. ~5–7 LLM calls/job total.

**Rate limits / quota strategy:** batch deterministic work first (taxonomy matching, embeddings are
local — zero quota); cache JD analyses by URL hash (postings repeat across portals); route by time of
day across providers when one throttles; retry with backoff then fallback chain
(Gemini → gpt-oss → NVIDIA). Concurrency: 3–4 parallel jobs is safe under all free tiers.

## 14. The verification loop

```
JD ──► [1] JD ANALYSIS (LLM-A, JSON-validated)          required / preferred / nice / languages / years / knockouts / keywords
        ──► [2] NORMALIZE (deterministic)                ESCO mapping, dedupe, exact-form variants
        ──► [3] EVIDENCE MATCHING (deterministic+emb)    JD requirements × candidate KB → what may be claimed
        ──► [4] CONTROLLED GENERATION (LLM-B)            select+tailor from KB evidence ONLY; no invention slots
        ──► [5] GENERATE DOC (deterministic)             LaTeX/DOCX build (existing step 5, hardened)
        ═══════════ VERIFICATION (all deterministic except [9]) ═══════════
        [6] PARSE SIMULATION                             Docling + PyMuPDF → fields, sections, reading order
        [7] COVERAGE                                     keywords × extracted text → required %, preferred %
        [8] SEMANTIC MATCH                               e5 embeddings + reranker → per-requirement evidence
        [9] FACT REVIEW (LLM-C, independent model)       claim-by-claim: supported by KB? y/n/evidence
        [10] HALLUCINATION CHECK (deterministic)         every value in extracted text ∈ KB or JD-mirrored set
        [11] FORMAT CHECK                                §11 checklist
        ──► SCORE (§16) ──► iterate [4] if below threshold (max 2 iterations)
        ──► ACCEPT if score improves and fact-check stays clean; else keep V1
```

**Stopping conditions (from §16 research):** max 2 optimization iterations; iteration accepted only if
(coverage+semantic) improves ≥ small ε AND hallucination check stays clean AND length constraints hold;
on tie → keep earlier version. This prevents loops and stuffing by construction (stuffing raises
coverage but the naturalness/length checks and the LLM-C review gate it).

**Failure recovery (§33):** LLM-A JSON malformed → 1 repair call → else fall back to deterministic
keyword-only analysis (pipeline still runs, score flagged "low confidence"). LLM-B fails/flagged →
retry with fallback model → else job parked with reason (visible, not silently dropped). Parser fails
on our own PDF → build failure, fix template, never ship unverified. Score decreases after iteration →
revert. German JD → analyze in German, generate English resume (or German later — §21), keep German
verbatim keywords where truthful.

## 15. Candidate knowledge base

The single most valuable structural change. Replace "LLM re-reads prose facts in 6 prompts" with one
authoritative file (YAML/JSON) the whole system consumes:

```yaml
profile:
  name: RAVAL MEETKUMAR RITESHKUMAR
  contact: {phone, email, linkedin, github, location}
  work_authorization: <e.g. student visa 140 full-days rule — facts to state truthfully>
education:
  - degree: MSc Artificial Intelligence
    school: BTU Cottbus-Senftenberg, Germany
    dates: {start: 2025-04, end: present}
    highlights: [courses/projects relevant per course]
experience:
  - id: soham
    company: Soham Infotech
    title_options: [Software Engineer, Backend Engineer]      # ONLY these are defensible
    dates: {start: 2023-12, end: 2025-01}
    evidence:                                                   # EVERY claim links here
      - "integrated backend systems, servers and databases to improve latency,
         data management and performance (cross-functional team)"
    allowed_skills: [backend engineering, system integration, database management,
                     performance optimization, ...]             # curated, evidence-tagged
    forbidden: [any seniority word, frontend, devops, cloud, ml engineering]
  - id: pantechelearning
    company: Pantechelearning
    dates: {start: 2021-12, end: 2022-02}
    evidence:
      - "MySQL for data management/storage supporting ML workflows"
      - "backend infrastructure for web applications with Django and Flask"
    allowed_skills: [MySQL, Django, Flask, backend development, ...]
    title_must_include: Intern
projects:                                   # REAL projects — kills invention
  - id: tradingview-data-fetch
    title: TradingView Data Fetch
    evidence: ["fetches market data ... 40+ stars, 24+ forks on GitHub"]
    allowed_skills: [python, APIs, data pipelines, ...]
  - id: sarcasm-detection-research          # the real LLM research
    evidence: ["empirical study on LLMs for sarcasm detection in low-resourced Indic languages"]
    allowed_skills: [NLP, LLMs, transformers, ...]
skills:            # every entry: {name, aliases, evidence_ids}
  - {name: Python, aliases: [python3], evidence: [tradingview, soham?]}   # evidence REQUIRED
certifications: [...]
languages: [{English: C2}, {German: A2}, ...]
achievements: [...]
```

**Enforcement mechanism (§30 — facts vs generation):** after generation, every skill token, every
metric, every role title in the output is matched against the KB (exact + alias + taxonomy). Any token
not in the KB or the JD's *verbatim* keyword set → hard fail, regenerate with the violation listed.
The LLM may rewrite/reorder/summarize/select; it may not introduce a single noun that isn't licensed
by the KB. This converts truthfulness from a prompt suggestion into a compile error.

## 16. Scoring framework

Proposed weighted score with **hard gates** — informed by what parsers/search actually reward (§4)
and by the requirement-priority distinction:

**Hard gates (pass/fail, before any score):**
- G1: document parses; name/contact/sections extracted correctly
- G2: hallucination check clean (every claim KB-licensed)
- G3: all required sections present
- G4: all dates/locations/companies intact

**Weighted score (0–100):**

| Component | Weight | Measured by | Rationale for weight |
|---|---|---|---|
| Hard-requirement coverage | 25% | KB/JD-required keywords present (exact or taxonomy-alias) in extracted text | highest ATS search weight; recruiters filter on must-haves |
| Semantic requirement match | 20% | e5+reranker per-requirement evidence | captures synonyms modern systems use |
| Preferred-skill coverage | 15% | same, preferred tier | differentiates but doesn't disqualify |
| Profile parse fidelity | 10% | parser field extraction vs intent | garbled profile = recruiter sees garbage |
| Machine readability/format | 10% | §11 checks incl. reading order | silent killer when it fails |
| Experience relevance | 10% | semantic match of experience bullets vs JD responsibilities | human-screen weight |
| Seniority/language fit signals | 5% | years-req ≤ ours, language reqs surfaced | knockout proxy |
| Naturalness (LLM-C or perplexity proxy) | 5% | independent review verdict | anti-stuffing guard |

Weights are **configuration, not gospel**: the benchmark (§17) should re-fit them against outcomes
(dataset labels first; real invite-rate data later). Key design decision: it is *not*
`found/total` — it's tiered (required vs preferred), taxonomy-expanded, and gated by truthfulness.

## 17. Benchmarking framework

**Public datasets for calibration (verified to exist on HF/GitHub):**
- `cnamuangtoun/resume-job-description-fit` (HF) — resume+JD pairs with fit labels
- `facehuggerapoorv/resume-jd-match` (HF) — JD↔resume pairs
- `netsol/resume-score-details` (HF) — 1,031 resume-JD pairs with alignment scores
- `jensjorisdecorte/Skill-Extraction-benchmark` (GitHub) — ESCO skill-extraction benchmark (JCD)
- Kaggle resume-dataset (resume corpus + categories)

**Own benchmark (more important — domain-matched):** freeze a set of the already-fetched postings
(e.g., 50–100 jobs spanning English/German, tech/non-tech) + the master candidate KB. Then:
1. **Regression suite:** fixed jobs → fixed pipeline → all scores; any code change must not drop the
   suite (per-metric before/after table).
2. **A/B evaluation:** old pipeline vs new on the same jobs; compare coverage %, semantic score,
   hallucination count (should go: invented-project >0 → 0), parse fidelity.
3. **Agreement metrics:** % of claims accepted by LLM-C; extractor agreement (Docling vs PyMuPDF).
4. **Human anchor (tiny but real):** user blind-ranks 10 old-vs-new resume pairs; check ranking
   correlation with score. This validates weights cheaply.
5. **Dataset scoring check:** run the scorer on labeled pairs; verify the score separates fit vs
   no-fit (AUC-style check) before trusting it for iteration decisions.

**Adversarial suite (§20):** JD with 12-word title; German-only JD; JD with "K8s/CI-CD" abbreviations;
JD demanding unsupported skills (watch for hallucination); PDF with LaTeX special chars in title
(`C++ & R&D (m/w/d)`); contradictory requirements; duplicate postings; empty description; German date
formats. Each is a named test case with expected behavior.

## 18. Recommended architecture

```
                ┌──────────────────────── CANDIDATE KB (YAML, evidence-linked) ────────────────────────┐
                │  profile · education · experience(stints+allowed_skills+forbidden) · REAL projects    │
                │  skills(+aliases, evidence_ids) · certs · languages · achievements                    │
                └───────────────────────────────────┬──────────────────────────────────────────────────┘
                                                    │
JOB CSV ─► JD CLEANER ─► [LLM-A] JD ANALYST (JSON)  │
 (existing        (deterministic)   │               │
  steps 1–2)                        ▼               ▼
              REQUIREMENT EXTRACTION + SKILL NORMALIZATION (ESCO dict + fuzzy + aliases)
                                    │
                                    ▼
                        EVIDENCE MATCHER (KB × requirements → claimable set)
                                    │
                                    ▼
                        [LLM-B] CONTROLLED GENERATOR (select & tailor ONLY from claimable set)
                                    │
                                    ▼
                        DOCUMENT BUILDER (existing step 5, hardened; PDF+DOCX)
                                    │
        ┌───────────────────────────┴──────────────── VERIFICATION ───────────────────────────┐
        │  PARSER SIM (Docling+PyMuPDF+heuristics) · COVERAGE · SEMANTIC (e5+reranker)         │
        │  HALLUCINATION CHECK (KB lookup) · FORMAT CHECK · [LLM-C] INDEPENDENT REVIEW          │
        └───────────────────────────┬──────────────────────────────────────────────────────────┘
                                    ▼
                    SCORE (hard gates + weighted) ──► iterate ≤2× ──► ACCEPT/REVERT
                                    ▼
              SCORECARD (json) + resume + per-job history (append-only runs/ directory)
```

Removed from current system: LLM-invented projects, prompt-only truthfulness, per-prompt re-analysis
of the raw JD, silent dropping of flagged jobs, single-attempt stages, unverifiable quality.
Kept: scraping/filter steps, LaTeX+DOCX builders, tectonic, the 4-component output shape (familiar),
the user's manual CSV curation step.

## 19. Recommended technology stack

| Layer | Choice | License note |
|---|---|---|
| JD/skill taxonomy | **ESCO** (API v1.1.6 or bulk CSV download; German labels included) | free reuse w/ attribution; not OSI but fine for this use |
| Generation LLM | gpt-oss:120b via Ollama Cloud (keep) | free tier |
| Analyst LLM | Gemini free tier (JSON mode) w/ gpt-oss fallback | free tier |
| Critic LLM | NVIDIA NIM model (different family) w/ OpenRouter fallback | free credits |
| Embeddings | `intfloat/multilingual-e5-small` (+ `cross-encoder/ms-marco-MiniLM-L-6-v2` reranker) | Apache-2.0 |
| PDF/DOCX extraction | Docling (primary) + PyMuPDF or pdfplumber (secondary) | MIT / MIT / ⚠️AGPL(PyMuPDF) — pick pdfplumber if commercial future matters |
| Resume-parse heuristics | port of OpenResume 4-step logic (reimplemented, not vendored) | logic inspired; original is AGPL |
| Keyword extraction | KeyBERT + spaCy (de_core_news_sm + en_core_web_sm) + rapidfuzz | MIT |
| NLP pipeline | spaCy, sentence-transformers | MIT / Apache-2.0 |
| Data/schema | Pydantic models for JD-analysis & scorecard JSONs | MIT |
| Storage | append-only `runs/<date>/<job_id>/` dirs + SQLite index for history/benchmark | stdlib |
| Orchestration | plain Python module (no framework warranted at this scale) | — |
| Docs/build | existing tectonic, python-docx | MIT |

Explicitly **not** recommended now: LangChain/agent frameworks (weight without benefit here), paid
parsers (Jobscan etc. — benchmark reference only), PyMuPDF in a future commercial build, GPU inference
(e5-small is CPU-fine).

## 20. Implementation roadmap

- **Phase 1 — Quick wins (1–2 days):** candidate KB file; unify retries (all stages, backoff, key rotation); shared `common.py`; enforce objective word count in code; concurrency 3–4; caching by URL; "runs/" history directory.
- **Phase 2 — ATS verification (3–5 days):** Docling+pdfplumber extraction of our own PDFs/DOCX; parse-fidelity checks (name/contact/sections/dates); coverage counter (start: JD keywords from a simple LLM-A call, exact+rapidfuzz match); hard gates + basic scorecard JSON; make flagged jobs visible in dashboard instead of silently dropped.
- **Phase 3 — Structured JD + taxonomy (3–5 days):** Gemini JD-analyst with JSON schema (required/preferred/nice, years, languages, knockouts); ESCO dictionary matching + alias table; tiered coverage scoring; evidence matcher against KB.
- **Phase 4 — Controlled generation (2–4 days):** rewrite generator prompts to consume KB evidence + claimable set (kill invention slots); deterministic hallucination check (every output token ∈ KB ∪ JD-verbatim); LLM-C independent fact review; iterate-≤2 loop with accept/revert.
- **Phase 5 — Semantic layer + benchmark (3–5 days):** multilingual-e5 matcher + reranker; semantic component of score; HF dataset calibration; own 50–100-job frozen benchmark + adversarial suite; re-fit weights.
- **Phase 6 — Hardening (ongoing):** fallback chains across all three providers; German-output mode (Lebenslauf variant: MM/YYYY dates, tabular style, photo option, drop DECLARATION); dashboard score panels; nightly regression run.

## 21. Recommendation table

| Area | Current | Problem | Better | Tool/model | Expected gain | Difficulty |
|---|---|---|---|---|---|---|
| Projects | invented per JD (+fabricated metric) | integrity + interview risk | real projects from KB, tailored emphasis | KB + LLM-B | removes worst hallucination class | low |
| Truthfulness | prompt-only | unverifiable | deterministic KB check on every token | rapidfuzz+aliases | hallucinations → compile error | medium |
| JD understanding | raw text into prompts | no measurable contract | structured JSON analysis | Gemini free tier | coverage becomes measurable | medium |
| Skill normalization | none | synonym misses | ESCO + alias map | ESCO bulk/API | recovers exact-match losses | medium |
| Coverage | none | blind | tiered keyword coverage on *extracted* text | rapidfuzz + heuristics | tunable, honest metric | low |
| Machine readability | unverified | silent garbling | dual-parser simulation | Docling + pdfplumber | catches layout failures pre-send | medium |
| Semantic match | none | synonym blind spot | e5-small + reranker evidence match | sentence-transformers | +relevance signal, local & free | medium |
| Independent review | none | single-model bias | LLM-C different-family reviewer | NVIDIA NIM | catches prompt blindspots | low |
| Iteration | one-shot | no improvement path | ≤2-iteration accept/revert loop | scorecard | monotonic quality | low |
| Reliability | no retry in 2 stages; 1 key; serial | silent drops, slow | unified retries, rotation, 3–4 workers, caching | — | fewer lost jobs, ~3× throughput | low |
| History | overwrite | no regression safety | append-only runs + SQLite | stdlib | benchmarkable | low |
| Germany fit | US-style CV, DECLARATION, odd dates | market mismatch | Lebenslauf variant; DE date format; language-req surfacing | template work | recruiter-fit | medium |
| Benchmarking | none | unfalsifiable claims | frozen suite + HF calibration + blind human ranking | HF datasets | every change is evidence-based | medium |

## 22. Priorities P0–P3

**P0 — must implement:** candidate KB with evidence links; real projects (kill invention); deterministic hallucination check; parse-fidelity verification of own PDF/DOCX; unified retries + concurrency + caching; runs/history directory.
**P1 — strong improvement:** structured JD analysis (JSON schema); ESCO normalization + tiered coverage scoring; scorecard with hard gates; independent LLM-C review; benchmark suite v0 (20 jobs, before/after).
**P2 — experimental:** semantic matching layer (e5+reranker) folded into scoring; multilingual German resume variant; KeyBERT/NER recall net; weight re-fitting on HF datasets.
**P3 — not worth it (now):** multi-agent frameworks; fine-tuned CareerBERT-style models; OCR paths; vendor-ranking emulation; GPU inference; paid APIs.

## 23. What cannot be verified

- Exact ranking/scoring algorithms of Workday, SuccessFactors, Greenhouse, Lever, Personio, etc. — private; vendor docs describe *parsing*, never ranking. (Public help pages, e.g., Workday's "Concept: Resume Parsing," document profile-population behavior only.)
- Whether any specific vendor uses semantic search, and with which models.
- Real recruiter-search query distributions (no public data).
- Any commercial "ATS score" as a representation of actual ATS behavior — algorithms are private and mutually inconsistent; treat all such scores as the vendor's own model (§26 in the task, resolved here: separate REAL PARSING from SCORING-MARKETING — we simulate the former, we do not pretend to predict the latter).
- Discrimination/penalty effects of AI-tailored resumes (no reliable public study).

**What we do instead:** multi-parser agreement (lower-bound robustness), taxonomy+exact+semantic
coverage (models the three observable mechanisms), truthful content (immune to the unmeasurable),
and an own benchmark (the only honest arbiter of "better").

## 24. Final answer: the architecture I would build

**Rebuild, concretely:**

**Remove:** (1) LLM-invented projects and the permitted fabricated metric; (2) prompt-only
truthfulness as the sole guard; (3) the five separate per-prompt raw-JD re-readings; (4) silent
dropping of flagged jobs; (5) single-attempt stages and the one-key serial client; (6) the assumption
that the output is machine-readable without checking.

**Add:** (1) a **candidate knowledge base** — one YAML with evidence-linked facts; the *only* source
of claims; (2) an **LLM-A JD analyst** (Gemini free tier, JSON-validated) producing required/preferred/
knockout/language requirements + keywords; (3) **ESCO+alias normalization** (German-aware); (4) an
**evidence matcher** deciding what may be claimed; (5) **controlled generation** (gpt-oss:120b)
restricted to the claimable set; (6) a **verification battery**: Docling+pdfplumber parse simulation,
tiered coverage, multilingual-e5 semantic evidence match, deterministic hallucination lookup,
format checks, plus one independent LLM-C review (NVIDIA family) — all feeding a hard-gated weighted
scorecard; (7) a **≤2-iteration accept/revert loop** and append-only run history; (8) a frozen
50–100-job benchmark + adversarial suite so every future change is measured, not felt.

**Why:** every mechanism above corresponds to an *observable* ATS behavior (parsing, field extraction,
exact/taxonomy/semantic matching, knockout visibility) — nothing depends on unknowable vendor
rankings. The heavy lifting is deterministic and free (ESCO, rapidfuzz, e5-small on CPU); LLMs are
used where language genuinely requires them, 5–7 calls per job, with independent verification coming
from a *different* model family. Most importantly, the system becomes **falsifiable**: hallucination
is a compile error, coverage is a number, quality is a benchmark — which is exactly what the current
JOB → LLM → RESUME design cannot ever be.

---

*Research basis: Workday & SAP SuccessFactors public parsing docs; OpenResume's documented parser pipeline; the 2024 open-source PDF-parser comparative study (arXiv:2410.09871); KeyBERT/comparative keyword-extraction literature (D'Agostino benchmark; IEEE Access 2023 comparative assessment); ESCO API/O*NET documentation; Nesta skills-extractor library; Skill-Extraction-benchmark (ESCO/JCD); CareerBERT (ESWA 2025); LLM-as-a-judge and hallucination-detection literature 2024–2026; Hugging Face datasets (resume-job-description-fit, resume-jd-match, resume-score-details); 2024–2026 ATS-myth analyses (multiple independent sources). Vendor ranking behavior remains unverified by design — see §23.*
