# How a Resume Is Created (engine v3)

> **Moved (2026-10-17):** the runnable pipeline now lives in [`E:\WorkSpace\2 Tech\2 Job Automation\REGULAR_APPLICATION`](../REGULAR_APPLICATION/README.md) (`python run.py --days N` inside it; it does not depend on this repo). The engine package `resume_content_improve_research/` was renamed `REGULAR_APPLICATION/engine/`; paths below that name the old package refer to it. The old `main.py`, dashboard and tests no longer run from here.

**Scope:** how the current pipeline (`resume_content_improve_research/`) turns one
scraped posting into a tailored, verified resume (PDF + DOCX, at most 2 pages).
It describes the code as it stands (October 2026).

Companion documents:
- [COVER_LETTER_CREATION.md](COVER_LETTER_CREATION.md): the letter phase (step 6)
- [RESUME_ATS_REVIEW.md](RESUME_ATS_REVIEW.md): the research and plan behind v3
- `resume_content_improve_research/FINAL_MODEL.md`: earlier measurements (v2)

---

## 0. The keyword policy (what v3 optimizes for)

The goal is the maximum number of interview calls, so the resume aims for
**100 % of the job ad's keywords** in the parsed PDF and DOCX:

| Content | Rule |
|---|---|
| **Skills section** | Every job-ad keyword is printed, in the ad's spelling, sorted into category rows (Programming, AI & ML, Data, Backend/Cloud/DevOps, Security, Tools & Methods, Soft skills, Domain). Acronyms are paired once: "Machine Learning (ML)". |
| **Experience and project bullets** | A keyword is used only when that entry's KB evidence already describes the work (`generation/evidence_vocab.py`). Never an invented tool, outcome, metric or employer. |
| **Profile** | 2-3 sentences opening with the candidate (MSc AI student + Software Engineer). Keywords the KB does not back may appear only as a skills list, never as delivered work. |
| **Facts** (name, dates, employers, degrees, permit, availability) | KB only. |
| **Achievements the ad asks for** ("Published CVE", "Meetup talk", "AWS Certified ...") | Never printed: they are facts, not skills. They go to the eligibility/gap list. |

Keywords that are printed but not backed by the KB go onto a per-job **prep
sheet** (`output_v2/prep/*.md`) and a cross-job **learning priorities** list, so
the candidate can learn them before an interview.

## 1. Where resume creation sits in the pipeline

```
STEP 1  1_fetch_jobs.py        scrape -> program_files/output/todays_overall_jobs.csv
STEP 2  2_filter_jobs.py       filter -> program_files/output/2_filted_jobs.csv
STEP 3  3_test_ollama_keys.py  validate Ollama keys
STEP 4  run_step4.py           analyze + keyword plan + generate + gate   -> output_v2/components_v2.json
STEP 5  run_step5.py           ground + build + parse back + verify       -> output_v2/resume_report.json
STEP 6  run_step6.py           cover letters (see COVER_LETTER_CREATION.md)
```

## 2. Inputs

| Input | Path |
|---|---|
| Filtered jobs | `program_files/output/2_filted_jobs.csv` |
| Candidate KB (only source of facts) | `knowledge_base/candidate_kb.json` (schema-validated, candidate-approved) |
| Tech lexicon (~405 terms, variants, categories) | `knowledge_base/tech_lexicon.json` |
| Truthful rewordings per KB skill | `knowledge_base/evidence_synonyms.json` |
| Template | `templates/core_resume_template_v3.tex` (TeX Gyre Pagella, ragged right, ligatures off) |
| LLM | Ollama Cloud `gpt-oss:120b`, serial calls |
| LaTeX | `tools/tectonic.exe` |

## 3. Step 4: components

Per job, `run_step4.process_job()` (never raises; a failure parks the job):

1. **Domain gate** (no LLM cost).
2. **Analyst** (1 LLM call) on the whole ad (description, requirements, tasks,
   profile, offer), then a deterministic post-check that also fixes the posting
   language (`detect_posting_language`, function-word counts).
3. **Keyword plan** (`generation/keywords.py`): analyst terms + a lexicon sweep
   of the whole ad + ad phrases. The ad's spelling wins over analyst
   paraphrases. Every keyword gets a category.
4. **Claimable set**: KB skills plus the plan's keywords (so the Skills rows may
   print them; G2 still blocks anything outside the ad and the KB).
5. **Generation** (3 JSON calls, 4000-token budget, each with one repair retry):
   profile + skill rows, experience bullets, project bullets. Each entry in the
   prompt lists the job keywords that truthfully describe it.
6. **Tailoring** (deterministic): category rows, acronym pairs, project re-pick.
7. **Gates + regeneration** (up to 2 rounds, findings fed back to the prompts):
   - G2: no tech token outside the claimable set, no unlicensed digit, titles
     within `titles_allowed`;
   - G3: no leftover tokens, 4-digit years;
   - **vocabulary**: a bullet that uses a keyword its KB entry does not support
     (for example "AI assistants" at an employer whose evidence never mentions
     them). These trigger a regeneration. If only vocabulary findings remain, the
     job continues and step 5 drops exactly those bullets.

## 4. Step 5: build and verify

`run_step5.build_record()` per job:

1. **Ground** (`factual_content.ground_components`): every bullet is re-checked
   against its KB entry (plan-aware vocabulary + digit rule). An offending
   bullet is dropped; with no clean bullet left, the entry's own evidence lines
   are printed. Gap phrases ("working toward", "eager to") are stripped.
   Non-breaking hyphens and spaces from the LLM are normalized. The profile goes
   through `generation/claim_check.honest_profile`: a sentence that states an
   unbacked keyword as work done ("hands-on experience in pandas") is dropped,
   and those keywords move to one "Role-relevant skills: ..." sentence.
2. **Document model** (`templates/render.py`) feeds both the PDF and the DOCX,
   so they carry identical content.
3. **Keyword insurance** (`verification/keyword_gate.ensure_keywords`): any plan
   keyword not yet printed is added to its category row.
4. **Compile** with tectonic, then build the DOCX.
5. **Parse back** (pdfplumber + second extractor) and check:
   - G1: text extracts, name/email/phone found, sections detected, at most 2 pages, word count limits;
   - G3: no leftover tokens;
   - **keyword gate**: every plan keyword is found in the PDF text **and** the DOCX text.
   A failure quarantines the files in `output_v2/failed/`.
6. **Scorecard, fit tier and prep**: coverage score, `kb_backed_share` (what share
   of the keywords the KB really backs), fit tier (strong ≥ 0.6, good ≥ 0.4,
   stretch below), and the prep sheet listing the non-KB keywords.

## 5. Outputs

```
program_files/output_v2/
├── components_v2.json           step 4 records
├── resume_report.json           step 5 status, gates, keyword gate, grounded bullets, paths
├── shortlist.json               ranked by fit tier and kb_backed_share
├── resume/pdf/Meetkumar_Raval_CV_<Company>_<Role>.pdf
├── resume/docx/Meetkumar_Raval_CV_<Company>_<Role>.docx
├── prep/<job>.md                keywords to learn before the interview
├── learning_priorities.{json,md} non-KB keywords ranked by how many companies ask for them
└── failed/                      quarantined (never shipped)
```

## 6. How to run

```bash
python resume_content_improve_research/run_step4.py --jobs <url-substring>,<...> --force
python resume_content_improve_research/run_step5.py
python -m pytest resume_content_improve_research/tests -q      # no live LLM calls (conftest blocks them)
```

## 7. Known limits

- The truth check works on known vocabulary (lexicon + job keywords + KB
  synonyms). A completely new phrase that is neither a keyword nor a lexicon
  term is not checked; the prompts forbid it, but no gate proves it.
- Keywords printed only in the Skills section help ATS matching. A recruiter can
  still ask about them, so read the prep sheet before each interview.
- Generation depends on one Ollama key; a 20-job run takes several minutes.
