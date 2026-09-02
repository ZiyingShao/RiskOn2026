"""Track C: raw rows -> LLM  vs.  brief -> IR -> solver.

Same shape as direct_baseline.py, but the feasibility test is far richer than
a knapsack's: an assignment can put one driver inside two trips at once. That
failure is invisible in the output — the JSON looks like a dispatch plan.

The prompt is deliberately CHARITABLE: pickup/dropoff are pre-converted to
minutes so the model never has to parse a timestamp. The task is purely the
optimisation.

    python direct_dispatch.py build      # prompts/direct_dispatch.md
    python direct_dispatch.py truth
    python direct_dispatch.py report     # score everything in results_direct/
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "IR_Compiler"))

from ir import ModelSpec                                   # noqa: E402
from compiler import bind, compile_model, solve            # noqa: E402

ROOT = str(HERE.parent / "IR_Compiler")          # taxis.csv lives beside the spec
SPECS = {"small": "track_c_dispatch.json", "large": "track_c_dispatch_large.json"}
CAP = 4
SIZE = "small"          # set by the CLI; drivers are read from the spec itself


def _bound(size: str | None = None):
    spec = ModelSpec.model_validate(
        json.load(open(HERE.parent / "IR_Compiler" / SPECS[size or SIZE])))
    return spec, bind(spec, root=ROOT)


def drivers(spec) -> list[str]:
    return [str(m) for s in spec.sets if s.kind == "literal" for m in s.members]


def build_prompt() -> str:
    spec, bm = _bound()
    DRIVERS = drivers(spec)
    df = bm.frames["trips"]
    rows = "\n".join(
        f"{i},{r.pickup_min:.1f},{r.dropoff_min:.1f},{int(r.passengers)},{r.total:.2f}"
        for i, r in df.iterrows())
    return (
        "You are the dispatcher for a ride-hailing platform. Below is the queue of "
        f"pending customer requests for this shift, and you have {len(DRIVERS)} "
        f"drivers available: {', '.join(DRIVERS)}.\n\n"
        "Each request line is:\n"
        "task_id,start_minute,end_minute,passengers,revenue_usd\n"
        f"{rows}\n\n"
        "Assign requests to drivers to MAXIMISE total revenue, subject to:\n"
        "- a request may be given to at most one driver (some will go unserved)\n"
        "- a driver cannot be in two places at once: the trips assigned to any one "
        "driver must not overlap in time (a trip occupies its driver from its "
        "start_minute until its end_minute)\n"
        f"- a vehicle holds at most {CAP} passengers\n\n"
        "Reply with ONLY this JSON and nothing else:\n"
        '{"assignments": {' + ", ".join(f'"{d}": [task_ids]' for d in DRIVERS)
        + '}, "total_revenue": <number>}\n'
    )


def ground_truth() -> dict:
    spec, bm = _bound()
    rep = solve(compile_model(bm))
    return {"objective": rep["objective"], "assign": rep["selected_by_var"]["y"],
            "df": bm.frames["trips"]}


def score(answer_text: str) -> dict:
    spec, bm = _bound()
    DRIVERS = drivers(spec)
    df = bm.frames["trips"]
    gt = ground_truth()

    txt = re.sub(r"^```(?:json)?|```$", "", answer_text.strip(), flags=re.M).strip()
    s, e = txt.find("{"), txt.rfind("}")
    try:
        ans = json.loads(txt[s:e + 1])
    except Exception:
        return {"parse": "FAILED — not valid JSON"}

    assign = ans.get("assignments", {}) or {}
    claimed = float(ans.get("total_revenue", 0) or 0)

    ghost, seen, viol = [], {}, []
    per_driver: dict[str, list] = {}
    for d, ids in assign.items():
        if d not in DRIVERS:
            viol.append(f"unknown driver '{d}'")
            continue
        keep = []
        for i in (ids or []):
            if i not in df.index:
                ghost.append(i)
                continue
            seen.setdefault(i, []).append(d)
            keep.append(i)
        per_driver[d] = keep

    # a request handed to two drivers at once
    for i, ds in seen.items():
        if len(ds) > 1:
            viol.append(f"task {i} assigned to {len(ds)} drivers {ds}")

    # the scheduling constraint: no driver inside two trips at the same minute
    overlaps = []
    for d, ids in per_driver.items():
        iv = sorted((df.loc[i, "pickup_min"], df.loc[i, "dropoff_min"], i) for i in ids)
        for k in range(1, len(iv)):
            if iv[k][0] < iv[k - 1][1] - 1e-9:
                overlaps.append(
                    f"{d}: task {iv[k-1][2]} ({iv[k-1][0]:.1f}-{iv[k-1][1]:.1f}) "
                    f"and task {iv[k][2]} ({iv[k][0]:.1f}-{iv[k][1]:.1f})")
    viol += overlaps

    served = sorted({i for ids in per_driver.values() for i in ids})
    for i in served:
        if df.loc[i, "passengers"] > CAP:
            viol.append(f"task {i} has {df.loc[i,'passengers']} passengers > {CAP}")

    actual = float(df.loc[served, "total"].sum()) if served else 0.0
    return {
        "claimed_revenue": round(claimed, 2),
        "actual_revenue": round(actual, 2),
        "arithmetic_error": round(claimed - actual, 2),
        "tasks_served": len(served),
        "ghost_ids": ghost,
        "overlap_count": len(overlaps),
        "violations": viol,
        "feasible": not viol and not ghost,
        "optimum": round(gt["objective"], 2),
        "gap_vs_optimum_pct": round(100 * (actual - gt["objective"]) / gt["objective"], 1),
    }


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    SIZE = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] in SPECS else "small"
    if cmd == "build":
        p = HERE / "prompts" / f"direct_dispatch_{SIZE}.md"
        p.write_text(build_prompt())
        print(f"wrote {p.relative_to(HERE)} ({len(p.read_text()):,} chars)")
    elif cmd == "truth":
        gt = ground_truth()
        print(f"solver optimum: ${gt['objective']:.2f} from "
              f"{len(gt['assign'])} assignments")
    elif cmd == "report":
        gt = ground_truth()
        spec, _ = _bound()
        DRIVERS = drivers(spec)
        avail = gt["df"].total.sum()
        print(f"\nTRACK C — urban dispatch: {len(gt['df'])} requests, "
              f"{len(DRIVERS)} drivers, ${avail:.2f} of revenue on the table")
        print(f"solver optimum (ground truth): ${gt['objective']:.2f}\n")
        print(f"{'run':<24}{'claims':>9}{'actual':>9}{'arith err':>11}"
              f"{'served':>8}{'overlaps':>10}{'feasible':>10}{'gap%':>8}")
        for f in sorted((HERE / "results_direct").glob(f"dispatch{'_lg' if SIZE=='large' else ''}_*.json")):
            r = score(f.read_text())
            if "parse" in r:
                print(f"{f.stem:<24}{'— unparseable —':>55}")
                continue
            print(f"{f.stem:<24}{r['claimed_revenue']:>9.2f}{r['actual_revenue']:>9.2f}"
                  f"{r['arithmetic_error']:>+11.2f}{r['tasks_served']:>8}"
                  f"{r['overlap_count']:>10}"
                  f"{('YES' if r['feasible'] else 'NO'):>10}"
                  f"{r['gap_vs_optimum_pct']:>+8.1f}")
        print(f"{'PIPELINE (IR -> HiGHS)':<24}{gt['objective']:>9.2f}"
              f"{gt['objective']:>9.2f}{0.0:>+11.2f}"
              f"{len(gt['assign']):>8}{0:>10}{'YES':>10}{0.0:>+8.1f}")
        print()
        for f in sorted((HERE / "results_direct").glob(f"dispatch{'_lg' if SIZE=='large' else ''}_*.json")):
            r = score(f.read_text())
            if r.get("violations") or r.get("ghost_ids"):
                print(f"  {f.stem}:")
                for v in (r.get("ghost_ids") and
                          [f"{len(r['ghost_ids'])} ids not in the queue: {r['ghost_ids'][:5]}"] or []):
                    print(f"     - {v}")
                for v in r["violations"][:6]:
                    print(f"     - {v}")
