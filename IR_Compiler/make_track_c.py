"""Emit track_c_dispatch.json — the Urban Dispatch Assignment model.

Written by script only because the time-slot set is 120 literal members; the
IR itself is ordinary JSON an LLM can produce. Run: python make_track_c.py
"""

import json
from pathlib import Path

import sys

# Two instances. The small one is the demo; the large one exists because the
# small one turned out to be EASY — a direct LLM solves it — and the honest
# question is where that stops being true.
SIZES = {
    "small": dict(drivers=4, start="2019-03-06 08:00:00", end="2019-03-06 09:00:00",
                  out="track_c_dispatch.json"),
    "large": dict(drivers=8, start="2019-03-06 07:00:00", end="2019-03-06 11:00:00",
                  out="track_c_dispatch_large.json"),
}
SIZE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in SIZES else "small"
CFG = SIZES[SIZE]
DRIVERS = [f"d{i+1}" for i in range(CFG["drivers"])]

# Time discretisation note: a fixed grid of slots is both wasteful and WRONG —
# two trips can overlap by less than one slot and never share a grid point.
# For interval scheduling it is sufficient (and exact) to check occupancy at
# every task's START instant: if two intervals overlap, one begins inside the
# other. So the slot set is the distinct pickup times, which `categories` over
# the numeric pickup_min column already gives us — no new IR feature needed.

spec = {
    "name": f"urban_dispatch_{SIZE}",
    "tables": [{
        "name": "trips", "path": "taxis.csv",
        # "ingest an operational time slice": one busy hour out of the log
        "filter": [{"column": "pickup", "op": "gte", "value": CFG["start"]},
                   {"column": "pickup", "op": "lt", "value": CFG["end"]}],
        "parse_datetime": ["pickup", "dropoff"],
    }],
    "sets": [
        {"name": "TASK", "kind": "rows", "table": "trips"},
        {"name": "DRIVER", "kind": "literal", "members": DRIVERS},
        {"name": "SLOT", "kind": "categories", "table": "trips", "column": "pickup_min"},
    ],
    "params": [
        {"name": "rev", "index": ["TASK"], "table": "trips", "column": "total"},
        {"name": "pax", "index": ["TASK"], "table": "trips", "column": "passengers"},
        {"name": "veh_cap", "value": 4},
    ],
    "vars": [{"name": "y", "index": ["TASK", "DRIVER"], "domain": "Binary"}],
    "objective": {
        "sense": "max",
        "source_text": "assign tasks to drivers to maximise platform revenue",
        "expr": {"terms": [{"var": "y", "weight": "rev",
                            "over": [{"set": "TASK"}, {"set": "DRIVER"}]}]},
    },
    "constraints": [
        {"name": "one_driver_per_task",
         "source_text": "a customer request is served by at most one driver",
         "forall": ["TASK"],
         "lhs": {"terms": [{"var": "y", "over": [{"set": "TASK", "bind": "$TASK"},
                                                 {"set": "DRIVER"}]}]},
         "rel": "<=", "rhs": {"const": 1.0}},

        # No-overlap without pairwise big-M: a driver may be inside at most one
        # trip at any minute. pickup_min <= t < dropoff_min is "task covers slot t".
        {"name": "no_overlapping_schedule",
         "source_text": "no driver receives overlapping schedules",
         "forall": ["DRIVER", "SLOT"],
         "lhs": {"terms": [{"var": "y", "over": [
             {"set": "TASK", "where": [
                 {"column": "pickup_min", "op": "lte", "value": "$SLOT"},
                 {"column": "dropoff_min", "op": "gt", "value": "$SLOT"}]},
             {"set": "DRIVER", "bind": "$DRIVER"}]}]},
         "rel": "<=", "rhs": {"const": 1.0}},

        {"name": "vehicle_capacity",
         "source_text": "passenger counts never exceed vehicle limits",
         "forall": ["TASK"],
         "lhs": {"terms": [{"var": "y", "weight": "pax",
                            "over": [{"set": "TASK", "bind": "$TASK"},
                                     {"set": "DRIVER"}]}]},
         "rel": "<=", "rhs": {"terms": [{"weight": "veh_cap"}]}},
    ],
}

if __name__ == "__main__":
    p = Path(__file__).resolve().parent / CFG["out"]
    p.write_text(json.dumps(spec, indent=1) + "\n")
    print(f"wrote {p.name}: {len(DRIVERS)} drivers, event-based slots, "
          f"{len(spec['constraints'])} constraint families")
