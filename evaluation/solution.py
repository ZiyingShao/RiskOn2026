"""Solution equivalence.

Solve both IRs. If the objectives match within tolerance the models agree even
if they are written differently. If they don't, the sign of the gap says which
direction the error runs: a HIGHER objective from the generated IR means a
constraint went missing or got loosened — the dangerous direction.

Uses its own minimal solve (status + objective only) so a generated spec with
an unconventionally named variable still solves; IR_Compiler.solve's report
assumes the variable is called `x`.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "IR_Compiler"))

import pyomo.environ as pyo                                   # noqa: E402
from ir import ModelSpec                                      # noqa: E402
from compiler import bind, compile_model, diagnose_infeasible  # noqa: E402
from semantic import jaccard                                   # noqa: E402

REL_TOL = 1e-6


def solve_objective(spec: ModelSpec, root: str, solver: str = "appsi_highs") -> dict:
    bm = bind(spec, root=root)
    m = compile_model(bm)
    res = pyo.SolverFactory(solver).solve(m, load_solutions=False)
    status = str(res.solver.termination_condition)
    if status not in ("optimal", "feasible"):
        return {"status": status, "objective": None, "bm": bm}
    m.solutions.load_from(res)
    return {"status": status, "objective": float(pyo.value(m.OBJ)), "bm": bm}


def compare_solutions(gen: ModelSpec, ref: ModelSpec, root: str,
                      expect_infeasible: bool,
                      infeasible_sentence: str | None = None) -> dict:
    g = solve_objective(gen, root)
    r = solve_objective(ref, root)

    if expect_infeasible:
        out = {"reference_status": r["status"], "generated_status": g["status"],
               "agree": g["objective"] is None and r["objective"] is None,
               "gap": None, "direction": None, "diagnosis_names_sentence": None}
        if g["objective"] is None:
            diag = diagnose_infeasible(g["bm"])
            texts = [v["source_text"] for v in diag.get("violations", [])]
            out["diagnosis_names_sentence"] = (
                any(jaccard(infeasible_sentence, t) >= 0.25 for t in texts)
                if infeasible_sentence else bool(texts))
        return out

    if g["objective"] is None or r["objective"] is None:
        return {"reference_status": r["status"], "generated_status": g["status"],
                "agree": False, "gap": None,
                "direction": "generated_infeasible" if g["objective"] is None
                else "reference_infeasible"}

    gap = (g["objective"] - r["objective"]) / max(1.0, abs(r["objective"]))
    return {
        "reference_objective": round(r["objective"], 6),
        "generated_objective": round(g["objective"], 6),
        "agree": abs(gap) <= REL_TOL,
        "gap": round(gap, 8),
        "direction": (None if abs(gap) <= REL_TOL
                      else "dangerous_too_high" if gap > 0
                      else "too_low"),
    }
