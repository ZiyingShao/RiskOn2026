"""Aggregate the four measurements into results/summary.json + a slide table.

Reads results/state.json and the *.final.json specs, computes:
  1. structural fidelity   (fingerprint recall / precision vs reference)
  2. semantic fidelity     (source_text coverage of obligation sentences)
  3. solution equivalence  (objective agreement + gap direction)
  4. resilience            (first-pass validity, repairs, success, error histogram)
plus the per-variant probes (volume leak, contradiction choice).
Usage:  python aggregate.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "IR_Compiler"))

from ir import ModelSpec                      # noqa: E402
from briefs import BY_NAME                    # noqa: E402
from fingerprint import compare               # noqa: E402
from semantic import coverage                 # noqa: E402
from solution import compare_solutions        # noqa: E402

import os
RESULTS = HERE / os.environ.get("EVAL_RESULTS", "results")   # e.g. results_ablation
ROOT = str(HERE.parent)


def contradiction_choice(spec_dict: dict) -> str:
    """Which cut-share cap did the run encode? Inspect rhs coefficients of
    constraints whose rows are filtered per cut grade."""
    found = set()
    for c in spec_dict.get("constraints", []):
        text = json.dumps(c).lower()
        if '"cut"' not in text:
            continue
        for t in c.get("rhs", {}).get("terms", []):
            if t.get("var") and t.get("coef") is not None:
                found.add(round(float(t["coef"]), 4))
        rc = c.get("rhs", {}).get("const", 0)
        if c.get("rel") == "<=" and 0 < rc < 1:
            found.add(round(float(rc), 4))
    if found == {0.2}:
        return "picked_20"
    if found == {0.3}:
        return "picked_30"
    if 0.2 in found and 0.3 in found:
        return "kept_both"
    return f"other:{sorted(found)}"


def main() -> None:
    state = json.loads((RESULTS / "state.json").read_text())
    refs = {n: ModelSpec.model_validate(json.load(open(HERE / "references" / f"{n}.json")))
            for n in ("base", "cap25", "small_stones", "no_volume",
                      "renamed_budget", "infeasible", "vague_case")}

    per_brief: dict[str, dict] = defaultdict(lambda: {
        "runs": 0, "first_pass_valid": 0, "converged": 0, "repairs": [],
        "recall": [], "precision": [], "objective_match": 0,
        "semantic_rate": [], "solve_agree": 0, "solved": 0,
        "dangerous_gaps": 0, "volume_leak": 0, "diagnosis_fired": 0,
        "contradiction": Counter(),
    })
    histogram: Counter = Counter()
    repair_outcome: Counter = Counter()

    for key, rec in sorted(state.items()):
        brief = rec["brief"]
        b = BY_NAME[brief]
        agg = per_brief[brief]
        agg["runs"] += 1

        for i, a in enumerate(rec["attempts"]):
            for code in a["codes"]:
                histogram[code] += 1
                if i + 1 < len(rec["attempts"]) or rec["status"] == "converged":
                    repair_outcome[code] += 0   # placeholder keeps key order stable
        if rec["attempts"] and rec["attempts"][0]["stage"] == "valid":
            agg["first_pass_valid"] += 1
        if rec["status"] != "converged":
            continue
        agg["converged"] += 1
        agg["repairs"].append(len(rec["attempts"]) - 1)

        spec_dict = json.load(open(RESULTS / "attempts" /
                                   rec["final_spec"].replace(".json", ".final.json")))
        spec = ModelSpec.model_validate(spec_dict)

        sem = coverage(b["obligations"], spec_dict)
        agg["semantic_rate"].append(sem["rate"])

        if brief == "contradiction":
            agg["contradiction"][contradiction_choice(spec_dict)] += 1
            continue

        ref = refs[brief]
        fp = compare(spec, ref, ROOT)
        agg["recall"].append(fp["recall"])
        agg["precision"].append(fp["precision"])
        agg["objective_match"] += int(fp["objective_match"])
        if brief == "no_volume" and any(
                "volume" in n for n in fp["invented_generated_constraints"]):
            agg["volume_leak"] += 1

        sol = compare_solutions(spec, ref, ROOT, b["expect_infeasible"],
                                b["obligations"][4] if b["expect_infeasible"] else None)
        agg["solved"] += 1
        agg["solve_agree"] += int(bool(sol["agree"]))
        if sol.get("direction") == "dangerous_too_high":
            agg["dangerous_gaps"] += 1
        if b["expect_infeasible"] and sol.get("diagnosis_names_sentence"):
            agg["diagnosis_fired"] += 1

    summary = {"per_brief": {}, "error_histogram": dict(histogram.most_common()),
               "overall": {}}
    fp_all, conv_all, rep_all, agree_all, solved_all, runs_all = 0, 0, [], 0, 0, 0
    for brief, a in per_brief.items():
        runs_all += a["runs"]
        fp_all += a["first_pass_valid"]
        conv_all += a["converged"]
        rep_all += a["repairs"]
        agree_all += a["solve_agree"]
        solved_all += a["solved"]
        summary["per_brief"][brief] = {
            "runs": a["runs"],
            "first_pass_valid": a["first_pass_valid"],
            "repair_success_rate": a["converged"] / a["runs"] if a["runs"] else 0,
            "mean_repairs": round(mean(a["repairs"]), 2) if a["repairs"] else None,
            "mean_recall": round(mean(a["recall"]), 3) if a["recall"] else None,
            "mean_precision": round(mean(a["precision"]), 3) if a["precision"] else None,
            "objective_match": a["objective_match"],
            "mean_semantic_coverage": round(mean(a["semantic_rate"]), 3)
                if a["semantic_rate"] else None,
            "solve_agree": a["solve_agree"], "solved_runs": a["solved"],
            "dangerous_gaps": a["dangerous_gaps"],
            "volume_leak_runs": a["volume_leak"] if brief == "no_volume" else None,
            "diagnosis_fired": a["diagnosis_fired"]
                if BY_NAME[brief]["expect_infeasible"] else None,
            "contradiction_choices": dict(a["contradiction"]) or None,
        }
    summary["overall"] = {
        "runs": runs_all,
        "first_pass_validity_rate": round(fp_all / runs_all, 3) if runs_all else None,
        "mean_repairs_to_convergence": round(mean(rep_all), 2) if rep_all else None,
        "repair_success_rate": round(conv_all / runs_all, 3) if runs_all else None,
        "solve_agreement_rate": round(agree_all / solved_all, 3) if solved_all else None,
    }

    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary["overall"], indent=1))
    print("error histogram:", dict(histogram.most_common()))
    print("-> results/summary.json")


if __name__ == "__main__":
    main()
