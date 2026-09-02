"""
compiler.py — bind, compile, solve.

The checks live elsewhere (checkpoint 1 is generated from ir.py, checkpoints 2
and 3 are hand-written in validate.py). This module is the data + solver half:

  bind(spec, root)        IR + CSVs -> BoundModel  (sets materialised, params as dicts)
  compile_model(bound)    BoundModel -> pyomo.ConcreteModel
  solve(model)            -> report dict (status, objective, KPIs, binding constraints)
  diagnose_infeasible(bm) elastic re-solve, read by the repair loop

The binder is the only place that touches raw data. The compiler is the only place
that knows what a solver is. Swapping Pyomo for gurobipy touches one function.
Imports run one way — ir.py <- validate.py <- compiler.py — never back.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import pandas as pd
import pyomo.environ as pyo

from ir import ModelSpec, LinExpr
from validate import IRError, BindError, forall_tuples, select_rows

# ---------------------------------------------------------------- binding


@dataclass
class BoundModel:
    spec: ModelSpec
    frames: dict[str, pd.DataFrame]
    sets: dict[str, list]                       # set name -> members
    params: dict[str, Any]                      # scalar float, or dict[member] -> float


def bind(spec: ModelSpec, root: str = ".") -> BoundModel:
    """Raises BindError (a list of IRErrors) when the data contradicts the spec,
    so run.py can treat a bad column the same way as any other checkpoint failure."""
    errs: list[IRError] = []

    frames: dict[str, pd.DataFrame] = {}
    for t in spec.tables:
        try:
            df = pd.read_csv(t.path if t.path.startswith("http") else f"{root}/{t.path}")
        except Exception as ex:
            errs.append(IRError("BAD_TABLE_PATH", f"tables.{t.name}.path", str(ex),
                                "fix the path/URL, or drop the table"))
            continue
        if t.sample:
            df = df.sample(n=min(t.sample["n"], len(df)), random_state=t.sample.get("seed", 0))
        df = df.reset_index(drop=True)
        for d in t.derived:
            try:
                df[d.name] = df.eval(d.expr)
            except Exception as ex:
                errs.append(IRError("BAD_DERIVED_EXPR", f"tables.{t.name}.derived.{d.name}",
                                    str(ex), f"use columns from {list(df.columns)}"))
        frames[t.name] = df
    if errs:
        raise BindError(errs)  # nothing downstream is meaningful without the tables

    sets: dict[str, list] = {}
    for s in spec.sets:
        df = frames[s.table]
        if s.kind == "rows":
            sets[s.name] = list(df.index)
        elif s.column not in df.columns:
            errs.append(IRError("UNKNOWN_COLUMN", f"sets.{s.name}.column",
                                f"no column '{s.column}' in table '{s.table}'",
                                f"use one of {list(df.columns)}"))
        else:
            sets[s.name] = sorted(df[s.column].unique().tolist())

    params: dict[str, Any] = {}
    for p in spec.params:
        if not p.index:
            params[p.name] = float(p.value)
        elif p.column not in frames[p.table].columns:
            errs.append(IRError("UNKNOWN_COLUMN", f"params.{p.name}.column",
                                f"no column '{p.column}' in table '{p.table}'",
                                f"use one of {list(frames[p.table].columns)}"))
        else:
            params[p.name] = frames[p.table][p.column].to_dict()
    if errs:
        raise BindError(errs)

    return BoundModel(spec, frames, sets, params)


# ---------------------------------------------------------------- compilation


def _expr(bm: BoundModel, m: pyo.ConcreteModel, e: LinExpr, binding: dict[str, Any]):
    acc = e.const
    for t in e.terms:
        w = bm.params.get(t.weight) if t.weight else None
        if t.var is None and t.over is None:                       # scalar constant
            acc += t.coef * (w if w is not None else 1.0)
        elif t.var is None:                                        # data aggregate
            rows = select_rows(bm, t.over, binding)
            acc += t.coef * sum((w[i] if w is not None else 1.0) for i in rows)
        else:                                                      # variable term
            v = getattr(m, t.var)
            rows = select_rows(bm, t.over, binding)
            acc += t.coef * sum((w[i] if w is not None else 1.0) * v[i] for i in rows)
    return acc


def compile_model(bm: BoundModel) -> pyo.ConcreteModel:
    m = pyo.ConcreteModel(name=bm.spec.name)
    m._ir_index = {}                                               # constraint name -> source_text

    for s in bm.spec.sets:
        setattr(m, s.name, pyo.Set(initialize=bm.sets[s.name]))

    dom = {"Binary": pyo.Binary, "Integer": pyo.Integers,
           "NonNegReal": pyo.NonNegativeReals, "Real": pyo.Reals}
    for v in bm.spec.vars:
        idx = [getattr(m, i) for i in v.index]
        setattr(m, v.name, pyo.Var(*idx, domain=dom[v.domain], bounds=(v.lb, v.ub)))

    sense = pyo.maximize if bm.spec.objective.sense == "max" else pyo.minimize
    m.OBJ = pyo.Objective(expr=_expr(bm, m, bm.spec.objective.expr, {}), sense=sense)

    for c in bm.spec.constraints:
        block = pyo.ConstraintList()
        setattr(m, c.name, block)
        for g in forall_tuples(bm, c.forall):
            lhs = _expr(bm, m, c.lhs, g)
            rhs = _expr(bm, m, c.rhs, g)
            block.add(lhs <= rhs if c.rel == "<=" else lhs >= rhs if c.rel == ">=" else lhs == rhs)
        m._ir_index[c.name] = c.source_text
    return m


# ---------------------------------------------------------------- solving


KNOWN_SOLVERS = ("appsi_highs", "highs", "cbc", "glpk", "gurobi", "cplex")


def make_solver(name: str):
    """SolverFactory with a readable failure instead of Pyomo's ApplicationError."""
    opt = pyo.SolverFactory(name)
    try:
        ok = bool(opt.available(exception_flag=False))
    except TypeError:            # appsi interfaces take no exception_flag
        ok = bool(opt.available())
    except Exception:
        ok = False
    if not ok:
        raise RuntimeError(f"solver '{name}' is not installed or not licensed — "
                           f"try one of {', '.join(KNOWN_SOLVERS)}")
    return opt


def _shadow_prices(m: pyo.ConcreteModel, solver: str) -> dict:
    """Duals for the shadow-price column of the report.

    Duals only exist for an LP, so the sequence is: solve the MILP, fix the
    integer variables at their solution, re-solve as an LP, read m.dual[con].
    When EVERY variable is integer (a pure selection model like this one),
    fixing leaves no free variables and all duals are trivially zero — then we
    relax integrality instead and price the constraints in the LP relaxation.
    Either way the number reads as: objective gained per unit of extra rhs
    ("one more display slot is worth 0.9 carats").
    """
    lp = m.clone()
    all_vars = [v[i] for v in lp.component_objects(pyo.Var) for i in v]
    int_vars = [v for v in all_vars if v.is_integer() or v.is_binary()]
    if len(int_vars) < len(all_vars):
        basis = "fixed_integer_lp"
        for v in int_vars:
            v.fix(round(v.value))
    else:
        basis = "lp_relaxation"
    # Relax domains in both cases: a fixed var with an Integer domain still
    # makes the solver treat the model as a MIP, and MIPs have no duals.
    pyo.TransformationFactory("core.relax_integer_vars").apply_to(lp)

    lp.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    res = make_solver(solver).solve(lp)          # default loading fills the suffix
    if str(res.solver.termination_condition) not in ("optimal", "feasible"):
        return {"basis": basis, "values": {}}

    values = {}
    for name in m._ir_index:
        block = getattr(lp, name)
        strongest = 0.0
        for k in block:
            d = lp.dual.get(block[k])
            if d is not None and abs(d) > abs(strongest):
                strongest = float(d)
        values[name] = round(strongest, 6)
    return {"basis": basis, "values": values}


def solve(m: pyo.ConcreteModel, solver: str = "appsi_highs", tee: bool = False,
          duals: bool = True) -> dict:
    opt = make_solver(solver)
    res = opt.solve(m, tee=tee, load_solutions=False)
    status = str(res.solver.termination_condition)
    if status not in ("optimal", "feasible"):
        return {"status": status, "objective": None}
    m.solutions.load_from(res)

    picked = [i for i in m.x if pyo.value(m.x[i]) > 0.5]
    report = {"status": status, "objective": float(pyo.value(m.OBJ)), "selected": picked, "constraints": []}
    for name, text in m._ir_index.items():
        block = getattr(m, name)
        worst = None
        for k in block:
            con = block[k]
            body = pyo.value(con.body)
            ub, lb = con.upper, con.lower
            slack = min(v for v in
                        [(float(ub) - body) if ub is not None else None,
                         (body - float(lb)) if lb is not None else None] if v is not None)
            worst = slack if worst is None else min(worst, slack)
        report["constraints"].append(
            {"name": name, "source_text": text, "slack": round(float(worst), 4),
             "binding": abs(float(worst)) < 1e-6})

    if duals:
        sp = _shadow_prices(m, solver)
        report["shadow_price_basis"] = sp["basis"]
        for entry in report["constraints"]:
            entry["shadow_price"] = sp["values"].get(entry["name"])
    return report


def diagnose_infeasible(bm: BoundModel, solver: str = "appsi_highs") -> dict:
    """Elastic re-solve: give every constraint a slack variable, minimise total violation.
    The constraints that come back with non-zero slack are the ones the brief over-specified.
    This is what the repair loop reads to decide which `source_text` to raise with the user."""
    m = compile_model(bm)
    m.del_component(m.OBJ)
    m.s = pyo.Var(pyo.Set(initialize=[c.name for c in bm.spec.constraints]),
                  domain=pyo.NonNegativeReals)
    for c in bm.spec.constraints:
        block = getattr(m, c.name)
        for k in list(block):
            con = block[k]
            body, lo, up = con.body, con.lower, con.upper
            block[k].deactivate()
            if up is not None:
                block.add(body - m.s[c.name] <= float(up))
            if lo is not None:
                block.add(body + m.s[c.name] >= float(lo))
    m.OBJ = pyo.Objective(expr=sum(m.s[n] for n in m.s), sense=pyo.minimize)
    res = make_solver(solver).solve(m, load_solutions=False)
    if str(res.solver.termination_condition) not in ("optimal", "feasible"):
        return {"status": "elastic_failed"}
    m.solutions.load_from(res)
    return {"status": "infeasible",
            "violations": [{"constraint": c.name, "source_text": c.source_text,
                            "relax_by": round(float(pyo.value(m.s[c.name])), 3)}
                           for c in bm.spec.constraints if pyo.value(m.s[c.name]) > 1e-6]}
