"""Tests for portfolio_profiler.profile_for_portfolio."""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pytest

from portfolio_profiler import (
    CLARITY_ORDER,
    CUT_ORDER,
    DEFAULT_MARGIN_RATES,
    _clean_for_optimization,
    _dynamic_sample,
    profile_for_portfolio,
)

DIAMONDS_CSV = os.path.expanduser("~/Desktop/RiskOn2026/diamonds.csv")


def make_inventory(n: int = 200, seed: int = 1) -> pd.DataFrame:
    """Synthetic diamond-like inventory with valid rows only."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "carat": rng.uniform(0.2, 2.5, n).round(2),
        "cut": rng.choice(CUT_ORDER, n),
        "color": rng.choice(list("DEFGHIJ"), n),
        "clarity": rng.choice(CLARITY_ORDER, n),
        "depth": rng.uniform(55, 70, n).round(1),
        "table": rng.uniform(50, 70, n).round(1),
        "price": rng.integers(300, 19000, n).astype(float),
        "x": rng.uniform(3, 9, n).round(2),
        "y": rng.uniform(3, 9, n).round(2),
        "z": rng.uniform(2, 6, n).round(2),
    })


# ---------- dynamic sampling ----------

def test_small_data_gets_full_scan():
    df = make_inventory(500)
    assert len(_dynamic_sample(df)) == 500


def test_large_data_is_sampled_with_floor():
    # 10% of 30k is 3k, below the 10k floor -> expect exactly 10k
    df = make_inventory(30_000)
    assert len(_dynamic_sample(df)) == 10_000


def test_very_large_data_uses_ten_percent():
    df = make_inventory(200_000)
    assert len(_dynamic_sample(df)) == 20_000


def test_sampling_is_deterministic():
    df = make_inventory(30_000)
    a, b = _dynamic_sample(df, seed=0), _dynamic_sample(df, seed=0)
    pd.testing.assert_frame_equal(a, b)


# ---------- cleaning ----------

def test_overlapping_exclusion_criteria_do_not_double_count():
    df = make_inventory(30)
    df.loc[0, "price"] = 0        # fails cost AND (below) mass AND dimension
    df.loc[0, "carat"] = -1.0
    df.loc[0, "z"] = 0.0
    usable, excl = _clean_for_optimization(df, "price", "carat")
    assert excl["nonpositive_or_missing_cost"] == 1
    assert excl["nonpositive_or_missing_mass"] == 0   # already excluded by cost
    assert excl["zero_dimension_rows"] == 0
    assert sum(excl.values()) == 30 - len(usable) == 1


def test_cleaning_drops_bad_rows_and_reports_counts():
    df = make_inventory(50)
    df.loc[0, "price"] = 0          # nonpositive cost
    df.loc[1, "price"] = np.nan     # missing cost
    df.loc[2, "carat"] = -0.5       # nonpositive mass
    df.loc[3, "z"] = 0.0            # zero dimension
    df = pd.concat([df, df.iloc[[10]]], ignore_index=True)  # duplicate

    usable, excl = _clean_for_optimization(df, "price", "carat")

    assert excl["nonpositive_or_missing_cost"] == 2
    assert excl["nonpositive_or_missing_mass"] == 1
    assert excl["zero_dimension_rows"] == 1
    assert excl["duplicate_rows"] == 1
    assert len(usable) == 51 - 5
    assert sum(excl.values()) == 51 - len(usable)  # incremental counts are additive
    assert (usable["price"] > 0).all()
    assert (usable["carat"] > 0).all()
    assert (usable[["x", "y", "z"]] > 0).all().all()
    assert not usable.duplicated().any()


def test_cleaning_works_without_dimension_columns():
    df = make_inventory(20).drop(columns=["x", "y", "z"])
    usable, excl = _clean_for_optimization(df, "price", "carat")
    assert "zero_dimension_rows" not in excl
    assert len(usable) == 20


# ---------- report structure and semantics ----------

@pytest.fixture(scope="module")
def report():
    return profile_for_portfolio(make_inventory(1_000))


def test_report_is_json_serializable(report):
    json.dumps(report)  # raises TypeError on any numpy scalar leak


def test_cost_variable_stats_are_consistent(report):
    cost = report["cost_variable"]["unit_cost"]
    assert cost["min"] <= cost["median"] <= cost["p90"] <= cost["max"]
    assert report["cost_variable"]["total_cost_of_usable_pool"] > 0


def test_category_shares_sum_to_one(report):
    for col in ("cut", "clarity", "color"):
        shares = [v["pool_share"] for v in report["category_analysis"][col].values()]
        assert sum(shares) == pytest.approx(1.0, abs=0.01)


def test_share_caps_cover_every_observed_level(report):
    for col, levels in report["category_analysis"].items():
        caps = report["constraint_spec"]["category_share_caps"][col]
        assert set(caps) == set(levels)
        for cap in caps.values():
            assert cap["max_share_of_selection"] == 0.30
            assert cap["sense"] == "<="


def test_binding_risk_flags_match_pool_shares():
    # Force one dominant cut grade so its cap must be flagged as binding.
    df = make_inventory(1_000)
    df.loc[df.index[:600], "cut"] = "Ideal"
    r = profile_for_portfolio(df)
    caps = r["constraint_spec"]["category_share_caps"]["cut"]
    assert caps["Ideal"]["binding_risk"] == "structurally_binding"
    for level, cap in caps.items():
        share = r["category_analysis"]["cut"][level]["pool_share"]
        expected = "structurally_binding" if share > 0.30 else "slack_in_pool"
        assert cap["binding_risk"] == expected


def test_risk_tier_shares_sum_to_one(report):
    tiers = report["constraint_spec"]["risk_tier_bounds"]["pool_shares"]
    assert sum(tiers.values()) == pytest.approx(1.0, abs=0.01)
    assert set(tiers) <= {"low", "medium", "elevated", "high"}


def test_risk_tier_bounds_carry_binding_risk_flags(report):
    tiers = report["constraint_spec"]["risk_tier_bounds"]
    for tier, bound in tiers["suggested_bounds"].items():
        assert "binding_risk" in bound
        share = tiers["pool_shares"].get(tier)
        if share is None:
            assert bound["binding_risk"] == "tier_absent_from_pool"
        elif bound["sense"] == "<=":
            expected = ("structurally_binding"
                        if share > bound["max_share_of_selection"] else "slack_in_pool")
            assert bound["binding_risk"] == expected
        else:
            expected = ("structurally_binding"
                        if share < bound["min_share_of_selection"] else "slack_in_pool")
            assert bound["binding_risk"] == expected


def test_risk_tier_bounds_carry_binding_risk_flags(report):
    tiers = report["constraint_spec"]["risk_tier_bounds"]
    for tier, bound in tiers["suggested_bounds"].items():
        assert "binding_risk" in bound
        share = tiers["pool_shares"].get(tier)
        if share is None:
            assert bound["binding_risk"] == "tier_absent_from_pool"
        elif bound["sense"] == "<=":
            expected = "structurally_binding" if share > bound["max_share_of_selection"] \
                else "slack_in_pool"
            assert bound["binding_risk"] == expected
        else:
            expected = "structurally_binding" if share < bound["min_share_of_selection"] \
                else "slack_in_pool"
            assert bound["binding_risk"] == expected


def test_efficiency_metrics_are_positive(report):
    eff = report["efficiency"]
    assert eff["mass_per_cost_unit"]["median"] > 0
    # markup over the peer benchmark keeps the typical projected margin positive
    assert eff["margin_per_cost_unit"]["median"] > 0


def test_margin_per_cost_is_not_degenerate(report):
    # With the peer-benchmark margin, margin/cost varies per item; a
    # price-proportional margin would collapse it to the rate table.
    eff = report["efficiency"]["margin_per_cost_unit"]
    assert eff["p90"] > eff["median"]
    assert eff["p90"] not in DEFAULT_MARGIN_RATES.values()


def test_custom_margin_rates_and_unknown_cut_fallback():
    df = make_inventory(100)
    df.loc[df.index[:10], "cut"] = "Mystery"  # not in the rate table -> min(rates)
    lo = {"Ideal": 0.1, "Premium": 0.1, "Very Good": 0.1, "Good": 0.1, "Fair": 0.1}
    hi = {"Ideal": 0.5, "Premium": 0.5, "Very Good": 0.5, "Good": 0.5, "Fair": 0.5}
    r_lo = profile_for_portfolio(df, margin_rates=lo)
    r_hi = profile_for_portfolio(df, margin_rates=hi)
    json.dumps(r_lo)  # unknown cut must not break serialization
    # higher markup rates must raise the projected margin across the board
    assert (r_hi["efficiency"]["margin_per_cost_unit"]["median"]
            > r_lo["efficiency"]["margin_per_cost_unit"]["median"])


def test_budget_and_display_constraints_are_scaffolded(report):
    spec = report["constraint_spec"]
    assert spec["budget"]["variable"] == "price"
    assert spec["budget"]["sense"] == "<="
    assert spec["budget"]["value"] is None
    assert spec["display_slots"]["value"] is None


def test_missing_constraint_column_is_skipped():
    df = make_inventory(100).drop(columns=["color"])
    r = profile_for_portfolio(df)
    assert "color" not in r["category_analysis"]
    assert "color" not in r["constraint_spec"]["category_share_caps"]


# ---------- integration against the real dataset ----------

@pytest.mark.skipif(not os.path.exists(DIAMONDS_CSV), reason="diamonds.csv not present")
def test_real_diamonds_csv_end_to_end():
    df = pd.read_csv(DIAMONDS_CSV)
    r = profile_for_portfolio(df)
    assert r["sampling"]["total_rows"] == len(df)
    assert r["sampling"]["sampled_rows"] == 10_000
    assert r["sampling"]["usable_rows_after_cleaning"] <= 10_000
    json.dumps(r)
    # the known dominant grade in this dataset must be flagged
    caps = r["constraint_spec"]["category_share_caps"]["cut"]
    assert caps["Ideal"]["binding_risk"] == "structurally_binding"
