"""
validate.py — checkpoints 2 and 3.

Both hand-written checks live here because they are the same concern: producing
IRError objects for the repair loop. The repair node imports this one module.

  checkpoint 2   validate(spec)     meaning — names resolve, $SET bound, no empty exprs
                                    needs the JSON alone, cross-referenced
  checkpoint 3   check_bound(bm)    data — columns exist, filters match rows
                                    needs the JSON + the bound dataframes

(Checkpoint 1 — shape — is generated from ir.py: `ModelSpec.model_validate(json)`.)

Also home to the pure-pandas row selection (`select_rows`, `forall_tuples`),
which checkpoint 3 and the compiler both need. Imports run one way only:

    ir.py  <-  validate.py  <-  compiler.py

so this module needs pandas but never Pyomo — the repair node runs without a
solver installed. That is the practical test that the split is clean.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
import pandas as pd

from ir import ModelSpec, LinExpr, IndexRef

if TYPE_CHECKING:
    from compiler import BoundModel

# ---------------------------------------------------------------- errors


@dataclass
class IRError:
    code: str          # machine-readable; this is what the repair loop switches on
    location: str      # JSON-ish path into the spec
    message: str
    fix: str = ""      # suggested repair, fed back to the LLM verbatim

    def __str__(self) -> str:
        return f"[{self.code}] {self.location}: {self.message}" + (f"  -> {self.fix}" if self.fix else "")


class BindError(Exception):
    """Raised by bind() when the data contradicts the spec (missing column, bad
    derived expression, unreadable table). Carries IRErrors so the repair loop
    sees the same shape as checkpoints 2 and 3."""

    def __init__(self, errors: list[IRError]):
        self.errors = errors
        super().__init__("; ".join(str(e) for e in errors))


# ---------------------------------------------------------------- checkpoint 2: meaning


def validate(spec: ModelSpec) -> list[IRError]:
    errs: list[IRError] = []
    tables = {t.name for t in spec.tables}
    sets = {s.name: s for s in spec.sets}
    params = {p.name: p for p in spec.params}
    varnames = {v.name for v in spec.vars}

    for s in spec.sets:
        if s.table not in tables:
            errs.append(IRError("UNKNOWN_TABLE", f"sets.{s.name}.table",
                                f"table '{s.table}' is not declared",
                                f"declare it in `tables` or use one of {sorted(tables)}"))
        if s.kind == "categories" and not s.column:
            errs.append(IRError("MISSING_COLUMN", f"sets.{s.name}",
                                "a categories set needs a `column`", "set `column` to a categorical column"))

    for p in spec.params:
        if p.index and not p.column:
            errs.append(IRError("UNBOUND_PARAM", f"params.{p.name}",
                                "indexed parameter has no source column",
                                "add `table` and `column`, or drop the index"))
        if not p.index and p.value is None and not p.column:
            errs.append(IRError("UNBOUND_PARAM", f"params.{p.name}",
                                "scalar parameter has no value", "add `value`"))
        if p.index and p.column and not p.table:
            errs.append(IRError("UNBOUND_PARAM", f"params.{p.name}",
                                "indexed parameter has a `column` but no `table`", "add `table`"))
        if p.table and p.table not in tables:
            errs.append(IRError("UNKNOWN_TABLE", f"params.{p.name}.table",
                                f"table '{p.table}' is not declared",
                                f"declare it in `tables` or use one of {sorted(tables)}"))
        for ix in p.index:
            if ix not in sets:
                errs.append(IRError("UNKNOWN_SET", f"params.{p.name}.index", f"undefined set '{ix}'", ""))

    for v in spec.vars:
        for ix in v.index:
            if ix not in sets:
                errs.append(IRError("UNKNOWN_SET", f"vars.{v.name}.index", f"undefined set '{ix}'", ""))

    def check_expr(e: LinExpr, loc: str, bound_sets: set[str]) -> None:
        if not e.terms and e.const == 0.0:
            errs.append(IRError("EMPTY_EXPR", loc, "expression has no terms and no constant", ""))
        for k, t in enumerate(e.terms):
            tl = f"{loc}.terms[{k}]"
            if t.var and t.var not in varnames:
                errs.append(IRError("UNKNOWN_VAR", tl, f"undefined variable '{t.var}'",
                                    f"use one of {sorted(varnames)}"))
            if t.weight and t.weight not in params:
                errs.append(IRError("UNKNOWN_PARAM", tl, f"undefined parameter '{t.weight}'",
                                    f"declare '{t.weight}' in `params` or bind it to a column"))
            if t.var and t.over is None:
                errs.append(IRError("SCALAR_VAR", tl, "variables must be summed over an index set",
                                    "add an `over` clause"))
            if t.over:
                if t.over.set not in sets:
                    errs.append(IRError("UNKNOWN_SET", tl, f"undefined set '{t.over.set}'", ""))
                for pr in t.over.where:
                    if isinstance(pr.value, str) and pr.value.startswith("$"):
                        tgt = pr.value[1:]
                        if tgt not in bound_sets:
                            errs.append(IRError("UNBOUND_INDEX", tl,
                                                f"'{pr.value}' is not bound by this constraint's `forall`",
                                                f"add '{tgt}' to `forall`, or use a literal value"))

    check_expr(spec.objective.expr, "objective.expr", set())
    for c in spec.constraints:
        for g in c.forall:
            if g not in sets:
                errs.append(IRError("UNKNOWN_SET", f"constraints.{c.name}.forall", f"undefined set '{g}'", ""))
        check_expr(c.lhs, f"constraints.{c.name}.lhs", set(c.forall))
        check_expr(c.rhs, f"constraints.{c.name}.rhs", set(c.forall))
        if not c.source_text.strip():
            errs.append(IRError("NO_PROVENANCE", f"constraints.{c.name}",
                                "constraint has no source_text",
                                "quote the sentence from the brief this constraint encodes"))
    return errs


# ---------------------------------------------------------------- row selection

_OPS = {
    "eq":  lambda col, v: col == v,
    "ne":  lambda col, v: col != v,
    "in":  lambda col, v: col.isin(v),
    "gte": lambda col, v: col >= v,
    "lte": lambda col, v: col <= v,
    "gt":  lambda col, v: col > v,
    "lt":  lambda col, v: col < v,
}


def forall_tuples(bm: "BoundModel", forall: list[str]) -> list[dict[str, Any]]:
    if not forall:
        return [{}]
    import itertools
    return [dict(zip(forall, combo)) for combo in itertools.product(*[bm.sets[g] for g in forall])]


def select_rows(bm: "BoundModel", ref: IndexRef, binding: dict[str, Any]) -> list:
    sdef = next(s for s in bm.spec.sets if s.name == ref.set)
    df = bm.frames[sdef.table]
    mask = pd.Series(True, index=df.index)
    for pr in ref.where:
        val = pr.value
        if isinstance(val, str) and val.startswith("$"):
            val = binding[val[1:]]
        mask &= _OPS[pr.op](df[pr.column], val)
    return list(df.index[mask])


# ---------------------------------------------------------------- checkpoint 3: data


def check_bound(bm: "BoundModel") -> list[IRError]:
    errs: list[IRError] = []
    exprs = [("objective.expr", [], bm.spec.objective.expr)]
    for c in bm.spec.constraints:
        exprs.append((f"constraints.{c.name}.lhs", c.forall, c.lhs))
        exprs.append((f"constraints.{c.name}.rhs", c.forall, c.rhs))

    for loc, forall, e in exprs:
        for k, t in enumerate(e.terms):
            if not t.over:
                continue
            sdef = next(s for s in bm.spec.sets if s.name == t.over.set)
            df = bm.frames[sdef.table]
            tl = f"{loc}.terms[{k}]"
            missing = [pr.column for pr in t.over.where if pr.column not in df.columns]
            if missing:
                errs.append(IRError("UNKNOWN_COLUMN", tl,
                                    f"no column(s) {missing} in table '{sdef.table}'",
                                    f"use one of {list(df.columns)}"))
                continue  # select_rows would KeyError on these predicates
            if not t.over.where:
                continue  # an unfiltered sum can't be empty unless the table is
            for g in forall_tuples(bm, forall):
                if len(select_rows(bm, t.over, g)) == 0:
                    errs.append(IRError(
                        "EMPTY_SELECTION", tl,
                        f"filter selects no rows for {g or '()'} — constraint is vacuous or infeasible",
                        "widen the filter, or raise the sample size"))
    return errs
