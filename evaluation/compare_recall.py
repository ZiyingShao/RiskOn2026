"""Compare constraint recall across models — the metric the validator can't see.

A missing constraint has no error code: all three checkpoints validate what
was written, never what wasn't. Structural recall against the reference IR is
the only detector. This prints recall (and the probes) side by side for any
number of scored result directories.

Usage:  python compare_recall.py results_luna_noex results_terra_noex ...
        (each dir must already have summary.json from aggregate.py)

Decision rule: if recall is equal across models, take the cheap one — the
capability difference is invisible on this task. If the small model's recall
drops on `vague_case` or `small_stones`, that gap is the silently-dropped
constraint your validator cannot catch, and it prices the stronger model.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
dirs = sys.argv[1:] or ["results", "results_ablation"]
summaries = {d: json.loads((HERE / d / "summary.json").read_text()) for d in dirs}

briefs = ["base", "cap25", "small_stones", "no_volume",
          "renamed_budget", "vague_case", "infeasible"]

print(f"{'brief':<16}" + "".join(f"{d:>24}" for d in dirs))
for b in briefs:
    row = f"{b:<16}"
    for d in dirs:
        pb = summaries[d]["per_brief"].get(b)
        if pb is None or pb.get("mean_recall") is None:
            row += f"{'-':>24}"
        else:
            row += f"{pb['mean_recall']:.3f} R / {pb['mean_precision']:.3f} P".rjust(24)
    print(row)

print(f"\n{'overall':<16}" + "".join(
    f"fp {s['overall']['first_pass_validity_rate']:.0%} agree "
    f"{s['overall']['solve_agreement_rate'] or 0:.0%}".rjust(24)
    for s in summaries.values()))
for d, s in summaries.items():
    print(f"{d}: errors {s['error_histogram'] or '{}'}")
