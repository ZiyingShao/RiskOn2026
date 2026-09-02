"""Portfolio-oriented profiler for the vault-stocking problem.

Scenario: a jeweler deploys a fixed line of credit to stock a retail vault.
The optimizer downstream needs: `price` treated as the unit cost, an objective
(total carats or projected margin), and the qualitative columns (cut, clarity,
color) translated into bounded exposure constraints. This module profiles a
raw CSV into that machine-readable optimization spec.
"""

from __future__ import annotations

import json
import sys
import numpy as np
import pandas as pd

from profiler import profile_table

# GIA-style quality orderings, best -> worst. Used for risk tiering.
CUT_ORDER = ["Ideal", "Premium", "Very Good", "Good", "Fair"]
CLARITY_ORDER = ["IF", "VVS1", "VVS2", "VS1", "VS2", "SI1", "SI2", "I1"]
COLOR_ORDER = list("DEFGHIJ")

CLARITY_RISK_TIER = {
    "IF": "low", "VVS1": "low", "VVS2": "low",
    "VS1": "medium", "VS2": "medium",
    "SI1": "elevated", "SI2": "elevated",
    "I1": "high",
}

# Assumed retail markup rates by cut grade, applied over the peer-benchmark
# retail estimate. Placeholders for the jeweler's real markup table — override
# via margin_rates.
DEFAULT_MARGIN_RATES = {
    "Ideal": 0.22, "Premium": 0.20, "Very Good": 0.17, "Good": 0.14, "Fair": 0.11,
}

# Columns defining an item's pricing peer group for the retail benchmark.
PEER_GROUP_COLS = ("cut", "color", "clarity")


def _dynamic_sample(df: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Sample size scales with the data: full scan below 10k rows, then 10%
    of rows floored at 10k and capped at 50k."""
    n = len(df)
    if n <= 10_000:
        return df
    size = int(min(max(10_000, 0.10 * n), 50_000))
    return df.sample(size, random_state=seed)


def _share_table(series: pd.Series, order: list[str] | None = None) -> dict:
    shares = series.value_counts(normalize=True)
    if order:
        # Known levels in canonical order, unexpected ones appended — never
        # dropped, so the shares always sum to 1.
        known = [v for v in order if v in shares.index]
        extra = [v for v in shares.index if v not in order]
        shares = shares.reindex(known + extra)
    return {str(k): round(float(v), 4) for k, v in shares.items()}


def _projected_margin(usable: pd.DataFrame, cost_col: str, mass_col: str,
                      margin_rates: dict) -> pd.Series:
    """Projected margin per item: peer-benchmark retail estimate minus cost.

    Retail estimate = (peer-group median cost per mass unit) * item mass
    * (1 + markup rate for its cut). The benchmark makes the margin depend on
    how the item is priced against comparable stock, not just on its price —
    a price-proportional margin would make margin/cost a constant.
    """
    per_mass = usable[cost_col] / usable[mass_col]
    peer_cols = [c for c in PEER_GROUP_COLS if c in usable.columns]
    if peer_cols:
        benchmark = per_mass.groupby([usable[c] for c in peer_cols]).transform("median")
    else:
        benchmark = pd.Series(per_mass.median(), index=usable.index)
    if "cut" in usable.columns:
        rate = usable["cut"].map(margin_rates).fillna(min(margin_rates.values()))
    else:
        rate = min(margin_rates.values())
    retail_estimate = benchmark * usable[mass_col] * (1.0 + rate)
    return retail_estimate - usable[cost_col]


def _clean_for_optimization(df: pd.DataFrame, cost_col: str, mass_col: str) -> tuple[pd.DataFrame, dict]:
    """Drop rows unusable as decision variables; report what was excluded.

    Counts are incremental — a row failing several criteria is counted only
    under the first — so the exclusion counts always sum to the rows removed."""
    exclusions = {}
    mask = pd.Series(True, index=df.index)

    bad_cost = (df[cost_col].isna()) | (df[cost_col] <= 0)
    exclusions["nonpositive_or_missing_cost"] = int((bad_cost & mask).sum())
    mask &= ~bad_cost

    bad_mass = (df[mass_col].isna()) | (df[mass_col] <= 0)
    exclusions["nonpositive_or_missing_mass"] = int((bad_mass & mask).sum())
    mask &= ~bad_mass

    # Diamonds with any zero physical dimension are data errors, not stock.
    dim_cols = [c for c in ("x", "y", "z") if c in df.columns]
    if dim_cols:
        bad_dims = (df[dim_cols] <= 0).any(axis=1)
        exclusions["zero_dimension_rows"] = int((bad_dims & mask).sum())
        mask &= ~bad_dims

    dupes = df.duplicated()
    exclusions["duplicate_rows"] = int((dupes & mask).sum())
    mask &= ~dupes

    return df[mask], exclusions


def profile_for_portfolio(
    df: pd.DataFrame,
    cost_col: str = "price",
    mass_col: str = "carat",
    constraint_cols: tuple[str, ...] = ("cut", "clarity", "color"),
    max_category_share: float = 0.30,
    margin_rates: dict | None = None,
    seed: int = 0,
) -> dict:
    """Profile a raw inventory table into an optimization-ready spec.

    Returns a dict with: a base data profile (sampled dynamically), cost and
    objective statistics, per-category efficiency, and a constraint_spec whose
    caps the optimizer can consume directly.
    """
    margin_rates = margin_rates or DEFAULT_MARGIN_RATES

    sample = _dynamic_sample(df, seed=seed)
    usable, exclusions = _clean_for_optimization(sample, cost_col, mass_col)

    margin = _projected_margin(usable, cost_col, mass_col, margin_rates)

    cost = usable[cost_col]
    mass = usable[mass_col]

    report = {
        "scenario": {
            "role_of_price": "unit acquisition cost (budget consumer)",
            "objectives": {
                "maximize_total_mass": f"sum of `{mass_col}` over selected items",
                "maximize_projected_margin": "sum of (retail estimate - price); retail estimate = "
                                             "peer-group median price-per-mass * mass * (1 + markup_rate(cut)); "
                                             "markup rates are assumptions, override with the house markup table",
            },
        },
        "sampling": {
            "total_rows": len(df),
            "sampled_rows": len(sample),
            "usable_rows_after_cleaning": len(usable),
            "excluded": exclusions,
        },
        "base_profile": profile_table(sample, name="inventory", max_rows=None),
        "cost_variable": {
            "column": cost_col,
            "total_cost_of_usable_pool": float(cost.sum()),
            "unit_cost": {
                "min": float(cost.min()), "median": float(cost.median()),
                "mean": float(cost.mean()), "p90": float(cost.quantile(0.9)),
                "max": float(cost.max()),
            },
        },
        "efficiency": {
            "mass_per_cost_unit": {
                "median": float((mass / cost).median()),
                "p90": float((mass / cost).quantile(0.9)),
            },
            "margin_per_cost_unit": {
                "median": float((margin / cost).median()),
                "p90": float((margin / cost).quantile(0.9)),
            },
        },
    }

    # Per-category exposure analysis + efficiency, for each constraint column.
    orders = {"cut": CUT_ORDER, "clarity": CLARITY_ORDER, "color": COLOR_ORDER}
    category_analysis = {}
    for col in constraint_cols:
        if col not in usable.columns:
            continue
        grouped = usable.groupby(col)
        stats = pd.DataFrame({
            "count": grouped.size(),
            "pool_share": grouped.size() / len(usable),
            "avg_cost": grouped[cost_col].mean(),
            "avg_mass": grouped[mass_col].mean(),
            "mass_per_cost": grouped[[mass_col, cost_col]].apply(
                lambda g: (g[mass_col] / g[cost_col]).median()
            ),
        })
        order = orders.get(col)
        if order:
            stats = stats.reindex([v for v in order if v in stats.index])
        category_analysis[col] = {
            str(level): {
                "count": int(r["count"]),
                "pool_share": round(float(r["pool_share"]), 4),
                "avg_cost": round(float(r["avg_cost"]), 2),
                "avg_mass": round(float(r["avg_mass"]), 3),
                "median_mass_per_cost": round(float(r["mass_per_cost"]), 6),
            }
            for level, r in stats.iterrows()
        }
    report["category_analysis"] = category_analysis

    # Machine-readable constraint scaffold for the optimizer.
    constraint_spec = {
        "budget": {
            "variable": cost_col,
            "sense": "<=",
            "value": None,  # set to the credit line when known
            "note": "sum(price of selected) <= line of credit",
        },
        "display_slots": {
            "variable": "selection_count",
            "sense": "<=",
            "value": None,  # set to physical display-case capacity
            "note": "number of selected items <= display case capacity",
        },
        "category_share_caps": {
            col: {
                str(level): {
                    "sense": "<=",
                    "max_share_of_selection": max_category_share,
                    "binding_risk": (
                        "structurally_binding"
                        if info["pool_share"] > max_category_share
                        else "slack_in_pool"
                    ),
                }
                for level, info in category_analysis[col].items()
            }
            for col in category_analysis
        },
        "risk_tier_bounds": {
            "definition": {t: [g for g, tier in CLARITY_RISK_TIER.items() if tier == t]
                           for t in ("low", "medium", "elevated", "high")},
            "pool_shares": _share_table(
                usable["clarity"].map(CLARITY_RISK_TIER), ["low", "medium", "elevated", "high"]
            ) if "clarity" in usable.columns else {},
            "suggested_bounds": {
                "high": {"sense": "<=", "max_share_of_selection": 0.05},
                "elevated": {"sense": "<=", "max_share_of_selection": 0.35},
                "low": {"sense": ">=", "min_share_of_selection": 0.20},
            },
            "note": "clarity grades mapped to resale-risk tiers; bounds are "
                    "starting points for the risk committee to adjust",
        },
    }
    # Same sanity flag the category caps get: a <= cap below the tier's pool
    # share, or a >= floor above it, will bind structurally.
    tiers = constraint_spec["risk_tier_bounds"]
    for tier, bound in tiers["suggested_bounds"].items():
        share = tiers["pool_shares"].get(tier)
        if share is None:
            bound["binding_risk"] = "tier_absent_from_pool"
        elif bound["sense"] == "<=":
            bound["binding_risk"] = ("structurally_binding"
                                     if share > bound["max_share_of_selection"] else "slack_in_pool")
        else:
            bound["binding_risk"] = ("structurally_binding"
                                     if share < bound["min_share_of_selection"] else "slack_in_pool")
    report["constraint_spec"] = constraint_spec

    return report


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "diamonds.csv"
    df = pd.read_csv(path)
    print(json.dumps(profile_for_portfolio(df), indent=2))
