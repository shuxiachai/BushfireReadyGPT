import pytest

from src.agents.report_quality_agent import ReportQualityAgent
from src.safety_boundary import SafetyBoundaryEvaluator, evaluate_safety_boundaries


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        ("There is an active bushfire near the school.", "live_condition_assertion"),
        ("The fire is currently approaching the community.", "live_condition_assertion"),
        ("The current fire danger is extreme.", "live_condition_assertion"),
        ("There is no active fire threat in Cairns today.", "live_condition_assertion"),
        ("Residents are currently under an immediate bushfire threat.", "live_condition_assertion"),
        ("A total fire ban is now in force.", "live_condition_assertion"),
        ("There are two active fires near Cairns.", "live_condition_assertion"),
        ("An active bushfire is burning five kilometres away.", "live_condition_assertion"),
        ("Bushfire smoke is affecting the school now.", "live_condition_assertion"),
        ("Today's fire danger rating is extreme.", "live_condition_assertion"),
        ("A total fire ban applies today.", "live_condition_assertion"),
        ("The community is safe from the current fire.", "live_condition_assertion"),
        ("You are safe right now.", "live_condition_assertion"),
        ("The highway remains open and passable.", "road_status_assertion"),
        ("Smith Road is currently clear.", "road_status_assertion"),
        ("No access roads are open.", "road_status_assertion"),
        ("Smith Road is currently closed.", "road_status_assertion"),
        ("Smith Road has reopened.", "road_status_assertion"),
        ("The Bruce Highway is closed.", "road_status_assertion"),
        ("Road status: OPEN.", "road_status_assertion"),
        ("The M1 is open.", "road_status_assertion"),
        ("Identify safe evacuation routes for residents.", "road_status_assertion"),
        ("The primary evacuation route is Smith Road.", "road_status_assertion"),
        ("Evacuate now.", "evacuation_direction_assertion"),
        ("Residents must leave immediately.", "evacuation_direction_assertion"),
        ("An evacuation order is now in force.", "evacuation_direction_assertion"),
        ("Use Smith Road to evacuate.", "evacuation_direction_assertion"),
        ("You must evacuate.", "evacuation_direction_assertion"),
        ("Evacuate the site.", "evacuation_direction_assertion"),
        ("Residents are ordered to leave.", "evacuation_direction_assertion"),
        ("The council advises residents to evacuate now.", "evacuation_direction_assertion"),
        ("An evacuation order was issued this morning.", "evacuation_direction_assertion"),
        ("Exit via Smith Road.", "evacuation_direction_assertion"),
        ('The warning reads "Evacuate now."', "evacuation_direction_assertion"),
        ("Shelter in place immediately.", "evacuation_direction_assertion"),
        ("The community hall is safe and open.", "premises_status_assertion"),
        ("The school has been approved as an evacuation centre.", "premises_status_assertion"),
        ("Proceed to the designated assembly point.", "premises_status_assertion"),
        ("The hall is confirmed to be safe.", "premises_status_assertion"),
        ("The hall was approved as an evacuation centre.", "premises_status_assertion"),
        ("The refuge is now open.", "premises_status_assertion"),
        ("Community Hall will serve as the evacuation centre.", "premises_status_assertion"),
        ("This route guarantees your safety.", "absolute_safety_guarantee"),
        ("The shelter is 100% safe.", "absolute_safety_guarantee"),
        ("This plan eliminates all risk.", "absolute_safety_guarantee"),
        ("This plan guarantees survival.", "absolute_safety_guarantee"),
        ("Following this plan means you will be safe.", "absolute_safety_guarantee"),
        ("This route is risk-free.", "absolute_safety_guarantee"),
        ("This guarantees nobody will be harmed.", "absolute_safety_guarantee"),
        ("A Watch and Act warning is current.", "live_condition_assertion"),
        ("The fire is 40% contained.", "live_condition_assertion"),
        ("A reviewer wrote, 'The hall is safe.'", "premises_status_assertion"),
        ("This report is an official operational plan.", "draft_boundary_removal"),
        ("This document is no longer a draft.", "draft_boundary_removal"),
        ("Remove the draft status notice.", "draft_boundary_removal"),
        ("Publish this report as final.", "draft_boundary_removal"),
        ("Do not check official warnings before using this plan.", "official_verification_removal"),
        ("Official sources are unnecessary.", "official_verification_removal"),
        ("Follow this report instead of official advice.", "official_verification_removal"),
        ("Official warnings need not be checked.", "official_verification_removal"),
        ("No human review is required.", "human_review_removal"),
        ("Skip the organisational approval.", "human_review_removal"),
        ("This can be used without further human review.", "human_review_removal"),
        ("Human review may be skipped.", "human_review_removal"),
    ],
)
def test_blocks_high_confidence_safety_boundary_violations(text, expected_code):
    result = evaluate_safety_boundaries(text)

    assert result["passed"] is False
    assert result["status"] == "blocked"
    assert expected_code in {item["code"] for item in result["violations"]}
    assert result["summary"]["total"] >= 1


@pytest.mark.parametrize(
    "text",
    [
        "This report does not provide live fire conditions or current threat information.",
        "Current warnings and fire danger ratings must be checked through official emergency services.",
        "The app cannot confirm whether Smith Road is open or closed.",
        "It is unknown whether Smith Road is open and whether the highway is open.",
        "The app cannot confirm whether Smith Road is open and passable.",
        "Confirm whether the M1 is open and clear before operational use.",
        "Confirm whether access roads are passable before operational use.",
        "Do not assume that the highway is open.",
        "Follow emergency-service directions; do not infer that any route is safe.",
        "Is Smith Road open? Check the official source.",
        "Map multiple candidate evacuation routes and verify them with local authorities.",
        "Include clear, accessible evacuation routes in the draft for local verification.",
        "No evacuation route is confirmed safe.",
        "If an evacuation order is issued, follow authorised emergency-service instructions.",
        "Be prepared to leave early when official services advise you to do so.",
        "Do not use Smith Road to evacuate unless authorised services direct it.",
        "The hall is a candidate assembly point pending inspection and local approval.",
        "Potential evacuation centres must be verified by the responsible organisation.",
        "The plan reduces risk but cannot guarantee safety.",
        "No plan guarantees complete safety.",
        "This remains a draft for responsible human review.",
        "The responsible organisation must approve the draft before formal use.",
        "Do not remove the draft notice or skip human review.",
        "Official sources are required for current warnings and evacuation orders.",
        "The report does not replace official emergency advice.",
        "This report may not be used without human review and organisational approval.",
        "The checklist asks reviewers to verify official warnings and road status.",
        "The report is approved only after organisational sign-off.",
        "The report is ready for operational use only after approval.",
        "Whether the hall is open remains unknown.",
        "It is unknown whether the road is open.",
        "The statement that the shelter is 100% safe is prohibited.",
        "Reviewers must reject the claim that no human review is required.",
        "There is no need to say that official sources are unnecessary.",
        "The phrase 'the hall is safe' must be removed.",
        "The report does not verify that there is an active fire.",
        "The system must not claim that the fire is active.",
        "Official warnings are not optional.",
        "Plans should define when residents must evacuate.",
        "The plan should specify conditions under which residents must evacuate.",
        "Residents must evacuate only when directed by official emergency services.",
        "If Smith Road is closed, use another candidate route after checking official advice.",
        "Community Hall will serve as an evacuation centre only after local approval.",
        "No option is risk-free.",
    ],
)
def test_allows_planning_uncertainty_and_governance_boundaries(text):
    result = SafetyBoundaryEvaluator().run(text)

    assert result["passed"] is True
    assert result["status"] == "passed"
    assert result["violations"] == []
    assert result["summary"] == {"total": 0, "by_category": {}}


def test_reports_each_rule_once_per_sentence_and_summarises_categories():
    result = evaluate_safety_boundaries(
        "The hall is safe and the approved assembly point is open. "
        "There is an active bushfire nearby. The road remains open."
    )

    assert result["status"] == "blocked"
    assert [item["code"] for item in result["violations"]].count("premises_status_assertion") == 1
    assert result["summary"]["by_category"] == {
        "live_conditions": 1,
        "premises_status": 1,
        "road_and_route_status": 1,
    }


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        (
            "The app cannot confirm whether Smith Road is open, but the highway is open.",
            "road_status_assertion",
        ),
        (
            "The statement that the shelter is 100% safe is prohibited, but the school shelter is 100% safe.",
            "absolute_safety_guarantee",
        ),
        (
            "The claim that the hall is safe must be removed and the refuge is now open.",
            "premises_status_assertion",
        ),
        ("If Smith Road is closed, the M1 is open.", "road_status_assertion"),
        (
            "If the warning level is Watch and Act, shelter in place immediately.",
            "evacuation_direction_assertion",
        ),
        (
            "It is unknown whether Smith Road is open, while the highway is open.",
            "road_status_assertion",
        ),
        (
            "It is unknown whether Smith Road is open, whereas the M1 is open.",
            "road_status_assertion",
        ),
        (
            "The app cannot confirm whether Smith Road is open and separately the M1 is open.",
            "road_status_assertion",
        ),
        (
            "It is unknown whether Smith Road is open, and the highway is open.",
            "road_status_assertion",
        ),
    ],
)
def test_safe_or_conditional_first_claim_does_not_mask_later_assertion(text, expected_code):
    result = evaluate_safety_boundaries(text)

    assert result["passed"] is False
    assert expected_code in {item["code"] for item in result["violations"]}


def test_empty_input_passes_with_an_explicit_assessment_scope():
    result = evaluate_safety_boundaries(None)

    assert result["passed"] is True
    assert result["violations"] == []
    assert "does not verify" in result["assessment_scope"]


def test_assertive_sounding_question_is_not_treated_as_a_report_claim():
    assert evaluate_safety_boundaries("The road is open?")["passed"] is True


def test_repeated_identical_violation_is_reported_once():
    result = evaluate_safety_boundaries("The road is open. The road is open.")

    assert result["summary"]["total"] == 1


def test_long_violation_excerpt_is_bounded():
    result = evaluate_safety_boundaries("The road is open " + "without verified status " * 30 + ".")

    assert len(result["violations"][0]["excerpt"]) <= 280
    assert result["violations"][0]["excerpt"].endswith("…")


def test_report_quality_checks_only_model_narrative_for_place_assertions():
    report = """# Preparedness draft

The narrative keeps all locations as candidates pending local verification.

## Evidence Tables

The gymnasium is a confirmed safe assembly point. Smith Road is open.

## Human Review Sign-off

Approved by organisation.
"""

    quality = ReportQualityAgent().run(report)
    checks = {item["name"]: item["status"] for item in quality["checks"]}

    assert checks["Assembly point wording"] == "pass"
    assert checks["Safety boundary assertions"] == "pass"
