# Generalizing across tracks: Track B (vault) and Track C (dispatch)

## The finding that drove the design

Handed a Track C assignment model, the original pipeline did this:

```
checkpoint 1 (shape):  PASSES — a 2-D var index is legal
checkpoint 2 (meaning): PASSES — 0 errors
checkpoint 3 (bind):   PASSES — sets built
compile:               *** KeyError: "Index '0' is not valid for component 'y'"
```

All three checkpoints green, then a raw crash — the same blind spot as a
dropped constraint, in a new place. The cause was precise: `_expr` subscripted
a variable as `v[i]`, one index only. A 2-D assignment variable `y[task,
driver]` could be **declared** but never **used**.

So the generalization is not "pick a different solver" — both tracks are MILPs
and HiGHS solves both. It is that **the expression grammar was 1-D**.

## What changed (four small things, not a rewrite)

| change | why Track C needs it |
|---|---|
| `SetDef.kind: "literal"` with `members` | the driver pool is not in the data — assignment needs a second axis the CSV does not contain |
| `Term.over` accepts a **list** of `IndexRef`, one per variable dimension | `sum over (task, driver)` |
| `IndexRef.bind: "$SET"` | pins one axis to the `forall` value: "for THIS driver, over their own tasks" |
| `TableSpec.filter` + `parse_datetime` | "ingest an operational time slice" from a log; scheduling needs numbers, not timestamp strings |

Backwards compatible: a bare `IndexRef` still means 1-D, so every Track B spec,
every reference IR, and all 175 stored eval attempts run unchanged and produce
byte-identical results (57.970 carats, same shadow prices).

New guard rails, both learned from the crash above:

- **`ARITY_MISMATCH`** at checkpoint 2 — the axis count must match the variable's
  declared dimensions. The KeyError above is now a checkpoint-2 error with the
  fix spelled out.
- **`CONSTANT_INFEASIBLE`** at compile — an instance with no variable in it that
  is *false* is a data/model contradiction. One that is *true* (an idle time
  slot) is skipped silently, because rejecting it would reject a correct model.

## No-overlap without big-M

"No driver receives overlapping schedules" is written as slot occupancy:

```
forall (DRIVER d, SLOT t):   sum over { tasks i : start_i <= t < end_i }  y[i,d]  <=  1
```

Two subtleties, both found by verifying the produced schedule rather than
trusting the objective:

1. **A fixed time grid is wrong**, not merely coarse: two trips can overlap by
   less than one slot and share no grid point. The slot set is therefore the
   distinct **task start times** (`categories` over `pickup_min`) — if two
   intervals overlap, one begins inside the other, so checking at starts is
   exact. Bonus: 25 slots instead of 120.
2. **One origin per table when parsing timestamps.** Normalising `pickup` and
   `dropoff` each against its own minimum put them on different timelines and
   produced trips with `dropoff_min < pickup_min` — impossible schedules that
   inflated revenue from the true $282.80 to a fictional $447.01.

The second one is worth dwelling on: the model was *infeasible in reality* but
*optimal on paper*, and no checkpoint could see it. Only re-deriving the
schedule and testing pairwise overlap caught it.

## Scenario detection and routing (`scenarios.py`)

`classify(spec)` reads the **compiled structure**, not the prose, and reports
its evidence:

```
scenario: SELECTION                          scenario: SCHEDULING
  because: a single 1-D binary variable        because: a 2-D decision variable — pairs
  because: a share bound (rhs is a               because: an 'at most one per row' constraint
           fraction of the same variable)       because: a time-window predicate (start <= t < end)
  USING appsi_highs: knapsack-style models     skip  cp_sat: CP-SAT propagates no-overlap
        are its bread and butter                     natively  (not installed)
                                               USING appsi_highs: time-indexed MILP
```

`route()` walks an ordered preference list per archetype and takes the first
**available** backend, so a missing specialist degrades to HiGHS instead of
failing. The honest note: today only the Pyomo backends are wired in; when the
router picks `cp_sat` it says so and falls back out loud rather than pretending.

Where a specialist genuinely earns its place:
- **scheduling** → CP-SAT (`AddNoOverlap` propagates; time-indexed MILP grows with
  the horizon)
- **pure assignment** → network simplex (the assignment polytope is integral)
- everything else → HiGHS

## Both tracks, one pipeline

```bash
python run.py vault_stocking.json      # SELECTION  → 57.970 carats, 60 of 800 stones
python make_track_c.py && python run.py track_c_dispatch.json   # SCHEDULING → $282.80, 9 of 25 requests
```

Verified for Track C: no driver has overlapping trips, every duration is
positive, and passenger counts respect the vehicle limit.

## What a third track would need

Nothing, if it is selection, assignment, covering, or blending over table rows.
The grammar still does **not** cover: products of variables (non-linear),
hand-written big-M disjunctions, or flow conservation over arcs — that last one
needs a genuine `pairs` set kind (an edge list), which is the next extension if
a routing/network track appears.
