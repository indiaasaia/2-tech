# ATS Research Report V7 — Constrained Generation, Tested: The Honesty/Coverage Trade-off, Measured

**Relationship to V1–V6:** V6 proved fabrication is systemic (~9.6 unlicensed tool claims/job) and
proposed the fix: claimable-set generation + gates. V7 (this) **built that fix as a working
mini-pipeline** (analyst → claimable set → constrained generation → gates) and ran it end-to-end on
two real jobs (one English, one German) with the same model, measuring the three things that matter:
fabrication rate, coverage cost, and where prompt constraints alone fail.

**Artifacts:** `experiment/mini_pipeline.py` + `mini_pipeline_results.json` (full generated outputs,
gate findings, coverage per job). Reused: `verify_all.py` gates, `analyst_prototype.py`.

---

## 1. The experiment

End-to-end, 4 LLM calls total (2 analyst + 2 generation), ~26 s wall-clock on the serial free tier:
1. **Analyst** (patched prompt from V6) on two real JDs
2. **Claimable set** = KB skills ∪ JD tools (mirrorable, never ownable) + required/preferred terms
3. **Constrained generation** — one call producing objective + skills + both *real* projects, with
   explicit rules: only listed tools mentionable; projects must be the two real ones; no percentages;
   JD tools only in "targeting" framing
4. **Gates** — the V6 suite incl. the spelled-out-number patch, plus an invented-title check

## 2. Result 1 — fabrication: reduced ~4× but NOT eliminated by prompting alone

| Job | Unlicensed claims (current pipeline) | Gate findings (constrained, first attempt) |
|---|---|---|
| English (HRIS) | ~9.6 avg (V6) | **5** — `rexx` claimed as *"strong expertise in Python, SQL, and rexx"*, `hris`, `api` |
| German (AI Engineer) | ~9.6 avg (V6) | **2** — `gcp` claimed twice despite Cloud Run being JD-tool-only |

**Conclusion:** explicit constraints cut violations from systemic to residual, but the model *still*
converts "tools the job wants" into "tools I have" on first attempt — the exact bias the prompt
fights. **Therefore the architecture must be gate → regenerate, not trust-the-prompt**: the
deterministic gate is load-bearing, the prompt is only the first attempt. This validates the V6 loop
design and kills any "just write a better prompt" shortcut — measured, not argued.

## 3. Result 2 — the honesty/coverage trade-off, now quantified

| Metric | Current pipeline | Constrained prototype |
|---|---|---|
| Coverage (JD required+tools present in output) | **0.73** (V5, artifact) | **0.27** (EN) / **0.54** (DE) |

This is the round's central insight: **the current pipeline's 0.73 coverage is partly purchased with
fabrication.** Honest generation drops coverage by 0.2–0.45. The missing terms after constraining are
exactly the tools the candidate genuinely lacks (`cloud run`, `llm-as-judge`, `mcp`, `dashboards`,
`rexx`, HR-process terms). Three consequences:

1. **Coverage targets must be recalibrated** — chasing 0.7+ honest coverage via generation pressure
   would just re-create fabrication. The honest ceiling is set by the *KB*, not the prompt.
2. **The lever for honest coverage is KB expansion** (licensing more *real* skills: the candidate's
   actual coursework tools, genuinely-used libraries, certifications) plus surface-form mirroring of
   KB-licensed items only (e.g., resume says "SQL", JD says "database management" — alias map bridges).
3. **For genuinely-missing requirements, the correct output is a *gap report*, not a fabricated
   claim** — surfaced to the user (learn it / skip the job), never into the resume.

## 4. Result 3 — prompt patches alone failed on the analyst too

The V6-patched analyst (explicit language-requirement rule) **still returned `languages_required: []`
on both JDs** — including the one whose text says "ideally english and german". Measured lesson:
instruction-following at extraction is as unreliable as at generation. The analyst output therefore
also needs **deterministic enforcement**: regex sweep of the JD for language patterns
(english|german|deutsch|fließend|B2|C1…) → if found and absent from the JSON, force-insert + flag.
Same philosophy as the generation gates: LLM proposes, deterministic code disposes.

## 5. Consolidated architecture (final, every element measured in V1–V7)

```
JD → [analyst LLM, 1 call] → deterministic post-check (languages, tools, tiers)
   → claimable set (KB ∪ JD-tools-mirrorable)
   → [generator LLM, 1–3 calls, real projects + licensed skills only]
   → deterministic gates (tech ⊆ KB, digits incl. spelled-out, project titles, placeholders)
   → regenerate-with-violations if gates fail (≤2 iterations)      ← V7 §2: mandatory, not optional
   → coverage vs recalibrated targets + gap report to user          ← V7 §3: honest ceiling
   → template fixes + artifact parse gate (V4/V5) → PDF/DOCX
```

Measured parameter set: analyst ~5 s, generation ~7–9 s, gates <1 s; 3–5 LLM calls/job total;
serial free-tier feasible (~4 min per 20-job run including everything deterministic).

## 6. Research status: complete

Across seven rounds, every load-bearing component is now either **validated by artifact**
(parser fixes: V4 A/B), **rejected by measurement** (e5 scoring: V5; truncation worry: V4),
**prototyped working** (gates: V6; constrained pipeline: V7), or **quantified as a trade-off with a
policy** (coverage honesty: this round). No remaining claim rests on assumption. The implementation
order from V6 stands, with two V7 amendments: the gate→regenerate loop is *mandatory* (first-attempt
constraint violations measured), and the analyst needs a deterministic post-check (patch prompts
measured insufficient).

*Reproduce: `python resume_content_improve_research/experiment/mini_pipeline.py` (4 LLM calls,
~26 s). Prior reports V1–V6 remain in force where not superseded.*
