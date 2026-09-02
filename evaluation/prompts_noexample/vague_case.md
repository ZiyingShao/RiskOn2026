You translate a jeweler's natural-language stocking brief into a machine-readable optimization IR (a linear/mixed-integer model over table rows).

The IR is a JSON object with this exact shape (all unknown keys are rejected):

ModelSpec: {name, tables, sets, params, vars, objective, constraints}
- tables: [{name, path, sample: {n, seed}, derived: [{name, expr}]}]
  `derived` computes a new column with a pandas.eval expression, e.g. "x * y * z".
- sets: [{name, kind: "rows"|"categories", table, column?}]
  "rows" = one member per table row (the candidate stones);
  "categories" = distinct levels of a categorical column (needs `column`).
- params: [{name, index: [set...], table?, column?, value?}]
  indexed params bind a column; scalar params carry a literal `value`.
- vars: [{name, index: [set...], domain: "Binary"|"Integer"|"NonNegReal"|"Real"}]
- Expressions (LinExpr): {terms: [Term...], const: float}
  Term: {coef?, var?, weight?, over?: {set, where: [{column, op, value}]}}
  = coef * SUM over the selected rows of weight[i] * var[i].
  A Term with no `var` is a data/scalar constant. `op` is one of
  eq|ne|in|gte|lte|gt|lt. A `where` value of "$SETNAME" binds to the current
  member of a `forall` set.
- constraints: [{name, forall: [set...], lhs: LinExpr, rel: "<="|">="|"==",
   rhs: LinExpr, source_text}]
  `forall` replicates the constraint per member of a categories set.
  `source_text` MUST quote the exact sentence of the brief it encodes.
- objective: {sense: "min"|"max", expr: LinExpr, source_text}

Hard rules:
- Output ONLY the JSON object. No prose, no markdown fences.
- One table: name "inv", path "diamonds.csv", sample {"n": 800, "seed": 7}.
  Columns available: carat, cut, color, clarity, depth, table, price, x, y, z.
- Name the selection variable "x", Binary, indexed by the rows set.
- Every constraint sentence in the brief must become a constraint whose
  source_text quotes that sentence. Do not add constraints the brief does not
  state.

Translate this brief. Reply with ONLY the JSON IR.
BRIEF:
A high-end jeweler in Zurich stocks a retail vault from the wholesale inventory in diamonds.csv; each row is one stone available at wholesale cost. Deploy a fixed line of credit of CHF 250,000: the total wholesale price of the stones bought must not exceed it. Everything bought must physically fit in the retail display case, which has 60 individual slots and about 9,000 cubic millimetres of usable space. No single cut grade may exceed 30% of the stones held. Carry at least two stones of every clarity grade so the range stays saleable. At most 40% of deployed capital may sit in stones priced above CHF 8,000. The goal is to maximise the total carat mass held in the vault. Model only a fixed sample of the inventory: 800 rows, random seed 7.
