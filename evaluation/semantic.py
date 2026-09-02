"""Semantic translation fidelity.

Cheaper and complementary to the structural check: does every obligation
sentence in the brief have a `source_text` pointing at it? A sentence with no
pointer is a dropped constraint. Matching is deterministic token overlap —
no LLM judges anything here.
"""

from __future__ import annotations

import re

_STOP = {"the", "a", "an", "of", "in", "to", "be", "is", "are", "so", "may",
         "can", "must", "and", "or", "it", "its", "that", "this", "at", "on"}


def _tokens(s: str) -> set[str]:
    words = re.findall(r"[a-z0-9%]+", s.lower().replace(",", ""))
    return {w for w in words if w not in _STOP}


def jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def coverage(obligations: list[str], spec_dict: dict, threshold: float = 0.25) -> dict:
    """For each obligation sentence, the best-matching source_text in the spec."""
    pointers = [("objective", spec_dict["objective"].get("source_text", ""))]
    pointers += [(c["name"], c.get("source_text", ""))
                 for c in spec_dict.get("constraints", [])]
    table = []
    for sent in obligations:
        best_name, best_score = None, 0.0
        for name, src in pointers:
            s = jaccard(sent, src)
            if s > best_score:
                best_name, best_score = name, s
        table.append({"sentence": sent,
                      "covered": best_score >= threshold,
                      "matched": best_name,
                      "score": round(best_score, 3)})
    covered = sum(1 for row in table if row["covered"])
    return {"covered": covered, "total": len(table),
            "rate": covered / len(table) if table else 1.0, "table": table}
