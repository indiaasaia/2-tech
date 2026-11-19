# How a Cover Letter Is Created (engine v3)

> **Moved (2026-10-17):** the runnable pipeline now lives in [`E:\WorkSpace\2 Tech\2 Job Automation\REGULAR_APPLICATION`](../REGULAR_APPLICATION/README.md) (`python run.py --days N` inside it; it does not depend on this repo). The engine package `resume_content_improve_research/` was renamed `REGULAR_APPLICATION/engine/`; paths below that name the old package refer to it. The old `main.py`, dashboard and tests no longer run from here.

**Scope:** how step 6 (`resume_content_improve_research/run_step6.py`) writes one
cover letter per job (German *Anschreiben* for German ads, English letter for
English ads): the skeleton, the LLM paragraphs, the checks, the files and the
upload bundle. It describes the code as it stands (October 2026).

Companion documents:
- [RESUME_CREATION.md](RESUME_CREATION.md): the resume phase (steps 4-5) and the keyword policy
- `resume_content_improve_research/COVER_LETTER_MODEL.md`: design notes

---

## 1. Where letter creation sits

```
STEP 4  run_step4.py   stores a `letter_input` per gated_ok job (posting fields + analysis). No letter work.
STEP 5  run_step5.py   resumes only.
STEP 6  run_step6.py   letters, after every resume is built; then the per-portal bundles.
```

A parked letter never blocks a resume.

## 2. Letter shape

| Part | Source |
|---|---|
| Sender block, company block, date (`Essen, DD.MM.YYYY`) | deterministic (KB + posting) |
| Subject | "Application for <exact title>" / "Bewerbung als <exact title>" |
| Salutation | named contact if the ad gives one (gender never guessed), else "Dear Hiring Team," / "Sehr geehrte Damen und Herren," |
| **Opening** (2 sentences) | LLM: exact title + company, strongest real connection |
| **Fit** (3-4 sentences) | LLM: answers the ad's 2-3 main tasks with real KB evidence |
| **Motivation** (2 sentences) | LLM: one fact from the ad's About text (no invented company facts) |
| **Logistics** | deterministic: MSc AI at BTU until October 2027, available immediately, 20 h/week in lecture periods and up to 40 h/week in breaks or internships, no fixed end date, mandatory internship (internship roles only), permit valid until December 2028, interview offer |
| Sign-off | deterministic ("Kind regards" / "Mit freundlichen Grüßen") |

Language follows the posting (`detect_posting_language`, function-word counts),
so an English ad from a German city still gets an English letter.

## 3. Creating one letter

`run_step4.process_letter_input()` (called by step 6):

1. **Claimable set**: KB skills + the job's keywords (job keywords may be named).
2. **Prompt** (`cover_letter._body_prompt`): job title, company, a task excerpt,
   the top 12 keywords, the About text, the approved candidate facts, and per real
   entry the job keywords its evidence supports. Rules: facts only from the
   facts block; a sentence about work done may use only that entry's supported
   keywords; all other keywords only in one closing "My toolkit also includes ..."
   sentence; no digits, no flattery phrases.
3. **Finish**: typography normalized (non-breaking hyphens → "-"), logistics
   paragraph added, any missing top-8 keyword appended in the toolkit sentence
   (`ensure_letter_keywords`), post-checks, date probe.
4. **Checks** (any finding fails the attempt):

   | Check | What it catches |
   |---|---|
   | L1 structure | subject, salutation, paragraphs present, ≤ 90 words per paragraph, total length, sign-off, date, company name |
   | L2 truth | tech tokens outside the claimable set, unlicensed digits, salary talk, flattery, unbacked company names, biography claims taken from the ad |
   | L3 artifact | leftover tokens, markdown, apostrophe years, LaTeX errors |
   | L4 language | body language and salutation match the letter language |
   | **claims** (`generation/claim_check.py`) | a keyword the KB does not back, stated as work done ("Using pandas I trained models") |

   When all of these pass, one more LLM call **fact-checks** the body
   (`cover_letter.verify_letter_facts`): every "I did / built / used" sentence is
   compared with the approved facts, and an invented activity or purpose ("I
   assessed automation use cases during my internship") becomes a finding. An
   invalid or failed fact-check reply is ignored; it never blocks a letter alone.
   Before the checks, misspelled KB employer names are corrected ("Sohum
   Infotech" → "Soham Infotech"; `fix_entity_names`). In the claim check, the
   part of a sentence after "I can / equips me to / prepares me to" counts as the
   job's work, not as a claim.
5. **One repair round**: the failed findings go back to the LLM (temperature 0).
   If the repaired letter still fails **only** on flagged sentences, those
   sentences are removed, the rest is re-checked (all gates + a new fact check),
   and it ships when clean (`trimmed_sentences` in the report).
6. **Fallback**: if the repair also fails, the deterministic KB-grounded letter
   (`generate_grounded_letter`, zero LLM calls) is used. `letter_source` in the
   report says `llm` or `fallback`.
7. **Build**: LaTeX (tectonic) PDF, DOCX and a paste-ready TXT. File names:
   `Meetkumar_Raval_Cover_Letter_<Company>_<Role>` (English) or
   `Meetkumar_Raval_Anschreiben_<Company>_<Role>` (German).
8. **Bundle**: letter + the real step-5 resume, requested documents found in
   the ad (enrolment certificate, transcript, ...), and whether the letter is
   optional for that ad.

## 4. Outputs

```
program_files/output_v2/
├── letters_report.json        per letter: gates, claims, letter_source, top_keywords, paths
├── application_bundles.json   what to upload where, missing documents
├── letters/pdf/Meetkumar_Raval_Cover_Letter_<Co>_<Role>.pdf
├── letters/docx/...docx
└── letters/textfield/...txt   for message fields
```

## 5. How to run

```bash
python resume_content_improve_research/run_step6.py                  # new/parked letters only
python resume_content_improve_research/run_step6.py --force          # rebuild every letter
python resume_content_improve_research/run_step6.py --jobs id1,id2 --force   # rebuild some; others kept
```

Costs per letter: 2 LLM calls (letter + fact check), up to 5 with the repair round and a trim re-check.

## 6. Known limits

- The claim check matches the job's keyword spellings; paraphrased inventions are
  left to the LLM fact check, which uses the same model and is good but not perfect.
  Read each letter once before sending it.
- Company facts come only from the ad's About text. If the ad has none, the
  motivation paragraph talks about the role's domain instead.
