"""Build generation prompts covering ALL archetypes.

make_prompts.py stays Track-B-only and frozen, so the existing 175-run baseline
remains comparable. This builds two new prompt sets:

  prompts_multi/       each brief with a selection example AND an assignment
                       example -> the realistic deployment prompt
  prompts_heldout/     the dispatch brief with ONLY selection examples -> can
                       the model produce an assignment model from the GRAMMAR
                       DOCUMENTATION alone, having never seen one?

No brief is ever shown its own reference IR. The dispatch example used in
prompts_multi is the LARGE instance (8 drivers, a 4-hour window), while the
dispatch brief asks for the small one (4 drivers, one hour) — so the shape can
be copied but the content cannot.

Run: python make_prompts_multi.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from briefs import ALL_BRIEFS, ALL_BY_NAME      # noqa: E402
from grammar import GRAMMAR, PATTERNS, RULES    # noqa: E402

DATA_NOTE = (
    "Available data files and their columns:\n"
    "  diamonds.csv           carat, cut, color, clarity, depth, table, price, x, y, z\n"
    "  IR_Compiler/taxis.csv  pickup, dropoff, passengers, distance, fare, tip, tolls,\n"
    "                         total, color, payment, pickup_zone, dropoff_zone,\n"
    "                         pickup_borough, dropoff_borough\n\n")

LARGE_DISPATCH_BRIEF = (
    "A ride-hailing platform is dispatching a busy shift. The operational log "
    "taxis.csv holds completed trips; treat each row in the shift window as a "
    "pending customer request, with the fare in the `total` column as the "
    "revenue it would earn. Eight drivers are on shift: d1 through d8. A "
    "customer request can be given to at most one driver. No driver may receive "
    "overlapping schedules. Passenger counts must never exceed the four-seat "
    "vehicle limit. Maximise total platform revenue. Work the shift running "
    "from 07:00 to 11:00 on 2019-03-06.")


def build(target: dict, examples: list[tuple[str, str, dict]]) -> str:
    """examples: [(label, brief_text, ir_dict)] shown in order."""
    parts = [
        "You translate a natural-language operations brief into a "
        "machine-readable optimization IR (a linear/mixed-integer model over "
        "table rows). A downstream compiler binds it to the data and hands it "
        "to a solver, so the IR must be exactly right — you are NOT asked to "
        "solve anything yourself.\n\n",
        GRAMMAR, "\n", PATTERNS, "\n", RULES, "\n", DATA_NOTE,
    ]
    for i, (label, brief, ir) in enumerate(examples, 1):
        parts.append(f"=== WORKED EXAMPLE {i} — {label} ===\nBRIEF:\n{brief}\n\n"
                     f"IR:\n{json.dumps(ir, indent=1)}\n\n")
    parts.append("Now translate this brief. Decide which shape it is FIRST "
                 "(selection? assignment? scheduling?), then write the IR. "
                 "Reply with ONLY the JSON.\nBRIEF:\n" + target["text"] + "\n")
    return "".join(parts)


if __name__ == "__main__":
    ref = lambda n: json.load(open(HERE / "references" / f"{n}.json"))  # noqa: E731
    large = json.load(open(HERE.parent / "IR_Compiler" / "track_c_dispatch_large.json"))
    large["tables"][0]["path"] = "IR_Compiler/taxis.csv"

    sel = ("a SELECTION brief", ALL_BY_NAME["base"]["text"], ref("base"))
    sel_alt = ("another SELECTION brief", ALL_BY_NAME["cap25"]["text"], ref("cap25"))
    asg = ("an ASSIGNMENT + SCHEDULING brief", LARGE_DISPATCH_BRIEF, large)

    multi = HERE / "prompts_multi"; multi.mkdir(exist_ok=True)
    held = HERE / "prompts_heldout"; held.mkdir(exist_ok=True)

    for b in ALL_BRIEFS:
        # never show a brief its own reference
        s = sel_alt if b["name"] == "base" else sel
        (multi / f"{b['name']}.md").write_text(build(b, [s, asg]))
    print(f"prompts_multi/    {len(ALL_BRIEFS)} prompts (selection + assignment examples)")

    d = ALL_BY_NAME["dispatch"]
    (held / "dispatch.md").write_text(build(d, [sel, sel_alt]))
    print("prompts_heldout/  dispatch.md — ONLY selection examples; the model must "
          "build an assignment model from the grammar alone")
