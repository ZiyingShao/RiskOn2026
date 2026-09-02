"""Write prompts/<brief>.md — the full generation prompt for each brief.

Prompt = role + IR grammar reference + hard rules + one few-shot example
(the base brief paired with its reference IR) + the target brief.
The few-shot example deliberately CONTAINS the volume constraint, so the
`no_volume` brief tests whether the generator copies it anyway.
Run once:  python make_prompts.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from briefs import BRIEFS, BY_NAME   # noqa: E402

GRAMMAR = """\
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
"""

RULES = """\
Hard rules:
- Output ONLY the JSON object. No prose, no markdown fences.
- One table: name "inv", path "diamonds.csv", sample {"n": 800, "seed": 7}.
  Columns available: carat, cut, color, clarity, depth, table, price, x, y, z.
- Name the selection variable "x", Binary, indexed by the rows set.
- Every constraint sentence in the brief must become a constraint whose
  source_text quotes that sentence. Do not add constraints the brief does not
  state.
"""


def build_prompt(target_brief: dict, example_spec: dict) -> str:
    return (
        "You translate a jeweler's natural-language stocking brief into a "
        "machine-readable optimization IR (a linear/mixed-integer model over "
        "table rows).\n\n"
        + GRAMMAR + "\n" + RULES + "\n"
        "Worked example.\nBRIEF:\n" + BY_NAME["base"]["text"] + "\n\n"
        "IR:\n" + json.dumps(example_spec, indent=1) + "\n\n"
        "Now translate this brief. Reply with ONLY the JSON IR.\nBRIEF:\n"
        + target_brief["text"] + "\n"
    )


def build_prompt_no_example(target_brief: dict) -> str:
    """Ablation variant: same grammar and rules, NO worked example — used to
    measure how much of first-pass validity the few-shot example buys."""
    return (
        "You translate a jeweler's natural-language stocking brief into a "
        "machine-readable optimization IR (a linear/mixed-integer model over "
        "table rows).\n\n"
        + GRAMMAR + "\n" + RULES + "\n"
        "Translate this brief. Reply with ONLY the JSON IR.\nBRIEF:\n"
        + target_brief["text"] + "\n"
    )


if __name__ == "__main__":
    example = json.load(open(HERE / "references" / "base.json"))
    out = HERE / "prompts"
    out.mkdir(exist_ok=True)
    nfs = HERE / "prompts_noexample"
    nfs.mkdir(exist_ok=True)
    for b in BRIEFS:
        (out / f"{b['name']}.md").write_text(build_prompt(b, example))
        (nfs / f"{b['name']}.md").write_text(build_prompt_no_example(b))
        print(f"prompts/{b['name']}.md + prompts_noexample/{b['name']}.md")
