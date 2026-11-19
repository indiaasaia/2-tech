# Final Report: Resume + Cover Letter Engine v3 (2026-10-17)

> **Update (later on 2026-10-17):** the runnable pipeline moved to `E:\WorkSpace\2 Tech\2 Job Automation\REGULAR_APPLICATION` (`python run.py --days N` inside it). The documents described below are still in `program_files/output_v2/`; new runs write to its `output/applications/`.

## 1. What was tested

Four real jobs from the current scrape, run live end to end (analyst → keyword
plan → generation → checks → PDF/DOCX → letter):

| # | Company | Role | Why chosen |
|---|---|---|---|
| 1 | Deutsche Bank AG | Internship (m/f/x) in Risk 2027 | finance / risk, few tech keywords |
| 2 | Quantum-Systems GmbH | Working Student - AI Automation, Procurement | AI + ERP |
| 3 | SIXT | Working Student Data Science | core ML / data |
| 4 | iLert GmbH | Working Student / Intern: Offensive Security Engineer | security stretch role (44 keywords) |

All 20 stored ads are in English, so no German letter was produced in this run.
German letters are covered by the test suite.

## 2. Your documents

All files are in `program_files/output_v2/`:

| Job | Resume (PDF + DOCX) | Cover letter (PDF + DOCX + TXT) | Interview prep |
|---|---|---|---|
| Deutsche Bank | `resume/pdf/Meetkumar_Raval_CV_Deutsche-Bank-AG_Internship-mfx-in-Risk-2027.pdf` | `letters/pdf/Meetkumar_Raval_Cover_Letter_Deutsche-Bank-AG_Internship-mfx-in-Risk-2027.pdf` | `prep/Deutsche-Bank-AG_Internship-mfx-in-Risk-2027.md` |
| Quantum-Systems | `resume/pdf/Meetkumar_Raval_CV_Quantum-Systems-GmbH_Working-Student-AI-Automation.pdf` | `letters/pdf/Meetkumar_Raval_Cover_Letter_Quantum-Systems-GmbH_Working-Student-AI-Automation.pdf` | `prep/Quantum-Systems-GmbH_Working-Student-AI-Automation-Procurement.md` |
| SIXT | `resume/pdf/Meetkumar_Raval_CV_SIXT_Working-Student-Data-Science.pdf` | `letters/pdf/Meetkumar_Raval_Cover_Letter_SIXT_Working-Student-Data-Science.pdf` | `prep/SIXT_Working-Student-Data-Science.md` |
| iLert | `resume/pdf/Meetkumar_Raval_CV_iLert-GmbH_Working-Student-Intern-Offensive.pdf` | `letters/pdf/Meetkumar_Raval_Cover_Letter_iLert-GmbH_Working-Student-Intern-Offensive.pdf` | `prep/iLert-GmbH_Working-Student-Intern-Offensive-Security.md` |

The DOCX files have the same names under `resume/docx/` and `letters/docx/`;
paste-ready letter text is under `letters/textfield/`. The other 14 jobs got the
same treatment (18 resumes + 18 letters in total).

## 3. Results (independent audit)

The audit re-reads the finished PDF and DOCX (not the pipeline's own data) and
checks every claim against `candidate_kb.json`.

| Check | Deutsche Bank | Quantum | SIXT | iLert |
|---|---|---|---|---|
| Job keywords printed (PDF **and** DOCX) | 13/13 | 15/15 | 27/27 | 44/44 |
| Pages | 2 | 2 | 2 | 2 |
| Bullets checked against KB evidence | 10, 0 problems | 10, 0 | 9, 0 | 10, 0 |
| Profile states only KB-backed work | yes | yes | yes | yes |
| No percentages / invented numbers | yes | yes | yes | yes |
| Name, email, phone, permit, availability in text | yes | yes | yes | yes |
| Letter: 1 page, logistics, top keywords | yes | yes | yes | yes |
| Letter source | LLM, fact-checked | LLM, fact-checked (1 sentence trimmed) | KB fallback | KB fallback |
| Keywords the KB backs | 38% | 60% | 39% | 11% |
| Fit tier | stretch | **strong** | stretch | stretch |

Across all 18 jobs: 18/18 resumes carry 100% of their job keywords; 18/18
letters pass every gate (12 LLM-written and fact-checked, 6 KB-grounded
fallback). Tests: 408 passed, 1 skipped.

What "KB fallback" means: the LLM letter kept inventing work after its repair,
so the system used the deterministic letter built only from your KB facts. It is
accurate but more generic; you can personalise its motivation paragraph by hand.

## 4. Defects found during this check, and fixed

| Found in the live output | Fix |
|---|---|
| "Implemented **AI assistants**…" at Pantechelearning (never in your KB) | per-entry check now covers every job keyword; "AI" no longer counts as backing "AI assistants" |
| Profile: "hands-on experience in **pandas, NumPy**", "skilled in **Java, Rust**" | profile claim check: unbacked keywords move to a "Role-relevant skills: …" sentence |
| Letters: "I built CSV/JSON ingestion pipelines", "I pentested…", "I assessed automation use cases during my internship" | claim check + new **LLM fact check** + one repair round + trim/fallback |
| "**Published CVE**", "**Meetup talk**" printed as skills | achievements/credentials are never printed as skills |
| "70 **percent** accuracy" printed | percentages are always removed from bullets |
| Employer misspelled "**Sohum / Sohat** Infotech" | corrected automatically before checks |
| Non-breaking hyphens in DOCX ("real‑time" ≠ "real-time" for an ATS) | normalized to plain hyphens |
| "My toolkit also includes X. My toolkit also includes Y." | merged into one sentence |
| 12 letters wrongly blocked because the opening quoted the job title | job title is excluded from the claim check |
| "…Artificial Intelligence and AI" in fallback letters | AI = Artificial Intelligence dedupe |
| "the Tooling" as a keyword | leading articles stripped |
| Running step 6 with `--jobs` deleted 14 letters from the report | other jobs are now kept |
| 44 resume PDFs for 18 jobs (old file names mixed in) | stale files are **moved** to `output_v2/stale/` (nothing deleted) |
| A test wrote a sample letter into the real output folder | test now uses a temp folder |
| File names: "Working-Student---AI", "…-Intern-20" | single dashes, cut at a word boundary |

## 5. What you should know before applying

1. **Stretch jobs need preparation.** Every keyword is on the resume (that is the
   ATS strategy you chose), but SIXT lists 14 and iLert 32 skills your KB does not
   back. Read the job's prep sheet before an interview. The cross-job list is
   `prep/learning_priorities.md`. Top items: Documentation, Data Science, Java,
   Quality Assurance, CI/CD, pandas, NumPy.
2. **If you already know pandas, NumPy, scikit-learn, Java, etc.**, add them to
   `candidate_kb.json` with real evidence. They then become backed skills and can
   appear in bullets and letters, not only in the Skills section.
3. **Read each letter once before sending.** The fact check uses the same model
   that writes the letter. It caught the clear inventions in this run, but mild
   overstatement can remain (the Quantum letter says "delivering functional
   prototypes ready for integration" about your resume-generator project).
4. **Bosch and Airbus ask for a transcript.** Set
   `config.APPLICATION_DOCUMENTS['transcript']` to your file to complete those bundles.
5. **Two jobs have no documents**: SAP Signavio (the ad requires SAP, which the
   KB cannot back) and Scalable Capital GRC (the analyst LLM returned no answer;
   re-run step 4 for it).
6. **Security:** `program_files/autonomous_job_applier.py` contains a hardcoded
   API key. The file is untracked but **not** in `.gitignore`, so `git add .`
   would commit it. Move the key to an environment variable and/or ignore the file.
7. **Nothing is committed.** Previous outputs are backed up in
   `program_files/output/backup_output_v2_2026-10-17/`; replaced files are in
   `program_files/output_v2/stale/`.

## 6. How to re-run

```bash
python resume_content_improve_research/run_step4.py --jobs <id>,<id> --force   # generate
python resume_content_improve_research/run_step5.py                            # resumes + prep
python resume_content_improve_research/run_step6.py --force                    # all letters
python -m pytest resume_content_improve_research/tests -q                      # 408 tests, no live LLM
```

Details: [RESUME_CREATION.md](RESUME_CREATION.md), [COVER_LETTER_CREATION.md](COVER_LETTER_CREATION.md), [REPO_GUIDE.md](REPO_GUIDE.md).
