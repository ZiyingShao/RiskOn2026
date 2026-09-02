"""Structural translation fidelity.

Compare a generated IR to the reference IR constraint by constraint — but not
by diffing JSON: the model may write the same constraint differently and be
right. Instead each constraint is compiled ALONE into its coefficient rows
over the bound data, the rows are canonicalized, and equal rows are the same
constraint regardless of naming.

Canonical row: move everything to the LHS of `<=`, so a row is
    {(canonical_var, row_index): coef}  <=  const
- ">=" rows are negated into "<="; "==" rows keep an "eq" tag and a canonical
  sign (first nonzero coefficient positive).
- The whole row is scaled by 1/max|coef| — writing "10*a <= 3*b" instead of
  "a <= 0.3*b" must not change the fingerprint.
- Variable NAMES are canonicalized by signature (domain + index-set sizes),
  so `x` in one spec matches `pick` in another.
- Coefficients are rounded to 9 decimals and the sorted row is sha1-hashed.

recall    = reference rows with a generated counterpart   (1 - missed)
precision = generated rows with a reference counterpart   (1 - invented)

Both specs must be bound to the SAME data (same csv, sample n, seed) — the
harness normalizes `tables` before calling in here.
"""

from __future__ import annotations

import hashlib
import itertools
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "IR_Compiler"))

from ir import ModelSpec, LinExpr, ConstraintDef            # noqa: E402
from validate import forall_tuples, select_members, dims, weight_lookup              # noqa: E402
from compiler import bind, BoundModel                        # noqa: E402

ROUND = 9


def _canonical_var_names(spec: ModelSpec, bm: BoundModel) -> dict[str, str]:
    """Map real var names to signature-based canonical names, so two specs
    that call the selection variable different things still compare equal."""
    sigs = []
    for v in spec.vars:
        sig = (v.domain, tuple(sorted(len(bm.sets[s]) for s in v.index)))
        sigs.append((sig, v.name))
    mapping = {}
    seen: Counter = Counter()
    for sig, name in sorted(sigs):
        mapping[name] = f"v{sig}#{seen[sig]}"
        seen[sig] += 1
    return mapping


def _row(bm: BoundModel, varmap: dict, lhs: LinExpr, rhs: LinExpr,
         rel: str, binding: dict) -> tuple | None:
    """One constraint instance -> (tag, ((key, coef), ...), const), canonical."""
    coeffs: dict[tuple, float] = {}
    const = 0.0

    def add(e: LinExpr, sign: float) -> None:
        """Mirrors compiler._expr exactly — N-dimensional, sharing select_members
        and weight_lookup with it, so the grader and the solver cannot disagree
        about what a term means."""
        nonlocal const
        const -= sign * e.const
        for t in e.terms:
            axes = dims(t)
            if not axes:                                   # scalar constant / param
                w = bm.params.get(t.weight) if t.weight else None
                const -= sign * t.coef * (float(w) if w is not None else 1.0)
                continue
            axis_sets = [d.set for d in axes]
            wf = weight_lookup(bm, t.weight, axis_sets)
            members = [select_members(bm, d, binding) for d in axes]
            for combo in itertools.product(*members):
                val = sign * t.coef * wf(combo)
                if t.var is None:                          # data aggregate
                    const -= val
                else:
                    key = (varmap[t.var], combo[0] if len(combo) == 1 else combo)
                    coeffs[key] = coeffs.get(key, 0.0) + val

    add(lhs, +1.0)
    add(rhs, -1.0)

    coeffs = {k: c for k, c in coeffs.items() if abs(c) > 1e-12}
    if not coeffs:
        return None                                    # vacuous row
    if rel == ">=":
        coeffs = {k: -c for k, c in coeffs.items()}
        const = -const
        tag = "le"
    elif rel == "<=":
        tag = "le"
    else:
        tag = "eq"
        first = min(coeffs)
        if coeffs[first] < 0:
            coeffs = {k: -c for k, c in coeffs.items()}
            const = -const

    scale = max(abs(c) for c in coeffs.values())
    items = tuple(sorted((k, round(c / scale, ROUND)) for k, c in coeffs.items()))
    return (tag, items, round(const / scale, ROUND))


def _hash(row: tuple) -> str:
    return hashlib.sha1(repr(row).encode()).hexdigest()[:16]


def constraint_rows(spec: ModelSpec, bm: BoundModel,
                    c: ConstraintDef, varmap: dict) -> set[str]:
    hashes = set()
    for g in forall_tuples(bm, c.forall):
        row = _row(bm, varmap, c.lhs, c.rhs, c.rel, g)
        if row is not None:
            hashes.add(_hash(row))
    return hashes


def spec_fingerprints(spec: ModelSpec, root: str) -> dict:
    """{'rows': {hash: constraint_name}, 'objective': hash, 'bm': BoundModel}"""
    bm = bind(spec, root=root)
    varmap = _canonical_var_names(spec, bm)
    rows: dict[str, str] = {}
    for c in spec.constraints:
        for h in constraint_rows(spec, bm, c, varmap):
            rows[h] = c.name
    obj = _row(bm, varmap, spec.objective.expr, LinExpr(), "==", {})
    sense = spec.objective.sense
    # a min of -f is the same objective as a max of f
    obj_hash = _hash(("obj", sense, obj)) if obj else None
    return {"rows": rows, "objective": obj_hash, "bm": bm}


def compare(gen: ModelSpec, ref: ModelSpec, root: str) -> dict:
    g = spec_fingerprints(gen, root)
    r = spec_fingerprints(ref, root)
    gset, rset = set(g["rows"]), set(r["rows"])
    matched = gset & rset
    missed = sorted({r["rows"][h] for h in rset - matched})
    invented = sorted({g["rows"][h] for h in gset - matched})
    return {
        "recall": len(matched & rset) / len(rset) if rset else 1.0,
        "precision": len(matched) / len(gset) if gset else 0.0,
        "objective_match": g["objective"] == r["objective"],
        "missed_reference_constraints": missed,
        "invented_generated_constraints": invented,
        "reference_rows": len(rset),
        "generated_rows": len(gset),
    }
