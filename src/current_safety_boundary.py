"""Current-policy corrections without changing the frozen historical safety lint."""

from __future__ import annotations

import re
from collections import Counter

from src.safety_boundary import evaluate_safety_boundaries

_ROAD_STATUS_DENIAL = (
    "It is planning support only: no live warning feed is connected, "
    "and no road, route, place or premises is confirmed safe or operational."
)
_WRAPPED_ROAD_STATUS_DENIAL = re.compile(re.escape(_ROAD_STATUS_DENIAL).replace(r"\ ", r"\s+"), re.I)


def evaluate_current_safety_boundaries(text: str) -> dict:
    """Exclude one complete status denial; retain every other rule and assertion.

    Folding is confined to this exact complete sentence so soft wrapping does
    not split it in the historical line-based lint. Original report bytes and
    all other sentence/clause boundaries are untouched. Exact full-excerpt
    equality (well below the excerpt limit) never excuses appended advice.
    """
    shadow = _WRAPPED_ROAD_STATUS_DENIAL.sub(lambda match: " ".join(match[0].split()), str(text or ""))
    result = evaluate_safety_boundaries(shadow)
    violations = [
        item
        for item in result["violations"]
        if not (
            item["code"] == "road_status_assertion"
            and " ".join(item["excerpt"].split()).casefold() == _ROAD_STATUS_DENIAL.casefold()
        )
    ]
    if len(violations) == len(result["violations"]):
        return result
    categories = Counter(item["category"] for item in violations)
    return {
        **result,
        "passed": not violations,
        "status": "blocked" if violations else "passed",
        "violations": violations,
        "summary": {"total": len(violations), "by_category": dict(sorted(categories.items()))},
    }
