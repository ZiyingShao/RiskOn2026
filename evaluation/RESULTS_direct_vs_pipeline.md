# Raw rows → LLM  vs.  brief → IR → solver

The question this answers: *why build a compiler at all — why not just show the
model the data and ask?*

**Setup.** Identical inventory rows, identical constraints, identical model
(Claude Haiku 4.5 — the same one that scores 100% first-pass through our
pipeline). Only the scaffolding differs:

- **Direct**: the actual rows are dumped into the prompt
  (`id,carat,cut,clarity,price,volume` — 800 lines, 25 KB) and the model is
  asked to return the selected stone ids and the totals.
- **Pipeline**: the model never sees a row. It emits an IR; `bind` loads the
  data; HiGHS solves it.

**Ground truth is not an opinion**: it is the MILP optimum over exactly those
rows, proven optimal by the solver.

Reproduce: `python direct_baseline.py build|truth`, then `python direct_report.py`.

## The real problem — 800 rows, 6 constraints

Solver optimum: **57.970 carats**.

| run | claims | actual | arithmetic error | feasible? | gap vs optimum |
|---|---|---|---|---|---|
| direct, run 0 | 35.07 | 34.23 | **+0.84 ct overstated** | yes | **−41.0%** |
| direct, run 1 | 50.78 | 51.18 | −0.40 ct | **NO** — Ideal cut at 40% vs 30% cap | −11.7% |
| direct, run 2 | 32.33 | 33.40 | −1.07 ct | **NO** — Ideal cut at 31.7% vs 30% cap | −42.4% |
| **pipeline** | **57.970** | **57.970** | **0** | **yes, by construction** | **0.0% (proven optimal)** |

Same numbers as a jeweler reads them:

| | carats | stones | capital deployed | max cut share | carats forgone |
|---|---|---|---|---|---|
| pipeline | 57.97 | 60 | CHF 249,521 of 250,000 | 26.7% ✓ | — |
| direct r0 | 34.23 | 60 | CHF 106,299 | 26.7% ✓ | **23.74** |
| direct r1 | 51.18 | 60 | CHF 241,027 | **40.0% ✗** | 6.79 |
| direct r2 | 33.40 | 60 | CHF 108,420 | **31.7% ✗** | 24.57 |

Two runs left **more than half the credit line unspent** while filling every
display slot — they used up the scarce resource (slots) on small stones and
stopped, with no notion that the budget was slack. The one run that came close
on carats got there by **breaking the concentration limit** — the constraint
that exists precisely to stop the buyer over-indexing on one cut grade.

## The easy control — 60 rows, 4 constraints

If the failure were just context length, a tiny instance should be safe. It isn't.
Solver optimum: **7.300 carats** from 12 stones.

| run | claims | actual | arithmetic error | feasible? | gap |
|---|---|---|---|---|---|
| direct (Haiku) r0 | 6.53 | 6.53 | −0.00 | yes | −10.5% |
| direct (Haiku) r1 | 5.25 | 4.95 | **+0.30 ct overstated** | yes | −32.2% |
| direct (Haiku) r2 | 6.31 | 6.30 | +0.01 | yes | −13.7% |
| direct (Sonnet) | 7.13 | 7.13 | +0.00 | yes | −2.3% |
| **pipeline** | **7.300** | **7.300** | **0** | **yes** | **0.0%** |

Sixty rows, twelve stones to add up, all of it visible — and one run still
misreported its own total by 0.30 carats (6% of its answer). A stronger model
(Sonnet) closes most of the optimality gap but **still does not reach the
optimum**, and it cannot certify that it has.

## What this shows

1. **The answer is confident and wrong.** Every direct run returned clean JSON
   with a stone list and a total. Nothing in the output signals that it is
   41% below optimal or violating a constraint — it looks exactly like a
   solution.
2. **It cannot add its own selection.** Claimed totals disagreed with the
   stones actually chosen in 5 of 7 runs, twice in the flattering direction.
   The number a human would read off the summary is not the number the
   portfolio delivers.
3. **Constraints are suggestions.** 2 of 3 runs on the real problem silently
   breached the cut-concentration cap. No error, no flag.
4. **Scale is not the fix.** The gap shrinks with a stronger model (−2.3%)
   but never reaches zero, and the strong model still offers no proof.
5. **The pipeline is exact, feasible, and certified** — and additionally
   returns *why*: binding constraints and shadow prices ("one more display
   slot is worth 0.0096 carats"), which no direct answer can produce.

The division of labour is the point: **the LLM is good at reading a sentence
and deciding it means a constraint; it is bad at arithmetic over 800 rows.**
So let it do the translation, and let a solver do the optimisation.
