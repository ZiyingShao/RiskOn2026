# Can the agent generate IR for all three archetypes?

The compiler was generalized first (selection / assignment / scheduling); this
measures whether the **generator** can actually produce those models. It could
not before: `make_prompts.py` documents only the 1-D grammar, so an LLM reading
it had no way to know a 2-D assignment variable exists.

New: `grammar.py` (the full grammar + the three shape patterns, as prompt text),
`make_prompts_multi.py`, a Track C brief and reference, and `score_generated.py`
— a scorer with no Track-B-specific normalization.

Two conditions, so the result cannot be explained by copying:

| condition | examples shown | question |
|---|---|---|
| `prompts_multi/` | a selection IR **and** an assignment IR from a *different* instance (8 drivers, 4-hour window) | realistic deployment |
| `prompts_heldout/` | **only selection IRs** | can it build an assignment model from the grammar documentation alone? |

No brief is ever shown its own reference.

## Track C generation — reference optimum $282.80

| run | reached | objective | == optimum | recall | precision | semantic |
|---|---|---|---|---|---|---|
| heldout r0 | solved | 282.80 | **yes** | 0.833 | 0.556 | 1.000 |
| heldout r1 | solved | 282.80 | **yes** | 1.000 | 1.000 | 1.000 |
| heldout Sonnet | solved | 282.80 | **yes** | 1.000 | 1.000 | 1.000 |
| multi r0/r1/r2 | solved | 282.80 | **yes** | 1.000 | 1.000 | 1.000 |

**6 of 6 passed all three checkpoints and solved to the exact optimum**, and the
held-out runs did it having never seen an assignment model — inventing the 2-D
variable, the literal driver pool, `parse_datetime`, and the event-time
occupancy constraint from the documentation.

Schedules were verified, not assumed: for `heldout_r0`, `heldout_sonnet` and
`multi_r0`, no driver has overlapping trips and no vehicle exceeds four seats.

### The one imperfect score is the grader's limitation, not the model's

`heldout_r0` wrote capacity **per driver-minute** — "a driver never carries more
than four passengers at any instant" — instead of per task:

```json
{"name": "passenger_capacity", "forall": ["DRIVER", "SLOT"],
 "lhs": {"terms": [{"var": "y", "weight": "passengers", "over": [
     {"set": "REQUEST", "where": [{"column": "pickup_min", "op": "lte", "value": "$SLOT"},
                                  {"column": "dropoff_min", "op": "gt",  "value": "$SLOT"}]},
     {"set": "DRIVER", "bind": "$DRIVER"}]}]},
 "rel": "<=", "rhs": {"const": 4.0}}
```

Given no-overlap the two are equivalent, and this is arguably the more literal
reading of the sentence. It still reached the optimum. **Structural recall
measures "same coefficient rows", which is stricter than "same feasible set"** —
so a legitimate alternative formulation is scored as a miss. That is a known and
acceptable conservatism: it never passes a wrong model, it occasionally fails a
right one, and solve-agreement is the check that resolves the disagreement.

## Does the assignment example corrupt Track B?

Carrying two examples risks the model reaching for the wrong template. It did not:

| run | objective | == optimum | recall | precision |
|---|---|---|---|---|
| base r0 / r1 | 57.97 | yes | 1.000 | 1.000 |
| vague_case r0 / r1 | 57.97 | yes | 1.000 | 1.000 |

No dispatch machinery leaked into a vault model.

## The `vague_case` probe, run for the first time

`vague_case` is the brief where **one sentence must become two constraints** —
"the display case has 60 slots and about 9,000 cubic millimetres of usable
space" — and the volume one needs a derived `x*y*z` column that does not exist.
This is exactly the failure class no checkpoint can see: a dropped constraint
has no error code.

**Both runs scored recall 1.000.** The model split the sentence into a slot
count and a volume cap, quoted it twice, and derived the missing column. On this
probe, with this grammar documentation, the modelling failure did not appear.

Two honest caveats: n=2 is a demonstration, not a rate; and the prompt's RULES
section explicitly warns that one sentence may imply more than one constraint,
so this measures the agent *with that instruction*, not a bare model.

## Reproduce

```bash
python make_prompts_multi.py                       # build both prompt sets
python score_generated.py results_gen_c dispatch   # Track C generations
python score_generated.py results_gen_b base       # Track B leakage check
```
