# Resume & Cover Letter Plan (v3, re-researched 2026-10-17)

**Goal:** maximum interview calls. Every keyword a job ad asks for appears in the resume, whether or not it's in the KB today.

**Two rules hold throughout:**
1. **Keywords** (skills, tools, methods, domain terms, soft-skill terms, the job title) are **all** added, in the ad's exact spelling.
2. **Verifiable facts** (employers, job titles held, dates, degrees, university, certificates, numbers) stay exactly as in the KB, and no invented accomplishment bullets are written at real employers.

Everything below was checked in this pass:
- **(code)** = read in the source, with file:line;
- **(run)** = measured on the last run's real outputs (36 filtered jobs, 18 verified resumes);
- **(test)** = reproduced by compiling with the repo's own `tools/tectonic.exe`;
- **(source)** = external, linked at the end, with its strength stated.

## 0. Corrections to v2

| v2 said | Corrected |
|---|---|
| Jobscan: title match → 3.5× interviews | Jobscan's study page says **10.6×** (2.5M applications of Jobscan users; correlational, vendor data) |
| An audit "proved" LLM screeners reward keywords | It's an **arXiv preprint by one independent researcher**: 2 of 8 tools rewarded stuffing (Grok-fast 92 vs 15, LeChat 89.5 vs 10); ChatGPT and Gemini gave **zero** credit, and ChatGPT called the stuffed resume an incoherent attempt to mimic experience. → keywords must read coherently |
| Fix the font by switching to Pagella | Pagella alone **merges words in extraction** ("efficientoffice"). Only Pagella + `Ligatures=NoCommon` + `\raggedright` + `\spaceskip 0.34em` extracts cleanly (test) |
| Four places block keywords | **Six**: v2 missed the step-5 re-gate and the letter gate |
| (missing) | **Half the job requirements never reach the analyst** (A1), the biggest single keyword loss |
| (missing) | Exclusion regex silently drops real keywords (A3) |
| (missing) | Changing the name/headings breaks G1 and the parse checks (F1-F3) |

## 1. Code and run findings

### A. Keyword input: the analyst sees only part of the ad
| # | Finding | Evidence | Fix |
|---|---|---|---|
| A1 | The analyst receives only `job_description`. The scraper stores `requirements`, `your_tasks`, `applicant_profile` separately, and **for 17/36 jobs the requirements text isn't inside `job_description`** | code `run_step4.py:172`; run: e.g. the ilert security job → Burp Suite, OWASP, SAST, DAST, Java, TypeScript, Rust exist only in `requirements` | Pass the joined, de-duplicated `title + job_description + requirements + your_tasks + applicant_profile` to the analyst |
| A2 | Analyst input is cut at 6,000 chars (3/36 jobs are longer); its lists are capped (required ≤12, preferred ≤10, tools ≤15) | code `analyst.py:15`, schema | Raise the limit to ~12,000 after joining; add a **deterministic keyword sweep** over the full text so caps can't lose terms |
| A3 | `INELIGIBLE_TERM_RE` has no word boundaries and drops real keywords: "Very good **MS Office**" (matches `office`), "**Card** authorization" (matches `car`), "stakeholder communication", "degree in **Computer Science**". 31 of 234 terms are excluded | code `coverage.py:48`; run | Word-boundary rules; split eligibility (enrolment, months, hours) from skills; keep "Computer Science", "MS Office", soft skills as keywords |
| A4 | `tools` are never scored for coverage (only required/preferred). The post-check also deletes single-tool items from `required` | code `coverage.py:209`, `analyst_postcheck._drop_tools_from_required` | The coverage gate checks required + preferred + tools + swept keywords |
| A5 | The analyst returns phrases, not keywords: "pandas library", "experience with APIs", "strong interest generative AI" | run (SIXT gap report) | Keyword cleaner in the new keyword engine (§4) |

### B. Places that block JD keywords (all six must change)
| # | Where | What it does |
|---|---|---|
| B1 | `generator.py:80, :123, :132` | Prompt: JD tools only "as working toward"; skill rows KB-only |
| B2 | `tailoring.py:141, :398` | Adds "Working toward hands-on X experience" (13/18 resumes); also builds labels like `Python: …` (`:393`) |
| B3 | `gates.py:104` (G2 tech-token loop) | Parks/regenerates any tech word outside the KB |
| B4 | `factual_content.py:283-340, :355` (`ground_components`, `owned_row`) | Filters every skill row back to KB/pool skills at build time |
| B5 | `run_step5.py:107` | Re-runs the G2 gate on grounded content; fails the build |
| B6 | `cl_gates.py:130, :172` | Letter L2 gate: same G2 check + "mirrorable tool claimed as owned" regex |

Keep: the G2 **digit/metric rule**, **title rule**, employer/date/degree grounding, G3 artifact checks.

### C. Resume rendering (PDF)
| # | Finding | Evidence | Fix |
|---|---|---|---|
| C1 | Font `cfr-lm` drops `—` and `’` under XeTeX: "Software Engineer Soham Infotech", "Runners Up" (4 missing-character warnings) | test; template `:6` | `fontspec` + `texgyrepagella` `[Ligatures=NoCommon]` + `\raggedright` + `\spaceskip/\xspaceskip 0.34em` (test: clean extraction, `C#`, `C++`, `Node.js`, `CI/CD` intact, 0 ligatures). Separator ` \| ` |
| C2 | Two evidence sentences glued without a full stop ("decision-making Designed…") | `factual_content.py:55, :84` | One bullet per evidence line |
| C3 | Languages render as `English (C2 (native)` | `factual_content.py:188` | `English – Fluent (C2) · German – Basic (A2) · Hindi – Native · Gujarati – Native` |
| C4 | Achievements/certifications/projects printed two-per-line with `\hfill`; Textkernel calls columnar data a "HUGE MISTAKE" (code 433) | `factual_content.py:153` etc. | One item per line |
| C5 | `[Link]` as link text, URL invisible | `factual_content.py:173` | Visible URL text |
| C6 | Name printed surname-first in caps (`RAVAL MEETKUMAR RITESHKUMAR`); parsers rely on position and need first and last name (Textkernel code 302) | template `:28` | `Meetkumar Raval` (your decision, §9) |
| C7 | No location in the header; Textkernel flags a missing address (code 213); German recruiters and ATS location filters need it | template | `Essen, Germany` (postcode optional) |
| C8 | PDF has no Title/Author metadata | run (`pypdf`) | `\hypersetup{pdfauthor=…, pdftitle=…}` |
| C9 | File named after the job title (`Working-Student-Data-Science.pdf`) | `build.py:211` | `Meetkumar_Raval_CV_{Company}.pdf` (Jobscan/VisualCV convention) |

### D. DOCX (used by Workday-type autofill)
| # | Finding | Fix |
|---|---|---|
| D1 | **No experience dates or locations** (`build.py:112`), so Textkernel flags jobs without dates (codes 224/225) and total experience is computed as 0 | Same line structure as the PDF: `Role \| Company \| Location \| Mon YYYY – Mon YYYY` |
| D2 | LinkedIn/GitHub cut to `meetraval/ \| ravalmeet` (`build.py:104`) | Full URLs |
| D3 | Headings use `Normal` style; Textkernel wants clear, commonly-used headers on their own line (code 151) | Real `Heading 1` styles, standard names |
| D4 | Section order differs from the PDF (Education last) | Same order as the PDF |

### E. Cover letters
| # | Finding | Fix |
|---|---|---|
| E1 | Step 6 calls `generate_grounded_letter` (`run_step4.py:145`): **0 LLM calls**, hard-coded text, identical letter for every job (SIXT data science letter offers "Python, AI, HTML"). An LLM path `generate_letter` exists but is unused | New LLM prompt via `generate_letter` (§5) |
| E2 | No start date, hours/week, duration, enrolment or permit | Logistics paragraph from profile |
| E3 | Signed `RAVAL MEETKUMAR RITESHKUMAR`, header `RAVAL MEETKUMAR`; English letters saved as `Anschreiben_…` | One name form; `Cover_Letter_` prefix for English |

### F. Gates that will break when the layout changes (must change together)
| # | Where | Why |
|---|---|---|
| F1 | `gates.py:210`, `parse_sim.py:115` check `"RAVAL"` uppercase | Fails if the header becomes `Meetkumar Raval` → use a case-insensitive name check |
| F2 | `gates.py:45`, `parse_sim.py:31` section lists lack `profile`, `summary`, `technical skills`, `work experience`; G1 needs ≥6 | Add the new headings |
| F3 | `parse_sim.py:128` reading order keyed on "career objective" | Key on the name → first section |
| F4 | `run_step5.py:195` hard one-page rule; word cap 800 | Allow 2 pages (§3.1); raise the word cap |
| F5 | Tests encoding the old policy: `test_gates.py` (41 refs), `test_tailoring.py` (14), `test_motivation.py` (13), `test_kb_pipeline.py` (8), `test_domain_filter.py` (7), `test_cover_letter.py` (5) | Update to the new policy; keep the digit/title/employer tests |
| F6 | Step 4 keeps old `gated_ok` records | Re-run with `--force` after the change |

### G. Scoring
- `required_coverage` can't reach 100% today because of A1-A5. It will be replaced by **`keyword_coverage`**: every target keyword found in the *parsed-back* PDF and DOCX.
- A second number, **`kb_backed_share`**, records what share of printed keywords is in the KB, for the prep list (§7).

## 2. External research: what changes the design

| Finding | Strength | Design consequence |
|---|---|---|
| Recruiters search ATS by **title + 2-3 skills**; Greenhouse auto-reject comes only from **screening questions**, not resume text; Talent Matching only **sorts** (Strong/Good/Partial) | Greenhouse official docs | Exact JD terms + title matter for being *found*; knockout answers matter for not being dropped |
| **Workday HiredScore** grades A-D: A = all required + most preferred qualifications; based on resume vs JD skills/qualifications | Workday official doc | Cover **every required** term first, then preferred |
| **SAP SuccessFactors** AI extracts skills from resumes and matches exact + related skills | SAP product page | Exact spelling + common synonyms both help |
| **Textkernel** (the parser behind SuccessFactors/iCIMS per resumap): code 112 "skills should be included in the context of work history and education descriptions"; 303 flags sections longer than Work + Education combined; 433 columns; 151 standard headers; 302 first/last name; 213 address; 224/225 job dates | Textkernel official docs | Keywords in **bullets/profile where truthful**, Skills section **shorter than Experience + Education**, no columns, standard headers |
| Resumap ran 36 templates through Textkernel: 36/36 parsed, all 10 job-critical skills kept; 5/36 job-segmentation errors | Vendor test | Single-column layout is safe; keep job blocks simple |
| Jobscan match logic: hard skills weigh most, then title, then soft skills; exact word forms matter (plural/singular); target ≥75% | Jobscan tutorial (vendor) | Hard skills first; print JD's exact forms; include soft skills too |
| Hidden/white text: parsers extract it and show it to recruiters; style-aware sanitising removes it before AI scoring | Vendor blogs + arXiv benchmark | **Never** hidden text; everything visible |
| AI screeners: some reward keyword stuffing, strong ones (ChatGPT, Gemini) penalise incoherent stuffing | arXiv preprint | Keywords in a clean categorised Skills block + coherent sentences, never keyword soup |
| ~20% of US hiring managers would reject an AI-generated resume/letter; 52% accept AI-assisted if human-finalised | TopResume survey (n=600, US) | Letters must sound specific and human; you skim each before sending |
| Germany: 2 pages normal for experienced; 1 page common for entrants | German career guides | Aim for 1 page, **allow 2** rather than drop keywords |
| Photo, birth date, marital status are voluntary (AGG); international/tech firms often go without | German guides incl. StepStone | No photo/birth date in the ATS version |
| Apply in the language of the ad | LMU career service and others | English ad → English CV/letter; German ad → German letter + German keywords in the CV (an English CV is accepted at A2, but titles/keywords mirror the German ad) |
| Werkstudent CV: enrolment, programme, expected end date, availability/hours | Randstad DE, contract samples | Header availability line + "expected graduation" |
| Early applicants get reviewed first (6,600-hire study: ~50% of hires applied in week 1) | ERE/StartWire, older, correlational | Keep the today/yesterday freshness filter; apply the same day |
| DOCX is usually safer for Workday-type autofill; text-based PDF fine elsewhere | Vendor blogs | Ship both, identical content |
| File name: `First_Last_Resume`, no special characters | Jobscan, VisualCV | `Meetkumar_Raval_CV_{Company}.pdf` |

From your own job set (run): 6/36 ads ask for an **enrolment certificate**, 5/36 for **transcripts/certificates**, 10/36 state a **3-6 month** duration, 4/36 ask for a **start date/availability**, and only 3/36 mention a cover letter at all.

## 3. Target resume

### 3.1 Layout (single column, standard headers, ≤2 pages; page 1 = everything that wins the call)
```
Meetkumar Raval
{Exact JD title, (m/w/d) removed} | MSc Artificial Intelligence
Essen, Germany · +49 15565 468731 · ravalmeett@gmail.com · linkedin.com/in/meetraval · github.com/ravalmeet
Available from {month} · {20 h/week | full-time internship 3-6 months} · {permit line, your wording}

PROFILE           2-3 sentences: JD title words + top 6-8 JD keywords + degree + 1+ yr software engineering
TECHNICAL SKILLS  4-6 categorised rows, JD keywords first in JD spelling, acronym + long form once
                  (e.g. "Natural Language Processing (NLP)"); shorter than Experience + Education
WORK EXPERIENCE   Software Engineer | Soham Infotech | Gujarat, India | Dec 2023 – Jan 2025
                  4 bullets (all 4 evidence lines), rewritten in JD vocabulary, JD-relevant first
                  Machine Learning Intern | Pantechelearning | Chennai, India | Dec 2021 – Feb 2022 (2 bullets)
PROJECTS          2 best-matching real projects, 2 bullets each + "Tech:" line
EDUCATION         MSc Artificial Intelligence, BTU Cottbus-Senftenberg | Apr 2025 – expected {date}
                  (Relevant coursework: only modules you took, JD-matching first)
                  BE Computer Engineering, Gujarat Technological University | 2020 – 2024
RESEARCH · ACHIEVEMENTS · CERTIFICATIONS · LANGUAGES  (one item per line)
```

### 3.2 Where each keyword goes
1. **Every** target keyword → Technical Skills (categorised, JD spelling).
2. Keywords that describe real work → also in the experience/project bullets, in JD wording: API endpoints → REST APIs / backend services; data transformation pipelines → ETL / data pipelines; LLM + prompt workflows → Generative AI / prompt engineering; agile Git team → Scrum / version control. Textkernel code 112 rewards this context.
3. Top 6-8 keywords → Profile.
4. JD title → headline (and file name).

No hidden text, no keyword-only lines, no "working toward".

## 4. Keyword engine (new `generation/keywords.py`)
1. **Input:** the joined ad text (A1) + analyst output.
2. **Deterministic sweep** of the full text with the tech lexicon (`TECH_TOKEN_RE` extended, ESCO labels, alias map, plus a curated list of ~300 common tech/AI/data/cloud/security terms). It catches what the analyst caps or misses.
3. **Clean phrases → keywords** (`pandas library` → `pandas`; `experience with APIs` → `APIs`), keeping the ad's exact casing/spelling.
4. **Classify:** `programming`, `ml_ai`, `data`, `backend_cloud_devops`, `security`, `tools_methods`, `soft_skills`, `domain`. **Eligibility** items (enrolment, hours, months, location, "studying X") go to the header/letter, not Skills.
5. **German ads:** keep the German term and add the English one once (`Datenanalyse (Data Analysis)`).
6. **Output:** an ordered target list: required → tools → preferred → swept.

**Gate:** after build, every target keyword must be found in the parsed PDF **and** DOCX. If any are missing → insert → rebuild (≤2 loops). Report `keyword_coverage`, ship at 100%.

## 5. Cover letter (LLM via `generate_letter`, gated)
- **Language** = ad language.
- **Subject:** `Bewerbung als {title} – Ref. {ref}` / `Application: {title} – Ref. {ref}`. Named salutation when detected (code exists).
- **P1:** exact title + company + one real hook.
- **P2:** the ad's 2-3 main tasks, each answered with real evidence in ad vocabulary, plus one sentence naming the ad's top tools.
- **P3:** one company fact from `about_us`, never invented.
- **P4 logistics:** start date, hours or duration, enrolment, permit line; offer of an interview.
- **Gates kept:** no invented numbers/companies, 1 page, language match. Gate added: top-8 keywords present.
- **When to send:** if the portal has an optional slot, attach it. Writing effort goes to ads that ask for one.

## 6. Application package per job
`Meetkumar_Raval_CV_{Company}.pdf` + `.docx`, `Meetkumar_Raval_Cover_Letter_{Company}.pdf` (or `Anschreiben_` for German) + `.txt`. Add the enrolment certificate when the ad asks (6/36): `certificate_of_enrolment_small.pdf` is already in the repo. Add transcripts/certificates when the ad asks (5/36; you'd need to supply these files).

## 7. Interview prep + learning loop
- Per job, `prep/{Company}_{Role}.md`: every printed keyword **not** in the KB, plus the ad's tasks.
- The dashboard ranks the most frequent non-KB keywords across all applications.
- Build a small weekend project for each of the top few (e.g. Docker, AWS, pandas). Each becomes a **real KB project**, so those keywords move from the Skills list into real bullets (Textkernel code 112) and hold up in interviews.

## 8. Implementation order and checks

| Step | Work | Files | Done when |
|---|---|---|---|
| 1 | Input fix + keyword engine + exclusion regex | `run_step4.py:172`, `analyst.py`, new `generation/keywords.py`, `coverage.py:48` | Ilert job's list contains Burp Suite/OWASP/SAST/DAST; SIXT's contains pandas/NumPy/scikit-learn |
| 2 | Unblock B1-B6 + keyword injector | `generator.py`, `tailoring.py`, `gates.py`, `factual_content.py`, `run_step5.py`, `cl_gates.py` | No "Working toward"; digit/title tests still pass |
| 3 | Template + rendering + DOCX + gates F1-F4 | template, `factual_content.py`, `build.py`, `gates.py`, `parse_sim.py`, `run_step5.py` | Font test passes on the real template; DOCX has dates/URLs/headings; Textkernel-style checks (codes 112-433 subset) pass |
| 4 | 100% keyword gate on PDF + DOCX | `run_step5.py`, `coverage.py`, `scorecard.py`, `triage.py` | 18/18 resumes at 100%, ≤2 pages |
| 5 | Letters | `cover_letter.py`, `run_step4.py:145`, `cl_gates.py`, templates | 5 letters reviewed by you side by side |
| 6 | Package + file names + prep files + dashboard tab | `build.py`, `run_step6.py`, `portal_delivery.py`, `6_dashboard.py` | Bundle per job complete |
| 7 | Tests updated (F5), `--force` re-run, before/after report | `tests/` | Test suite green; report per job |

Effort ≈ 6-7 working days.

## 9. Your input needed (blocks steps 3 and 5)
1. **Name on documents:** `Meetkumar Raval` (recommended) or the full `Meetkumar Riteshkumar Raval`?
2. **Availability line:** start month; Werkstudent 20 h/week and/or full-time internship (3-6 months; your mandatory internship qualifies); permit wording. Suggested: "Student residence permit – eligible for working-student employment and mandatory internship".
3. **Expected graduation** month (shown under the MSc).
4. **Coursework:** BTU modules completed or in progress (only real ones are printed).
5. **KB open notes:** BTU location (Cottbus vs Berlin, flagged in the KB) and whether to print your postcode.
6. Transcript/certificate PDFs for ads that request them.

## 10. Limits stated plainly
- 100% keyword coverage guarantees **findability and AI-grade input**, not interviews. Workday-type grading also weighs required qualifications such as degree field, years and language, which a resume can't change.
- Keywords outside your real experience can surface in a technical screen. §7 is the countermeasure.
- Ads requiring German B2+/fluency stay filtered out (`3_language_filter.py`); keywords can't fix a language knockout.

## Sources
- Jobscan interview-rate study (10.6× title match, methodology): https://www.jobscan.co/blog/interview-rates-study
- Jobscan tutorial (match priorities, 75%): https://Jobscan.co/jobscan-tutorial
- Workday HiredScore candidate grades: https://doc.workday.com/hiredscore/en-us/workday-hiredscore/recruiter-productivity-/reference--candidate-grades.html
- Greenhouse AI FAQ / Talent Matching: https://my.greenhouse.com/blogs/how-does-greenhouse-use-ai-heres-everything-candidates-need-to-know · https://support.greenhouse.io/hc/en-us/articles/41131886674075
- SAP SuccessFactors applicant screening: https://www.sap.com/products/hcm/successfactors-recruiting-applicant-screening.html
- Textkernel resume quality codes: https://developer.textkernel.com/tx-platform/v10/resume-parser/overview/parser-output/
- Textkernel parse test (36 templates): https://resumap.io/articles/textkernel-parsing-test
- Keyword-stuffing audit (arXiv preprint, Webster): https://arxiv.org/pdf/2507.11548
- Hidden-text attacks vs sanitisation: https://arxiv.org/html/2512.20164v1
- TopResume hiring-manager AI survey: https://topresume.com/career-advice/ai-in-hiring-survey
- How recruiters search: https://resumegeni.com/blog/how-recruiters-search-inside-ats
- Early applicants (ERE): https://www.ere.net/speed-the-hidden-driver-of-candidate-quality/
- CV length (DE): https://karrierebibel.de/lebenslauf-seitenzahl/
- Personal data/photo (DE): https://www.stepstone.de/magazin/artikel/persoenliche-daten-lebenslauf
- Application language: https://www.lmu.de/de/workspace-fuer-studierende/career-service/tipps-fuer-bewerbungen/
- Werkstudent CV: https://www.randstad.de/karriere/bewerbungsratgeber/lebenslauf/werkstudent/
- PDF vs DOCX (Workday): https://atsverification.com/blog/workday-pdf-resume-parsing/
- Resume file names: https://www.jobscan.co/blog/writing-a-resume-pay-attention-to-the-file-name/ · https://www.visualcv.com/blog/how-to-name-your-resume-file/
- Non-US names and parsing: https://slategit.com/blog/ats-resume-name-formatting-non-us-names
