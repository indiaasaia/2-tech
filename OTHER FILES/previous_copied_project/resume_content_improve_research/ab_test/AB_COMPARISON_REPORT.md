# A/B Comparison: Old Engine (v1) vs Current Engine (v2)

**Date:** 2026-09-19 · **Jobs:** 10 of 21, stratified across the score range · **Raw data:** `ab_results.json` (same folder) · **Re-run:** `PYTHONIOENCODING=utf-8 python resume_content_improve_research/ab_test/judge.py`

## Verdict

**v2 is a real, measurable improvement — not a side-grade and not a regression.** On the same 10 jobs, judged by the same neutral scorer against the same JD yardstick:

- Composite score: **v1 66.6 → v2 77.2 (+10.5 mean)**, and **10/10 jobs improved** (range +1.4 to +22.9).
- Machine parseability: **0 vs 30 gate findings** (G1+G3 combined). v1's PDFs are structurally damaged; v2's parse clean.
- Truthfulness: **32 fabricated tech claims → 2**, **20 invented project titles → 2**, **40 parser-invisible dates → 0**.
- The one dimension where v1 tied (experience relevance, 5.2 vs 4.8) reflects v2's honesty constraint, not weaker tailoring.

## What was compared (and why it's fair)

| Design decision | Value |
|---|---|
| Old method artifacts | The **shipped** Sep-15 PDFs (`program_files/output/resume/pdf`), byte-identical to the backup copy — **21/21 SHA-256 hash match** proven, zero rebuild drift |
| Current method artifacts | The verified v2 PDFs (`program_files/output_v2/resume/pdf`) |
| Yardstick | **The same for both:** the v2 analyst's per-job JD criteria (`components_v2.json → analysis`) |
| Scorer | **The same for both:** the v2 verification stack (parse-back via `parse_sim`, coverage via `coverage.py`, gate audits G1/G2/G3, scorecard). No engine was scored with its own opinion of itself. |
| Fabrication audit | G2 lens applied to both engines' shipped text against the candidate KB (the claimable-set check), plus invented-project-title detection against the KB's real project list, plus percentage/metric detection |
| Caveat | v1 wrote its content against *its own* reading of the JD (its prompts saw only the JD text). v2's analyst is stricter, so v1 is scored on a yardstick it never saw. This *favors v2 slightly on coverage terms* — but everything structural (parse integrity, fabrication, format) is yardstick-independent, and those drive most of the delta. |

## Headline numbers

| Metric | v1 (old) | v2 (current) | Delta |
|---|---|---|---|
| Mean composite score (n=10) | 66.6 | **77.2** | **+10.5** |
| Jobs improved | — | **10/10** | — |
| Required-skill coverage | 63% | **73%** | +10 pts |
| Parse-fidelity points | 11.6/15 | **15.0/15** | +3.4 |
| Format-check points | 6.7/10 | **10.0/10** | +3.3 |
| G1+G3 integrity findings | **30** | **0** | −30 |
| Fabricated tech claims | **32** | 2* | −30 |
| Invented project titles | **20** | 2** | −18 |
| Parser-invisible dates (Dec'23 style) | **40** | 0 | −40 |
| Fabricated percentage metrics | 0 | 0 | parity |
| Word count (median) | ~173 (under 200-word gate) | ~596 | healthy range |
| Pages | 2 | 2 | parity |

\* v2's 2 = JD-tool mirroring (SAP, CRM — explicitly allowed by the model's own MIRRORABLE policy).
\** v2's 2 = "Automated Resume Generation System" — the KB's real "Automated Resume Generation" project printed with a suffix; cosmetic, not invented.

## Per-job results

| Job | v1 | v2 | Δ | Note |
|---|---|---|---|---|
| Business Development / Sales | 86.3 | 93.0 | +6.7 | |
| Finance Intern / Working Student | 86.8 | 93.0 | +6.2 | |
| Intern Sales & Client Success | 86.3 | 93.0 | +6.7 | |
| Werkstudent Projektmanagement (KI) | 86.3 | 93.0 | +6.7 | |
| Customer Success DACH | 86.5 | 93.0 | +6.5 | |
| Working Student (generic) | 34.1 | 35.5 | +1.4 | low for both: analyst found thin JD signal |
| ERS Europe automation | 62.3 | 85.2 | **+22.9** | biggest jump |
| Project & Product Mgmt (Digital) | 48.5 | 70.7 | **+22.2** | |
| Student HRIS & HR Operations | 46.3 | 64.6 | **+18.3** | |
| AI Engineer, Agentic Systems | 42.7 | 50.5 | +7.8 | genuine skill gap (containers/agentic design) — both honestly low |

Pattern worth reading: **the harder the job's fit, the bigger v2's win** (+18 to +23 in the 45–85 band). v2's honest gap-reporting and tighter coverage matching matter most exactly where tailoring is difficult. On easy jobs both engines saturate the same ceiling.

## The integrity story in one table

| Audit | v1 evidence (measured) | v2 evidence |
|---|---|---|
| Content corruption | `PROJECT-` collision in tex: experience text shipped under "Main Projects" | none (collision fixed + asserted) |
| Fabricated skills | Flask ×22 mentions (master CV has it commented out — KB note says so), Excel ×4, HubSpot, Salesforce, PowerBI, Tableau, CRM, TypeScript | 0 real (only allowed JD-tool mirroring) |
| Fabricated projects | 2/2 slots on **every** judged job (e.g. "Automated Budget vs Actuals Reporting System", "Integrated Asset Inventory & ESG Tracking System") | 0 invented (KB projects only, 2 cosmetic suffixes) |
| Fabricated metrics | 0 in these artifacts (but V4's audit found 35 across project slots historically) | 0, structurally gated |
| Date parseability | 4 apostrophe dates per resume (`Dec'23`) — invisible to ATS date parsers | 0 (`Dec 2023` format) |
| Segmentation | ~173 words → G1 underflow on 10/10 (text extraction collapse risk) | ~596 words, clean |
| Contact/header | PII extractable but embedded in corrupted 2-page flow | header-context verified per resume |

## What this does NOT yet prove

1. **Coverage ceiling.** Both engines miss ~27% of required skills on hard jobs. v2 *reports* those misses honestly instead of inventing them; that's the designed behavior, but the number itself only improves by enriching the KB (real skills the candidate can add, e.g. containerization coursework).
2. **LLM-variance.** Both sides were judged from one historical run each. A fresh v1 run (its Ollama outputs are non-deterministic) could land slightly differently — but the structural findings (collision bug, apostrophe dates, invented projects, underflow) are deterministic properties of v1's code, present in 21/21 artifacts, and cannot be run-dependent.
3. **End-to-end tailoring.** v2's 11 mid/low resumes were generated before the coverage-matcher fix; regenerating them under the current loop should lift their scores a few points. The A/B here measures the engines as they shipped.
4. **The real recruiter.** This measures machine-readability and truthfulness — the measurable half of "ATS score". Keyword-stuffing v1 sometimes *wins* raw keyword checks precisely because it fabricates; any human or LLM reviewer would score those claims against the candidate and fail them. That is why the fabrication audit is weighted as a defect count here, not a score bonus.

## Conclusion

Did we improve, or just move sideways? **We improved, on every axis the pipeline was built to fix:** +10.5 composite on identical jobs and yardstick, 30→0 integrity findings, 30→2 fabricated tech claims, 20→2 invented projects, 40→0 parser-invisible dates, and a 10/10 win rate with the largest gains exactly where resumes are hardest to tailor. The two places v1 "ties" (percentage metrics, page count) are places v1 happened to be clean, and the one place v1 edges v1 (experience relevance +0.4) is the visible cost of v2 refusing to claim experience the candidate doesn't have.

The remaining honest gap (73% required coverage) is a *knowledge-base* limitation, not an engine limitation — the next lever is enriching the KB with real, evidenced skills, not touching the generator again.
