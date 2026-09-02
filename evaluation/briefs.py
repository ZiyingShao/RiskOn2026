"""The perturbation set: one base brief and six variants.

Each brief is a dict:
  name                 short id, used in file names
  text                 the full natural-language brief handed to the generator
  obligations          the sentences that MUST be represented in the IR
                       (used by the semantic-fidelity check; the sampling
                       sentence is deliberately not an obligation)
  reference            file name under references/, or None (contradiction
                       brief has no unique ground truth)
  expect_infeasible    True when the correct model has no feasible solution
  probe                optional note on what this variant is testing
"""

_PREAMBLE = (
    "A high-end jeweler in Zurich stocks a retail vault from the wholesale "
    "inventory in diamonds.csv; each row is one stone available at wholesale cost. "
)
_SAMPLING = (
    " Model only a fixed sample of the inventory: 800 rows, random seed 7."
)

_S = {
    "budget": "Deploy a fixed line of credit of CHF 250,000: the total wholesale "
              "price of the stones bought must not exceed it.",
    "budget_renamed": "The bank has extended a CHF 400,000 facility; the total "
                      "wholesale price of the stones bought must stay within the facility.",
    "slots": "The retail vault has 60 individual display slots, so at most 60 "
             "stones can be held.",
    "volume": "Total displayed stone volume cannot exceed 9,000 cubic millimetres; "
              "a stone's volume is x times y times z.",
    "cut30": "No single cut grade may exceed 30% of the stones held.",
    "cut25": "No single cut grade may exceed 25% of the stones held.",
    "cut20_late": "Because the buyer dislikes concentration, keep every cut grade "
                  "to at most 20% of the stones held.",
    "clarity2": "Carry at least two stones of every clarity grade so the range "
                "stays saleable.",
    "clarity80": "Carry at least eighty stones of every clarity grade so the "
                 "range stays saleable.",
    "premium": "At most 40% of deployed capital may sit in stones priced above "
               "CHF 8,000.",
    "small": "Hold no more than 10 stones lighter than 0.3 carats.",
    "case_vague": "Everything bought must physically fit in the retail display "
                  "case, which has 60 individual slots and about 9,000 cubic "
                  "millimetres of usable space.",
    "objective": "The goal is to maximise the total carat mass held in the vault.",
}


def _brief(sentences: list[str]) -> str:
    return _PREAMBLE + " ".join(sentences) + _SAMPLING


BRIEFS = [
    {
        "name": "base",
        "text": _brief([_S["budget"], _S["slots"], _S["volume"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["objective"]]),
        "obligations": [_S["budget"], _S["slots"], _S["volume"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["objective"]],
        "reference": "base.json",
        "expect_infeasible": False,
        "probe": "control - matches the few-shot example",
    },
    {
        "name": "cap25",
        "text": _brief([_S["budget"], _S["slots"], _S["volume"], _S["cut25"],
                        _S["clarity2"], _S["premium"], _S["objective"]]),
        "obligations": [_S["budget"], _S["slots"], _S["volume"], _S["cut25"],
                        _S["clarity2"], _S["premium"], _S["objective"]],
        "reference": "cap25.json",
        "expect_infeasible": False,
        "probe": "30% -> 25%: does the number track?",
    },
    {
        "name": "small_stones",
        "text": _brief([_S["budget"], _S["slots"], _S["volume"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["small"], _S["objective"]]),
        "obligations": [_S["budget"], _S["slots"], _S["volume"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["small"], _S["objective"]],
        "reference": "small_stones.json",
        "expect_infeasible": False,
        "probe": "new constraint family not in the few-shot example",
    },
    {
        "name": "no_volume",
        "text": _brief([_S["budget"], _S["slots"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["objective"]]),
        "obligations": [_S["budget"], _S["slots"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["objective"]],
        "reference": "no_volume.json",
        "expect_infeasible": False,
        "probe": "volume limit removed: does it disappear, or leak in from the "
                 "few-shot example? (the overfitting probe)",
    },
    {
        "name": "renamed_budget",
        "text": _brief([_S["budget_renamed"], _S["slots"], _S["volume"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["objective"]]),
        "obligations": [_S["budget_renamed"], _S["slots"], _S["volume"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["objective"]],
        "reference": "renamed_budget.json",
        "expect_infeasible": False,
        "probe": "budget renamed to 'CHF 400,000 facility': does it still find it?",
    },
    {
        "name": "infeasible",
        "text": _brief([_S["budget"], _S["slots"], _S["volume"], _S["cut30"],
                        _S["clarity80"], _S["premium"], _S["objective"]]),
        "obligations": [_S["budget"], _S["slots"], _S["volume"], _S["cut30"],
                        _S["clarity80"], _S["premium"], _S["objective"]],
        "reference": "infeasible.json",
        "expect_infeasible": True,
        "probe": "80 stones x 8 clarity grades > 60 slots: does the diagnosis fire?",
    },
    {
        "name": "vague_case",
        "text": _brief([_S["budget"], _S["case_vague"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["objective"]]),
        "obligations": [_S["budget"], _S["case_vague"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["objective"]],
        "reference": "vague_case.json",
        "expect_infeasible": False,
        "probe": "one vague sentence must become TWO constraints (slot count + "
                 "volume cap) and the volume one needs a derived x*y*z column. "
                 "A dropped constraint here is invisible to every checkpoint — "
                 "only structural recall against the reference catches it.",
    },
    {
        "name": "contradiction",
        "text": _brief([_S["budget"], _S["slots"], _S["volume"], _S["cut30"],
                        _S["clarity2"], _S["premium"], _S["cut20_late"], _S["objective"]]),
        "obligations": [_S["budget"], _S["slots"], _S["volume"],
                        _S["clarity2"], _S["premium"], _S["objective"]],
        "reference": None,
        "expect_infeasible": False,
        "probe": "brief says 30% early and 20% late for the same cap: "
                 "does it notice, or silently pick one?",
    },
]

BY_NAME = {b["name"]: b for b in BRIEFS}

# ---------------------------------------------------------------- Track C
# Assignment / scheduling over an operational log. Same harness, different
# archetype: the model needs a 2-D variable and a resource pool that the data
# does not contain.

_C_PREAMBLE = (
    "A ride-hailing platform is dispatching a busy shift. The operational log "
    "taxis.csv holds completed trips; treat each row in the shift window as a "
    "pending customer request, with its pickup and dropoff timestamps, its "
    "passenger count, and the fare in the `total` column as the revenue it "
    "would earn. "
)
_C_SLICE = (" Work only the shift running from 08:00 to 09:00 on 2019-03-06.")

_CS = {
    "drivers": "Four drivers are on shift: d1, d2, d3 and d4.",
    "once": "A customer request can be given to at most one driver, and some "
            "requests will go unserved.",
    "overlap": "No driver may receive overlapping schedules — a trip occupies "
               "its driver from its pickup time until its dropoff time.",
    "capacity": "Passenger counts must never exceed the four-seat vehicle limit.",
    "objective": "Assign requests to drivers so as to maximise total platform "
                 "revenue.",
}

TRACK_C_BRIEFS = [
    {
        "name": "dispatch",
        "text": (_C_PREAMBLE + " ".join([_CS["drivers"], _CS["once"], _CS["overlap"],
                                         _CS["capacity"], _CS["objective"]])
                 + _C_SLICE),
        "obligations": [_CS["once"], _CS["overlap"], _CS["capacity"], _CS["objective"]],
        "reference": "dispatch.json",
        "expect_infeasible": False,
        "probe": "the assignment/scheduling archetype: needs a 2-D variable, a "
                 "literal driver pool, parsed timestamps and an occupancy "
                 "constraint — none of which the Track B grammar could express",
    },
]

ALL_BRIEFS = BRIEFS + TRACK_C_BRIEFS
ALL_BY_NAME = {b["name"]: b for b in ALL_BRIEFS}
