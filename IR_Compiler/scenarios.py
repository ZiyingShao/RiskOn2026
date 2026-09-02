"""Scenario detection and solver routing.

Two honest claims up front:

1. The thing that differs between Track B and Track C is NOT the solver — both
   are MILPs and HiGHS solves both. It is the model SHAPE: a 1-D selection
   variable versus a 2-D assignment variable plus a time-covering constraint.
   So detection reads the compiled structure, not the prose.
2. Routing therefore has to earn its keep on structure/scale, not vibes: a pure
   assignment problem is a network flow (totally unimodular — the LP relaxation
   is already integral); a large disjunctive schedule is CP-SAT's home turf.
   Where a specialised backend is genuinely better we say so, and we fall back
   to HiGHS when it is absent rather than failing.

`classify` returns the evidence it used, so a wrong call is arguable rather
than mysterious.
"""

from __future__ import annotations

from typing import Any

from ir import ModelSpec
from validate import dims


# ---------------------------------------------------------------- detection

def _features(spec: ModelSpec) -> dict[str, Any]:
    setkind = {s.name: s.kind for s in spec.sets}
    f: dict[str, Any] = {
        "n_vars": len(spec.vars),
        "arities": sorted({len(v.index) for v in spec.vars}),
        "domains": sorted({v.domain for v in spec.vars}),
        "set_kinds": sorted(set(setkind.values())),
        "n_constraint_families": len(spec.constraints),
        "has_time_window": False,     # two-sided predicate on a bound forall value
        "has_at_most_one": False,     # sum over a whole axis <= 1
        "has_share_bound": False,     # rhs is a fraction of the same variable
        "parsed_datetime": any(t.parse_datetime for t in spec.tables),
    }
    for c in spec.constraints:
        for t in c.lhs.terms:
            axes = dims(t)
            bound_preds = [pr for d in axes for pr in d.where
                           if isinstance(pr.value, str) and pr.value.startswith("$")]
            ops = {pr.op for pr in bound_preds}
            if {"lte", "gt"} <= ops or {"lt", "gte"} <= ops:
                f["has_time_window"] = True          # start <= t < end
            if (len(axes) >= 2 and c.rel == "<=" and not c.rhs.terms
                    and abs(c.rhs.const - 1.0) < 1e-9):
                f["has_at_most_one"] = True
        for t in c.rhs.terms:
            if t.var and 0 < abs(t.coef) < 1:
                f["has_share_bound"] = True
    return f


def classify(spec: ModelSpec) -> dict[str, Any]:
    """-> {archetype, evidence[], features}."""
    f = _features(spec)
    ev: list[str] = []
    max_arity = max(f["arities"]) if f["arities"] else 0

    if max_arity >= 2:
        ev.append(f"a {max_arity}-D decision variable — pairs, not a subset")
        if f["has_at_most_one"]:
            ev.append("an 'at most one per row' constraint")
        if f["has_time_window"] or f["parsed_datetime"]:
            ev.append("a time-window predicate (start <= t < end) over a bound index")
            arch = "scheduling"
        else:
            arch = "assignment"
    elif "NonNegReal" in f["domains"] or "Real" in f["domains"]:
        ev.append("continuous decision variables")
        arch = "blending"
    else:
        ev.append("a single 1-D binary variable indexed by table rows")
        if f["has_share_bound"]:
            ev.append("a share bound (rhs is a fraction of the same variable)")
        arch = "selection"

    if any(c.rel == ">=" for c in spec.constraints):
        ev.append("at least one >= requirement (coverage)")
    return {"archetype": arch, "evidence": ev, "features": f}


# ---------------------------------------------------------------- routing

# archetype -> ordered backend preference. First AVAILABLE one wins.
ROUTES: dict[str, list[tuple[str, str]]] = {
    "selection":  [("appsi_highs", "MILP branch-and-bound; knapsack-style models are its bread and butter")],
    "covering":   [("appsi_highs", "MILP branch-and-bound")],
    "blending":   [("appsi_highs", "LP/MILP simplex")],
    "assignment": [("appsi_highs", "assignment polytope is integral, so the LP relaxation "
                                   "is usually already integer — HiGHS closes it fast")],
    "scheduling": [("cp_sat",      "disjunctive scheduling: CP-SAT propagates no-overlap "
                                   "natively instead of enumerating time slots"),
                   ("appsi_highs", "time-indexed MILP formulation")],
}


def backend_available(name: str) -> bool:
    if name == "cp_sat":
        try:
            from ortools.sat.python import cp_model  # noqa: F401
            return True
        except Exception:
            return False
    try:
        import pyomo.environ as pyo
        opt = pyo.SolverFactory(name)
        try:
            return bool(opt.available(exception_flag=False))
        except TypeError:
            return bool(opt.available())
    except Exception:
        return False


def route(spec: ModelSpec, force: str | None = None) -> dict[str, Any]:
    """-> {archetype, solver, why, considered[], evidence[]}"""
    c = classify(spec)
    if force:
        return {**c, "solver": force, "why": "forced on the command line",
                "considered": []}
    considered = []
    for name, why in ROUTES.get(c["archetype"], ROUTES["selection"]):
        ok = backend_available(name)
        considered.append((name, ok, why))
        if ok:
            return {**c, "solver": name, "why": why, "considered": considered}
    return {**c, "solver": "appsi_highs", "why": "fallback — nothing preferred was available",
            "considered": considered}


def describe(spec: ModelSpec, force: str | None = None) -> str:
    r = route(spec, force)
    lines = [f"scenario: {r['archetype'].upper()}"]
    for e in r["evidence"]:
        lines.append(f"    because: {e}")
    for name, ok, why in r["considered"]:
        mark = "USING " if ok and name == r["solver"] else ("skip  " if not ok else "      ")
        note = "" if ok else "  (not installed)"
        lines.append(f"    {mark}{name}: {why}{note}")
    if not r["considered"]:
        lines.append(f"    USING {r['solver']}: {r['why']}")
    return "\n".join(lines)
