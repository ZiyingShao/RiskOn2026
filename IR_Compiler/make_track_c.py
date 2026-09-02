"""Emit track_c_dispatch.json — the Urban Dispatch Assignment model.

Written by script only because the time-slot set is 120 literal members; the
IR itself is ordinary JSON an LLM can produce. Run: python make_track_c.py
"""

import json
from pathlib import Path

DRIVERS = ["d1", "d2", "d3", "d4"]

# Time discretisation note: a fixed grid of slots is both wasteful and WRONG —
# two trips can overlap by less than one slot and never share a grid point.
# For interval scheduling it is sufficient (and exact) to check occupancy at
# every task's START instant: if two intervals overlap, one begins inside the
# other. So the slot set is the distinct pickup times, which `categories` over
# the numeric pickup_min column already gives us — no new IR feature needed.

spec = {
    "name": "urban_dispatch",
    "tables": [{
        "name": "trips", "path": "taxis.csv",
        # "ingest an operational time slice": one busy hour out of the log
        "filter": [{"column": "pickup", "op": "gte", "value": "2019-03-06 08:00:00"},
                   {"column": "pickup", "op": "lt", "value": "2019-03-06 09:00:00"}],
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
    p = Path(__file__).resolve().parent / "track_c_dispatch.json"
    p.write_text(json.dumps(spec, indent=1) + "\n")
    print(f"wrote {p.name}: {len(DRIVERS)} drivers, event-based slots, "
          f"{len(spec['constraints'])} constraint families")
