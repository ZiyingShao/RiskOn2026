"""Baseline comparison: raw rows -> LLM  vs.  brief -> IR -> solver.

The claim under test: an LLM handed the actual inventory rows and asked to
"optimise" produces an answer that LOOKS like a solution — a stone list, a
total, a confident summary — but is arithmetically wrong, constraint-violating,
and far from optimal. The pipeline instead emits a model, hands it to HiGHS,
and returns a provably optimal, feasible selection.

Ground truth is not an opinion here: it is the MILP optimum from the solver,
on exactly the same rows the LLM sees.

    python direct_baseline.py build            # write prompts/direct_*.md
    python direct_baseline.py truth            # print the solver optimum
    python direct_baseline.py score <file> <instance>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "IR_Compiler"))

from ir import ModelSpec                       # noqa: E402
from compiler import bind                      # noqa: E402
from solution import solve_objective           # noqa: E402

ROOT = str(HERE.parent)

# ---------------------------------------------------------------- instances

def _spec(n: int, seed: int, budget: float, slots: int, vol_cap: float,
          cut_cap: float, min_clarity: int | None, premium_share: float | None) -> dict:
    """Build the IR for an instance — this is what the PIPELINE solves."""
    spec = {
        "name": f"direct_cmp_{n}",
        "tables": [{"name": "inv", "path": "diamonds.csv",
                    "sample": {"n": n, "seed": seed},
                    "derived": [{"name": "vol_mm3", "expr": "x * y * z"}]}],
        "sets": [{"name": "I", "kind": "rows", "table": "inv"},
                 {"name": "CUT", "kind": "categories", "table": "inv", "column": "cut"},
                 {"name": "CLARITY", "kind": "categories", "table": "inv", "column": "clarity"}],
        "params": [
            {"name": "price", "index": ["I"], "table": "inv", "column": "price"},
            {"name": "carat", "index": ["I"], "table": "inv", "column": "carat"},
            {"name": "vol", "index": ["I"], "table": "inv", "column": "vol_mm3"},
        ],
        "vars": [{"name": "x", "index": ["I"], "domain": "Binary"}],
        "objective": {"sense": "max", "source_text": "maximise total carat mass",
                      "expr": {"terms": [{"var": "x", "weight": "carat",
                                          "over": {"set": "I"}}]}},
        "constraints": [
            {"name": "credit_line", "source_text": "budget",
             "lhs": {"terms": [{"var": "x", "weight": "price", "over": {"set": "I"}}]},
             "rel": "<=", "rhs": {"const": budget}},
            {"name": "display_slots", "source_text": "slots",
             "lhs": {"terms": [{"var": "x", "over": {"set": "I"}}]},
             "rel": "<=", "rhs": {"const": float(slots)}},
            {"name": "display_volume", "source_text": "volume",
             "lhs": {"terms": [{"var": "x", "weight": "vol", "over": {"set": "I"}}]},
             "rel": "<=", "rhs": {"const": vol_cap}},
            {"name": "cut_concentration", "source_text": "cut cap", "forall": ["CUT"],
             "lhs": {"terms": [{"var": "x", "over": {"set": "I", "where": [
                 {"column": "cut", "op": "eq", "value": "$CUT"}]}}]},
             "rel": "<=",
             "rhs": {"terms": [{"coef": cut_cap, "var": "x", "over": {"set": "I"}}]}},
        ],
    }
    if min_clarity:
        spec["constraints"].append({
            "name": "clarity_coverage", "source_text": "clarity coverage",
            "forall": ["CLARITY"],
            "lhs": {"terms": [{"var": "x", "over": {"set": "I", "where": [
                {"column": "clarity", "op": "eq", "value": "$CLARITY"}]}}]},
            "rel": ">=", "rhs": {"terms": [], "const": float(min_clarity)}})
    if premium_share:
        spec["constraints"].append({
            "name": "premium_risk_bound", "source_text": "premium exposure",
            "lhs": {"terms": [{"var": "x", "weight": "price", "over": {"set": "I", "where": [
                {"column": "price", "op": "gte", "value": 8000}]}}]},
            "rel": "<=",
            "rhs": {"terms": [{"coef": premium_share, "var": "x", "weight": "price",
                               "over": {"set": "I"}}]}})
    return spec


INSTANCES = {
    # the real vault problem — identical constraints to references/base.json
    "large": dict(n=800, seed=7, budget=250_000, slots=60, vol_cap=9_000,
                  cut_cap=0.30, min_clarity=2, premium_share=0.40),
    # a deliberately EASY instance: few rows, few constraints, small arithmetic
    "small": dict(n=60, seed=7, budget=20_000, slots=12, vol_cap=2_000,
                  cut_cap=0.40, min_clarity=None, premium_share=None),
}

RULES = {
    "large": ("- total price of selected stones <= CHF 250,000\n"
              "- at most 60 stones\n"
              "- total volume of selected stones <= 9,000 mm3\n"
              "- no single cut grade may exceed 30% of the stones selected\n"
              "- at least 2 stones of EVERY clarity grade present in the list\n"
              "- at most 40% of the money spent may go to stones priced >= CHF 8,000"),
    "small": ("- total price of selected stones <= CHF 20,000\n"
              "- at most 12 stones\n"
              "- total volume of selected stones <= 2,000 mm3\n"
              "- no single cut grade may exceed 40% of the stones selected"),
}


def frame(instance: str):
    spec = ModelSpec.model_validate(_spec(**INSTANCES[instance]))
    return bind(spec, root=ROOT).frames["inv"], spec


# ---------------------------------------------------------------- prompt

def build_prompt(instance: str) -> str:
    df, _ = frame(instance)
    rows = "\n".join(
        f"{i},{r.carat},{r.cut},{r.clarity},{int(r.price)},{r.vol_mm3:.1f}"
        for i, r in df.iterrows())
    return (
        "You are stocking a jeweler's retail vault. Below is the complete "
        "wholesale inventory available to you, one stone per line:\n\n"
        "id,carat,cut,clarity,price_chf,volume_mm3\n"
        f"{rows}\n\n"
        "Select the subset of stones that MAXIMISES total carat mass, subject to:\n"
        f"{RULES[instance]}\n\n"
        "Reply with ONLY this JSON and nothing else:\n"
        '{"selected": [<ids>], "total_carat": <number>, "total_price": <number>}\n'
    )


# ---------------------------------------------------------------- ground truth

def ground_truth(instance: str) -> dict:
    spec = ModelSpec.model_validate(_spec(**INSTANCES[instance]))
    r = solve_objective(spec, ROOT)
    df = r["bm"].frames["inv"]
    import pyomo.environ as pyo
    from compiler import compile_model
    m = compile_model(r["bm"])
    pyo.SolverFactory("appsi_highs").solve(m)
    picked = [i for i in m.x if pyo.value(m.x[i]) > 0.5]
    return {"status": r["status"], "objective": r["objective"],
            "selected": picked, "df": df}


# ---------------------------------------------------------------- scoring

def score(answer_text: str, instance: str) -> dict:
    cfg = INSTANCES[instance]
    df, _ = frame(instance)
    gt = ground_truth(instance)

    txt = re.sub(r"^```(?:json)?|```$", "", answer_text.strip(), flags=re.M).strip()
    s, e = txt.find("{"), txt.rfind("}")
    try:
        ans = json.loads(txt[s:e + 1])
    except Exception:
        return {"parse": "FAILED — not valid JSON"}

    ids = ans.get("selected", [])
    valid = [i for i in ids if i in df.index]
    ghost = [i for i in ids if i not in df.index]
    dupes = len(ids) - len(set(ids))
    sel = df.loc[valid]

    actual_carat = float(sel.carat.sum())
    actual_price = float(sel.price.sum())
    claimed_carat = float(ans.get("total_carat", 0) or 0)
    claimed_price = float(ans.get("total_price", 0) or 0)

    viol = []
    if actual_price > cfg["budget"] + 1e-6:
        viol.append(f"budget: spent CHF {actual_price:,.0f} > {cfg['budget']:,.0f}")
    if len(valid) > cfg["slots"]:
        viol.append(f"slots: {len(valid)} stones > {cfg['slots']}")
    if float(sel.vol_mm3.sum()) > cfg["vol_cap"] + 1e-6:
        viol.append(f"volume: {sel.vol_mm3.sum():,.0f} mm3 > {cfg['vol_cap']:,.0f}")
    if len(sel):
        share = sel.cut.value_counts().max() / len(sel)
        if share > cfg["cut_cap"] + 1e-9:
            worst = sel.cut.value_counts().idxmax()
            viol.append(f"cut cap: {worst} is {share:.1%} > {cfg['cut_cap']:.0%}")
    if cfg["min_clarity"]:
        for grade in sorted(df.clarity.unique()):
            got = int((sel.clarity == grade).sum())
            if got < cfg["min_clarity"]:
                viol.append(f"clarity {grade}: {got} < {cfg['min_clarity']}")
    if cfg["premium_share"] and actual_price > 0:
        prem = float(sel.loc[sel.price >= 8000, "price"].sum())
        if prem > cfg["premium_share"] * actual_price + 1e-6:
            viol.append(f"premium: {prem / actual_price:.1%} of spend > "
                        f"{cfg['premium_share']:.0%}")

    return {
        "instance": instance,
        "rows_shown": len(df),
        "ghost_ids": ghost,
        "duplicate_ids": dupes,
        "claimed_carat": claimed_carat,
        "actual_carat": round(actual_carat, 3),
        "arithmetic_error": round(claimed_carat - actual_carat, 3),
        "claimed_price": claimed_price,
        "actual_price": round(actual_price, 2),
        "violations": viol,
        "feasible": not viol and not ghost,
        "optimum": round(gt["objective"], 3),
        "gap_vs_optimum_pct": round(
            100 * (actual_carat - gt["objective"]) / gt["objective"], 1),
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        out = HERE / "prompts"
        out.mkdir(exist_ok=True)
        for inst in INSTANCES:
            p = out / f"direct_{inst}.md"
            p.write_text(build_prompt(inst))
            print(f"{p.relative_to(HERE)}  ({len(p.read_text()):,} chars, "
                  f"{INSTANCES[inst]['n']} rows)")
    elif cmd == "truth":
        for inst in INSTANCES:
            gt = ground_truth(inst)
            print(f"{inst:<6} {gt['status']:<9} optimum {gt['objective']:.3f} carats "
                  f"from {len(gt['selected'])} stones")
    elif cmd == "score":
        print(json.dumps(score(Path(sys.argv[2]).read_text(), sys.argv[3]), indent=1))
