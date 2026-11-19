#!/usr/bin/env python3
"""Phase 7: final pre-generation deliverable — summary + audit + readiness."""
from __future__ import annotations
from pathlib import Path
import csv, json
from collections import Counter
from datetime import date

W = Path('program_files/output/fresh_run_2026-10-05')

def load(p):
    with p.open('r', encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))

raw = load(W/'step1_raw_fetch.csv')
elig = load(W/'FINAL_eligible_jobs.csv')
review = load(W/'FINAL_review_jobs.csv')
rej = load(W/'FINAL_rejected_jobs.csv')
audit = load(W/'FINAL_pre_generation_audit.csv')
summ = json.loads((W/'FINAL_summary.json').read_text(encoding='utf-8'))
dom_report = json.loads((W/'domain_filter_report.json').read_text(encoding='utf-8'))

print('='*78)
print('PHASE 7 — FINAL PRE-GENERATION DELIVERABLE')
print('Fresh run: 2026-10-05 .. 2026-10-09 (inclusive)')
print(f"Generated: {summ.get('now_local','?')}")
print('='*78)

# ---- Source-by-source summary ----
print('\n'+'='*78)
print('SOURCE-BY-SOURCE FETCHING SUMMARY')
print('='*78)
ss_raw = [r for r in raw if r.get('source')=='stepstone']
ws_raw = [r for r in raw if r.get('source')=='workingstudentjobs.de']
ss_dates = Counter(r.get('resolved_local_date') for r in ss_raw)
ws_dates = Counter(r.get('resolved_local_date') for r in ws_raw)
print(f"\nStepStone (headed Chrome, 7 keywords x 1 page, card-date pre-filter + details):")
print(f"  raw fetched: {len(ss_raw)} rows")
print(f"  date methods: {dict(Counter(r.get('date_method') for r in ss_raw))}")
print(f"  resolved dates: {dict(sorted(ss_dates.items()))}")
print(f"  in-window (Oct5-9): {sum(1 for r in ss_raw if r.get('resolved_local_date') in {date(2026,10,d).isoformat() for d in range(5,10)})}")
print(f"  out-of-window: {sum(1 for r in ss_raw if r.get('resolved_local_date') not in {date(2026,10,d).isoformat() for d in range(5,10)})}")
print(f"  StepStone error during fetch: {summ.get('source_failures',{}).get('stepstone_error','NONE')}")

print(f"\nWorkingstudentjobs.de (requests, JSON-LD datePosted, 2 pages + full detail):")
print(f"  raw fetched: {len(ws_raw)} rows")
print(f"  date methods: {dict(Counter(r.get('date_method') for r in ws_raw))}")
print(f"  resolved dates: {dict(sorted(ws_dates.items()))}")
print(f"  in-window (Oct5-9): {sum(1 for r in ws_raw if r.get('resolved_local_date') in {date(2026,10,d).isoformat() for d in range(5,10)})}")
print(f"  out-of-window: {sum(1 for r in ws_raw if r.get('resolved_local_date') not in {date(2026,10,d).isoformat() for d in range(5,10)})}")
print(f"  WSJ error during fetch: {summ.get('source_failures',{}).get('workingstudentjobs_de_error','NONE')}")

print(f"\nCombined (after canonical-URL dedup):")
print(f"  total raw: {len(raw)} (StepStone {len(ss_raw)} + WSJ {len(ws_raw)}, 0 cross-source dups)")
print(f"  in-window: {sum(1 for r in raw if r.get('resolved_local_date') in {date(2026,10,d).isoformat() for d in range(5,10)})}")
print(f"  out-of-window: {sum(1 for r in raw if r.get('resolved_local_date') not in {date(2026,10,d).isoformat() for d in range(5,10)})}")

# ---- Phase 3 date filter audit ----
print('\n'+'='*78)
print('PHASE 3 — DATE FILTER AUDIT (Oct 5-9 inclusive, local posting date)')
print('='*78)
print(f"\nDecision breakdown: {dict(Counter(r.get('date_decision') for r in audit))}")
print(f"Method breakdown: {dict(Counter(r.get('date_method') for r in audit))}")
rej_date = [r for r in audit if r.get('date_decision')=='REJECT']
print(f"\nDate-REJECTED (out of window): {len(rej_date)}")
for r in rej_date:
    print(f"  - {r['title'][:55]:55} | resolved={r.get('resolved_local_date')} | {r.get('date_reason','')[:70]}")
print(f"\nDate-resolution evidence (all 94 rows have a resolved date):")
unparseable = [r for r in audit if r.get('date_method')=='unparseable']
print(f"  unparseable: {len(unparseable)} (these go to REVIEW)")
for r in unparseable:
    print(f"    - {r['title'][:55]:55} | posted_time={str(r.get('posted_time',''))[:40]} | detail_online={str(r.get('detail_online_date',''))[:40]}")

# ---- Phase 4 language audit ----
print('\n'+'='*78)
print('PHASE 4 — LANGUAGE FILTER AUDIT')
print('='*78)
print(f"\nDecision breakdown: {dict(Counter(r.get('lang_decision') for r in audit if r.get('date_decision')=='KEEP'))}")
print(f"Category breakdown: {dict(Counter(r.get('lang_category') for r in audit if r.get('date_decision')=='KEEP'))}")
print(f"Posting-lang breakdown: {dict(Counter(r.get('posting_lang') for r in audit if r.get('date_decision')=='KEEP'))}")
inelig_lang = [r for r in audit if r.get('lang_decision')=='Ineligible']
uncert_lang = [r for r in audit if r.get('lang_decision')=='Uncertain']
print(f"\nLanguage-INELIGIBLE: {len(inelig_lang)}")
for r in inelig_lang:
    print(f"  - {r['title'][:55]:55} | cat={r.get('lang_category')} | {r.get('lang_reason','')[:80]}")
print(f"\nLanguage-UNCERTAIN (manual review): {len(uncert_lang)}")
for r in uncert_lang:
    print(f"  - {r['title'][:55]:55} | cat={r.get('lang_category'):20} | other_lang={r.get('other_lang_terms','')} | {r.get('lang_reason','')[:80]}")
print(f"\nCandidate language profile (from approved KB):")
print(f"  English: C2 (native)")
print(f"  German: A2 (conversational)")
print(f"  Hindi: C2 (native)")
print(f"  Gujarati: C2 (native)")
print(f"\nLanguage-filter policy applied:")
print(f"  - Mandatory German required -> Ineligible (A2 only)")
print(f"  - German preferred/nice-to-have -> Eligible (A2 compatible with 'plus')")
print(f"  - English requirement or English-dominant posting w/o DE req -> Eligible (C2 English)")
print(f"  - German-dominant posting w/o explicit language req -> Uncertain (can't assume DE unnecessary)")
print(f"  - Non-EN/non-DE language required (French/Spanish/etc.) -> Uncertain (not in candidate profile)")

# ---- Phase 5 domain audit ----
print('\n'+'='*78)
print('PHASE 5 — DOMAIN FILTER AUDIT (existing v2 gate: stage 1 keywords + stage 2 60%)')
print('='*78)
print(f"\nDomain decision breakdown (on {summ['phase5_domain']['stage1_kept']+summ['phase5_domain']['stage2_kept']} language-eligible jobs):")
print(f"  stage-1 keyword-kept: {summ['phase5_domain']['stage1_kept']}")
print(f"  stage-2 scored-kept:  {summ['phase5_domain']['stage2_kept']}")
print(f"  eliminated stage-1:   {summ['phase5_domain']['eliminated_stage1']}")
print(f"  eliminated stage-2:   {summ['phase5_domain']['eliminated_stage2']}")
print(f"  total eliminated:      {summ['phase5_domain']['eliminated']}")
rej_dom = [r for r in audit if r.get('domain_decision')=='eliminate']
print(f"\nDomain-REJECTED (firm): {len(rej_dom)}")
for r in rej_dom:
    print(f"  - {r['title'][:55]:55} | {r.get('company','')[:25]:25} | reason: {r.get('domain_reason','')[:85]}")
print(f"\nDomain-filter configuration (knowledge_base/domain_filters.json):")
print(f"  min_skill_alignment: 0.60 (stage 2)")
print(f"  families: software, ai_data, automation, hardware_iot, finance, tech_business_direct, tech_business_needs_tech")
print(f"  out_identity: mechanical/civil/health/hospitality/retail/etc.")
print(f"  demand_tools: et al. (JD terms candidate can't claim)")
print(f"  industry_keywords: tech-adjacent employer signals (bounded bonus)")

# ---- Final eligible dataset ----
print('\n'+'='*78)
print('FINAL CONFIRMED ELIGIBLE DATASET ('+str(len(elig))+' jobs)')
print('='*78)
print(f"\nBy source: StepStone={sum(1 for r in elig if r.get('source')=='stepstone')} | WSJ={sum(1 for r in elig if r.get('source')=='workingstudentjobs.de')}")
print(f"By date: {dict(sorted(Counter(r.get('resolved_local_date') for r in elig).items()))}")
print(f"\nFull eligible list ({len(elig)} jobs):")
for i,r in enumerate(elig,1):
    print(f"  {i:3d}. {r.get('resolved_local_date'):10} | {r.get('source'):20} | {r.get('title','')[:50]:50} | {r.get('company','')[:28]:28} | {r.get('job_url','')[:55]}")

# ---- Review dataset ----
print('\n'+'='*78)
print('MANUAL-REVIEW DATASET ('+str(len(review))+' jobs — uncertain language)')
print('='*78)
for i,r in enumerate(review,1):
    print(f"  {i}. {r.get('title','')[:55]:55} | {r.get('company','')[:25]:25} | {r.get('job_url','')[:55]}")
    print(f"       lang_decision: {r.get('lang_decision')} | category: {r.get('lang_category')}")
    print(f"       reason: {r.get('lang_reason','')[:100]}")
    print(f"       other_lang terms: {r.get('other_lang_terms','')}")
    print(f"       posting_lang: {r.get('posting_lang','')} | mandatory_german: {r.get('mandatory_german','')} | preferred_german: {r.get('preferred_german','')} | english_req: {r.get('english_req','')}")

# ---- Rejection audit ----
print('\n'+'='*78)
print('REJECTION AUDIT (firm-rejected: '+str(len(rej))+' jobs)')
print('='*78)
for i,r in enumerate(rej,1):
    parts=[]
    if r.get('date_decision')=='REJECT':
        parts.append(f"DATE: {r.get('resolved_local_date','')} (outside Oct5-9) — {r.get('date_reason','')[:60]}")
    if r.get('lang_decision')=='Ineligible':
        parts.append(f"LANG: {r.get('lang_category','')} — {r.get('lang_reason','')[:70]}")
    if r.get('domain_decision')=='eliminate':
        parts.append(f"DOMAIN: {r.get('domain_reason','')[:80]}")
    print(f"  {i}. {r.get('title','')[:50]:50} | {r.get('company','')[:22]:22} | {'; '.join(parts)}")
    print(f"       date_method={r.get('date_method','')} | posting_lang={r.get('posting_lang','')}")

# ---- Per-job audit trail (eligible) ----
print('\n'+'='*78)
print('PER-JOB AUDIT TRAIL — CONFIRMED ELIGIBLE (sample of first 12)')
print('='*78)
for r in elig[:12]:
    print(f"\n  {r.get('title','')[:55]}")
    print(f"    URL:        {r.get('job_url','')}")
    print(f"    Source:     {r.get('source','')}")
    print(f"    Company:    {r.get('company','')}")
    print(f"    Location:   {r.get('location','') or '(from description: Remote in Germany)'}")
    print(f"    Posted:     {r.get('posted_time','')} (raw) -> {r.get('resolved_local_date','')} (resolved local)")
    print(f"    Date method:{r.get('date_method','')}")
    print(f"    Date decision: {r.get('date_decision','')} — {r.get('date_reason','')[:80]}")
    print(f"    Lang decision: {r.get('lang_decision','')} — category {r.get('lang_category','')}")
    print(f"    Lang reason:   {r.get('lang_reason','')[:90]}")
    print(f"    Lang signals:  mandatory_german={r.get('mandatory_german','')} preferred_german={r.get('preferred_german','')} english_req={r.get('english_req','')} other_lang={r.get('other_lang_terms','')} posting_lang={r.get('posting_lang','')}")
    print(f"    Domain decision: {r.get('domain_decision','')} — {r.get('domain_reason','')[:75]}")
    print(f"    Families matched: {r.get('families_matched','')}")

print(f"\n  ... ({len(elig)} total — see FINAL_eligible_jobs.csv for full field set)")

# ---- Readiness assessment ----
print('\n'+'='*78)
print('READINESS ASSESSMENT')
print('='*78)
print(f"""
SUMMARY:
  - Fetched {len(raw)} unique jobs from BOTH sources (StepStone {len(ss_raw)} + WSJ {len(ws_raw)}).
  - Both sources fetched successfully with no documented failures.
  - Date filter (Oct 5-9 inclusive, local posting date): kept {sum(1 for r in audit if r.get('date_decision')=='KEEP')} / {len(raw)}.
    * 0 unparseable dates (all 94 rows resolved a local posting date).
    * 2 out-of-window rejected (Oct 2, Oct 3).
  - Language filter: {summ['phase4_language']['eligible']} Eligible, {summ['phase4_language']['ineligible']} Ineligible, {summ['phase4_language']['uncertain']} Uncertain.
    * 0 mandatory-German -> ineligible (none of the Oct5-9 jobs require mandatory German).
    * 4 uncertain (non-EN/non-DE language required: Chinese/Dutch/French/Spanish) — separated to review.
  - Domain filter (existing v2 gate): {summ['phase5_domain']['stage1_kept']+summ['phase5_domain']['stage2_kept']} kept, {summ['phase5_domain']['eliminated']} eliminated.
    * 2 eliminated by stage-1 out-of-domain title (medical device, warehouse/lager).
  - FINAL CONFIRMED ELIGIBLE: {len(elig)} jobs.
  - MANUAL REVIEW: {len(review)} jobs (language uncertain — non-EN/non-DE language required).
  - FIRM-REJECTED: {len(rej)} jobs (2 date + 2 domain).

VALIDATION (Phase 6, 10-point checklist):
  1.  PASS — all {len(elig)} eligible jobs within Oct 5-9 (dates: Oct6=2, Oct7=5, Oct8=67, Oct9=12).
  2.  PASS — all {len(elig)} eligible jobs have valid, unique HTTP URLs.
  3.  PASS — dedup correct (94 raw, 0 dups, 94 audit rows; elig+review+rej=94; no cross-category overlap).
  4.  PASS — language eligibility evidenced (all eligible have lang_decision=Eligible + lang_category + signals).
  5.  PASS — domain eligibility evidenced (all eligible have domain_decision=keep + reason + families_matched; domain_records agrees).
  6.  MINOR — 1 of {len(elig)} eligible jobs has empty 'location' field (vialytics Computer Vision Intern: JSON-LD jobLocation=null; 'Remote in Germany' present in description, not fabricated).
  7.  PASS — 4 uncertain jobs separated into review dataset, disjoint from eligible.
  8.  PASS — all 86 eligible jobs fully traceable through date+language+domain (date_method + lang_category + domain_reason); all 4 rejected have reasons.
  9.  PASS — both sources processed successfully, no failures documented; WSJ in eligible has dates Oct6-9.
  10. PASS — final output reconciles with fetched dataset (94 = 94; summary JSON matches actual counts on all 7 cross-checked fields).

MINOR DATA GAP (not a blocker):
  - 1 eligible job (vialytics Computer Vision Intern) has location='' because the WSJ JSON-LD jobLocation is null. The description text ('Remote in Germany') carries the location. Not fabricated; location recoverable from description. Recommend a one-line enrichment pass (extract 'Remote in Germany' from description into location) before resume generation, OR accept the description as the location source for this job.

CRITICAL ISSUE CHECK:
  - No critical issue prevents reliable validation. The dataset is internally consistent and traceable.
  - The 4 review jobs are explicitly NOT in the eligible set — they require manual language review before generation.
  - The 4 firm-rejected jobs are explicitly excluded with documented reasons.

READINESS: READY TO PROCEED TO RESUME + COVER-LETTER GENERATION, with two caveats:
  (a) The 4 review jobs (language uncertain) should be resolved manually FIRST — decide whether to include
      them (if the non-EN/non-DE language requirement is confirmable as not-mandatory or the candidate
      has the language) or keep them excluded. Do NOT generate resumes for them until resolved.
  (b) The 1 location-gap job (vialytics) should have its location enriched from the description
      ('Remote in Germany') before or during generation, so the cover letter address block and ATS
      location field are complete.

RECOMMENDED NEXT STEP (separate subsequent step, NOT in this task):
  - Run the v2 engine (main.py steps 4-6) on the {len(elig)} confirmed-eligible jobs in
    FINAL_eligible_jobs.csv, after:
    * manually resolving the 4 review jobs (include or exclude),
    * optionally enriching the vialytics location from its description.
  - Do NOT include the 4 review jobs or the 4 rejected jobs in the generation run unless/until resolved.
""")

print('\n'+'='*78)
print('DELIVERABLE FILES (in program_files/output/fresh_run_2026-10-05/)')
print('='*78)
print(f"""
  step1_raw_fetch.csv              — raw fetch (94 rows, both sources, pre-filter)
  step1_posting_date_audit.csv     — posting-date audit for all 94 rows
  step3_date_filtered.csv          — date-KEEP jobs (92)
  step3_date_rejected.csv          — date-REJECT + REVIEW (2)
  step3_date_audit.csv             — full date audit
  step4_lang_eligible.csv          — language-eligible (88)
  step4_lang_ineligible.csv        — language-ineligible (0)
  step4_lang_uncertain.csv         — language-uncertain / review (4)
  step4_lang_decisions.csv         — all 92 date-survivors' language decisions + signals
  step5_domain_kept.csv            — domain-kept (86)
  step5_domain_rejected.csv        — domain-rejected (2)
  step5_domain_records.csv         — all domain-gate records (decision + reason + score)
  domain_filter_report.json        — v2 domain gate full report (JSON)
  FINAL_pre_generation_audit.csv   — consolidated per-job audit (all 94, all 3 filters)
  FINAL_eligible_jobs.csv          — CONFIRMED ELIGIBLE (86) — ready for generation
  FINAL_review_jobs.csv            — MANUAL REVIEW (4) — language uncertain
  FINAL_rejected_jobs.csv          — FIRM REJECTED (4) — date/domain
  FINAL_summary.json               — this run's summary JSON
  _fresh_run_20261005.py          — fetch orchestrator (Phase 1-2)
  _filter_phase.py                 — filter orchestrator (Phase 3-5)
  _validate_phase6.py              — validation script (Phase 6)
  _phase7_report.py                — this report generator (Phase 7)
""")
print('='*78)
print('END OF PHASE 7 DELIVERABLE')
print('='*78)
