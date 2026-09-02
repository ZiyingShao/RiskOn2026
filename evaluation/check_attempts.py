"""Driver: score every generation attempt on disk and emit repair tasks.

Layout (all under results/):
  attempts/<brief>_r<run>_a<attempt>.json   raw generator output (any text)
  attempts/<brief>_r<run>_a<attempt>.errors.txt   feedback for the repairer
  state.json      per-run record: attempts so far, stage history, final status
  pending.json    repair tasks: [{brief, run, attempt, prompt, prev, errors, out}]

Idempotent: re-run after each wave of generations. A run converges when an
attempt passes all three checkpoints; it fails hard after MAX_ATTEMPTS.
Usage:  python check_attempts.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from checkpoints import check_attempt, errors_as_feedback   # noqa: E402

import os
RESULTS = HERE / os.environ.get("EVAL_RESULTS", "results")   # e.g. results_ablation
ATTEMPTS = RESULTS / "attempts"
MAX_ATTEMPTS = 4          # 1 first pass + up to 3 repairs


def load_state() -> dict:
    p = RESULTS / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def main() -> None:
    ATTEMPTS.mkdir(parents=True, exist_ok=True)
    state = load_state()

    for f in sorted(ATTEMPTS.glob("*_r*_a*.json")):
        if f.stem.endswith(".final"):
            continue                                   # our own output, not an attempt
        brief, run, attempt = f.stem.rsplit("_", 2)
        key = f"{brief}_{run}"
        rec = state.setdefault(key, {"brief": brief, "attempts": [], "status": "pending"})
        idx = int(attempt[1:])
        if idx < len(rec["attempts"]):
            continue                                   # already scored
        result = check_attempt(f.read_text())
        rec["attempts"].append({
            "stage": result["stage"],
            "codes": sorted({e["code"] for e in result["errors"]}),
        })
        if result["stage"] == "valid":
            rec["status"] = "converged"
            rec["final_spec"] = f.name
            (ATTEMPTS / f"{f.stem}.final.json").write_text(
                json.dumps(result["spec"], indent=1))
        else:
            (ATTEMPTS / f"{f.stem}.errors.txt").write_text(
                errors_as_feedback(result))
            rec["status"] = ("failed" if len(rec["attempts"]) >= MAX_ATTEMPTS
                             else "pending_repair")

    pending = []
    for key, rec in sorted(state.items()):
        if rec["status"] == "pending_repair":
            brief, run = key.rsplit("_", 1)
            n = len(rec["attempts"])
            pending.append({
                "brief": brief, "run": run, "attempt": n,
                "prompt": f"prompts/{brief}.md",
                "prev": f"results/attempts/{key}_a{n - 1}.json",
                "errors": f"results/attempts/{key}_a{n - 1}.errors.txt",
                "out": f"results/attempts/{key}_a{n}.json",
            })

    (RESULTS / "state.json").write_text(json.dumps(state, indent=1))
    (RESULTS / "pending.json").write_text(json.dumps(pending, indent=1))

    tally = {"converged": 0, "pending_repair": 0, "failed": 0, "pending": 0}
    for rec in state.values():
        tally[rec["status"]] += 1
    print(json.dumps(tally), f"| {len(pending)} repair tasks -> results/pending.json")


if __name__ == "__main__":
    main()
