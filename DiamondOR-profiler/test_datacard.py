"""Tests for datacard.build_card / render_card / emit."""

from __future__ import annotations

import json
import os

import pandas as pd
import pytest

from datacard import KEEP_THRESHOLD, build_card, emit, render_card
from test_portfolio_profiler import make_inventory

DIAMONDS_CSV = os.path.expanduser("~/Desktop/RiskOn2026/diamonds.csv")


@pytest.fixture(scope="module")
def df():
    return make_inventory(1_000)


@pytest.fixture(scope="module")
def card(df):
    return build_card(df, run_id="test-run")


# ---------- relevance and keep ----------

def test_roles_and_scores(card):
    assert card["columns"]["price"]["role"] == "cost"
    assert card["columns"]["carat"]["role"] == "objective"
    for col in ("cut", "clarity", "color"):
        assert card["columns"][col]["role"] == "constraint"
    assert card["columns"]["depth"]["relevance"] < KEEP_THRESHOLD


def test_keep_holds_only_scenario_columns(card):
    assert set(card["keep"]) == {"price", "carat", "cut", "clarity", "color"}
    # ordered by relevance: cost/objective (1.0) before constraints (0.9)
    assert card["keep"][:2] == ["carat", "price"] or card["keep"][:2] == ["price", "carat"]
    assert card["keep"][0] in ("price", "carat")


def test_every_column_is_in_the_json_card(card, df):
    assert set(card["columns"]) == set(df.columns)


def test_redundant_numeric_is_downweighted():
    d = make_inventory(500)
    d["carat_copy"] = d["carat"] * 2  # perfectly correlated with the mass col
    c = build_card(d, run_id="redundancy")
    assert c["columns"]["carat_copy"]["relevance"] < KEEP_THRESHOLD
    assert "correlated" in c["columns"]["carat_copy"]["relevance_reason"]


# ---------- rendering ----------

def test_txt_contains_only_keep_columns(card):
    txt = render_card(card)
    for name in card["keep"]:
        assert name in txt
    # dropped columns must not appear as column lines
    for dropped in ("depth", "table"):
        assert f"\n{dropped} " not in txt


def test_txt_enumerates_all_categorical_levels(card):
    txt = render_card(card)
    for level in ("Ideal", "Premium", "Very Good", "Good", "Fair"):
        assert level in txt
    for level in ("IF", "VVS1", "I1"):
        assert level in txt


def test_txt_has_dataset_header_and_risk_tiers(card):
    txt = render_card(card)
    assert txt.startswith("DATASET: inventory")
    assert "RISK TIERS (clarity):" in txt


def test_render_is_deterministic(card):
    assert render_card(card) == render_card(card)


def test_binding_note_appears_when_pool_is_dominated():
    d = make_inventory(1_000)
    d.loc[d.index[:600], "cut"] = "Ideal"
    c = build_card(d, run_id="dominated")
    txt = render_card(c)
    assert any("structurally binding" in n for n in c["notes"])
    assert "structurally binding" in txt


# ---------- emission and round trip ----------

def test_emit_writes_exactly_two_artifacts(df, tmp_path):
    run_dir = emit(df, run_id="r1", out_dir=tmp_path)
    assert sorted(p.name for p in run_dir.iterdir()) == ["01_card.json", "01_card.txt"]


def test_txt_round_trips_from_json(df, tmp_path):
    # re-rendering the stored json must reproduce the stored txt byte-for-byte
    run_dir = emit(df, run_id="r2", out_dir=tmp_path)
    stored_card = json.loads((run_dir / "01_card.json").read_text())
    assert render_card(stored_card) == (run_dir / "01_card.txt").read_text()


def test_emit_is_deterministic_across_runs(df, tmp_path):
    a = emit(df, run_id="a", out_dir=tmp_path)
    b = emit(df, run_id="b", out_dir=tmp_path)
    # txt carries no run identity: byte-identical for identical data
    assert (a / "01_card.txt").read_text() == (b / "01_card.txt").read_text()
    # json identical apart from the run_id field itself
    ca = json.loads((a / "01_card.json").read_text())
    cb = json.loads((b / "01_card.json").read_text())
    ca.pop("run_id"), cb.pop("run_id")
    assert ca == cb


# ---------- integration against the real dataset ----------

@pytest.mark.skipif(not os.path.exists(DIAMONDS_CSV), reason="diamonds.csv not present")
def test_real_diamonds_card_end_to_end(tmp_path):
    d = pd.read_csv(DIAMONDS_CSV)
    run_dir = emit(d, run_id="diamonds", out_dir=tmp_path)
    card = json.loads((run_dir / "01_card.json").read_text())
    txt = (run_dir / "01_card.txt").read_text()
    # x/y/z are strongly correlated with carat -> curated out of the prompt
    assert not {"x", "y", "z"} & set(card["keep"])
    assert set(card["keep"]) == {"price", "carat", "cut", "clarity", "color"}
    assert "structurally binding" in txt
    assert render_card(card) == txt
