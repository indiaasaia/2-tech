# COVER LETTER MODEL — The Anschreiben Engine (design + measured decisions)

Companion to `FINAL_MODEL.md`. Everything here was either sourced from the
German application norm (DIN 5008 / Agentur für Arbeit guidance) or measured
in this repo (E2E tectonic builds, 2026-09-23). No design choice is assumed.

---

## 1. The German norm the engine implements

A German cover letter (Anschreiben) is a **one-page formal letter** in a
DIN 5008-style layout. Recruiters expect exactly this shape, and the letter
language must match the posting language. The engine bakes the norm in
deterministically:

| Element | Norm | Engine implementation |
|---|---|---|
| Length | exactly one page A4 | L1 word bounds + E2E page-count assert |
| Sender block | top right | template, fixed |
| Company block | left | posting company (detail field preferred) |
| Date | DD.MM.YYYY (city-prefixed) | deterministic, at fill time |
| Subject | bold, exact job title + reference, never the word "Betreff:" | `build_subject` from the posting title verbatim |
| Salutation | gendered "Sehr geehrte Frau/Herr <Name>," if a contact is named, else "Sehr geehrte Damen und Herren," | honorific regex, case-sensitive, stopword-guarded; gender NEVER guessed from names |
| Body | 3-4 short paragraphs | exactly 4: opening / fit / motivation / closing, ≤ 55 words each |
| Sign-off | "Mit freundlichen Grüßen" | deterministic — never LLM-written |
| Photo | none in the letter | template has no photo slot |
| Salary | never volunteered | L2 blocks money/`Gehalt` claims outright |

Language choice follows the analyst's posting-language detection (en/de,
umlaut+function-word fallback): German posting → German letter, English
posting → English letter. This matches the norm "apply in the posting's
language; German is the safer default."

## 2. Pipeline position — a SEPARATE phase after ALL resume work

The letter phase is its own step (step 6, `run_step6.py`), run strictly after
step 5 has built and verified every resume. Letters are written to their own
separate files; the two phases share no writes. Rationale: a letter can never
cost a resume, the phases are independently re-runnable, and the letter joins
the resume report only at bundle time.

```
STEP 4 (per job)          RESUME-side only
  ... resume generation ... -> gated_ok record + letter_input payload
  letter_input = { posting fields (config.LETTER_POSTING_COLS), analysis }
  (NO letter work — zero letter LLM cost)

STEP 5 (per gated_ok job) RESUME-side only
  resume build + verify + scorecard -> resume_report.json
  (NO letter work — letters cannot slow or block the resume phase)

STEP 6 (per gated_ok job) LETTER PHASE — after ALL resume work
  letter_input -> deterministic skeleton -> ONE constrained LLM call
  -> post-checks -> creation-time gates L1-L4 (run_step4.process_letter_input)
  -> build-day date (probe_date_line) -> re-gate L1-L4
  -> fill @@CL_*@@ template (de/en) -> L3 artifact checks -> tectonic PDF
  -> SEPARATE FILES per letter: Anschreiben_<Company>_<Role>.{tex,pdf,docx,txt}
  -> letters_report.json + application_bundles.json (per-portal upload guide)
  legacy migration: old records with components.cover_letter re-gate + rebuild
  WITHOUT any LLM call
```

Cost: +1 LLM call per job (repair: +1). Everything else is deterministic.
Resume-mode: letters already verified in letters_report.json are kept (no
call) unless --force.

## 3. Truth licensing (the same anti-fabrication discipline as the resume)

- The body prompt receives the **claimable set**: OWNABLE skills may be
  claimed; MIRRORABLE JD tools only as learning targets ("working toward").
- **Zero digits** allowed in generated paragraphs (dates/subject are added by
  the system) — the V6 digit-rule evasion class cannot even form.
- Company facts may only reference the posting's own `about_us`/snippet text;
  unverifiable flattery ("preisgekrönt", "award-winning") is flagged by L2.
- **L2 reuses `check_g2_claims`** — tech tokens ⊆ claimable set, spelled-out
  numbers, percentages — plus letter-specific salary/flattery checks.
- Gate failure at step 4 = letter parked with the violations recorded; the
  resume still ships and the bundle honestly reports the missing letter.

## 4. Portal awareness (delivery, not content)

The letter CONTENT is portal-agnostic by design; what varies per portal is
the DELIVERY. `portal_delivery.PORTAL_REQUIREMENTS` encodes it:

| Portal | PDF slot | Text field | DOCX |
|---|---|---|---|
| stepstone | "Anschreiben" document slot | no | no |
| workingstudentjobs | cover letter upload | yes | yes |
| linkedin / xing / indeed | attachment | yes | no |
| unknown | upload | yes | yes |

The engine always ships **pdf + txt + docx** and a manifest
(`application_bundles.json`) that says, per job, what to upload where, which
artifacts exist, and what is missing (`artifacts_complete` flag). The .txt is
the paste-ready version for "Nachricht"/message fields (XING/Indeed/LinkedIn
quick-apply), where a PDF alone is not enough.

## 5. Template parser-safety (measured, E2E)

New findings from this build — both would have shipped silently:

1. **Justified text destroys word boundaries.** With justification, Pagella's
   0.25em interword space compresses below pdfplumber's x_tolerance and the
   extracted text becomes "MitfreundlichenGrüßen". Fixes: `\raggedright` +
   `\spaceskip 0.34em` (measured: word gaps ≥ 3.3pt, clean extraction).
2. **cfr-lm silently overrides `\setmainfont`** in the resume template: shipped
   PDFs render LMRoman, not Pagella. The letter templates therefore load
   fontspec + texgyrepagella WITHOUT cfr-lm — and actually render it
   (verified via embedded fontname).
3. **`escape_latex` is not idempotent** (R&D → R\&D → R\textbackslash{}\&D).
   The double-escape corrupted values containing `& % $ # _` — several shipped
   resume .tex artifacts carry the signature. `fill_template` now treats
   values as final LaTeX and **fails loud** on unescaped specials
   (`@@...@@` spans exempt — they are template cross-references).

## 6. Files

| File | Role |
|---|---|
| `generation/cover_letter.py` | skeleton + 1 constrained call + post-checks + fill values |
| `verification/cl_gates.py` | L1 structure / L2 truth / L3 artifact / L4 language |
| `generation/portal_delivery.py` | plaintext rendering + per-portal bundles manifest |
| `templates/cover_letter_template_de.tex` | DIN 5008-style German letter |
| `templates/cover_letter_template_en.tex` | English letter (en postings) |
| `templates/build.py` | `build_letter_docx`, `letter_file_names` |
| `run_step4.py` | resume generation; stores `letter_input` per gated_ok job | |
| `run_step5.py` | resume build/verify (letter-free) | |
| `run_step6.py` | THE LETTER PHASE: create/verify/build all letters after all resume work |
| `tests/test_cover_letter.py` | 55 unit tests incl. the recheck regressions (no LLM) |
| `tests/test_letter_template_smoke.py` | template fill smoke tests |
| `tests/test_letter_e2e_build.py` | live tectonic build + parse-back (skips w/o engine) |
| `tests/test_letter_real_jd.py` | real German JD + real KB regression (skips w/o engine) |

Config: `CL_TOKENS`, `LETTER_TEMPLATE_DE/EN`, `LETTERS_*_DIR`,

## 7. Two-phase restructure (2026-09-23, later the same day)

Per the user's request, letter creation moved wholly OUT of steps 4/5 into the
new step 6 (`run_step6.py`), which runs after ALL resume work. Letters land in
their own separate files (`Anschreiben_<Company>_<Role>.{tex,pdf,docx,txt}`),
with `letters_report.json` and `application_bundles.json` owned by step 6.
Step 4 stores a deterministic `letter_input` payload (posting fields +
analysis) so step 6 needs no CSV re-read; a legacy-migration path re-gates
old stored letters without any LLM call. Verified by the rewritten E2E
(`tests/test_letter_e2e_build.py`: two-phase flow, parked-letter path,
bundles manifest) — which also caught a missing `fill_template` import in
the first step-6 draft and a hermeticity hole (the letter call hit the real
Ollama endpoint; the body call is mocked now).

## 8. Recheck round (measured corrections, 2026-09-23)

A full re-read of the shipped engine against the real code (not memory) found
and fixed ten defects — each now pinned by a regression test:

1. **Single date source.** The gate probe hardcoded `23.09.2026` while fill
   re-derived the date locally — the same letter set could carry three
   different days (probe / PDF / report). Now `german_today()`
   (Europe/Berlin) is applied by `probe_date_line` at BOTH gate sites, and
   `to_fill_values` reuses the letter's own date. PDF/DOCX/TXT/report agree.
2. **Letter file names.** Letters were written under the resume stem (the
   `Anschreiben_<Company>` helper was dead code). Letters now carry their own
   neutral German name `Anschreiben_<Company>_<Role>` (role part keeps
   same-company applications from overwriting each other).
3. **Word bounds.** config said 180, L1 enforced 80 — a dead constant, and 180
   would park real letters (LLM bodies on real postings measure ~110-160
   words). One source now: `LETTER_WORD_MIN=100 / MAX=330` in config, enforced
   by L1 and injected into the prompt so the requested and enforced windows
   cannot diverge.
4. **L3 false positive.** A plain English exclamation ("strong fit! My...")
   matched the LaTeX-error marker `"! "` and parked the letter. Only a
   line-start `! Uppercase` (a real TeX error line) is flagged now.
5. **Company-mention gate.** A wrong/unbacked legal-form company in the body
   was only *logged*, never gated. L2 now parks such letters; KB employers
   (`soham infotech`, `pantechelearning`) and the target company are licensed.
   The detection regex is case-sensitive after measuring a greedy
   "Bank AG und die Commerzbank GmbH" collapse into one mention.
6. **Reference prose traps.** "Referenznummer bitte angeben" → `bitte`,
   "Kennziffer des Stellenangebots" → `des`. German articles, pronouns and
   imperative words are stoplisted; validated on 29 real scraped jobs: 2
   references found, both genuine, zero prose hits.
7. **Mixed contact pairs.** "Frau Weber oder Herr Maier" saluted only Frau
   Weber — a real mis-gendering. Any pair form (name between honorifics
   included) now yields the neutral plural salutation.
8. **KB-licensed languages.** The prompt hardcoded "English C2, German A2..."
   instead of reading `profile.languages_spoken` from the KB.
9. **Contact links.** The portfolio URL (present in the KB) was dropped from
   the sender block; a missing phone/email could also leave a dangling pipe.
10. **Company address block.** Only the company name was printed; the block
    now carries `detail_location` as well, and an unparseable KB address no
    longer silently falls back to a hardcoded city.

Final state: **184/184 tests green** (55 letter unit tests, template smoke,
mocked step-4 path, live tectonic E2E, real-JD regression), py_compile clean
across all touched modules.
`BUNDLES_PATH`, in `config.py`.
