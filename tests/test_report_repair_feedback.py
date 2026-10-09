"""Offline tests for application-owned content repair instructions and hostile inputs."""

from copy import deepcopy

import pytest

from src.report_generation_quality import (
    MAX_REPORT_REPAIR_PROMPT_CHARACTERS,
    _content_repair_feedback,
)
from src.report_generation_quality import (
    build_report_repair_prompt as _production_repair_prompt,
)
from tests.support.report_fixtures import with_owned_field_selectors


def build_report_repair_prompt(*args, analysis=None, **kwargs):
    return _production_repair_prompt(*args, analysis=with_owned_field_selectors(analysis or {}), **kwargs)


_FINDINGS = [
    ("Processed community provenance", "p2_period_missing", "P2"),
    ("Local proposal attribution", "local_task_requires_own_proposal_and_confirmer", "TASK"),
    ("Rule-derived causal qualification", "causal_planning_inference_unqualified", "CAUSAL"),
    (
        "Submitted passage scope and conflicts",
        "physical_assembly_criteria_require_authority_verification",
        "SOURCE/ASSEMBLY",
    ),
    ("Narrative word budget", "narrative_word_budget", "LENGTH"),
]


def _failed_check(name, code, **extra):
    return {"name": name, "status": "fail", "findings": [{"code": code}], **extra}


@pytest.mark.parametrize("name,code,group", _FINDINGS)
def test_each_recognized_failed_check_adds_only_its_fixed_group(name, code, group):
    quality = {"checks": [_failed_check(name, code)]}
    original = deepcopy(quality)
    feedback = _content_repair_feedback(quality)
    assert feedback.startswith(f"- {group}:")
    assert feedback.count("\n- ") == 0
    assert code not in feedback
    assert quality == original


@pytest.mark.parametrize("status", ["pass", "warning", "FAIL", None, [], {}])
def test_only_exact_failed_status_can_select_content_corrections(status):
    check = _failed_check("Processed community provenance", "p2_period_missing")
    check["status"] = status
    assert _content_repair_feedback({"checks": [check]}) == ""


@pytest.mark.parametrize(
    "change",
    [
        {"name": "Processed community provenance HOSTILE"},
        {"name": ["Processed community provenance"]},
        {"findings": None},
        {"findings": "p2_period_missing"},
        {"findings": [{"code": ["p2_period_missing"]}]},
        {"findings": [{"code": "p2_period_missing HOSTILE"}]},
        {"findings": [{"code": "narrative_word_budget"}]},
        {"findings": [{"name": "p2_period_missing"}]},
        {"findings": ["p2_period_missing"]},
    ],
)
def test_exact_name_and_matching_structured_code_are_required(change):
    check = _failed_check("Processed community provenance", "p2_period_missing")
    check.update(change)
    check["detail"] = "p2_period_missing HOSTILE DETAIL"
    assert _content_repair_feedback({"checks": [check]}) == ""


@pytest.mark.parametrize("checks", [None, {}, "HOSTILE CHECKS", [None, "HOSTILE", 123]])
def test_malformed_check_containers_are_not_instructions(checks):
    assert _content_repair_feedback({"checks": checks}) == ""


@pytest.mark.parametrize("word_count", [0, 649, 650, 800, 801, 100_000])
def test_only_bounded_integer_word_count_is_rendered(word_count):
    feedback = _content_repair_feedback(
        {"checks": [_failed_check("Narrative word budget", "narrative_word_budget", word_count=word_count)]}
    )
    assert f"Measured authored words: {word_count}." in feedback
    assert "650–800 authored words" in feedback
    assert "all 15 sections with at least 300 prose words" in feedback


@pytest.mark.parametrize("word_count", [-1, 100_001, 10**100, True, False, 801.0, "801 HOSTILE", None, [], {}])
def test_invalid_word_metrics_never_reach_feedback(word_count):
    feedback = _content_repair_feedback(
        {"checks": [_failed_check("Narrative word budget", "narrative_word_budget", word_count=word_count)]}
    )
    assert "- LENGTH:" in feedback
    assert "Measured authored words:" not in feedback
    assert "HOSTILE" not in feedback


def test_word_count_is_not_taken_from_other_checks_or_gate_details():
    quality = {
        "checks": [_failed_check("Processed community provenance", "p2_period_missing", word_count=98765)],
        "word_count": 98765,
        "approval_gate": {
            "blocking_failures": [
                {"name": "Narrative word budget", "detail": "narrative_word_budget: word_count 98765"}
            ]
        },
    }
    feedback = _content_repair_feedback(quality)
    assert "Measured authored words:" not in feedback
    assert "98765" not in feedback
    assert "- LENGTH:" not in feedback


def test_all_content_groups_are_deduplicated_bounded_and_do_not_repeat_free_text():
    checks = [_failed_check(name, code, detail="PRIVATE CLAIM", word_count=100_000) for name, code, _group in _FINDINGS]
    quality = {"checks": checks * 100}
    original = deepcopy(quality)
    feedback = _content_repair_feedback(quality)
    assert 1200 <= len(feedback) <= 1400
    for _name, _code, group in _FINDINGS:
        assert feedback.count(f"- {group}:") == 1
    assert feedback.count("Measured authored words: 100000.") == 1
    assert "PRIVATE CLAIM" not in feedback
    assert quality == original


def test_repair_prompt_does_not_echo_hostile_names_details_codes_metrics_or_prior_text():
    checks = [
        _failed_check(name, code, detail="HOSTILE_DETAIL", findings=[{"code": code, "excerpt": "HOSTILE_CLAIM"}])
        for name, code, _group in _FINDINGS
    ]
    checks.append(_failed_check("HOSTILE_NAME", "HOSTILE_CODE", word_count="HOSTILE_METRIC"))
    checks[0]["findings"].append({"code": "HOSTILE_UNKNOWN_CODE"})
    quality = {
        "checks": checks,
        "approval_gate": {
            "blocking_failures": [{"name": item["name"], "detail": "HOSTILE_GATE_DETAIL"} for item in checks]
            + [{"name": "Required sections", "detail": "HOSTILE_GENERIC_DETAIL"}],
        },
    }
    prompt = build_report_repair_prompt(
        "HOSTILE_ORIGINAL_PROMPT", "HOSTILE_PRIOR_RESPONSE", quality, analysis={"profile": {}}
    )
    assert "HOSTILE" not in prompt
    assert "- Required sections" in prompt
    assert "- P2:" in prompt and "- TASK:" in prompt
    assert "- Processed community provenance" not in prompt
    assert "p2_period_missing" not in prompt
    assert len(prompt) <= MAX_REPORT_REPAIR_PROMPT_CHARACTERS == 18_000


def test_gate_detail_cannot_trigger_content_feedback_without_structured_findings():
    prompt = build_report_repair_prompt(
        "Original",
        "Prior",
        {"approval_gate": {"blocking_failures": [{"name": name, "detail": code} for name, code, _group in _FINDINGS]}},
        analysis={"profile": {}},
    )
    feedback = prompt.split("Blocking checks and content corrections:\n", 1)[1].split("Targeted corrections:", 1)[0]
    for _name, code, group in _FINDINGS:
        assert f"- {group}:" not in feedback
        assert code not in prompt
