"""Current safety corrections preserve historical checks and independent advice."""

import pytest

from src.agents.report_quality_agent import ReportQualityAgent
from src.current_safety_boundary import evaluate_current_safety_boundaries
from src.safety_boundary import evaluate_safety_boundaries

_ROAD_STATUS_DENIAL = (
    "It is planning support only: no live warning feed is connected, "
    "and no road, route, place or premises is confirmed safe or operational."
)


@pytest.mark.parametrize(
    "text",
    [
        _ROAD_STATUS_DENIAL,
        _ROAD_STATUS_DENIAL.upper(),
        _ROAD_STATUS_DENIAL.replace("and no road", "and\nno road"),
        _ROAD_STATUS_DENIAL.replace("is confirmed", "is\t confirmed"),
    ],
)
def test_complete_planning_status_denial_is_allowed_only_by_current_adapter(text):
    assert len(_ROAD_STATUS_DENIAL) < 280
    result = evaluate_current_safety_boundaries(text)
    assert result["passed"] is True
    assert result["violations"] == []
    assert result["summary"] == {"total": 0, "by_category": {}}
    quality = ReportQualityAgent().run("## 2. Executive Summary\n" + text)
    check = next(item for item in quality["checks"] if item["name"] == "Safety boundary assertions")
    assert check["status"] == "pass"


def test_historical_safety_function_keeps_original_denial_finding():
    before = evaluate_safety_boundaries(_ROAD_STATUS_DENIAL)
    assert before["passed"] is False
    assert {item["code"] for item in before["violations"]} == {"road_status_assertion"}
    assert evaluate_current_safety_boundaries(_ROAD_STATUS_DENIAL)["passed"] is True
    assert evaluate_safety_boundaries(_ROAD_STATUS_DENIAL) == before


@pytest.mark.parametrize(
    "text,code",
    [
        (_ROAD_STATUS_DENIAL + " The highway is open.", "road_status_assertion"),
        (_ROAD_STATUS_DENIAL + "\nThe highway is open.", "road_status_assertion"),
        (_ROAD_STATUS_DENIAL[:-1] + ", but the highway is open.", "road_status_assertion"),
        (_ROAD_STATUS_DENIAL[:-1] + "; the highway is open.", "road_status_assertion"),
        (_ROAD_STATUS_DENIAL[:-1] + " and the highway is open.", "road_status_assertion"),
        (_ROAD_STATUS_DENIAL[:-1] + ", so use Smith Road to evacuate.", "evacuation_direction_assertion"),
        (_ROAD_STATUS_DENIAL + " The hall is safe.", "premises_status_assertion"),
        (_ROAD_STATUS_DENIAL + " No human review is required.", "human_review_removal"),
        (_ROAD_STATUS_DENIAL.replace("and no road", "and the road"), "road_status_assertion"),
        ("No access roads are open.", "road_status_assertion"),
        (
            "| Disclaimer | Status |\n| --- | --- |\n| " + _ROAD_STATUS_DENIAL + " | The highway is open. |",
            "road_status_assertion",
        ),
        ("The highway is open and " + _ROAD_STATUS_DENIAL, "road_status_assertion"),
        (
            _ROAD_STATUS_DENIAL[:-1] + ", " + "unverified context " * 40 + "and the highway is open.",
            "road_status_assertion",
        ),
    ],
)
def test_denial_does_not_exempt_appended_assertions_other_cells_or_other_categories(text, code):
    result = evaluate_current_safety_boundaries(text)
    assert result["passed"] is False
    assert code in {item["code"] for item in result["violations"]}
    assert result["summary"]["total"] == len(result["violations"])


def test_only_known_denial_is_removed_and_other_findings_keep_their_exact_content():
    unsafe = "The highway is open. The hall is safe. No human review is required."
    expected = evaluate_safety_boundaries(unsafe)
    result = evaluate_current_safety_boundaries(_ROAD_STATUS_DENIAL + " " + unsafe)
    assert result == expected


def test_unrelated_hypothetical_newline_does_not_gain_the_denial_whitespace_exception():
    text = "If an official update arrives\nThe highway is open."
    assert evaluate_current_safety_boundaries(text) == evaluate_safety_boundaries(text)
    assert evaluate_current_safety_boundaries(text)["passed"] is False
