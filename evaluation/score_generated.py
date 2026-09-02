"""Score generated IRs for ANY track — no Track-B-specific normalization.

checkpoints.py rewrites every table to diamonds.csv/n=800/seed=7, which is
correct for the Track B eval and wrong for anything else. This scorer takes the
spec as written, runs the three checkpoints, solves it, and compares against a
reference: objective agreement plus structural recall/precision.

    python score_generated.py results_gen_c dispatch
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "IR_Compiler"))

from pydantic import ValidationError            # noqa: E402
from ir import ModelSpec                        # noqa: E402
from validate import validate, check_bound, BindError   # noqa: E402
from compiler import bind                       # noqa: E402
from solution import solve_objective            # noqa: E402
from fingerprint import compare                 # noqa: E402
from semantic import coverage                   # noqa: E402
from briefs import ALL_BY_NAME                  # noqa: E402

ROOT = str(HERE.parent)


def extract(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(t[a:b + 1])
    except json.JSONDecodeError:
        return None


def score(text: str, brief_name: str) -> dict:
    brief = ALL_BY_NAME[brief_name]
    ref_raw = json.load(open(HERE / "references" / brief["reference"]))
    ref = ModelSpec.model_validate(ref_raw)
    truth = solve_objective(ref, ROOT)

    raw = extract(text)
    if raw is None:
        return {"stage": "parse", "detail": "not valid JSON"}
    try:
        spec = ModelSpec.model_validate(raw)
    except ValidationError as ve:
        return {"stage": "shape", "detail": f"{len(ve.errors())} shape error(s): "
                + ve.errors()[0]["msg"]}
    if errs := validate(spec):
        return {"stage": "meaning", "detail": "; ".join(e.code for e in errs[:4]),
                "codes": sorted({e.code for e in errs})}
    try:
        bm = bind(spec, root=ROOT)
        errs = check_bound(bm)
    except BindError as be:
        errs = be.errors
    if errs:
        return {"stage": "data", "detail": "; ".join(e.code for e in errs[:4]),
                "codes": sorted({e.code for e in errs})}

    out = {"stage": "valid"}
    try:
        r = solve_objective(spec, ROOT)
        out["status"] = r["status"]
        out["objective"] = round(r["objective"], 2) if r["objective"] is not None else None
    except Exception as e:                       # compile-stage failure
        out["stage"] = "compile"
        out["detail"] = f"{type(e).__name__}: {str(e)[:80]}"
        return out

    out["optimum"] = round(truth["objective"], 2)
    if out["objective"] is not None:
        out["obj_match"] = abs(out["objective"] - out["optimum"]) < 1e-4
    fp = compare(spec, ref, ROOT)
    out["recall"] = round(fp["recall"], 3)
    out["precision"] = round(fp["precision"], 3)
    out["missed"] = fp["missed_reference_constraints"]
    out["invented"] = fp["invented_generated_constraints"]
    out["semantic"] = round(coverage(brief["obligations"], raw)["rate"], 3)
    return out


if __name__ == "__main__":
    d = HERE / (sys.argv[1] if len(sys.argv) > 1 else "results_gen_c")
    brief = sys.argv[2] if len(sys.argv) > 2 else "dispatch"
    truth = solve_objective(
        ModelSpec.model_validate(json.load(
            open(HERE / "references" / ALL_BY_NAME[brief]["reference"]))), ROOT)
    print(f"\nbrief '{brief}' — reference optimum {truth['objective']:.2f}\n")
    print(f"{'run':<20}{'reached':<10}{'objective':>10}{'==opt':>7}"
          f"{'recall':>8}{'prec':>7}{'sem':>7}  detail")
    for f in sorted(d.glob("*.json")):
        r = score(f.read_text(), brief)
        if r["stage"] != "valid":
            print(f"{f.stem:<20}{r['stage']:<10}{'—':>10}{'—':>7}{'—':>8}{'—':>7}{'—':>7}"
                  f"  {r.get('detail','')}")
            continue
        obj = f"{r['objective']:.2f}" if r["objective"] is not None else "infeasible"
        print(f"{f.stem:<20}{'solved':<10}{obj:>10}"
              f"{('YES' if r.get('obj_match') else 'no'):>7}"
              f"{r['recall']:>8.3f}{r['precision']:>7.3f}{r['semantic']:>7.3f}"
              + (f"  missed={r['missed']}" if r["missed"] else "")
              + (f"  invented={r['invented']}" if r["invented"] else ""))
