# ATS Research Report V4 — Validated: Fixes Proven, New Bug Found, Claims Re-Audited

**Relationship to V1–V3:** V1 = architecture, V2 = primary sources, V3 = empirical measurement.
V4 (this) = **validation of V3's proposed fixes by actually building them** (original vs fixed PDF,
compiled and re-measured), a **data audit of the pipeline's real outputs**, and the discovery of a
**new, previously unknown shipping bug** that only artifact-level testing could find.

**Artifacts in this folder:**
- `experiment/validate_fixes.py` — the A/B experiment script (original vs fixed → compile → extract)
- `experiment/original.tex|pdf`, `experiment/fixed.tex|pdf` — the evidence
- `empirical_parser_test.py`, `empirical_parser_results.json` — the V3 test (still valid)

---

## 1. V3's fixes: validated by A/B build (not just proposed)

`validate_fixes.py` takes the real filled `.tex` of a shipped resume, applies the four V3 fixes,
compiles **both** versions with the project's own tectonic, and extracts both PDFs.

### Result matrix

| Check | original.pdf | fixed.pdf |
|---|---|---|
| Compiles under tectonic (XeTeX) | ✅ | ✅ |
| Section titles extract clean | ❌ ("AREER BJECTIVE", "E XPERIENCE") | ✅ ("Career Objective", "Experience", "Skills") |
| pypdf title corruption ("AREER", "KILLS") | present | **gone** |
| pdfplumber title corruption ("E XPERIENCE") | present | **gone** |
| Apostrophe dates (`Dec’23`) | 8 instances | **0** |
| Experience date machine-parseable | ❌ | ✅ `Dec 2023 – Jan 2025` |
| Ligature codepoints (ﬁ ﬂ ﬀ) | 18 | **6** (residual: `ﬀ`-type only) |
| Full name "…RITESHKUMAR" in extracted header | ❌ | ✅ (plumber shows it as own line) |

### The exact working fix configuration (validated — the two *failed* attempts matter)

| Attempt | Result | Lesson |
|---|---|---|
| `\input{glyphtounicode}` + `\pdfgentounicode=1` | ❌ compile crash: `\pdfglyphtounicode` undefined | pdfTeX-only; **tectonic is XeTeX** — the most common online advice does not apply to this stack |
| `\setmainfont{Latin Modern Roman}[Ligatures=NoCommon]` | ❌ font not found by name | tectonic's font resolution needs full file-based specs |
| **`\setmainfont{texgyrepagella}[Ligatures=NoCommon, Extension=.otf, UprightFont=*-regular, …]`** | ✅ compiles, ligatures 18→6, titles clean | **the validated recipe** |

Fix 1+2 (titleformat `\scshape`→`\bfseries`+`\MakeUppercase`; `Dec'yy`→`Dec yyyy`) applied cleanly
via regex on the filled tex and verified in output. **All four V3 fixes are now proven, with the
exact LaTeX required, on the project's own toolchain.**

### Residual open item
Fixed version still has 6 ligature codepoints (the `ﬀ` family) and the header name splits across
lines in extraction ("RAVAL MEETKUMAR" / "RITESHKUMAR" as separate lines for pdfplumber). Both are
minor; the ligature residue likely comes from `fontspec` default ligature set on *other* fonts
(`cfr-lm` body?) — needs the same `Ligatures=NoCommon` treatment applied to the body font family,
or accept 6 instances. Re-measure after full-font treatment.

---

## 2. NEW BUG FOUND (validation's biggest catch): every shipped resume shows wrong project content

**A/B testing the fixed tex surfaced text like `Skills: PROJECT-System integration, …` — never
predicted by any desk analysis.** Root-cause verified in `program_files/5_create_resume.py`:

```python
text = text.replace("SKILLS-1", experience_skills)        # ← runs FIRST
...
text = text.replace("PROJECT-SKILLS-1", project_skills)   # ← too late: placeholder already gone
```

`PROJECT-SKILLS-1` **contains the substring** `SKILLS-1`. The earlier generic replacement consumes
it, leaving `PROJECT-<experience skills>` in the document. Same collision for `DESCRIPTION-1` ⊂
`PROJECT-DESCRIPTION-1` and `SKILLS-2` ⊂ `PROJECT-SKILLS-2`. Consequence, **measured in 21/21
shipped PDFs**:

- The "Main Projects" **description lines show the *experience* description** (prefixed with
  literal `PROJECT-`)
- The "Main Projects" **skill lines show the *experience* skill list**
- The project *titles* (`PROJECT-1`/`PROJECT-2`) are correct — so the section looks plausible to a
  human skim, which is why this survived every run

**Why no existing check caught it:** the step-5 sanity check searches for *leftover* placeholders
(`PROJECT-\d`, `DESCRIPTION-\d`…). After the collision, none remain — they were consumed. The
literal string `PROJECT-` in output text was never checked.

**Concrete fix (validated by inspection, apply-ready):**
1. Replace in **longest-first order**: `PROJECT-DESCRIPTION-1` before `DESCRIPTION-1`,
   `PROJECT-SKILLS-1` before `SKILLS-1` (and the -2 twins). One-line reorder of the replace block.
2. Better: use collision-proof tokens (`@@PROJECT_DESC_1@@` in the template).
3. Add a sanity check: `assert "PROJECT-" not in filled_text` — this single assert would have
   blocked 21/21 broken resumes.

**Impact assessment:** this is a *content* bug, not just parsing — recruiters reading "Main
Projects" see duplicated experience text with a stray prefix, on every single resume sent. It is
plausibly the most damaging defect found in four research rounds, and it was found by
artifact-level A/B testing, not by reading code or prompts.

---

## 3. Data audit of the pipeline's real outputs (challenging earlier claims with numbers)

Ran directly against `2_filted_jobs.csv` + the four component JSONs (21 jobs, current run):

| # | Question from earlier rounds | Measured answer |
|---|---|---|
| A | How many JDs are German? | **7/21 German-signal** (33%) — the English-only resume assumption affects a third of targets |
| B | Does the 6000/4000-char truncation lose data? | **0/21 truncated** — truncation is a non-issue at current posting sizes; deprioritize |
| C | Are objectives within the 60-word rule? | **21/21 compliant** (longest exactly 60) — model obeys this constraint well; no code enforcement needed urgently |
| D | Cross-job duplication ("same resume for every job"? challenged) | **Roles: 14 distinct/21** (mode: "System Integration Engineer" ×5); **descriptions: 0 identical**; **project titles: 21/21 unique**; **skills rows: 21/21 distinct** — tailoring is real, not template-clone. The "artificial sameness" concern from V1 is *smaller than claimed* |
| E | Fabricated metrics in projects | **35 metric tokens across 42 slots** ("20%", "15 percent", "18%") — the V1-flagged fabrication class is *pervasive in practice*, not hypothetical. Under the KB rule (V2 C4: digits must exist in evidence), all 35 would be rejected → regenerated |

**Audit conclusions:** (1) the truncation worry is dead; (2) tailoring diversity is genuinely good;
(3) the two live content risks are exactly the two the KB design targets — fabricated metrics (35
instances) and over-conservative skill omission (V3's Python/SQL/LLM finding); (4) one-third German
JDs quantifies the Lebenslauf-variant priority.

---

## 4. Updated priority list (evidence-ranked, all four rounds combined)

| Rank | Item | Evidence | Effort |
|---|---|---|---|
| **1** | Fix replacement-order collision (§2) + `"PROJECT-" not in` assert | 21/21 PDFs shipping wrong project content | ~30 min |
| **2** | Apply the 4 validated template fixes (§1, exact LaTeX in `experiment/fixed.tex`) | titles/dates/name measured broken → fixed in A/B | ~1 h + re-run |
| **3** | Candidate KB + digit rule (V2 C4) | 35 fabricated metrics measured | 1–2 days |
| **4** | Coverage scorer over extracted text (V2 C3) | V3's over-conservatism (Python 9/21) | 1–2 days |
| **5** | JD analyst consolidation 6→3–4 calls (V2 A6) | call budget + serial free tier | 1 day |
| **6** | Lebenslauf variant (MM/YYYY, no DECLARATION) | 7/21 German JDs | 1 day |
| 7 | ESCO lookup + alias map | synonym misses (K8s etc.) | 2 days |
| 8 | Semantic layer (e5) after τ validation | nice-to-have vs 1–7 | later |

**Meta-lesson of V4 (the "challenge everything" payoff):** the three most valuable findings across
all rounds — the scshape corruption, the date-format invisibility, and the replacement-order bug —
were **all discovered by testing artifacts, not by analyzing code or searching the web**. The
project's future changes should be gated on the same loop: build → extract → assert → ship.

---

*Evidence chain: audit queries ran live on this run's CSV/JSONs (§3 numbers are reproducible from
`resume_content_improve_research/` scripts); A/B compile/extract results from
`experiment/validate_fixes.py` output (§1); root cause located in
`program_files/5_create_resume.py::fill_template` replacement order and confirmed in 21/21 shipped
PDFs (§2).*
