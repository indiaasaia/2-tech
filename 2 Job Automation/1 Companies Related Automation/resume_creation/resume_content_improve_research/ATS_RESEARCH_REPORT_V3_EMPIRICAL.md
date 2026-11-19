# ATS Research Report V3 — Empirical Edition: Measured, Not Assumed

**Relationship to V1/V2:** V1 = architecture research. V2 = primary-source verification + concrete
schemas. V3 (this) = **empirical measurement on the actual generated artifacts** + the challenged
remaining assumptions + the honest reframing of what optimization can and cannot deliver.

**New in V3:**
1. An actual parser simulation was **run on all 21 generated PDFs** (script:
   `empirical_parser_test.py`, raw output: `empirical_parser_results.json` in this folder).
2. **Three real defects were measured** in the current output — including two that no amount of
   desk research had predicted correctly, and one V2 prediction that was **wrong**.
3. The premise itself is challenged: what does evidence say about whether resume tailoring even
   moves outcomes, and what is the real German application path.

---

## 1. The empirical test — what was run

`empirical_parser_test.py` applies ATS-style heuristics (modeled on OpenResume's *published*
parser algorithm + standard ATS date regexes) to every PDF in `program_files/output/resume/pdf/`,
using **pdfplumber** as primary extractor and **pypdf** as independent cross-check (the dual-extractor
principle from V2, executed rather than proposed).

Aggregate results across the 21 real resumes:

| Check | Result |
|---|---|
| Text extracts at all | 21/21 ✅ |
| Name extractable | 21/21 ✅ |
| Email extractable | 21/21 ✅ |
| Phone extractable (EU regex) | 21/21 ✅ |
| Reading order (name before first section) | 21/21 ✅ |
| Section titles intact after extraction | **0/21 ❌** |
| Experience dates machine-parseable | **0/21 ❌** |

The headline: **the resume body extracts perfectly, but every section header and every experience
date is text-corrupted or regex-invisible in machine extraction.** A keyword-matching ATS search
still works (body text is clean), but section-aware parsing — how ATS build the structured profile —
silently degrades.

## 2. Finding 1 — Section titles are corrupted by the small-caps font (measured, not theorized)

Every section title in the template uses `\scshape` (small caps). Extraction result, 21/21 files:

```
"AREER BJECTIVE"      (Career Objective)      — pypdf
"E XPERIENCE"         (Experience)            — pdfplumber
"E DUCATION"          "M AIN P ROJECTS"
"ESEARCH AND UBLICATIONS"  "CHIEVEMENTS"  "KILLS"  "ERTIFICATIONS"  "DDITIONAL ROJECTS"  "ANGUAGES"
"RAVAL MEETKUMAR"     ← the NAME is corrupted too (small-caps header font)
```

- **Why:** in small-caps fonts, capital letters are rendered as larger *small-cap glyphs* whose
  Unicode mapping is lost by extractors — "C" of Career has no uppercase codepoint to map back to.
- **Extractor variance measured:** pdfplumber yields `"E XPERIENCE"` (letter + space); pypdf yields
  `"AREER BJECTIVE"` (letter dropped). **Different ATS parsers will get different corruptions.**
- **Fallback behavior:** keyword matching ("experience" in "E XPERIENCE") partially rescues
  pdfplumber-style output but fails pypdf-style output ("xperience" gone). Measured: keyword
  fallback detects only ~2 sections/file reliably.
- **Fix (one line):** replace `\scshape` with `\textbf` + normal case (or ALL-CAPS) in the section
  title format. This single change repairs: section detection, title-based profile mapping, *and*
  the corrupted **name in the header** — across all extractors.
- **V2 prediction that was WRONG:** V2 predicted the primary bold+ALLCAPS parser heuristic would
  fail on TitleCase titles and rely on keyword fallback. Reality: the titles *did* satisfy an
  uppercase-ish heuristic (that's why they surfaced as "sections" at all) — but their *content* was
  corrupted. The measured risk was different and worse than the predicted risk. Lesson recorded:
  template risks must be measured, not derived.

## 3. Finding 2 — Dates are invisible to standard ATS date regexes (measured)

Template emits `Dec'23 -- Jan'25` (apostrophe + 2-digit year). Results:

- The core year regex `(19|20)\d{2}` used by ATS parsers (OpenResume core, verified in V2): **0
  matches for experience/education date ranges** in 21/21 files. Only the education "April 2025 /
  June 2020 / May 2024" lines contain parseable years.
- pypdf additionally shows the apostrophe extracts as `’` (U+2019 curly quote), and the en-dash as
  `–` — so even custom `Dec'yy` regexes must handle three variants (`'`, `’`, missing).
- **Fix (one line in template):** `Dec'23 -- Jan'25` → `Dec 2023 -- Jan 2025`. Every parser's date
  regex then matches. This also aligns with German MM/YYYY convention (`12/2023 -- 01/2025`).

## 4. Finding 3 — Ligatures corrupt skill text (measured)

The Palatino-derived font produces fi/ff/fl **ligatures** that extract as single Unicode codepoints
U+FB01/U+FB02 ("efﬁciency", "workﬂows" — verified in both extractors). Impact: any ATS keyword
match against "efficiency" or "workflow" silently fails; ESCO/taxonomy matching likewise.

- **Fix (one line in preamble):** `\usepackage[T1]{fontenc}` is present, but ligature preservation
  requires `\input{glyphtounicode}\pdfgentounicode=1` (pdfTeX) — with **tectonic (XeTeX engine),
  the robust fix is disabling ligatures via `\usepackage[no-ligatures]{...}` or
  `\defaultfontfeatures{Ligatures=TeX}` handling / fontspec `Ligatures=NoCommon`**. Must be
  *measured after the change* with the same script — this is now a one-command verification loop.
- Severity: moderate (affects a handful of words per resume) but it hits *skill words* — the exact
  tokens coverage scoring cares about.

## 5. Finding 4 — the LLM's own output contradicts the prompt contract (measured)

The kb-probe in the test found: `python` absent from 12/21 resumes, `sql` from 16/21, `llm` from
20/21 — while experience 2 explicitly includes MySQL/Django/Flask work. Cross-reading the component
JSONs against the PDFs shows the model routinely writes "Backend development" instead of "Python"
— prompt-compliant (Python is indeed not established for stint 1) but **ATS-hostile**: a posting
asking for Python will keyword-match zero. This is not hallucination — it is the *opposite*:
over-conservatism that no deterministic validator would catch. It can only be detected by the
coverage metric comparing (KB-allowed skills) × (JD keywords) × (extracted text) — exactly the C3
metric from V2, now with measured motivation.

## 6. The German application-path reality (challenged the "ATS score" premise)

Researched how the resume actually flows in this user's market:

- **Stepstone (the pipeline's #1 portal):** application is via profile + uploaded CV; Stepstone
  Group's own FAQ states the resume "will be reviewed by the recruiter" — parsing into structured
  profile fields happens at portal/employer ATS level. Stepstone itself is owned by... Axel Springer;
  its employer-side products include reciprocal parsing tools. The parse-relevant insight: **your CV
  is parsed by the employer's ATS after download** — so the section/date fixes above apply directly.
- **workingstudentjobs.de:** smaller portal; typically forwards applications to employer email/ATS.
- **The German ATS stack** (SuccessFactors, Workday, Personio, Umantis, softgarden, d.vinci): all
  parse uploads into structured profiles; most recruiters then search/filter on parsed fields.
- **What this means:** "ATS score" as marketed is still fiction (V2 §23 stands), but
  *parse-fidelity* is the real, measurable proxy — and it is currently 0/21 on dates and section
  titles. Fixing measurable parse fidelity is worth more than any keyword-stuffing heuristic.

## 7. Does tailoring actually help? The evidence, honestly stated

The task asks for effectiveness, so the meta-question was challenged directly:

- **Causal evidence exists for content, not for keyword optimization.** Large-scale resume audit
  experiments (Quillian et al. meta-analyses; NBER field experiments) show randomized *credentials*
  move callbacks — that's evidence that what the resume *claims* (truthfully) matters.
- **No credible public RCT isolates "keyword tailoring" as a lever.** The 1.7M-application analyses
  (community-sourced, moderate evidence) found no ATS auto-rejection and substantial recruiter
  variance. Jobscan-class tools never publish callback-correlation data.
- **The defensible model of what works:** (1) *be findable* — parse cleanly + carry the terms a
  recruiter searches (truthful mirroring); (2) *be credible* — no hallucinations (interview risk);
  (3) *be relevant in 7 seconds* — recruiter-facing top-third. Keyword-stuffing beyond truthful
  mirroring has no evidence of benefit.
- **Consequence for the architecture:** coverage optimization remains valid *within* the
  truth-boundary (fixing Finding 4 = put allowed skills in, in the JD's own words), but the
  system's biggest measured wins are **parse fidelity** (Findings 1–3) and **fact safety**, not
  score-chasing. This is a genuine re-prioritization vs V2: parse/template fixes are P0 *before*
  the KB/coverage machinery.

## 8. Re-prioritized roadmap (supersedes V2 §D ordering)

**P0 — measured defects, one-line fixes (hours):**
1. Section titles: `\scshape` → bold normal-case/ALL-CAPS; re-run `empirical_parser_test.py` →
   expect 21/21 clean titles + uncorrupted name.
2. Dates: `Dec'yy` → `Dec yyyy` (or `MM/YYYY` German); re-run → expect year regex hits.
3. Ligatures: fix via XeTeX/fontspec setting; re-run → expect zero U+FB01/FB02.
4. Name line: ensure "RAVAL MEETKUMAR RITESHKUMAR" full name in PDF header (currently truncated to
   first two words in the visible header; V1 flagged; now measurable).

**P1 — KB + coverage (the V2 plan, now with measured motivation):** candidate KB; one JD-analyst
call; claimable-set generation; C3 coverage over the *extracted* text; C4 layer-1 hallucination gate.
Finding 4 is the concrete motivation: coverage would have flagged the missing "Python/SQL/LLM" tokens.

**P2 — semantic layer + benchmark harness** (V2 C6/C10, unchanged, including the τ_sem validation
and HF-dataset AUC gate).

**P3 — multi-model critic sampling** (NVIDIA 1,000-credit budget as in V2 A2).

## 9. Answer to "more concrete and effective" — the delta this round produced

| | V2 (desk) | V3 (empirical) |
|---|---|---|
| Template risks | predicted (2 of 3 wrong/misweighted) | measured: 3 defects, each with a one-line fix |
| Parse fidelity | assumed OK | **measured 0/21 on dates+titles** |
| Skill presence | assumed prompt-governed | measured over-conservatism (Python in 9/21) |
| ATS score value | "fiction" (argued) | reframed: parse-fidelity is the real KPI; score is secondary |
| Verification | "should test" | `empirical_parser_test.py` exists — every future template change is one command from verification |

The concrete, effective path is now: **run 4 template fixes, re-run the script, watch 0/21 become
21/21 — then build the KB/coverage layer on top of a document that machines can actually read.**

*Sources for this round: own measurements (empirical_parser_results.json); OpenResume published
algorithm (V2); Stepstone Group applicant FAQ; German ATS-market documentation; Quillian et al.
field-experiment meta-analyses and NBER audit studies (what moves callbacks: credentials, not
keyword tricks); all V2 primary sources remain in force where not superseded.*
