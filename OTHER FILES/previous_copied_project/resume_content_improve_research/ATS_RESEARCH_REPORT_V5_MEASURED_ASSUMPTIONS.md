# ATS Research Report V5 — Assumptions Tested: One Design Rejected, One Confirmed

**Relationship to V1–V4:** V4 validated the template fixes. V5 (this) tests the *remaining
unvalidated assumptions* in the proposed architecture — specifically the semantic-matching layer
(V2 §C6, carried through V3/V4 as "P2") and the coverage scorer (V2 §C3). Both were tested against
real data on this machine. **One is rejected by measurement; one is confirmed with a discovered
blind spot.** All numbers below are reproducible from the commands shown.

---

## 1. Experiment A — the semantic layer (V2 C6): REJECTED by measurement

V2 specified: e5-small cosine ≥ τ_sem = 0.72 → "semantically covered." That τ was a guess. Tested
with `intfloat/multilingual-e5-small` (proper `query:`/`passage:` prefixes, normalized embeddings):

### Short phrases (the exact usage V2 proposed)

| Pair | Cosine |
|---|---|
| Kubernetes ↔ container orchestration | 0.840 |
| MySQL ↔ data management | 0.842 |
| Kubernetes ↔ K8s | 0.843 |
| **Kubernetes ↔ cooking recipes** | **0.818** |
| SQL ↔ graphic design | 0.802 |
| Python ↔ Java | 0.809 |

**The entire useful range is compressed into 0.80–0.84.** Unrelated pairs score 0.80–0.82 — *above*
V2's 0.72 threshold. Every pair in the universe would be "covered." The threshold isn't tunable;
the *measurement itself* is degenerate for short phrases.

### Sentence level (attempted rescue)

Requirement-sentence ↔ evidence-sentence: positives 0.840–0.868, negatives 0.810–0.825 — a **~0.03
separation margin**. No stable threshold exists in that band; different domains will invert it.

### Cross-encoder reranker (`ms-marco-MiniLM-L-6-v2`)

Ranking works: true matches −4.6…−6.4 vs non-matches −10.5…−11.4 (clean ~5-point margin, every
ordering correct). **But** raw scores are uncalibrated (sigmoid ≈ 0.01 — nothing is above 0), and on
the sufficiency test it fails the way any retriever must: "German B2 required" vs "German A2" ranks
as *relevant* (−5.1) — relevance ≠ qualification. A reranker can order candidates; it cannot certify
that a requirement is *met*.

### Verdict (this is a real design reversal)

- **Kill** the e5 "semantic coverage" component (V2 C6's thresholded matrix) — measured degenerate.
- **Keep** semantic only as **ranked suggestions**: given a missing requirement, use the cross-encoder
  to find the best existing resume line (if any) that a *human or LLM* can then judge. Absolute
  similarity thresholds are banned from the scoring system.
- **Consequence for weights (V2 C7):** the 20% "semantic requirement match" weight is redistributed —
  primarily to exact/taxonomy coverage (which is deterministic and honest) and to the JD-analyst
  quality. Scoring gets *simpler* and more defensible.
- **Synonym handling** (K8s↔Kubernetes, ML↔Machine Learning) must come from the **alias/ESCO map**
  (deterministic), which never misfires — not from embeddings, which demonstrably do.

## 2. Experiment B — the coverage scorer (V2 C3): CONFIRMED, with a found blind spot

Ran a deterministic extractor (tech-term lexicon + capitalized-term filter, stopwords removed) over
all 21 real JDs, then measured coverage twice: against the **generation intent** (component JSONs)
and against the **parsed artifact** (pdfplumber text of the shipped PDFs).

### Results

- **Mean coverage: intent 0.72, artifact 0.73, gap +0.01** → what the model "meant" lands in the
  document; generation-to-artifact fidelity is essentially lossless for body keywords (the V3/V4
  corruption defects affect structure, not body tokens).
- Per-job spread: 6 jobs at 1.00, one QA job at 0.80 ("analytics" missing), the "automation" JD at
  0.00 — see blind spot below.
- Missing-keyword lists per job are exactly the actionable output the scorer was designed for.

### The blind spot my own extractor exposed (challenge applied to my own tool)

5 jobs scored 0.00–0.50 because their JDs are **German** and the lexicon is English-biased
("Kenntnisse", "Erfahrung" — terms don't match the tech list). This is a *property of the corpus*
(7/21 German, per V4's audit) hitting a *tool limitation*, and it quantifies the requirement: the
production scorer **cannot be English-lexicon-only**. Options measured against cost:
1. German+English lexicon merge (ESCO `skills_de.csv` — planned anyway) → deterministic, free.
2. One LLM analyst call per JD (V2 A6) → language-agnostic, but costs quota.
The design now requires **both**: lexicon as the floor, LLM analyst as the ceiling.

## 3. Experiment C — layout equivalence of the fixed template: confirmed, plus a new measurable defect

Original vs fixed PDF (V4's A/B artifacts):

| Metric | original | fixed |
|---|---|---|
| Pages | 2 | 2 |
| Chars extracted | 3,993 | 4,471 |
| **pdfplumber "words"** | **154** | **622** |

The word-count explosion is not growth in content — it is **broken word segmentation** in the
original: scshape corruption fuses letter runs so pdfplumber can't find spaces (154 giant "words";
section-title lookup returns *nothing*). The fixed version segments normally. **Add
word-count/segmentation sanity to the regression gate** — a healthy single-page resume must yield
~300–700 words; anything <200 indicates extraction corruption even when text "exists."

Section y-positions in the fixed version are stable (Objective 187, Experience 287, Education 482,
Skills 223) — no layout regression from the font change.

## 4. Consolidated, fully-measured priority list (V1–V5 combined)

| Rank | Item | Status |
|---|---|---|
| 1 | **Replacement-order bug fix + `PROJECT-` assert** (V4 §2) | proven defect in 21/21 PDFs; fix validated by inspection |
| 2 | **4 template fixes** (V4 §1) | **validated by A/B build** — exact LaTeX known |
| 3 | **Word-segmentation gate** (V5 §3) | new; joins the regression suite |
| 4 | **Coverage scorer** (V5 §2) | confirmed viable; needs DE+EN lexicon (ESCO) + LLM analyst |
| 5 | **KB + digit rule** (V4 §3-E: 35 fabricated metrics) | unchanged from V4 |
| 6 | JD analyst consolidation (V2 A6) | unchanged |
| 7 | Lebenslauf variant (7/21 German JDs) | unchanged |
| 8 | ~~e5 semantic coverage layer~~ | **REMOVED from the design (V5 §1)** — replaced by alias-map synonyms + cross-encoder *suggestions only* |

## 5. The scorecard spec, final form (all assumptions now either measured or removed)

```
GATES (fail = never ship):
  G1 parses; word-count 200–800/page (V5 §3); name/contact/sections extract intact
  G2 hallucination gate: tech tokens ⊆ KB; digits ∈ KB evidence (V2 C4, V4 §3-E)
  G3 no unfilled/collided placeholders ("PROJECT-" assert; V4 §2)

SCORE (0–100):
  40  required-keyword coverage  (exact + alias/ESCO-fuzzy; over parsed artifact)
  20  preferred-keyword coverage
  15  parse fidelity (fields exact vs intent)
  10  format checks (dates parse, reading order, section detection)
  10  experience relevance (LLM analyst verdict, 1 call)
   5  naturalness (critic verdict, sampled)
No embedding-similarity term exists. Ranking-suggestion output is advisory UI, not score input.
```

## 6. What "more concrete and effective" means after five rounds

The final architecture contains **zero unmeasured load-bearing claims**: every threshold is either
deterministic (exact/alias) or abolished (embeddings); every defect is reproduced with a script in
this folder; every fix is proven by A/B compile; the scoring model is smaller than V1 proposed
because two of its components (fabricated metrics, semantic layer) *died on contact with data*.
That is the deliverable: a shorter, proven, implementable design.

*Reproduction: Experiment A/B/C commands are embedded in this report's history and
`resume_content_improve_research/experiment/`; V3's `empirical_parser_test.py` remains the
regression instrument; all prior report sources remain in force where not superseded.*
