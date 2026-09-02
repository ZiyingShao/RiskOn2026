"""Build the reference IRs for the perturbation set.

Each reference is derived from IR_Compiler/vault_stocking.json, retargeted to
the local CSV and the eval's canonical sampling, with `source_text` rewritten
to quote the exact brief sentence (so the semantic check is exact on the
references). Run once:  python make_references.py
Every reference is pushed through all three checkpoints before it is written.
"""

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "IR_Compiler"))

from ir import ModelSpec                     # noqa: E402
from validate import validate, check_bound   # noqa: E402
from compiler import bind                    # noqa: E402
from briefs import BY_NAME, _S               # noqa: E402

CANON_TABLE = {"name": "inv", "path": "diamonds.csv",
               "sample": {"n": 800, "seed": 7},
               "derived": [{"name": "vol_mm3", "expr": "x * y * z"}]}


def base_spec() -> dict:
    spec = json.load(open(HERE.parent / "IR_Compiler" / "vault_stocking.json"))
    spec["tables"] = [copy.deepcopy(CANON_TABLE)]
    by_name = {c["name"]: c for c in spec["constraints"]}
    by_name["credit_line"]["source_text"] = _S["budget"]
    by_name["display_slots"]["source_text"] = _S["slots"]
    by_name["display_volume"]["source_text"] = _S["volume"]
    by_name["cut_concentration"]["source_text"] = _S["cut30"]
    by_name["clarity_coverage"]["source_text"] = _S["clarity2"]
    by_name["premium_risk_bound"]["source_text"] = _S["premium"]
    spec["objective"]["source_text"] = _S["objective"]
    return spec


def build_all() -> dict[str, dict]:
    refs = {}

    refs["base"] = base_spec()

    s = base_spec()
    c = next(c for c in s["constraints"] if c["name"] == "cut_concentration")
    c["rhs"]["terms"][0]["coef"] = 0.25
    c["source_text"] = _S["cut25"]
    refs["cap25"] = s

    s = base_spec()
    s["constraints"].append({
        "name": "small_stone_cap", "source_text": _S["small"],
        "lhs": {"terms": [{"var": "x", "over": {"set": "I", "where": [
            {"column": "carat", "op": "lt", "value": 0.3}]}}]},
        "rel": "<=", "rhs": {"const": 10.0},
    })
    refs["small_stones"] = s

    s = base_spec()
    s["constraints"] = [c for c in s["constraints"] if c["name"] != "display_volume"]
    s["params"] = [p for p in s["params"] if p["name"] not in ("vol", "case_vol")]
    refs["no_volume"] = s

    s = base_spec()
    next(p for p in s["params"] if p["name"] == "budget")["value"] = 400000
    next(c for c in s["constraints"]
         if c["name"] == "credit_line")["source_text"] = _S["budget_renamed"]
    refs["renamed_budget"] = s

    s = base_spec()
    # same physics as base — slots + volume — but both constraints trace to
    # the single vague "must physically fit" sentence
    for name in ("display_slots", "display_volume"):
        next(c for c in s["constraints"] if c["name"] == name)["source_text"] = \
            _S["case_vague"]
    refs["vague_case"] = s

    s = base_spec()
    next(p for p in s["params"] if p["name"] == "min_per_clarity")["value"] = 80
    c = next(c for c in s["constraints"] if c["name"] == "clarity_coverage")
    c["rhs"] = {"terms": [], "const": 80.0}
    c["source_text"] = _S["clarity80"]
    refs["infeasible"] = s

    return refs


if __name__ == "__main__":
    out = HERE / "references"
    out.mkdir(exist_ok=True)
    for name, raw in build_all().items():
        spec = ModelSpec.model_validate(raw)          # checkpoint 1
        errs = validate(spec)                          # checkpoint 2
        assert not errs, (name, [str(e) for e in errs])
        bm = bind(spec, root=str(HERE.parent))         # checkpoint 3 (raises BindError)
        errs = check_bound(bm)
        assert not errs, (name, [str(e) for e in errs])
        (out / f"{name}.json").write_text(json.dumps(raw, indent=1) + "\n")
        print(f"references/{name}.json  OK ({len(raw['constraints'])} constraints)")
    assert BY_NAME["contradiction"]["reference"] is None
