"""The IR grammar as the generator sees it — one source of truth for prompts.

Kept beside the eval rather than inside IR_Compiler because it is *prompt* text:
what an LLM must be told to emit valid IR. `test_grammar_matches_ir.py` checks
it against the pydantic schema so the two cannot drift apart silently.

Covers all three archetypes the compiler supports:
  selection   1-D binary over table rows            (Track B: vault stocking)
  assignment  2-D binary over rows x a literal set  (Track C: dispatch)
  scheduling  assignment + a time-window constraint (Track C: no overlap)
"""

GRAMMAR = """\
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
"""

PATTERNS = """\
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
"""

RULES = """\
Hard rules:
- Output ONLY the JSON object. No prose, no markdown fences.
- Every constraint sentence in the brief becomes a constraint whose source_text
  quotes that sentence. Do not add constraints the brief does not state.
- One sentence may imply MORE THAN ONE constraint (a display case with a slot
  count AND a volume limit is two). Write both, quoting the sentence twice.
- If a quantity the brief names is not a column, derive it.
"""
