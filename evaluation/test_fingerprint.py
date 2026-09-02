"""Self-test: the fingerprint must be invariant to renaming, scaling, side
swaps, and >=/<= flips — and must distinguish genuinely different constraints.
Run:  python test_fingerprint.py
"""

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "IR_Compiler"))

from ir import ModelSpec           # noqa: E402
from fingerprint import compare    # noqa: E402

ROOT = str(HERE.parent)
ref_raw = json.load(open(HERE / "references" / "base.json"))
ref = ModelSpec.model_validate(ref_raw)

# 1. identity
r = compare(ref, ref, ROOT)
assert r["recall"] == r["precision"] == 1.0 and r["objective_match"], r
print("identity: recall=precision=1.0  OK")

# 2. rewritten-but-equal: rename everything, scale the cut cap by 10,
#    move the budget rhs across sides, flip <= to >=.
alt = copy.deepcopy(ref_raw)
txt = json.dumps(alt)
for a, b in [('"x"', '"pick"'), ('"I"', '"STONES"'), ('"inv"', '"stock"')]:
    txt = txt.replace(a, b)
alt = json.loads(txt)
# ...except predicate columns must stay real columns: the renames above only
# touch exact-quoted tokens, and none of them collide with column names.
cut = next(c for c in alt["constraints"] if c["name"] == "cut_concentration")
cut["lhs"]["terms"][0]["coef"] = 10.0          # 10*sum_g <= 3*sum
cut["rhs"]["terms"][0]["coef"] = 3.0
credit = next(c for c in alt["constraints"] if c["name"] == "credit_line")
credit["rel"] = ">="                            # budget >= spend
credit["lhs"], credit["rhs"] = credit["rhs"], credit["lhs"]
r = compare(ModelSpec.model_validate(alt), ref, ROOT)
assert r["recall"] == r["precision"] == 1.0 and r["objective_match"], r
print("renamed+scaled+flipped rewrite: recall=precision=1.0  OK")

# 3. genuinely different: loosen the cut cap 0.3 -> 0.35 and drop a constraint.
bad = copy.deepcopy(ref_raw)
next(c for c in bad["constraints"]
     if c["name"] == "cut_concentration")["rhs"]["terms"][0]["coef"] = 0.35
bad["constraints"] = [c for c in bad["constraints"] if c["name"] != "display_slots"]
r = compare(ModelSpec.model_validate(bad), ref, ROOT)
assert r["recall"] < 1.0 and r["precision"] < 1.0, r
assert "cut_concentration" in r["missed_reference_constraints"]
assert "display_slots" in r["missed_reference_constraints"]
print(f"perturbed spec detected: recall={r['recall']:.3f} "
      f"precision={r['precision']:.3f}, missed={r['missed_reference_constraints']}  OK")
print("fingerprint self-test passed")
