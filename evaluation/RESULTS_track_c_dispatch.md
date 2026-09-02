# Track C: raw rows → LLM vs. brief → IR → solver

Same experiment as Track B, on the dispatch problem. Ground truth is the MILP
optimum over exactly the rows the model sees. The prompt is deliberately
**charitable**: pickup/dropoff are pre-converted to minutes, so no timestamp
parsing is required — the task is purely the optimisation.

**The headline result is not the one Track B produced, and that matters.**

## Small instance — 25 requests, 4 drivers

Solver optimum: **$282.80** (9 requests served; $547.87 was on the table).

| run | claims | actual | arith err | served | overlaps | feasible | gap |
|---|---|---|---|---|---|---|---|
| Haiku r0 | 269.85 | 269.85 | 0.00 | 8 | 0 | yes | −4.6% |
| Haiku r1 | 282.80 | 282.80 | 0.00 | 9 | 0 | yes | **0.0%** |
| Haiku r2 | 282.80 | 282.80 | 0.00 | 9 | 0 | yes | **0.0%** |
| Sonnet r0 | 282.80 | 282.80 | 0.00 | 9 | 0 | yes | **0.0%** |
| Sonnet r1 | 282.80 | 282.80 | 0.00 | 9 | 0 | yes | **0.0%** |
| **pipeline** | 282.80 | 282.80 | 0.00 | 9 | 0 | yes | **0.0%** |

**Four of five direct runs found the exact optimum.** No arithmetic errors, no
overlapping schedules, no capacity breaches. On this instance the direct
approach is genuinely competitive, and reporting otherwise would be dishonest.

Why: with 25 mostly-long trips over a ~79-minute horizon and only 4 drivers,
capacity is so tight that the optimum serves just **9 of 25** requests. Greedy
by revenue lands on or near the optimum. The instance looks like scheduling but
is barely combinatorial.

## Large instance — 74 requests, 8 drivers

Solver optimum: **$1,072.44** (63 requests served; $1,223.46 on the table).
Same brief, same constraints, 592 binary decisions instead of 100.

| run | claims | actual | arith err | served | overlaps | feasible | gap |
|---|---|---|---|---|---|---|---|
| Haiku r0 | 627.05 | 627.05 | 0.00 | 25 | 0 | yes | **−41.5%** |
| Haiku r1 | 658.34 | 658.34 | 0.00 | 25 | 0 | yes | **−38.6%** |
| Haiku r2 | 494.80 | 494.80 | 0.00 | 22 | 0 | yes | **−53.9%** |
| Sonnet r1 | 1062.85 | 1062.85 | 0.00 | 61 | 0 | yes | −0.9% |
| **pipeline** | **1072.44** | **1072.44** | **0.00** | **63** | **0** | **yes** | **0.0%** |

The small-model answers collapse: **22–25 requests served where 63 are
servable**, leaving most of the fleet idle for most of the shift. Every answer
is *feasible and internally consistent* — it just quietly forgoes 40–54% of the
achievable revenue, and nothing in the JSON says so.

## What actually distinguishes the two tracks

| | Track B (diamonds, 800 rows) | Track C small (25) | Track C large (74) |
|---|---|---|---|
| arithmetic errors | **5 of 7 runs** | none | none |
| constraint violations | **2 of 3 runs** | none | none |
| optimality gap | −11.7% to −42.4% | 0% (4/5) | −38.6% to −53.9% (Haiku) |

Three distinct failure modes, and they do not travel together:

1. **Arithmetic hallucination** appears when there are many numbers to add
   (60 stones), not when there are few (9 trips).
2. **Constraint violation** appears when the constraints are *entangled*
   (a share cap over categories) rather than *checkable locally* (does this
   trip overlap the previous one for this driver).
3. **Optimality collapse** appears with combinatorial room — and it is the one
   failure that survives everywhere. It scales with instance size, and it is
   the one a reader cannot detect.

## The conclusion, stated carefully

The direct approach is not uniformly bad; on a small, tightly-constrained
instance it matched the solver exactly. The problem is that **you cannot tell
from the output which regime you are in.** Every answer above — the four
optimal ones, the one 0.9% off, and the three that burned half the revenue —
arrives as the same confident JSON. The 25-request and 74-request answers are
indistinguishable in form.

That is the argument for the compiler, and it is a different argument from
"LLMs can't do maths":

- **Same answer every time.** The pipeline returned $282.80 and $1,072.44
  deterministically; the direct runs ranged over a 15-point spread on one
  instance and a 53-point spread on the other.
- **A certificate.** HiGHS proves no better assignment exists. Four correct
  direct runs cannot tell you they are correct, and the fifth was wrong.
- **It degrades gracefully with size.** The direct gap grew from 0% to −54%
  between two instances of the *same problem*; the pipeline's did not move.
- **It explains itself.** Binding constraints and shadow prices — a ninth
  driver-minute is worth $14.80 on the large instance — which no direct answer
  produces.

Stronger models narrow the gap (Sonnet: −0.9%) but do not close it and cannot
certify it. Buying a bigger model buys you a better guess; the solver ends the
guessing.

Reproduce: `python direct_dispatch.py build|truth|report [small|large]`.
One run (`dispatch_lg_sonnet_r0`) is missing — the account hit its spend limit
mid-batch, so the strong-model column on the large instance is n=1.
