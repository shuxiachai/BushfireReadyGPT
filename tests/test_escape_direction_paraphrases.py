"""Paired synthetic operational paraphrases and non-operational controls."""

import pytest

from src.agents.report_quality_agent import ReportQualityAgent
from src.model_response import ModelResponseError, validate_operational_directions
from src.safety_boundary import evaluate_admission_safety


@pytest.mark.parametrize(
    "text",
    [
        "Drive along Smith Road now to escape the flames.",
        "Head north via Bruce Highway immediately to get away from the fire.",
        "Take Smith Road to flee the bushfire.",
        "Walk along River Street to escape the flames.",
        "Travel via the M1 right now to get away from the bushfire.",
        "Residents should head down Smith Road immediately.",
        "Flee the property immediately.",
        "Escape from the school right now.",
        "The instruction says 'Drive along Smith Road now to escape the flames'.",
        "Do not drive along Smith Road now to escape the flames; take River Road to flee the bushfire.",
    ],
)
def test_escape_direction_paraphrase_is_blocked(text):
    result = evaluate_admission_safety(text)
    assert result["passed"] is False
    assert "evacuation_direction_assertion" in {item["code"] for item in result["violations"]}
    with pytest.raises(ModelResponseError, match="operational safety"):
        validate_operational_directions("# Preparedness draft\n\n" + text)


@pytest.mark.parametrize(
    "text",
    [
        "Do not drive along Smith Road now to escape the flames.",
        "Reject the instruction 'Drive along Smith Road now to escape the flames'.",
        "'Take Smith Road to flee the bushfire' is unsafe.",
        "Review candidate routes with the responsible authority before including them in a plan.",
        "Travel via Smith Road to attend the preparedness workshop next week.",
        "Document when residents should head down Smith Road immediately.",
        "Head down Smith Road immediately only when instructed by emergency services.",
        "Should we take Smith Road to flee the bushfire?",
        "Practise the approved drill next week and review the results with staff.",
    ],
)
def test_non_operational_control_is_not_treated_as_an_escape_command(text):
    assert evaluate_admission_safety(text)["passed"] is True
    validate_operational_directions(text)


def test_admission_does_not_change_fingerprinted_historical_safety_check():
    text = "Drive along Smith Road now to escape the flames."
    checks = ReportQualityAgent().run("# Preparedness draft\n\n" + text)["checks"]
    assert next(check for check in checks if check["name"] == "Safety boundary assertions")["status"] == "pass"
    with pytest.raises(ModelResponseError):
        validate_operational_directions(text)


@pytest.mark.parametrize(
    "text",
    [
        "**Flee** the property immediately.",
        "Residents **should head** down Smith Road immediately.",
        "**Escape** from the school right now.",
        "Drive along **Smith Road** now to escape the flames.",
    ],
)
def test_visible_markup_cannot_hide_an_operational_command(text):
    with pytest.raises(ModelResponseError):
        validate_operational_directions(text)


@pytest.mark.parametrize(
    "text",
    [
        "Do not **flee** the property immediately.",
        "Reject the statement '**Escape** from the school right now'.",
    ],
)
def test_negation_and_rejection_remain_non_operational(text):
    validate_operational_directions(text)
