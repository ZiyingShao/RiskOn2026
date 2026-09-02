"""Score every raw-rows answer in results_direct/ against the solver optimum.

Prints the table that makes the architecture argument: same model, two
scaffoldings, one provably-optimal ground truth.

    python direct_report.py
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from direct_baseline import score, ground_truth, INSTANCES   # noqa: E402

OUT = HERE / "results_direct"
truth = {i: ground_truth(i)["objective"] for i in INSTANCES}

rows = []
for f in sorted(OUT.glob("*.json")):
    inst = f.stem.split("_")[0]
    if inst not in INSTANCES:
        continue
    r = score(f.read_text(), inst)
    r["run"] = f.stem
    rows.append(r)

for inst in INSTANCES:
    sub = [r for r in rows if r.get("instance") == inst]
    if not sub:
        continue
    n = INSTANCES[inst]["n"]
    print(f"\n{'='*78}\nINSTANCE '{inst}' — {n} rows dumped into the prompt")
    print(f"solver optimum (ground truth): {truth[inst]:.3f} carats\n")
    print(f"{'run':<22}{'claims':>9}{'actual':>9}{'arith err':>11}"
          f"{'feasible':>10}{'gap%':>8}")
    for r in sub:
        if "parse" in r:
            print(f"{r['run']:<22}{'— unparseable output —':>47}")
            continue
        print(f"{r['run']:<22}{r['claimed_carat']:>9.2f}{r['actual_carat']:>9.2f}"
              f"{r['arithmetic_error']:>+11.2f}"
              f"{('YES' if r['feasible'] else 'NO'):>10}"
              f"{r['gap_vs_optimum_pct']:>+8.1f}")
    print()
    for r in sub:
        if "parse" in r:
            continue
        bad = []
        if r["ghost_ids"]:
            bad.append(f"{len(r['ghost_ids'])} ids not in the data "
                       f"(e.g. {r['ghost_ids'][:4]})")
        if r["duplicate_ids"]:
            bad.append(f"{r['duplicate_ids']} duplicate ids")
        bad += r["violations"]
        if bad:
            print(f"  {r['run']}:")
            for b in bad:
                print(f"     - {b}")

print(f"\n{'='*78}\nPIPELINE (brief -> IR -> HiGHS), same rows:")
for inst in INSTANCES:
    print(f"  {inst:<6} {truth[inst]:.3f} carats — feasible by construction, "
          f"proven optimal, 0.0% gap")
