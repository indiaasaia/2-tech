# Internship & Job Outreach Plan (complete)

Version 2, 2026-10-17. Every fact below is backed by a source at the end. **(verified)** means I tested it live against the real endpoint or read it in the primary document on that date. Where sources conflict, it says so and names who decides.

---

## 1. Summary

1. **The goal right now is your mandatory internship (BTU module 13602), not "any job".** It needs ≥260 working hours at an organisation outside the university. It is a precondition for your Master thesis. A Werkstudent job can be recognised as the internship. For a German employer it is the cheapest, lowest-risk way to hire you: no minimum-wage obligation for a curricular mandatory internship (§22 MiLoG), and it generally doesn't count against your 140 days.
2. **The chain to aim for:** Pflichtpraktikum / Werkstudent → Master thesis in the same company → full-time offer. That is the normal German path into industry, and each step makes the next one easier.
3. **Geography:** Germany carries ~85-90% of the effort. Abroad is realistic only for an internship in **Austria** (for a student enrolled in Germany it's exempt from the Austrian work permit law), the **Netherlands** (the employer must get a TWV/GVVA, so only large employers) and **Ireland** (Internship Employment Permit). Erasmus+ pays **€750/month** for internships in those countries. France, Belgium and Switzerland are not worth automating for you.
4. **Volume:** 20 manual + 20 automated applications per week, plus ~10 cold emails. Volume comes from new legal job sources (Bundesagentur API, Arbeitnow, company ATS boards), all tested live today.
5. **Cold email is legitimate in the form planned:** one-to-one, personalised, to HR/role addresses or the right person. German university career services recommend exactly this. It is not mass marketing, and it is capped at ≤15/day from your Gmail.

---

## 2. Research findings

### 2.1 Your internship: BTU rules (primary source: Prüfungs- und Studienordnung MSc AI, PO 2022, §6, §8, Annex 3; Module Handbook WiSe 26/27) (verified)

| Rule | Exact content | What it means for the plan |
|---|---|---|
| Size | "at least 260 working hours", 10 CP, outside the university (§6(7)); handbook: 270 h practice + 30 h report | ≈ 7 weeks full-time, or ≈ 13 weeks at 20 h/week. **There's no maximum**, so 3-6 month offers are fine. |
| Werkstudent counts | "Working Student jobs can be recognized by the examination board with the approval of the mentor if they correspond to the objectives of the internship" (§6(7)) | **Werkstudent and Pflichtpraktikum are one pipeline.** Any AI/software Werkstudent job can also satisfy the module. |
| Where | Companies active in computer science, and research institutions independent of universities, e.g. Fraunhofer (Annex 3 §5) | Fraunhofer, DLR, Helmholtz and Max Planck institutes are valid targets. |
| Supervisor | The company supervisor must hold a Diploma/Master's in a relevant field and be named in the report (Annex 3 §5) | Ask this in the interview; most tech teams qualify. |
| Approval | Mentor approves topic, company, supervisor (and NDA) **≥4 weeks before start**; register with Student Services ≤5 working days after start (Annex 3 §3) | Every accepted offer needs a start date ≥4 weeks out. Build this into the "earliest start" answer. |
| Abroad | "expressly welcomed … subject to the same guidelines as internships in Germany", refers to DAAD (Annex 3 §4) | The university side is fine; the work-permit side is the constraint (2.3). |
| Report | 3,500-4,000 words (handbook) / 3,000-3,500 (FAQ), signed by the company supervisor, due ≤8 weeks after the end | Plan for it after the internship. |
| Thesis link | Thesis: 30 CP, 24 weeks; at submission ≥78 CP **including the internship CP** (§8(2)); the handbook lists the internship as a mandatory prerequisite. Thesis "in cooperation with external institutions" allowed; the second examiner can be the company person (§8(6)) | **The internship is on your critical path to graduating.** The thesis can be done in a company. |
| Fallback | If no placement is found "despite adequate effort", the exam board and mentor can approve a replacement project (§6(10)) | Safety net. Keep the tracker as evidence of effort. |

**Timeline consequence:** `profile.json` says graduation 2027-03. Internship (≥7 weeks) + thesis (24 weeks) cannot both fit before March 2027, so that date will very likely move to ~Q3/Q4 2027. **Decide the real date with your mentor.** The CV and every application must show a consistent date; an inconsistent one makes a recruiter doubt everything else.

### 2.2 German immigration and labour law for the internship

| Topic | Finding | Confidence |
|---|---|---|
| 140-day rule | Most university sources (Heidelberg, Munich city, Giessen) say an internship prescribed by the study regulations is **not counted** against 140 days. HS Bremen says it is counted. Heidelberg: a *voluntary extension* beyond the required part counts. | Majority view. **Confirm in writing with Ausländerbehörde Essen** (step U2 in §8). |
| BA approval | §15 Nr. 3 BeschV: a stay that is a prescribed part of study is approval-free (my reading of the statute). Sources conflict. | Ausländerbehörde decides; same email as above. |
| Minimum wage | §22(1) Nr. 1 MiLoG: an internship mandatory under university regulations is exempt from the minimum wage | Well established. Employers know this; you don't need to mention it. |
| "≥260 h" with no maximum | Whether a 6-month internship is "fully mandatory" or "260 h mandatory + rest voluntary" is the Ausländerbehörde's call | Get a BTU letter stating the internship is required by the SPO (step U1). |
| After graduation | §20 AufenthG: up to 18 months job-search permit, work allowed | Track C (full-time) starts from ~graduation. |

### 2.3 Internship abroad: country matrix for a non-EU student enrolled in Germany

| Country | Rule found | Who acts / time | Verdict |
|---|---|---|---|
| **Austria** | workinaustria (official ABA portal) example: a student enrolled in Germany doing an internship in Austria → **exempt from the Ausländerbeschäftigungsgesetz**; an AMS confirmation is optional; may need a visa for gainful employment (≤6 months) | Student; check entry/residence with ABA | **Go.** Best abroad option. Vienna/Graz/Linz AI firms; English common. |
| **Netherlands** | Student enrolled abroad: employer applies for a **TWV at UWV (<3 months)** or a **GVVA at IND (>3 months)**; no exemption; can't start before the permit is issued | Employer; ~5 weeks | **Selective.** Only large firms / recognised sponsors that state "internship visa support". |
| **Ireland** | **Internship Employment Permit** for full-time students enrolled at an institution outside Ireland, degree level or higher, max 12 months, no labour market test; employer must have ≥50% EEA staff; paid | Employer; weeks | **Selective.** Dublin tech/AI firms. |
| Belgium | <90 days: work permit; >90 days: single permit; an exemption for mandatory internships of students at EEA universities is described by Baker McKenzie but called a draft by PwC | Region (Brussels/Flanders/Wallonia) | **Skip** unless a company offers to handle it. |
| France | I found no clear route for a student enrolled outside France; the official sources only cover holders of a French student permit | DREETS / préfecture | **Skip.** |
| Switzerland | A work permit is always required for non-EU nationals; voluntary internships only in rare exceptions | — | **Skip.** |

**Erasmus+ internship grant:** DAAD rates 2025/26: group 1 countries (AT, BE, DK, FI, FR, IE, IT, LU, NL, NO, SE, …) **€750/month**; group 2/3 €690. The internship must be **2-12 months, full-time (≥35 h/week)**. Eligibility is tied to enrolment at a programme-country university. I could not find an official sentence settling non-EU nationality, so **ask the BTU International Office** (step U3). There's also a free EU portal for these internships: **erasmusintern.org**, used in the manual lane.

### 2.4 Job data sources (verified 2026-10-17 by live calls)

| Source | Endpoint | Result today |
|---|---|---|
| Bundesagentur für Arbeit Jobsuche | `GET https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs` with header `X-API-Key: jobboerse-jobsuche`; params `was, wo, umkreis, angebotsart, page, size` | ✅ `v6` works, `v4/jobs` returns 403. Facet `angebotsart`: `1`=Arbeit, `34`=Praktikum/Trainee, `4`=Ausbildung. "Machine Learning" + `angebotsart=34` → 77 postings (BMW, Bayer…). |
| BA job details | `GET …/pc/v4/jobdetails/{base64(referenznummer)}` | ✅ Full text in `stellenangebotsBeschreibung`, plus `externeURL`, `homeofficemoeglich`. **In a sample of 30 Werkstudent-Informatik ads, 5 contained an email address** → feeds the email lane. |
| Arbeitnow | `GET https://www.arbeitnow.com/api/job-board-api?page=N` | ✅ 300 jobs per page, fields `remote, tags, job_types, location, created_at`; English-friendly. |
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | ✅ (n26: 35 jobs) |
| Lever | `GET https://api.lever.co/v0/postings/{slug}?mode=json` (EU accounts: `api.eu.lever.co`) | ✅ |
| SmartRecruiters | `GET https://api.smartrecruiters.com/v1/companies/{id}/postings?q=werkstudent` | ✅ (BoschGroup: 31 Werkstudent postings) |
| Personio | `GET https://{slug}.jobs.personio.de/xml?language=en` (some use `.com`) | ✅ for real slugs, 404 for wrong ones → each slug must be validated |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{slug}` | ✅ responds; slug must be correct |
| Adzuna | `https://api.adzuna.com/v1/api/jobs/{cc}/search/{page}?app_id&app_key` | Free key needed; only for Track C |
| EURES | No official public API found (only third-party scrapers) | ❌ Not used |
| LinkedIn / Indeed / Glassdoor | User agreements forbid bots; accounts get restricted | ❌ Manual lane only |
| Fraunhofer / DLR / Helmholtz / MPG | Career portals, no documented API found | Manual lane (weekly saved searches) |

### 2.5 Cold email: law and practice

- **UWG §7 (Germany)** bans *advertising* email without prior consent. No source I found treats a single, individual job application as advertising, and none says it is allowed either. The practical consensus: career offices of HU Berlin and Uni Hamburg explicitly recommend emailing a short application to the personal address of the contact person, and phoning first to get it. **Practical line:** one-to-one, individually written, about a concrete role or team, one follow-up, stop on "no". Never newsletter-style, never mass BCC.
- **GDPR:** you process business contact data of the recipient. Keep only name, role and email from a public company source; delete after 6 months without a reply; say where you got the address if asked.
- **Impressum:** §5 DDG requires German company websites to publish an email address. It's a reliable last-resort contact.
- **Deliverability:** Google's bulk-sender rules (SPF/DKIM/DMARC, one-click unsubscribe, spam rate <0.3%) apply at ~5,000/day. At ≤15/day from a normal Gmail you're far below that, but complaints still hurt, so the same discipline applies: plain text, no tracking pixel, one follow-up.

---

## 3. Strategy

### 3.1 Goals in order

| Goal | Target date | Success = |
|---|---|---|
| G1. Internship / Werkstudent recognised as module 13602 | Signed offer by **mid-Jan 2027**, start **Feb-Apr 2027** (≥4 weeks after signing for mentor approval) | Contract + mentor approval |
| G2. Master thesis in a company (ideally the G1 company) | Start right after the internship CP is in | Topic agreed with mentor + company |
| G3. Full-time job (DE or EU Blue Card) | Applications from ~3 months before graduation | Offer |

### 3.2 What to apply to (role types)

German keyword sets, all searched in the BA API, Arbeitnow and ATS boards:
- **Pflichtpraktikum:** `Pflichtpraktikum`, `Praktikum Informatik`, `Praktikum Data Science`, `Praktikum KI`, `Praktikum Machine Learning`, `Praxissemester`, `Internship AI/ML/Data/Software`.
- **Werkstudent** (recognisable as the internship): `Werkstudent` / `Working Student` + `KI, AI, Machine Learning, Data, Python, Software, Backend, Automatisierung`.
- **Thesis (G2, from ~Jan 2027):** `Masterarbeit`, `Abschlussarbeit`, `Master thesis` + AI/ML/Data.
- Domain fit stays as in `domain_filters.json`. The language filter (`3_language_filter.py`) keeps removing jobs that require B2+/fluent German.

### 3.3 Where

| Ring | Area | Share of effort |
|---|---|---|
| R1 | Ruhr/Rhineland around Essen: Essen, Bochum, Dortmund, Duisburg, Gelsenkirchen, Düsseldorf, Köln (BA `wo=Essen&umkreis=60`) | 40% |
| R2 | Remote / hybrid anywhere in Germany (`homeofficemoeglich`, Arbeitnow `remote=true`) | 20% |
| R3 | Rest of Germany, if relocating for the internship is OK (Berlin, Munich, Hamburg, Stuttgart, Frankfurt, Karlsruhe) | 25-30% |
| R4 | Abroad, internship only: AT (all), NL + IE (large employers that state visa/intern support), with Erasmus+ grant | 10-15% |

### 3.4 The pitch (the same truth in every channel)

> MSc AI student at BTU, looking for my **curricular mandatory internship (Pflichtpraktikum, ≥260 h)** or a Werkstudent role in AI/ML/data/software, from **{month}**. 1+ year as Software Engineer (Python, API endpoints, quant models, data pipelines) + ML internship. English C2, German A2 (learning).

Don't write "you don't have to pay me". HR knows the Pflichtpraktikum rules; saying "Pflichtpraktikum" is enough.

---

## 4. Weekly operating system

### 4.1 The 3 lanes

| Lane | What | Who does what | Weekly volume |
|---|---|---|---|
| **M: Manual** | Best-fit roles; LinkedIn / Indeed / Workday / SuccessFactors portals; Fraunhofer/DLR/Helmholtz; erasmusintern.org; all R4 abroad applications | Pipeline generates CV + letter; you add one personal line and submit | **20** |
| **A: Assisted ATS** | Roles on Personio, Greenhouse, Lever, SmartRecruiters, Join, Workable forms | Adapter fills the form; you check the screenshot and click submit. Auto-submit only after an adapter has done 10 clean runs | **~12** |
| **E: Email** | E1: ads saying "send your application to x@y" (≈17% of BA ads) · E2: cold Initiativbewerbung to target companies with no matching open role | Generated, gated emails; drafts in your Gmail; you send (auto-send after 2 clean weeks) | **~8 E1 + ~10 E2** |

M = your 20 own applications; A + E1 = the 20 automated ones; E2 cold emails come on top.

### 4.2 Weekly rhythm

| When | Machine | You |
|---|---|---|
| Mon 07:00 | `python main.py --sources all` → fetch, filter, classify, generate CV/letter for top ~45, route to lanes | 20 min: review the shortlist, move items between lanes |
| Mon-Fri | Lane A fills queued forms | 10 min/day: confirm and submit |
| Tue-Thu 08:00-10:30 | Lane E drafts / sends (≤15/day, 4-12 min gaps) | 10 min/day skimming drafts |
| Daily | Reply checker marks replies, cancels follow-ups | Answer replies the same day, yourself |
| Any time | — | Lane M: 20 applications; 5 LinkedIn connection notes/day to team leads at E2 companies |
| Fri | Follow-ups due; funnel report | 15 min: read numbers, adjust |

### 4.3 Hard rules
- Max 1 application per company per 30 days, across all lanes. No cold email to a company you applied to through its portal in the last 60 days.
- Every "earliest start" answer is ≥4 weeks out (the BTU approval rule).
- Nothing goes out that failed the existing gates. No invented skills, ever.
- Suppression list: any "no" or bounce → never contacted again.

### 4.4 Measure, then decide (from week 4)
Track sent → reply → interview → offer per lane, source, ring and role type. A lane/source with 0 positive replies after ~60 sends gets a changed message or targets, or is dropped, and its volume moves to the best one. Don't guess the rates in advance; measure them.

---

## 5. System build (concrete, in order)

Existing pieces kept as-is: steps 4-6 (KB, generator, gates, letters), `3_language_filter.py`, `4_filter_student_jobs.py`, `domain_filters.json`, the dashboard.

**Existing wiring issue to fix along the way:** `5_final_language_and_role_filter.py` writes its output **over** `program_files/output/2_filted_jobs.csv` (`OUTPUT_QUALIFIED_CSV`). Steps 3-5 aren't in `main.py`, and running them by hand silently replaces the step-2 file. Give each step its own output and wire them into `main.py` in order.

| # | Deliverable | Files | Effort | Done when |
|---|---|---|---|---|
| 0 | **Remove the hardcoded API key** from `program_files/autonomous_job_applier.py:9`, read it from env; **rotate the key** | that file, `.gitignore` | 15 min | No key in the repo |
| 1 | SQLite tracker (stdlib `sqlite3`): tables `jobs, companies, contacts, applications, emails`; `dedup_key = norm(company)+norm(title)`; import the current `job_status.csv` and `application_bundles.json` | `app/core/tracker.py`, `resume_content_improve_research/tests/test_tracker.py` | 0.5 d | Dedup + cooldown tests pass |
| 2 | **BA source**: search v6 (Praktikum `angebotsart=34` + Arbeit `1` with Werkstudent keywords) × keyword sets × rings; details v4; map to the `todays_overall_jobs.csv` columns + `country, remote_scope, apply_email, apply_channel, role_type` | `app/phase1/sources/ba_jobsuche.py`, contract test with a recorded fixture | 1 d | ≥150 new relevant jobs/day; steps 2-6 run unchanged |
| 3 | **Arbeitnow source** | `app/phase1/sources/arbeitnow.py` | 0.25 d | Wired into `1_fetch_jobs.py`, each source fails independently |
| 4 | **Role-type classifier**: `pflichtpraktikum / praktikum / werkstudent / thesis / fulltime / other`, extending `4_filter_student_jobs.py` markers (`pflichtpraktikum, praxissemester, abschlussarbeit, masterarbeit, master thesis`) | `program_files/4_filter_student_jobs.py` | 0.25 d | Every job has `role_type` |
| 5 | **CV/letter variants**: add an internship statement to the KB (`templates_policy`): "Curricular mandatory internship (Pflichtpraktikum, BTU MSc AI, ≥260 h, 10 ECTS), available from {month}"; letter skeleton variant for `role_type ∈ {pflichtpraktikum, praktikum}`; thesis variant later; update `profile.json` (`earliest_start_date`, real `expected_graduation`) | `knowledge_base/candidate_kb.json`, `generation/cover_letter.py`, `profile.json` + tests | 0.5 d | Gates pass for all three variants |
| 6 | **Target companies + ATS scan**: `data/target_companies.yaml` (name, domain, city, ring, ats, slug, tier, english_ok, sponsors_intern_visa). Auto-seed from apply URLs (`jobs.personio.*`, `boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com`, `jobs.smartrecruiters.com`, `join.com`, `apply.workable.com`); validate slugs (404 → drop); daily poll | `app/phase1/sources/ats_boards.py`, `data/target_companies.yaml` | 1 d + 1 evening curating | ≥150 companies polled daily |
| 7 | **Lane router**: `apply_email` → E1; known ATS → A; else M; R4 abroad → M with a note; cooldown check | `app/core/router.py` | 0.5 d | Every job has a lane |
| 8 | **Gmail sender (draft mode) + reply checker**: OAuth Desktop app, scopes `gmail.compose` + `gmail.readonly`; create drafts with CV + letter PDFs; thread polling, out-of-office detection, suppression | `outreach/gmail_client.py, compose.py, send.py, replies.py` | 1.5 d | 5 correct drafts in Gmail; a reply is detected |
| 9 | **Lane A adapters**: Personio + Greenhouse first, then Lever / SmartRecruiters / Join / Workable. Playwright; fields from `profile.json` + `data/answer_bank.yaml`; unknown question → park with screenshot; reuse cookie/stop-condition code from `autonomous_job_applier.py`; drop JEV | `app/apply/adapters/*.py`, `app/apply/run.py` | 1 d per adapter | 10 consecutive clean fills per adapter |
| 10 | **Lane E2 cold email**: address finder (careers page → past JD emails → `/impressum`; MX check only, **no SMTP probing**); 120-170-word template generated from KB + `motivation.py`, gated by a new `verification/cold_gates.py` (length, no invented facts, company named, single ask, opt-out line); 1 follow-up after 6 business days | `outreach/finder.py, followups.py`, `verification/cold_gates.py` + tests | 1.5 d | Week 1: 5/day, 0 bounces |
| 11 | **Funnel tab** in the dashboard + statuses `Applied / Replied / Interview / Offer / Rejected` | `program_files/6_dashboard.py` | 0.5 d | Weekly numbers per lane |
| 12 | **Track C (later):** Adzuna for NL/AT/IE/…, full-time CV variant, `sponsors_visa` flag | `app/phase1/sources/adzuna.py` | 1 d | Starts ~3 months before graduation |

Steps 0-8 ≈ 6 working days and already double or triple what reaches you, with the email lane live. Steps 9-11 ≈ 5 more days.

### 5.1 Email templates (the generator fills `{}` from the KB; gates check them)

**E1: replying to an ad that asks for email applications** (DE ad → German subject + greeting; body may be English if the ad is English or tolerates it):
```
Subject: Bewerbung: {job_title} (Pflichtpraktikum / Werkstudent) – Meet Raval
Sehr geehrte/r {name or "Damen und Herren"},
anbei sende ich Ihnen meine Bewerbung für die Stelle „{job_title}“ (Ref. {ref}).
{2-3 sentences from the step-6 letter: the strongest KB match to this ad}
Verfügbar ab {month}, {hours}. Lebenslauf und Anschreiben im Anhang.
Mit freundlichen Grüßen / Kind regards
Meet Raval · {phone} · {linkedin}
Attachments: CV.pdf, Anschreiben.pdf (+ Immatrikulationsbescheinigung if requested)
```

**E2: cold Initiativbewerbung** (≤170 words, plain text, CV only):
```
Subject: Initiativbewerbung: Pflichtpraktikum KI/Data ab {month} – Meet Raval
Guten Tag {name},
{1 line: why this company – a concrete product/team/tech from their site}
I'm an MSc Artificial Intelligence student at BTU and am looking for my
mandatory internship (Pflichtpraktikum, ≥260 h) or a Werkstudent role from {month}.
{1-2 lines: the single most relevant KB project/experience, phrased for their domain}
Would there be room in {team} for an intern? My CV is attached; I'm happy to talk
in English (my German is A2 and improving).
If this isn't relevant, just let me know and I won't contact you again.
Viele Grüße
Meet Raval · {phone} · {linkedin} · {github}
```
**Follow-up** (same thread, +6 business days): two lines, then stop.

---

## 6. Calendar from today

| Week | Dates | Build | Apply |
|---|---|---|---|
| W1 | Oct 19-25 | Steps 0-4 | Do U1-U4 (§8); Lane M 20/week with current pipeline |
| W2 | Oct 26-Nov 1 | Steps 5-8 | Lanes M + E1 (drafts) |
| W3 | Nov 2-8 | Step 9 (Personio, Greenhouse) | + Lane A in review mode |
| W4 | Nov 9-15 | Step 10, 11 | + Lane E2 at 5/day; first funnel review |
| W5-W10 | Nov 16-Dec 20 | Remaining adapters; tuning | Full volume (~50/week). **Main window**: German companies post Feb-Apr internships now |
| Xmas | Dec 21-Jan 4 | — | Low response period; queue follow-ups for Jan 5 |
| W11-W13 | Jan 5-25 | Thesis variant (role_type=thesis) | Interviews; target: signed offer by mid-Jan; mentor approval ≥4 weeks before start |
| Feb-Apr | | Track C prep | Internship starts; start the thesis search inside the company |

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| Ausländerbehörde counts the internship toward 140 days | Ask in writing first (U2). Keep the part-time job's days tracked in the tracker. |
| Gmail flagged | ≤15/day, plain text, personal, 1 follow-up, suppression list, draft-first ramp-up. |
| Bad automated applications hurting your name | Lane A only uses deterministic adapters + review until proven; Lane E uses the same no-fabrication gates as letters. |
| BA API changes (v4→v6 already happened) | Contract test with a recorded fixture; sources fail independently. |
| Abroad offer can't get a permit | R4 only for AT, or NL/IE employers that state intern visa support; start date ≥8 weeks after offer. |
| Graduation date inconsistency on the CV | U1: fix the real date with your mentor before W2 generation runs. |

---

## 8. Things only you can do (this week)

- **U1, mentor (BTU):** (a) realistic graduation date; (b) confirm a Werkstudent role can count as module 13602 (§6(7)) and what the mentor wants to see; (c) ask for a short **letter confirming the internship is mandatory under the SPO** ("Bescheinigung Pflichtpraktikum"). Companies and the Ausländerbehörde both ask for it.
- **U2, Ausländerbehörde Essen (email):** "My MSc AI regulations (PO 2022 §6) require an internship of at least 260 hours. Please confirm (1) it is not counted toward the 140/280-day limit and (2) no BA approval is needed, including if the internship runs 3-6 months." Keep the written answer.
- **U3, BTU International Office:** Erasmus+ internship grant eligibility for non-EU nationals, deadline, required documents; plus any company/Fraunhofer partner lists of the chairs (Annex 3 §2: "Chairs can and should provide assistance").
- **U4, LinkedIn:** headline "MSc AI student · looking for Pflichtpraktikum / Werkstudent (AI/ML/Data) from {month}"; Open-to-Work (recruiters only).
- **U5:** Create a Google Cloud project + OAuth desktop credentials for Gmail (I'll guide you when we reach step 8).

---

## 9. Still open (and who answers)

| Question | Who decides |
|---|---|
| 140-day treatment of the internship beyond 260 h | Ausländerbehörde Essen (U2) |
| Erasmus+ for non-EU nationals at BTU | BTU International Office (U3) |
| Belgium mandatory-internship exemption in force? | Regional authority. Not pursued. |
| Exact Adzuna country list/quota | Adzuna developer account (step 12, later) |

---

## Sources

**BTU**
- Study regulations MSc AI (English translation): https://fsr-it.de/docs/spo-artificial-intelligence-ms-english.pdf
- Module handbook WiSe 26/27: https://www-docs.b-tu.de/studierende/public/modulhandbuch/master/Artificial_Intelligence/WiSe_26_27/Modulhandbuch_WS2026_27_88_ARI_PO2022.pdf
- BTU AI FAQ: https://www.b-tu.de/en/artificial-intelligence-ms/faq

**German rules**
- Pflichtpraktikum & 140 days: https://www.uni-heidelberg.de/de/internationale-studierende-jobben-und-praktikum · https://stadt.muenchen.de/infos/studium-arbeiten-aufenthaltsrecht.html · https://hs-bremen.de/studieren/nach-dem-studium/bewerbung-und-berufseinstieg/karriereleitfaden-fuer-internationale-studierende/schritt-9-arbeitsbedingungen-in-deutschland
- BA guidance on internships of foreign students: https://www.fau.eu/wp-content/uploads/sites/6/2025/09/dok_ba036105.pdf · §15 BeschV: https://gesetze.legal/bund/beschv/15
- §20 AufenthG: https://lxgesetze.de/aufenthg/20

**Abroad**
- Austria: https://www.workinaustria.com/blog/was-internationale-studierende-fuer-ein-praktikum-in-oesterreich-brauchen
- Netherlands: https://www.nlarbeidsinspectie.nl/onderwerpen/wet-arbeid-vreemdelingen/buitenlandse-studenten
- Ireland: https://enterprise.gov.ie/en/what-we-do/workplace-and-skills/employment-permits/permit-types/internship-employment-permit/internship-employment-permit.html
- Belgium: https://resourcehub.bakermckenzie.com/en/resources/global-immigration-and-mobility/emea/belgium/topics/employment-assignments · https://news.pwc.be/work-permit-exemption-students
- France: https://www.lappelexpert.fr/question-juridique/un-etudiant-etranger-doit-il-avoir-une-autorisation-de-travail-pour-effectuer-un
- Switzerland (Swiss university career page, quoted in 2.3): https://hslucareer.castle.talentwerk.ch/en/for-students/internship

**Erasmus+**
- Rates 2025/26: https://www.uni-marburg.de/de/international/ins-ausland/studierende/finanzierung/erasmus-europa · https://www.uni-bonn.de/de/studium/studium-und-praktikum-im-ausland/praktikum-im-ausland/erasmus-praktikum/organisation-und-ablauf/download/erasmus_merkblatt_praktikum_2025_26.pdf
- Erasmusintern: https://education.ec.europa.eu/news/applying-for-internships-and-traineeships-in-europe

**Cold email and contacts**
- UWG §7: https://www.ihk-muenchen.de/ratgeber/recht/werbung-fairer-wettbewerb/marketing-per-email-telefon-brief-etc/
- Practice (career offices): https://crossingborders.hu-berlin.de/de/promint/praktikum/materialien/Bewerbungstipps · https://www.ew.uni-hamburg.de/studium/praktika/zap/files/anleitungkurzbewerbungallin-pdf.pdf
- Impressum §5 DDG: https://www.ihk.de/duesseldorf/recht-und-steuern/recht/internetrecht/impressum-5109750
- Google sender guidelines: https://support.google.com/a/answer/14229414

**Job APIs and platforms**
- BA Jobsuche API: https://github.com/bundesAPI/jobsuche-api
- Arbeitnow: https://www.arbeitnow.com/blog/job-board-api
- Adzuna: https://developer.adzuna.com/overview
- Personio feed: https://fantastic.jobs/ats/personio
- LinkedIn bot enforcement: https://semafor.com/article/09/12/2024/linkedins-have-nots-and-have-bots
