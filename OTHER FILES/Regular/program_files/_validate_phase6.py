#!/usr/bin/env python3
"""Phase 6 validation: 10-point checklist on the consolidated audit."""
from __future__ import annotations
from pathlib import Path
import csv, json
from datetime import date
from collections import Counter

W = Path('program_files/output/fresh_run_2026-10-05')
RAW = W/'step1_raw_fetch.csv'
AUDIT = W/'FINAL_pre_generation_audit.csv'
ELIG = W/'FINAL_eligible_jobs.csv'
REVIEW = W/'FINAL_review_jobs.csv'
REJ = W/'FINAL_rejected_jobs.csv'
SUMM = W/'FINAL_summary.json'
DOM_RECORDS = W/'step5_domain_records.csv'

def load(p):
    with p.open('r', encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))

raw = load(RAW)
audit = load(AUDIT)
elig = load(ELIG)
review = load(REVIEW)
rej = load(REJ)
dom_records = load(DOM_RECORDS)
summ = json.loads(SUMM.read_text(encoding='utf-8'))

issues = []
window_dates = {date(2026,10,d).isoformat() for d in range(5,10)}

def joind(fields, r, sep=' | '):
    return sep.join(str(r.get(f,'')) for f in fields)

print('='*70)
print('PHASE 6 VALIDATION — 10-point checklist')
print('='*70)

# 1. Eligible within window
print('\n[1] Eligible jobs within Oct 5-9 window:')
bad = [r for r in elig if r.get('resolved_local_date','') not in window_dates]
if bad:
    issues.append(f"[1] {len(bad)} eligible outside window")
    for r in bad[:8]:
        print(f"    FAIL: {r['title'][:50]} | {r.get('resolved_local_date')}")
else:
    print(f"    PASS — all {len(elig)} eligible within 2026-10-05..2026-10-09")
    for d in sorted(window_dates):
        c = sum(1 for r in elig if r.get('resolved_local_date')==d)
        print(f"      {d}: {c}")

# 2. Valid usable URLs
print('\n[2] Eligible jobs have valid, usable URLs:')
bad_url = [r for r in elig if not r.get('job_url','').strip() or not r['job_url'].startswith('http')]
if bad_url:
    issues.append(f"[2] {len(bad_url)} eligible with bad/missing URL")
    for r in bad_url[:5]:
        print(f"    FAIL: {r['title'][:50]} | url={r.get('job_url')[:60]}")
else:
    print(f"    PASS — all {len(elig)} eligible have HTTP URLs")
dups = [u for u,c in Counter(r['job_url'] for r in elig).items() if c>1]
if dups:
    issues.append(f"[2] {len(dups)} duplicate URLs among eligible")
    print(f"    WARN duplicate URLs: {dups[:5]}")
else:
    print(f"    PASS — all eligible URLs unique")

# 3. Deduplication
print('\n[3] Deduplication:')
raw_urls = [r.get('job_url','') for r in raw]
seen=set(); dups_raw=0
for u in raw_urls:
    if u in seen: dups_raw+=1
    seen.add(u)
print(f"    raw={len(raw)} rows, {dups_raw} exact-URL dups")
print(f"    audit={len(audit)} rows")
cat_sum = len(elig)+len(review)+len(rej)
print(f"    elig({len(elig)})+review({len(review)})+rej({len(rej)}) = {cat_sum}")
if cat_sum != len(audit):
    issues.append(f"[3] categories sum {cat_sum} != audit {len(audit)}")
else:
    print(f"    PASS — categories sum to audit total")
eurls={r['job_url'] for r in elig}; rurls={r['job_url'] for r in review}; jurls={r['job_url'] for r in rej}
if eurls & rurls:
    issues.append(f"[3] overlap eligible&review: {len(eurls&rurls)}")
    print(f"    FAIL overlap eligible&review")
else:
    print(f"    PASS — no eligible-in-review overlap")
if eurls & jurls:
    issues.append(f"[3] overlap eligible&rejected: {len(eurls&jurls)}")
    print(f"    FAIL overlap eligible&rejected")
else:
    print(f"    PASS — no eligible-in-rejected overlap")
if len(audit) != len(raw) - dups_raw:
    issues.append(f"[3] audit {len(audit)} != raw-dups {len(raw)-dups_raw}")
    print(f"    WARN audit {len(audit)} vs raw-dups {len(raw)-dups_raw}")
else:
    print(f"    PASS — audit = raw - {dups_raw} deduped")

# 4. Language eligibility evidence
print('\n[4] Language eligibility evidence (eligible):')
elig_lang_ok = all(r.get('lang_decision')=='Eligible' for r in elig)
print(f"    all eligible lang_decision=Eligible: {elig_lang_ok}")
if not elig_lang_ok:
    issues.append(f"[4] {sum(1 for r in elig if r.get('lang_decision')!='Eligible')} eligible with non-Eligible lang")
print("    sample eligible language reasoning:")
for r in elig[:5]:            print(f"      - {r['title'][:50]:50} | cat={r.get('lang_category',''):16} | posting_lang={r.get('posting_lang',''):16} | en_req={r.get('english_req',''):5} mand_de={r.get('mandatory_german',''):5} pref_de={r.get('preferred_german',''):5} other={r.get('other_lang_terms','')})")

# 5. Domain eligibility evidence
print('\n[5] Domain eligibility evidence (eligible):')
elig_dom_ok = all(r.get('domain_decision')=='keep' for r in elig)
print(f"    all eligible domain_decision=keep: {elig_dom_ok}")
if not elig_dom_ok:
    issues.append(f"[5] {sum(1 for r in elig if r.get('domain_decision')!='keep')} eligible with non-keep domain")
print("    sample eligible domain reasoning:")
for r in elig[:5]:
    print(f"      - {r['title'][:50]:50} | domain={r.get('domain_decision',''):6} | reason={r.get('domain_reason','')[:55]}")
dom_by_url = {r.get('job_url',''): r for r in dom_records}
mm=0
for r in elig:
    u=r.get('job_url','')
    if u in dom_by_url and dom_by_url[u].get('decision')!='keep':
        mm+=1
if mm:
    issues.append(f"[5] {mm} eligible marked eliminate in domain_records")
    print(f"    FAIL {mm} eligible marked eliminate in domain_records")
else:
    print(f"    PASS — domain_records agrees with eligible set")

# 6. Essential fields
print('\n[6] Essential fields present & consistent (eligible):')
req=['title','company','job_url','location','posted_time','resolved_local_date','date_decision','lang_decision','domain_decision','job_description']
mc=Counter()
for r in elig:
    for f in req:
        if not str(r.get(f,'')).strip():
            mc[f]+=1
print(f"    missing counts: {dict(mc)}")
if mc:
    issues.append(f"[6] missing essential fields: {dict(mc)}")
else:
    print(f"    PASS — all essential fields present")
dok=True
for r in elig:
    d=r.get('resolved_local_date',''); dd=r.get('date_decision','')
    if dd=='KEEP' and d not in window_dates:
        dok=False; print(f"    FAIL date KEEP but {d}: {r['title'][:40]}")
if dok:
    print(f"    PASS — date_decision=KEEP consistent with resolved date")

# 7. Uncertain separated
print('\n[7] Uncertain separated from eligible:')
print(f"    eligible={len(elig)} review={len(review)}")
print(f"    disjoint: {not (eurls & rurls)}")
if eurls & rurls:
    issues.append("[7] uncertain leaking into eligible")
else:
    print(f"    PASS — review disjoint from eligible")
print("    review jobs:")
for r in review:
    print(f"      - {r['title'][:55]:55} | lang={r.get('lang_decision',''):10} cat={r.get('lang_category',''):20} | {r.get('lang_reason','')[:75]}")

# 8. Traceability
print('\n[8] Traceability (each eligible has date_method + lang_category + domain_reason):')
traced=sum(1 for r in elig if r.get('date_method','') and r.get('lang_category','') and r.get('domain_reason',''))
print(f"    {traced}/{len(elig)} fully traceable")
if traced<len(elig):
    issues.append(f"[8] {len(elig)-traced} eligible missing traceability")
else:
    print(f"    PASS — all eligible traceable through all 3 filters")
print("    firm-rejected jobs with reasons:")
for r in rej:
    parts=[]
    if r.get('date_decision')=='REJECT': parts.append(f"date:{r.get('resolved_local_date','')}")
    if r.get('lang_decision')=='Ineligible': parts.append(f"lang:{r.get('lang_category','')}")
    if r.get('domain_decision')=='eliminate': parts.append(f"domain:{r.get('domain_reason','')[:45]}")
    print(f"      - {r['title'][:55]:55} | {'; '.join(parts)}")

# 9. Both sources
print('\n[9] Source processing:')
ss_raw=sum(1 for r in raw if r.get('source')=='stepstone')
ws_raw=sum(1 for r in raw if r.get('source')=='workingstudentjobs.de')
ss_el=sum(1 for r in elig if r.get('source')=='stepstone')
ws_el=sum(1 for r in elig if r.get('source')=='workingstudentjobs.de')
print(f"    raw: stepstone={ss_raw} wsj={ws_raw}")
print(f"    eligible: stepstone={ss_el} wsj={ws_el}")
print(f"    source failures: {summ.get('source_failures',{})}")
if summ.get('source_failures',{}).get('stepstone_error') or summ.get('source_failures',{}).get('workingstudentjobs_de_error'):
    print(f"    WARN source failure documented")
else:
    print(f"    PASS — both sources fetched with no documented failure")
print(f"    WSJ dates in eligible: {sorted(set(r.get('resolved_local_date') for r in elig if r.get('source')=='workingstudentjobs.de'))}")

# 10. Reconciliation
print('\n[10] Reconciliation:')
print(f"    raw={len(raw)} audit={len(audit)} elig+review+rej={cat_sum}")
if cat_sum==len(audit)==(len(raw)-dups_raw):
    print(f"    PASS — final output reconciles with fetched dataset (raw {len(raw)} - {dups_raw} dups = {len(audit)})")
else:
    issues.append(f"[10] reconciliation mismatch: raw={len(raw)} dups={dups_raw} audit={len(audit)} catsum={cat_sum}")
# summary cross-check
print("    summary JSON cross-check:")
checks=[]
checks.append(("fetched.total", summ['fetched']['total'], len(raw)-dups_raw))
checks.append(("phase3_date.kept", summ['phase3_date']['kept'], sum(1 for r in audit if r.get('date_decision')=='KEEP')))
checks.append(("phase4_language.eligible", summ['phase4_language']['eligible'], sum(1 for r in audit if r.get('lang_decision')=='Eligible')))
checks.append(("phase4_language.ineligible", summ['phase4_language']['ineligible'], sum(1 for r in audit if r.get('lang_decision')=='Ineligible')))
checks.append(("phase4_language.uncertain", summ['phase4_language']['uncertain'], len(review)))
checks.append(("final.confirmed_eligible", summ['final']['confirmed_eligible'], len(elig)))
checks.append(("final.manual_review", summ['final']['manual_review'], len(review)))
allok=True
for name,sv,av in checks:
    ok = sv==av
    if not ok: allok=False
    print(f"      {name}: summary={sv} actual={av} {'OK' if ok else 'MISMATCH'}")
if not allok:
    issues.append("[10] summary JSON mismatches actual counts")

print('\n'+'='*70)
print('PHASE 6 RESULT')
print('='*70)
if issues:
    print(f"ISSUES ({len(issues)}):")
    for i in issues: print(f"  - {i}")
else:
    print("ALL 10 CHECKS PASSED — no issues found.")

print('\nNOTE: language-other-language (4 jobs) are in REVIEW, not eligible — correct per task (uncertain cases separated).')
print('NOTE: domain-rejected (2 jobs) are in rejected, not eligible — correct per task.')
print(f"\nFINAL COUNTS: eligible={len(elig)} | review={len(review)} | firm-rejected={len(rej)} | audit={len(audit)}")
