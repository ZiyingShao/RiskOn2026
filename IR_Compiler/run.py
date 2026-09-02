"""
run.py — the pipeline. Three checkpoints, split by what information exists at
that moment, then solve:

    1  shape    ModelSpec.model_validate(json)   generated from ir.py
    2  meaning  validate(spec)                   validate.py
    3  data     check_bound(bm)                  validate.py

Every checkpoint yields IRError objects, so a LangGraph edge back to the
generator can leave after 1, 2 or 3 carrying the same shape.
"""

import json
import sys

from pydantic import ValidationError

from ir import ModelSpec
from validate import IRError, BindError, validate, check_bound
from compiler import bind, compile_model, solve, diagnose_infeasible
from scenarios import describe, route

spec_path = sys.argv[1] if len(sys.argv) > 1 else "vault_stocking.json"
forced_solver = sys.argv[2] if len(sys.argv) > 2 else None      # e.g. cbc, glpk, gurobi


def fail(checkpoint: str, errs: list[IRError]) -> None:
    print(f"CHECKPOINT {checkpoint} FAILED")
    for e in errs:
        print("  ", e)
    sys.exit(1)


try:                                                             # checkpoint 1: shape
    spec = ModelSpec.model_validate(json.load(open(spec_path)))
except ValidationError as ve:
    fail("1 (shape)", [IRError("BAD_SHAPE", ".".join(map(str, e["loc"])), e["msg"])
                       for e in ve.errors()])

if errs := validate(spec):                                       # checkpoint 2: meaning
    fail("2 (meaning)", errs)
print(f"validated: {len(spec.constraints)} constraint families, {len(spec.vars)} variable families")

try:
    bm = bind(spec, root=".")
except BindError as be:                                          # data contradicts spec
    fail("3 (data)", be.errors)

if errs := check_bound(bm):                                      # checkpoint 3: data
    fail("3 (data)", errs)
print("bound: " + ", ".join(f"|{k}|={len(v)}" for k, v in bm.sets.items()))

# scenario detection -> backend choice, from the model's structure
print()
print(describe(spec, forced_solver))
solver = route(spec, forced_solver)["solver"]
if solver == "cp_sat":
    # detected as CP-SAT's home turf, but this compiler emits Pyomo; be explicit
    # rather than silently pretending the route was taken.
    print("    note: cp_sat backend is not wired into this compiler yet — "
          "solving the time-indexed MILP with appsi_highs instead")
    solver = "appsi_highs"
print()

m = compile_model(bm)
rep = solve(m, solver=solver)

if rep["status"] in ("unbounded", "infeasibleOrUnbounded"):
    # opposite pathology to infeasible: too FEW constraints, not too many.
    # The elastic diagnosis has nothing to say about it.
    print(f"\nstatus={rep['status']} — the model is unbounded: the objective can grow "
          "without limit.\nA constraint the brief implies is missing entirely, or a "
          "variable needs a bound.")
    sys.exit(0)

if rep["objective"] is None:
    d = diagnose_infeasible(bm, solver=solver)
    print(f"\nstatus={rep['status']} — elastic diagnosis:")
    for v in d.get("violations", []):
        print(f"  relax by {v['relax_by']:>10.2f}: {v['source_text']}")
    sys.exit(0)

print(f"\nstatus={rep['status']}  objective={rep['objective']:.3f}")
for vname, picked in rep["selected_by_var"].items():
    print(f"  {vname}: {len(picked)} of "
          f"{len(getattr(m, vname))} decision(s) set")

# Scenario-agnostic summary: for each variable whose FIRST index is a rows set,
# total the columns the model actually reads (its indexed params).
rowsets = {s.name: s for s in spec.sets if s.kind == "rows"}
for v in spec.vars:
    if not v.index or v.index[0] not in rowsets:
        continue
    picked = rep["selected_by_var"].get(v.name, [])
    ids = sorted({(p[0] if isinstance(p, tuple) else p) for p in picked})
    if not ids:
        continue
    df = bm.frames[rowsets[v.index[0]].table]
    cols = [p.column for p in spec.params
            if p.index and p.index[0] == v.index[0] and p.column in df.columns]
    if cols:
        tot = df.loc[ids, cols].sum()
        print("  totals over selected rows: "
              + " | ".join(f"{c} {tot[c]:,.2f}" for c in cols))

print(f"\nconstraint report  (shadow prices: {rep.get('shadow_price_basis', 'off')}, "
      "objective units per unit of rhs)")
for c in rep["constraints"]:
    flag = "BINDING" if c["binding"] else f"slack {c['slack']:>10.3f}"
    sp = c.get("shadow_price")
    sptxt = f"shadow {sp:>9.4f}" if sp else " " * 16
    print(f"  {c['name']:<22} {flag:<20} {sptxt} <- {c['source_text']}")
