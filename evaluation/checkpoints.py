"""Run one raw generation attempt through the three checkpoints.

Input: the text a generator produced (possibly fenced, possibly not JSON).
Output: an attempt record the resilience metrics aggregate:

  {"stage": "parse|shape|meaning|data|valid",
   "errors": [{"code": ..., "location": ..., "message": ...}],
   "spec": <normalized spec dict, present when stage == "valid">}

Before checkpoint 3 the spec's tables are NORMALIZED to the eval's canonical
data (same csv path, sample n, seed) so every run binds identical rows —
required for fingerprint and solution comparison. Table names, derived
columns, and everything else the generator wrote are kept.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "IR_Compiler"))

from pydantic import ValidationError          # noqa: E402
from ir import ModelSpec                      # noqa: E402
from validate import validate, check_bound, BindError   # noqa: E402
from compiler import bind                     # noqa: E402

ROOT = str(HERE.parent)                       # diamonds.csv lives here
CANON_SAMPLE = {"n": 800, "seed": 7}


def extract_json(text: str) -> dict | None:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def normalize_tables(raw: dict) -> None:
    for t in raw.get("tables", []):
        t["path"] = "diamonds.csv"
        t["sample"] = dict(CANON_SAMPLE)


def check_attempt(text: str) -> dict:
    raw = extract_json(text)
    if raw is None:
        return {"stage": "parse",
                "errors": [{"code": "BAD_JSON", "location": "",
                            "message": "output is not parseable JSON"}]}
    normalize_tables(raw)

    try:
        spec = ModelSpec.model_validate(raw)                       # checkpoint 1
    except ValidationError as ve:
        return {"stage": "shape",
                "errors": [{"code": "BAD_SHAPE",
                            "location": ".".join(map(str, e["loc"])),
                            "message": e["msg"]} for e in ve.errors()]}

    if errs := validate(spec):                                     # checkpoint 2
        return {"stage": "meaning",
                "errors": [{"code": e.code, "location": e.location,
                            "message": e.message + (f" -> {e.fix}" if e.fix else "")}
                           for e in errs]}

    try:                                                           # checkpoint 3
        bm = bind(spec, root=ROOT)
        errs = check_bound(bm)
    except BindError as be:
        errs = be.errors
    if errs:
        return {"stage": "data",
                "errors": [{"code": e.code, "location": e.location,
                            "message": e.message + (f" -> {e.fix}" if e.fix else "")}
                           for e in errs]}

    return {"stage": "valid", "errors": [], "spec": raw}


def errors_as_feedback(record: dict) -> str:
    lines = [f"Your JSON failed checkpoint '{record['stage']}'. "
             "Fix ONLY these problems and output the full corrected JSON:"]
    for e in record["errors"][:12]:
        loc = f" at {e['location']}" if e["location"] else ""
        lines.append(f"- [{e['code']}]{loc}: {e['message']}")
    return "\n".join(lines)
