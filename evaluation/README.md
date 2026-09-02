# Evaluation

A defensible evaluation of the brief → IR translation pipeline, with no
external ground truth and **no LLM judging correctness** — the grader is a
deterministic structural comparison against hand-written reference IRs.

## Four measurements

1. **Translation fidelity — structural** (`fingerprint.py`).
   Each constraint of the generated and reference IR is compiled **alone**
   into its coefficient rows over the bound data; rows are canonicalized
   (sides merged, `>=` negated into `<=`, scaled by max |coef|, variable
   names replaced by signatures) and hashed. Two constraints producing the
   same row are the same constraint regardless of naming.
   `recall` = reference rows with a generated counterpart (1 − missed);
   `precision` = generated rows with a reference counterpart (1 − invented).
   Invariance is proven by `test_fingerprint.py` (rename + rescale + side-swap
   + relation-flip ⇒ identical fingerprint; a loosened cap ⇒ detected).

2. **Translation fidelity — semantic** (`semantic.py`).
   Does every obligation sentence of the brief have a `source_text` pointing
   at it? Matching is deterministic token-Jaccard (≥ 0.25). Sentences with no
   pointer are dropped constraints.

3. **Solution equivalence** (`solution.py`).
   Solve both IRs on identical data (path/sample/seed normalized before
   binding). Objectives within 1e-6 relative ⇒ the models agree. A **higher**
   generated objective is the dangerous direction (missing/loosened
   constraint). For the infeasible brief: both must be infeasible AND the
   elastic diagnosis must name the offending sentence.

4. **Resilience** (`check_attempts.py` + `aggregate.py`).
   Produced by the validator for free, per run:
   first-pass validity (all three checkpoints, no repair) · repairs to
   convergence · repair success rate · error-code histogram. Repairs are
   stateless: the repairer sees the task, its previous answer, and the
   checkpoint errors verbatim (`IRError.fix` included).

## Perturbation set (`briefs.py`)

| brief | probe |
|---|---|
| `base` | control — matches the few-shot example |
| `cap25` | 30% → 25%: does the number track? |
| `small_stones` | new constraint family not in the example |
| `no_volume` | volume limit removed — the overfitting probe: does it leak back in from the example? |
| `renamed_budget` | budget renamed to a "CHF 400,000 facility" |
| `infeasible` | 80 stones × 8 clarity grades > 60 slots: does the diagnosis fire? |
| `contradiction` | 30% cap early, 20% cap late: notice, or silently pick one? |

References live in `references/` (built by `make_references.py`, each pushed
through all three checkpoints; the contradiction brief deliberately has none).

## How the runs were produced

The measured generator is **Claude Haiku 4.5**, one fresh model instance per
(brief × run) with an identical prompt (`prompts/<brief>.md`: grammar + rules
+ one worked example — the base brief with its reference IR). In the original
session the samples were produced by disposable Haiku subagents (the session
had no CLI/API credential for a standalone generator); `generate_cli.py` is
the equivalent standalone driver for a logged-in machine. Current Claude
models take no temperature parameter — variance comes from default sampling.

## Reproduce

```bash
cd evaluation
python make_references.py        # build + verify reference IRs
python make_prompts.py           # build generation prompts
python test_fingerprint.py       # prove the matcher's invariances
python generate_cli.py 20        # 20 samples x 7 briefs (needs `claude` login)
python check_attempts.py         # score attempts, emit repair tasks
python aggregate.py              # -> results/summary.json
```

(Dependencies: pandas, pydantic, pyomo, highspy — e.g.
`uv run --with pandas --with pydantic --with pyomo --with highspy python ...`)

## Results

Two conditions, generator = Claude Haiku 4.5, one fresh instance per run.
Raw per-run records in `results/` (main) and `results_ablation/` (no example).

**Main condition — prompt with one worked example (20 runs x 7 briefs = 140):**

| metric | value |
|---|---|
| first-pass validity rate | **140/140 (100%)** |
| mean repairs to convergence | 0 |
| repair success rate | 100% |
| structural recall / precision vs reference | 1.000 / 1.000 (all 120 reference-comparable runs) |
| objective fingerprint match | 120/120 |
| semantic coverage (source_text ⇢ brief sentence) | 100% |
| solve agreement rate | **120/120**, zero dangerous (too-high) gaps |
| `no_volume` overfitting probe | **0/20 leaked** the example's volume constraint |
| `infeasible` diagnosis | 20/20 infeasible AND elastic diagnosis names the clarity sentence |
| `contradiction` (30% early, 20% late) | **19/20 silently encoded both caps** (stricter wins), 1/20 picked 20%; **0/20 flagged the conflict** |

The error histogram is empty — with the worked example the validator never
fires. That is a ceiling, not proof of resilience, hence:

**Ablation — same grammar and rules, NO worked example (5 runs x 7 briefs = 35):**

| metric | value |
|---|---|
| first-pass validity rate | **22/35 (63%)** |
| converged after one repair round | 30/35 (86%), mean 0.27 repairs |
| unresolved | 5/35 (the run was cut off by an account spend limit after one repair round; the harness allows three) |
| error histogram | `UNKNOWN_PARAM` 10 · `EMPTY_EXPR` 9 · `SCALAR_VAR` 6 · `UNBOUND_INDEX` 1 — **all caught at checkpoint 2**, none survived to bind or solve |
| solve agreement of everything that converged | **100%** — every IR that passes the three checkpoints solves to the reference optimum |

The slide sentence the histogram buys: *the few-shot example is worth 37
points of first-pass validity; every failure it prevents is a checkpoint-2
`meaning` error, and one verbatim-error repair round fixes 62% of them —
and nothing that passes the validator has ever disagreed with the reference
solution.*

Known limits: the contradiction probe shows the generator resolves conflicts
silently (encoding both bounds) rather than flagging them — a repair-loop
`source_text` conflict check would surface this; and `structurally identical`
is judged on one fixed 800-row sample (n=800, seed=7), as designed.
