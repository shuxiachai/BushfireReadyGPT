"""Current focus evaluation, isolated from frozen historical builder dependencies."""

from src.agents.planner_agent import PlannerAgent
from src.focus_coverage import (
    FOCUS_COVERAGE_CHECK_NAME,
    _contains_term,
    _coverage_visible_text,
)


def evaluate_focus_area_coverage(narrative, analysis):
    """Check only application-recognised focus concepts, never raw U0 values."""

    analysis = analysis if isinstance(analysis, dict) else {}
    plan = analysis.get("plan")
    profile = analysis.get("profile")
    if not isinstance(plan, dict):
        if isinstance(profile, dict) and "concerns" in profile:
            plan = {}
        else:
            return None
    if "focus_area_concepts" in plan:
        concepts = plan.get("focus_area_concepts")
        ignored_count = plan.get("ignored_focus_area_count", 0)
    elif isinstance(profile, dict) and "concerns" in profile:
        concerns = profile.get("concerns")
        if not isinstance(concerns, list):
            return {
                "status": "fail",
                "name": FOCUS_COVERAGE_CHECK_NAME,
                "detail": "The legacy focus-area input cannot be migrated safely; regenerate the report.",
            }
        concepts, ignored_count = PlannerAgent._resolve_focus_areas(concerns)
        if ignored_count:
            return {
                "status": "fail",
                "name": FOCUS_COVERAGE_CHECK_NAME,
                "detail": (
                    "The legacy focus-area input is not an exact current allowlist match; regenerate the report "
                    "before review or export."
                ),
            }
    else:
        return None
    if not isinstance(concepts, list):
        return {
            "status": "fail",
            "name": FOCUS_COVERAGE_CHECK_NAME,
            "detail": "The deterministic focus-area contract is malformed; regenerate the analysis snapshot.",
        }

    visible = _coverage_visible_text(narrative, analysis)
    missing = []
    for candidate in concepts:
        if not isinstance(candidate, dict):
            return {
                "status": "fail",
                "name": FOCUS_COVERAGE_CHECK_NAME,
                "detail": "The deterministic focus-area contract is malformed; regenerate the analysis snapshot.",
            }
        concept = PlannerAgent.canonical_focus_concept(candidate.get("id"))
        if concept is None:
            return {
                "status": "fail",
                "name": FOCUS_COVERAGE_CHECK_NAME,
                "detail": "The deterministic focus-area contract is unknown; regenerate the analysis snapshot.",
            }
        label = concept["label"]
        terms = concept["match_terms"]
        if concept["id"] == "official_sources":
            # The application uses this exact label in its selected focus and
            # planning cues. Preserve the same visible-text/negation checks;
            # candidate labels and arbitrary intervening words remain untrusted.
            terms = [*terms, label]
        if not any(_contains_term(visible, term) for term in terms):
            missing.append(label)

    if type(ignored_count) is not int or ignored_count < 0:
        return {
            "status": "fail",
            "name": FOCUS_COVERAGE_CHECK_NAME,
            "detail": "The deterministic focus-area ignore count is malformed; regenerate the analysis snapshot.",
        }

    if missing:
        return {
            "status": "fail",
            "name": FOCUS_COVERAGE_CHECK_NAME,
            "detail": (
                "Cover every application-recognised focus area in the model-authored narrative (missing: "
                + ", ".join(missing)
                + ")."
            ),
        }

    ignored_note = (
        f" {ignored_count} unrecognised U0 focus value(s) were not promoted into trusted planning instructions."
        if ignored_count
        else ""
    )
    return {
        "status": "pass",
        "name": FOCUS_COVERAGE_CHECK_NAME,
        "detail": f"All {len(concepts)} application-recognised focus area(s) are represented.{ignored_note}",
    }
