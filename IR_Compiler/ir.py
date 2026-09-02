"""
ir.py — the IR schema.

Scope: linear/mixed-integer models over *tabular rows*. Every decision variable is
indexed by an index set; every expression is a sum of linear terms, where a term is

        coef * SUM_{i in filtered(set)} weight[i] * var[i]

This grammar is deliberately narrow. It covers selection, knapsack, assignment,
blending and covering models. It does NOT cover products of variables, big-M
disjunctions written by hand, or flow conservation over arcs without an explicit
pair set. Widen it only when a real model forces you to.

Classes only. This module IS checkpoint 1 of the pipeline: `ModelSpec.model_validate(json)`
checks shape — types, required fields, legal ops, no unknown keys — generated for free
from the declarations below. Checkpoints 2 (meaning) and 3 (data) are hand-written in
validate.py.
"""

from __future__ import annotations
from typing import Literal, Optional, Union, Any
from pydantic import BaseModel, Field, ConfigDict


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown keys are LLM hallucination; reject loudly


# ---------------------------------------------------------------- data sources

class Derived(Base):
    """A column computed from other columns before binding.
    Discovered the hard way: 'display volume' is x*y*z and no such column exists."""
    name: str
    expr: str = Field(description="pandas.eval expression over existing columns, e.g. 'x * y * z'")


class TableSpec(Base):
    name: str
    path: str
    sample: Optional[dict[str, int]] = Field(
        default=None, description="{'n': 800, 'seed': 7} — reservoir for demo-scale models"
    )
    filter: list["Predicate"] = Field(
        default=[], description="row filter applied at LOAD time — this is how you take "
                                "'an operational time slice' out of a log")
    parse_datetime: list[str] = Field(
        default=[], description="timestamp columns to parse; each yields a numeric "
                                "'<col>_min' column, minutes from the earliest row. "
                                "Scheduling needs numbers, not strings.")
    derived: list[Derived] = []


# ---------------------------------------------------------------- sets & filters

class SetDef(Base):
    """Three kinds of index set:
      - 'rows'      : one member per row of a table (candidate assets, pending tasks)
      - 'categories': the distinct levels of a categorical column (cut, clarity, zone)
      - 'literal'   : members given outright, with NO table behind them — the driver
                      pool, the time slots of a shift, machines on a line. Assignment
                      and scheduling models need a second axis that the data does not
                      contain; this is it.
    """
    name: str
    kind: Literal["rows", "categories", "literal"]
    table: Optional[str] = None                 # required for rows/categories
    column: Optional[str] = None                # required iff kind == 'categories'
    members: list[Union[str, int, float]] = []  # required iff kind == 'literal'


class Predicate(Base):
    """A row filter. `value` may be a literal, or '$SETNAME' to bind to the current
    member of a forall index set (that is how 'for each cut grade g' is expressed)."""
    column: str
    op: Literal["eq", "ne", "in", "gte", "lte", "gt", "lt"]
    value: Union[str, float, int, list[Union[str, float, int]]]


class IndexRef(Base):
    """One axis of a summation.

    `bind` pins this axis to a value carried by the constraint's `forall` instead
    of summing over it — that is how "for each driver d, over that driver's own
    assignments" is written: over=[{set: I, where: ...}, {set: D, bind: "$D"}].
    """
    set: str
    where: list[Predicate] = []  # conjunction; row sets only
    bind: Optional[str] = Field(
        default=None, description="'$SETNAME' from `forall` — fix this axis instead of summing")


# ---------------------------------------------------------------- expressions

class Term(Base):
    coef: float = 1.0
    var: Optional[str] = None          # None => data-only term (a constant, computed at bind time)
    weight: Optional[str] = None       # param name; None => weight 1
    # One IndexRef = 1-D (selection models). A LIST = one entry per variable
    # dimension, in declaration order (assignment/scheduling models).
    over: Optional[Union[IndexRef, list[IndexRef]]] = None


class LinExpr(Base):
    terms: list[Term] = []
    const: float = 0.0


# ---------------------------------------------------------------- model elements

class ParamDef(Base):
    name: str
    index: list[str] = []                       # [] => scalar
    column: Optional[str] = None                # bind from a table column
    table: Optional[str] = None
    value: Optional[float] = None               # or a literal scalar


class VarDef(Base):
    name: str
    index: list[str]
    domain: Literal["Binary", "Integer", "NonNegReal", "Real"]
    lb: Optional[float] = None
    ub: Optional[float] = None


class ConstraintDef(Base):
    name: str
    forall: list[str] = []                      # index sets to replicate over; bound to $g, $h, ...
    lhs: LinExpr
    rel: Literal["<=", ">=", "=="]
    rhs: LinExpr
    source_text: str = Field(description="the sentence in the brief this constraint came from")


class Objective(Base):
    sense: Literal["min", "max"]
    expr: LinExpr
    source_text: str


class ModelSpec(Base):
    name: str
    tables: list[TableSpec]
    sets: list[SetDef]
    params: list[ParamDef] = []
    vars: list[VarDef]
    objective: Objective
    constraints: list[ConstraintDef] = []
