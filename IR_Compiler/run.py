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

spec_path = sys.argv[1] if len(sys.argv) > 1 else "vault_stocking.json"
solver = sys.argv[2] if len(sys.argv) > 2 else "appsi_highs"   # e.g. cbc, glpk, gurobi


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
print(f"bound: |I|={len(bm.sets['I'])}, "
      + ", ".join(f"|{k}|={len(v)}" for k, v in bm.sets.items() if k != "I"))

m = compile_model(bm)
rep = solve(m, solver=solver)

if rep["objective"] is None:
    d = diagnose_infeasible(bm, solver=solver)
    print(f"\nstatus={rep['status']} — elastic diagnosis:")
    for v in d.get("violations", []):
        print(f"  relax by {v['relax_by']:>10.2f}: {v['source_text']}")
    sys.exit(0)

print(f"\nstatus={rep['status']}  objective={rep['objective']:.3f} carats  "
      f"stones={len(rep['selected'])}")
df = bm.frames["inv"]
sel = df.loc[rep["selected"]]
print(f"capital deployed CHF {sel.price.sum():,.0f} | volume {sel.vol_mm3.sum():,.0f} mm3 | "
      f"mean CHF/ct {sel.price.sum()/sel.carat.sum():,.0f}")
print("\ncut mix:", (sel.cut.value_counts(normalize=True).round(3)).to_dict())
print("clarity counts:", sel.clarity.value_counts().to_dict())
print(f"\nconstraint report  (shadow prices: {rep.get('shadow_price_basis', 'off')}, "
      "carats per unit of rhs)")
for c in rep["constraints"]:
    flag = "BINDING" if c["binding"] else f"slack {c['slack']:>10.3f}"
    sp = c.get("shadow_price")
    sptxt = f"shadow {sp:>9.4f}" if sp else " " * 16
    print(f"  {c['name']:<22} {flag:<20} {sptxt} <- {c['source_text']}")
