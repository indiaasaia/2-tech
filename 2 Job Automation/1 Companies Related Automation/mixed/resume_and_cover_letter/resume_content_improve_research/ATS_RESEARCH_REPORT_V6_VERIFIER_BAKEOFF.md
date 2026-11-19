# ATS Research Report V6 — The Verifier Itself, Tested: 294 Findings, One Systemic Truth

**Relationship to V1–V5:** V5 fixed the architecture's shape (no embeddings, alias-map synonyms,
measured gates). V6 (this) tests the **verification system itself** — a working prototype of the
V5 gate suite was built and run against all 21 current jobs, its false-positive rate was triaged
finding-by-finding, and the JD-analyst LLM call (the pipeline's proposed replacement for 5× raw-JD
re-reading) was prototyped on real English and German postings.

**Artifacts (all in `experiment/`):** `verify_all.py` + `verify_results.json` (the gate bake-off),
`analyst_prototype.py` + `analyst_results.json` (the analyst test).

---

## 1. Gate bake-off: the verifier against reality

Ran the V5 gate suite (G1 parse sanity, G2 KB/hallucination, G3 artifact integrity) on all 21 jobs:

| Gate | Issues | Nature |
|---|---|---|
| G1 — parse sanity | 21 | word-segmentation collapse (153 "words" — the measured scshape defect, V5 §3) |
| G2 — KB/hallucination | **201** | unlicensed tech tokens + unexplained digits |
| G3 — artifact integrity | 72 | `PROJECT-` collision (21/21), corrupted titles (21/21), apostrophe dates (21/21) |
| **Total** | **294** | **0 of 21 jobs clean** |

Every known defect class was re-caught (the verifier reproduces V3/V4/V5 findings automatically),
and G2 added what no prior round had quantified. But a verifier that cries wolf is worthless —
so every major finding class was triaged:

## 2. The false-positive triage — and what it revealed

### 2a. The regex-FP fear that did NOT materialize
"rest" as English word inside `\brest\b` API-token regex: **0 occurrences** in generated fields
(checked contexts across all four stores). Word-boundary tech matching is safe on this corpus.

### 2b. The 201 G2 hits are overwhelmingly TRUE positives — and systemic
Context extraction on *generated fields only* (excluding the raw JD text that each record carries —
an earlier triage pass was confounded by exactly that; noted as a lesson in tooling rigor):

- "Working Student Project & Pr…" objective: *"leveraging **powerpoint, excel and azure devops**"*
- "Intern Sales & Client Success" projects: *"financial forecasts in **excel**"*, skills `vba, ms excel`
- "Working Student (m/f/d)": *"**sap** testing, **crm** data analysis"*; project *"reducing preparation time by **30 percent**"*
- "Working Student (part-time) Software QA": *"coordinated defects in **jira**, reducing regression testing time by 20%"*
- "Working Student: AI Engineer": project claims *"**gcp**, **cloud run**, **ci/cd**"*

**~9.6 unlicensed tool claims per job.** Root cause is now undeniable: the projects prompt
*instructs* the model to mirror the posting's tools. Any JD mentioning Excel/SAP/Jira/Docker
produces projects claiming them. The "invented projects" finding of V1 is not an occasional hazard —
**the fabrication mechanism is the prompt design working exactly as written**, roughly one unlicensed
claim family per job, invisible until a recruiter asks "tell me about your SAP testing."

### 2c. The digit rule's evasion hole (found by trying to break my own rule)
V2/V5's rule "every digit must be KB-licensed" caught "30%", "20%", "18%" — but missed
***"thirty percent" spelled out*** in a shipped project description. Concrete patch: the digit rule
must also map spelled-out numbers (thirty/twenty/five…) through the same check. Small fix, but it
demonstrates the method: every validator gets adversarially probed *before* it ships.

## 3. JD-analyst prototype: viable, with three measured weaknesses

One real call per language on the current run's JDs (`gpt-oss:120b`, temperature 0.1, strict-JSON
prompt):

| Metric | English JD (HRIS) | German JD (AI Engineer) |
|---|---|---|
| Latency | 5.6 s | 5.3 s |
| Valid JSON | ✅ | ✅ |
| Schema-complete | ✅ | ✅ |
| Tools found | `rexx` (!) | `Python, GCP, Cloud Run, CI/CD, Docker` |
| Domain | Human Resources | Artificial Intelligence |

- ✅ **Feasible:** 5.4 s/call fits the serial free tier; strict JSON worked first try, twice; it
  found `rexx` — a tool no English lexicon would contain — proving the LLM-analyst floor is needed
  alongside the lexicon (V5 §2's conclusion, now demonstrated).
- ⚠️ **Weakness 1:** missed a stated language requirement ("ideally english and german") on the
  English JD — `languages_required: []`. Patch: dedicated instruction + one worked example.
- ⚠️ **Weakness 2:** `preferred` came back empty both times — the model cannot distinguish tiers
  from prose alone without explicit guidance.
- ⚠️ **Weakness 3:** `required` items are full sentences (21 items on one JD) — needs a "≤4 words
  per item, verbatim terms" constraint for the coverage scorer to consume.

## 4. What this round settles (beyond all prior rounds)

1. **The verifier is real and buildable now** — fully deterministic, <1 s/job, and it catches 294
   concrete defects across the current 21 jobs with a triaged true-positive rate (201/201 sampled
   G2 hits confirmed true after FP probing).
2. **The KB redesign is not "hardening" — it is the only thing between the current pipeline and
   systematic fabrication.** Every non-tech-adjacent job shipped invented tool claims because the
   prompt mandates mirroring. The verification result reframes priority #3 (KB + digit rule +
   claimable-set generation) as **the** central fix, not one of several.
3. **The analyst call is validated at prototype level** (2/2 JSON, 5.4 s, finds lexicon-invisible
   tools) with a concrete 3-point prompt patch list.
4. **Tooling lesson (method, not code):** two of this round's intermediate conclusions were wrong
   until context-corrected (the `rest` FP scare; the confounded first triage that read JD text as
   claims). Verification of the verifier — with provenance discipline (generated fields ≠ stored JD
   text) — is what turned 294 raw findings into 294 defensible ones.

## 5. Final consolidated order (nothing further needs research to start)

| # | Item | Evidence status |
|---|---|---|
| 1 | Placeholder-collision fix + `PROJECT-` assert (V4) | 21/21 affected; fix known |
| 2 | 4 validated template fixes (V4 §1) | A/B-proven on this toolchain |
| 3 | **KB + claimable-set generation + digit rule incl. spelled-out numbers** (V6 §2b/2c) | **294 baked-off findings; systemic fabrication proven** |
| 4 | Gate suite as permanent step-5 regression (`verify_all.py` → pipeline) | prototype already catches everything |
| 5 | Coverage scorer (V5 §2) + analyst call with 3-point patch (V6 §3) | both prototyped on real data |
| 6 | Lebenslauf variant (V4: 7/21 German JDs) | quantified |
| — | ~~e5 semantic scoring~~ | rejected by measurement (V5) |

Every remaining item is now implementation, not research: the design contains no unmeasured
load-bearing claims, and both the verifier and the analyst exist as working prototype code in this
folder.

*Reproduction: `python resume_content_improve_research/experiment/verify_all.py` and
`.../analyst_prototype.py` (2 LLM calls, ~11 s total). Prior reports V1–V5 remain in force where
not superseded.*
