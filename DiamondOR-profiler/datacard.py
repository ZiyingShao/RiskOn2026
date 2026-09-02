"""DataCard emission: the profiler's two run artifacts.

runs/<run_id>/
  01_card.json   full DataCard — every column, every stat, relevance scores
  01_card.txt    rendered prompt view, built ONLY from the card's `keep` list

The .json is the audit artifact; the .txt is what goes into the LLM prompt.
The .txt is always derived from the .json by `render_card` — one render
function, so the two artifacts cannot disagree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from portfolio_profiler import (
    CLARITY_ORDER,
    COLOR_ORDER,
    CUT_ORDER,
    profile_for_portfolio,
)

KEEP_THRESHOLD = 0.5


def _relevance(name: str, stats: dict, cost_col: str, mass_col: str,
               constraint_cols: tuple, redundant_with_mass: set) -> tuple[str, float, str]:
    """Assign (role, score, reason) for one column."""
    if name == cost_col:
        return "cost", 1.0, "unit acquisition cost (budget consumer)"
    if name == mass_col:
        return "objective", 1.0, "objective mass"
    if name in constraint_cols:
        return "constraint", 0.9, "categorical exposure constraint"
    if stats.get("is_constant"):
        return "feature", 0.0, "constant column"
    if name in redundant_with_mass:
        return "feature", 0.2, f"strongly correlated with {mass_col} (redundant)"
    if stats.get("null_rate", 0) > 0.5:
        return "feature", 0.1, "mostly missing"
    return "feature", 0.3, "no assigned role in this scenario"


def build_card(
    df: pd.DataFrame,
    run_id: str,
    cost_col: str = "price",
    mass_col: str = "carat",
    constraint_cols: tuple = ("cut", "clarity", "color"),
    max_category_share: float = 0.30,
    seed: int = 0,
) -> dict:
    """Build the full DataCard from a raw inventory table."""
    report = profile_for_portfolio(
        df, cost_col=cost_col, mass_col=mass_col,
        constraint_cols=constraint_cols,
        max_category_share=max_category_share, seed=seed,
    )

    redundant = set()
    for pair in report["base_profile"].get("strong_correlations", []):
        a, b = pair["columns"]
        if mass_col in (a, b):
            redundant.add(b if a == mass_col else a)

    columns = {}
    for name, stats in report["base_profile"]["columns"].items():
        role, score, reason = _relevance(
            name, stats, cost_col, mass_col, constraint_cols, redundant)
        columns[name] = {
            "role": role,
            "relevance": score,
            "relevance_reason": reason,
            **stats,
        }

    order = list(df.columns)
    keep = sorted(
        (n for n, c in columns.items() if c["relevance"] >= KEEP_THRESHOLD),
        key=lambda n: (-columns[n]["relevance"], order.index(n)),
    )

    notes = []
    for col, caps in report["constraint_spec"]["category_share_caps"].items():
        for level, cap in caps.items():
            if cap["binding_risk"] == "structurally_binding":
                share = report["category_analysis"][col][level]["pool_share"]
                notes.append(
                    f"{level} {col} is {share:.1%} of pool: any per-level cap "
                    f"<= {max_category_share:.0%} is structurally binding."
                )
    tiers = report["constraint_spec"]["risk_tier_bounds"]
    for tier, bound in tiers.get("suggested_bounds", {}).items():
        cap = bound.get("max_share_of_selection")
        share = tiers["pool_shares"].get(tier)
        if cap is not None and share is not None and share > cap:
            notes.append(
                f"'{tier}' risk tier is {share:.1%} of pool: "
                f"the suggested {cap:.0%} cap will bind."
            )

    return {
        "run_id": run_id,
        "dataset": {
            "name": "inventory",
            "total_rows": report["sampling"]["total_rows"],
            "usable_rows": report["sampling"]["usable_rows_after_cleaning"],
            "excluded": report["sampling"]["excluded"],
            "row_unit": "1 row = 1 item",
        },
        "columns": columns,
        "keep": keep,
        "category_analysis": report["category_analysis"],
        "risk_tiers": report["constraint_spec"]["risk_tier_bounds"],
        "constraint_spec": report["constraint_spec"],
        "notes": notes,
    }


# ---------- rendering (json -> txt) ----------

def _num(v: float) -> str:
    if v is None:
        return "?"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:.1f}".rstrip("0").rstrip(".")
    return f"{v:.2f}".rstrip("0").rstrip(".")


_LEVEL_ORDERS = {"cut": CUT_ORDER, "clarity": CLARITY_ORDER, "color": COLOR_ORDER}


def _column_line(name: str, col: dict, card: dict, width: int) -> str:
    pad = name.ljust(width)
    tag = f"[{col['role']}]".ljust(12)
    if name in card["category_analysis"]:
        levels = card["category_analysis"][name]
        ordered = _LEVEL_ORDERS.get(name)
        keys = [k for k in ordered if k in levels] if ordered else list(levels)
        shares = " | ".join(f"{k} {levels[k]['pool_share']:.3f}" for k in keys)
        kind = f"categorical ({len(keys)}"
        kind += ", ordered best->worst)" if ordered else ")"
        return f"{pad} {tag} {kind}  {shares}"
    ns = col.get("numeric_stats")
    if ns:
        q = ns.get("quantiles", {})
        parts = [f"min {_num(ns['min'])}", f"median {_num(ns['median'])}"]
        if "p90" in q:
            parts.append(f"p90 {_num(q['p90'])}")
        parts.append(f"max {_num(ns['max'])}")
        return f"{pad} {tag} numeric  " + " | ".join(parts)
    return f"{pad} {tag} {col.get('inferred_type', 'unknown')}"


def render_card(card: dict) -> str:
    """Deterministically render the prompt view from the `keep` columns only."""
    ds = card["dataset"]
    excluded = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in ds["excluded"].items() if v)
    lines = [
        f"DATASET: {ds['name']} ({ds['usable_rows']:,} usable rows; {ds['row_unit']})",
    ]
    if excluded:
        lines.append(f"Excluded during cleaning: {excluded}")
    lines.append("")

    width = max(len(n) for n in card["keep"])
    for name in card["keep"]:
        lines.append(_column_line(name, card["columns"][name], card, width))

    tiers = card.get("risk_tiers", {})
    if tiers.get("pool_shares"):
        defs = tiers["definition"]
        parts = " | ".join(
            f"{t}={{{','.join(defs[t])}}} {share:.3f}"
            for t, share in tiers["pool_shares"].items()
        )
        lines += ["", f"RISK TIERS (clarity): {parts}"]

    if card.get("notes"):
        lines += ["", "NOTES"]
        lines += [f"- {n}" for n in card["notes"]]

    return "\n".join(lines) + "\n"


def emit(df: pd.DataFrame, run_id: str, out_dir: str | Path = "runs", **kwargs) -> Path:
    """Write both artifacts for one run; returns the run directory."""
    card = build_card(df, run_id, **kwargs)
    run_dir = Path(out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "01_card.json").write_text(json.dumps(card, indent=2) + "\n")
    (run_dir / "01_card.txt").write_text(render_card(card))
    return run_dir


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "diamonds.csv"
    run_id = sys.argv[2] if len(sys.argv) > 2 else "demo"
    run_dir = emit(pd.read_csv(path), run_id)
    print(f"wrote {run_dir}/01_card.json and 01_card.txt\n")
    print((run_dir / "01_card.txt").read_text())
