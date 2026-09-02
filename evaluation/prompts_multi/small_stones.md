You translate a natural-language operations brief into a machine-readable optimization IR (a linear/mixed-integer model over table rows). A downstream compiler binds it to the data and hands it to a solver, so the IR must be exactly right — you are NOT asked to solve anything yourself.

The IR is a JSON object with this exact shape. Unknown keys are REJECTED.

ModelSpec: {name, tables, sets, params, vars, objective, constraints}

TABLES — [{name, path, filter?, parse_datetime?, sample?, derived?}]
  filter          rows kept at LOAD time: [{column, op, value}]. This is how you
                  take "an operational time slice" out of a log.
  parse_datetime  ["pickup","dropoff"] — each timestamp column yields a NUMERIC
                  "<col>_min" column (minutes from the earliest row, one shared
                  origin). Scheduling arithmetic needs numbers, not strings.
  sample          {"n": 800, "seed": 7}
  derived         [{name, expr}] — a new column from a pandas expression,
                  e.g. {"name":"vol_mm3","expr":"x * y * z"}

SETS — [{name, kind, table?, column?, members?}]
  kind "rows"        one member per table row (candidate assets, pending tasks)
  kind "categories"  the distinct values of a column. Works on TEXT columns
                     (cut, clarity) and on NUMERIC ones — "categories" over a
                     numeric time column gives you the distinct event times.
  kind "literal"     members listed outright, NO table: {"kind":"literal",
                     "members":["d1","d2","d3"]}. Use this for an axis the data
                     does not contain — a driver pool, machines, shifts.

PARAMS — [{name, index, table?, column?, value?}]
  indexed: {"name":"price","index":["I"],"table":"inv","column":"price"}
  scalar : {"name":"budget","value":250000}

VARS — [{name, index, domain, lb?, ub?}]
  domain: "Binary" | "Integer" | "NonNegReal" | "Real"
  index is a LIST of set names. One set = a selection variable x[i].
  TWO sets = an assignment variable y[task, driver].

EXPRESSIONS (LinExpr) — {terms: [Term], const: number}
  Term: {coef?, var?, weight?, over?}
      = coef * SUM over the selected members of  weight[member] * var[member]
  A Term with no `var` is a constant or a data aggregate.
  `weight` names a param; a param indexed by only SOME of the term's axes is
  keyed on those axes (revenue[task] correctly weights y[task, driver]).

  `over` — THIS IS THE PART THAT DIFFERS BY ARCHETYPE:
    * ONE object  -> a 1-D variable:   "over": {"set":"I", "where":[...]}
    * A LIST      -> one entry PER VARIABLE DIMENSION, in declaration order:
                     "over": [{"set":"TASK"}, {"set":"DRIVER"}]
      The number of entries MUST equal the number of sets in the variable's
      `index`, or you get ARITY_MISMATCH.

    Each entry: {set, where?, bind?}
      where  [{column, op, value}] row filter; ops eq|ne|in|gte|lte|gt|lt.
             Only valid on a "rows" set. A value of "$SETNAME" binds to the
             current member of a `forall` set.
      bind   "$SETNAME" — FIX this axis to the forall value instead of summing
             over it. This is how you say "for THIS driver, over their own
             tasks": "over": [{"set":"TASK","where":[...]},
                              {"set":"DRIVER","bind":"$DRIVER"}]

CONSTRAINTS — [{name, forall?, lhs, rel, rhs, source_text}]
  forall       replicate the constraint over these sets; each binds "$SETNAME"
  rel          "<=" | ">=" | "=="
  source_text  MUST quote the exact sentence of the brief this encodes

OBJECTIVE — {sense: "min"|"max", expr, source_text}

Three model shapes and how to write each:

1. SELECTION (choose a subset of rows: portfolio, knapsack)
   var x[I] Binary.  Budget:      sum price[i]*x[i] <= B
   Share cap per category g:      forall ["CAT"],
       lhs sum over {rows where col == "$CAT"} of x[i]
       rhs {"coef":0.3,"var":"x","over":{"set":"I"}}     (a FRACTION of the total)

2. ASSIGNMENT (match rows to a resource pool)
   Declare the pool as a LITERAL set, and the variable 2-D:
       vars: [{"name":"y","index":["TASK","DRIVER"],"domain":"Binary"}]
   Objective sums both axes:  "over": [{"set":"TASK"},{"set":"DRIVER"}]
   "each row goes to at most one resource":  forall ["TASK"],
       "over": [{"set":"TASK","bind":"$TASK"}, {"set":"DRIVER"}]  <= 1

3. SCHEDULING (assignment + no two jobs at once on one resource)
   Do NOT invent pairwise big-M constraints. Use occupancy at event times:
     - parse_datetime the start/end columns -> start_min, end_min
     - make a SLOT set: {"kind":"categories","column":"<start>_min"}
       (checking at every job's START is exact: if two intervals overlap,
        one begins inside the other)
     - forall ["DRIVER","SLOT"]:
         sum over {rows where start_min <= $SLOT and end_min > $SLOT}
             of y[row, $DRIVER]   <=   1

Hard rules:
- Output ONLY the JSON object. No prose, no markdown fences.
- Every constraint sentence in the brief becomes a constraint whose source_text
  quotes that sentence. Do not add constraints the brief does not state.
- One sentence may imply MORE THAN ONE constraint (a display case with a slot
  count AND a volume limit is two). Write both, quoting the sentence twice.
- If a quantity the brief names is not a column, derive it.

Available data files and their columns:
  diamonds.csv           carat, cut, color, clarity, depth, table, price, x, y, z
  IR_Compiler/taxis.csv  pickup, dropoff, passengers, distance, fare, tip, tolls,
                         total, color, payment, pickup_zone, dropoff_zone,
                         pickup_borough, dropoff_borough

=== WORKED EXAMPLE 1 — a SELECTION brief ===
BRIEF:
A high-end jeweler in Zurich stocks a retail vault from the wholesale inventory in diamonds.csv; each row is one stone available at wholesale cost. Deploy a fixed line of credit of CHF 250,000: the total wholesale price of the stones bought must not exceed it. The retail vault has 60 individual display slots, so at most 60 stones can be held. Total displayed stone volume cannot exceed 9,000 cubic millimetres; a stone's volume is x times y times z. No single cut grade may exceed 30% of the stones held. Carry at least two stones of every clarity grade so the range stays saleable. At most 40% of deployed capital may sit in stones priced above CHF 8,000. The goal is to maximise the total carat mass held in the vault. Model only a fixed sample of the inventory: 800 rows, random seed 7.

IR:
{
 "name": "zurich_vault_stocking",
 "tables": [
  {
   "name": "inv",
   "path": "diamonds.csv",
   "sample": {
    "n": 800,
    "seed": 7
   },
   "derived": [
    {
     "name": "vol_mm3",
     "expr": "x * y * z"
    }
   ]
  }
 ],
 "sets": [
  {
   "name": "I",
   "kind": "rows",
   "table": "inv"
  },
  {
   "name": "CUT",
   "kind": "categories",
   "table": "inv",
   "column": "cut"
  },
  {
   "name": "CLARITY",
   "kind": "categories",
   "table": "inv",
   "column": "clarity"
  }
 ],
 "params": [
  {
   "name": "price",
   "index": [
    "I"
   ],
   "table": "inv",
   "column": "price"
  },
  {
   "name": "carat",
   "index": [
    "I"
   ],
   "table": "inv",
   "column": "carat"
  },
  {
   "name": "vol",
   "index": [
    "I"
   ],
   "table": "inv",
   "column": "vol_mm3"
  },
  {
   "name": "budget",
   "value": 250000
  },
  {
   "name": "case_slots",
   "value": 60
  },
  {
   "name": "case_vol",
   "value": 9000
  },
  {
   "name": "max_share",
   "value": 0.3
  },
  {
   "name": "min_per_clarity",
   "value": 2
  },
  {
   "name": "max_premium_exposure",
   "value": 0.4
  }
 ],
 "vars": [
  {
   "name": "x",
   "index": [
    "I"
   ],
   "domain": "Binary"
  }
 ],
 "objective": {
  "sense": "max",
  "source_text": "The goal is to maximise the total carat mass held in the vault.",
  "expr": {
   "terms": [
    {
     "coef": 1.0,
     "var": "x",
     "weight": "carat",
     "over": {
      "set": "I"
     }
    }
   ]
  }
 },
 "constraints": [
  {
   "name": "credit_line",
   "source_text": "Deploy a fixed line of credit of CHF 250,000: the total wholesale price of the stones bought must not exceed it.",
   "lhs": {
    "terms": [
     {
      "var": "x",
      "weight": "price",
      "over": {
       "set": "I"
      }
     }
    ]
   },
   "rel": "<=",
   "rhs": {
    "terms": [
     {
      "weight": "budget"
     }
    ]
   }
  },
  {
   "name": "display_slots",
   "source_text": "The retail vault has 60 individual display slots, so at most 60 stones can be held.",
   "lhs": {
    "terms": [
     {
      "var": "x",
      "over": {
       "set": "I"
      }
     }
    ]
   },
   "rel": "<=",
   "rhs": {
    "terms": [
     {
      "weight": "case_slots"
     }
    ]
   }
  },
  {
   "name": "display_volume",
   "source_text": "Total displayed stone volume cannot exceed 9,000 cubic millimetres; a stone's volume is x times y times z.",
   "lhs": {
    "terms": [
     {
      "var": "x",
      "weight": "vol",
      "over": {
       "set": "I"
      }
     }
    ]
   },
   "rel": "<=",
   "rhs": {
    "terms": [
     {
      "weight": "case_vol"
     }
    ]
   }
  },
  {
   "name": "cut_concentration",
   "source_text": "No single cut grade may exceed 30% of the stones held.",
   "forall": [
    "CUT"
   ],
   "lhs": {
    "terms": [
     {
      "var": "x",
      "over": {
       "set": "I",
       "where": [
        {
         "column": "cut",
         "op": "eq",
         "value": "$CUT"
        }
       ]
      }
     }
    ]
   },
   "rel": "<=",
   "rhs": {
    "terms": [
     {
      "coef": 0.3,
      "var": "x",
      "over": {
       "set": "I"
      }
     }
    ]
   }
  },
  {
   "name": "clarity_coverage",
   "source_text": "Carry at least two stones of every clarity grade so the range stays saleable.",
   "forall": [
    "CLARITY"
   ],
   "lhs": {
    "terms": [
     {
      "var": "x",
      "over": {
       "set": "I",
       "where": [
        {
         "column": "clarity",
         "op": "eq",
         "value": "$CLARITY"
        }
       ]
      }
     }
    ]
   },
   "rel": ">=",
   "rhs": {
    "terms": [],
    "const": 2.0
   }
  },
  {
   "name": "premium_risk_bound",
   "source_text": "At most 40% of deployed capital may sit in stones priced above CHF 8,000.",
   "lhs": {
    "terms": [
     {
      "var": "x",
      "weight": "price",
      "over": {
       "set": "I",
       "where": [
        {
         "column": "price",
         "op": "gte",
         "value": 8000
        }
       ]
      }
     }
    ]
   },
   "rel": "<=",
   "rhs": {
    "terms": [
     {
      "coef": 0.4,
      "var": "x",
      "weight": "price",
      "over": {
       "set": "I"
      }
     }
    ]
   }
  }
 ]
}

=== WORKED EXAMPLE 2 — an ASSIGNMENT + SCHEDULING brief ===
BRIEF:
A ride-hailing platform is dispatching a busy shift. The operational log taxis.csv holds completed trips; treat each row in the shift window as a pending customer request, with the fare in the `total` column as the revenue it would earn. Eight drivers are on shift: d1 through d8. A customer request can be given to at most one driver. No driver may receive overlapping schedules. Passenger counts must never exceed the four-seat vehicle limit. Maximise total platform revenue. Work the shift running from 07:00 to 11:00 on 2019-03-06.

IR:
{
 "name": "urban_dispatch_large",
 "tables": [
  {
   "name": "trips",
   "path": "IR_Compiler/taxis.csv",
   "filter": [
    {
     "column": "pickup",
     "op": "gte",
     "value": "2019-03-06 07:00:00"
    },
    {
     "column": "pickup",
     "op": "lt",
     "value": "2019-03-06 11:00:00"
    }
   ],
   "parse_datetime": [
    "pickup",
    "dropoff"
   ]
  }
 ],
 "sets": [
  {
   "name": "TASK",
   "kind": "rows",
   "table": "trips"
  },
  {
   "name": "DRIVER",
   "kind": "literal",
   "members": [
    "d1",
    "d2",
    "d3",
    "d4",
    "d5",
    "d6",
    "d7",
    "d8"
   ]
  },
  {
   "name": "SLOT",
   "kind": "categories",
   "table": "trips",
   "column": "pickup_min"
  }
 ],
 "params": [
  {
   "name": "rev",
   "index": [
    "TASK"
   ],
   "table": "trips",
   "column": "total"
  },
  {
   "name": "pax",
   "index": [
    "TASK"
   ],
   "table": "trips",
   "column": "passengers"
  },
  {
   "name": "veh_cap",
   "value": 4
  }
 ],
 "vars": [
  {
   "name": "y",
   "index": [
    "TASK",
    "DRIVER"
   ],
   "domain": "Binary"
  }
 ],
 "objective": {
  "sense": "max",
  "source_text": "assign tasks to drivers to maximise platform revenue",
  "expr": {
   "terms": [
    {
     "var": "y",
     "weight": "rev",
     "over": [
      {
       "set": "TASK"
      },
      {
       "set": "DRIVER"
      }
     ]
    }
   ]
  }
 },
 "constraints": [
  {
   "name": "one_driver_per_task",
   "source_text": "a customer request is served by at most one driver",
   "forall": [
    "TASK"
   ],
   "lhs": {
    "terms": [
     {
      "var": "y",
      "over": [
       {
        "set": "TASK",
        "bind": "$TASK"
       },
       {
        "set": "DRIVER"
       }
      ]
     }
    ]
   },
   "rel": "<=",
   "rhs": {
    "const": 1.0
   }
  },
  {
   "name": "no_overlapping_schedule",
   "source_text": "no driver receives overlapping schedules",
   "forall": [
    "DRIVER",
    "SLOT"
   ],
   "lhs": {
    "terms": [
     {
      "var": "y",
      "over": [
       {
        "set": "TASK",
        "where": [
         {
          "column": "pickup_min",
          "op": "lte",
          "value": "$SLOT"
         },
         {
          "column": "dropoff_min",
          "op": "gt",
          "value": "$SLOT"
         }
        ]
       },
       {
        "set": "DRIVER",
        "bind": "$DRIVER"
       }
      ]
     }
    ]
   },
   "rel": "<=",
   "rhs": {
    "const": 1.0
   }
  },
  {
   "name": "vehicle_capacity",
   "source_text": "passenger counts never exceed vehicle limits",
   "forall": [
    "TASK"
   ],
   "lhs": {
    "terms": [
     {
      "var": "y",
      "weight": "pax",
      "over": [
       {
        "set": "TASK",
        "bind": "$TASK"
       },
       {
        "set": "DRIVER"
       }
      ]
     }
    ]
   },
   "rel": "<=",
   "rhs": {
    "terms": [
     {
      "weight": "veh_cap"
     }
    ]
   }
  }
 ]
}

Now translate this brief. Decide which shape it is FIRST (selection? assignment? scheduling?), then write the IR. Reply with ONLY the JSON.
BRIEF:
A high-end jeweler in Zurich stocks a retail vault from the wholesale inventory in diamonds.csv; each row is one stone available at wholesale cost. Deploy a fixed line of credit of CHF 250,000: the total wholesale price of the stones bought must not exceed it. The retail vault has 60 individual display slots, so at most 60 stones can be held. Total displayed stone volume cannot exceed 9,000 cubic millimetres; a stone's volume is x times y times z. No single cut grade may exceed 30% of the stones held. Carry at least two stones of every clarity grade so the range stays saleable. At most 40% of deployed capital may sit in stones priced above CHF 8,000. Hold no more than 10 stones lighter than 0.3 carats. The goal is to maximise the total carat mass held in the vault. Model only a fixed sample of the inventory: 800 rows, random seed 7.
