"""Offline repair comparisons and transaction stops; no provider calls."""

import copy
import json
from types import SimpleNamespace

import pytest

from src import report_generation_quality as quality
from src.model_response import ModelResponseError, ModelServiceError
from src.report_repair_guard import (
    REPAIR_GUARD_RULESET,
    ReportRepairRegressionError,
    reject_repair_regression,
    snapshot_repair_assessment,
)
from tests.support.repair_quality_fixtures import repair_quality
from tests.support.report_fixtures import _valid_report, section_response_for_report


def _compare(previous, candidate):
    reject_repair_regression(
        snapshot_repair_assessment(previous),
        snapshot_repair_assessment(candidate),
        baseline_attempt_number=1,
        candidate_attempt_number=2,
    )


def _check(result, name):
    return next(check for check in result["checks"] if check["name"] == name)


def _setup_loop(monkeypatch, assessments, *, fail_at=None, before_call=None):
    narrative, analysis = _valid_report()
    response = section_response_for_report(narrative, analysis)
    assessed = iter(assessments)
    calls = []
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: next(assessed))
    monkeypatch.setattr(quality, "build_report_repair_prompt", lambda *_args, **_kwargs: "Repair synthetic draft.")

    def generate(prompt, number, repair):
        calls.append((number, getattr(prompt, "request_kind", None), repair))
        if before_call is not None:
            before_call(number)
        if fail_at and number in fail_at:
            raise ModelResponseError(fail_at[number])
        return response

    return analysis, generate, calls


def test_real_canonical_assessment_has_the_complete_guard_contract():
    narrative, analysis = _valid_report()
    snapshot = snapshot_repair_assessment(quality.assess_generated_narrative(narrative, analysis))
    assert snapshot.valid
    assert snapshot.word_counts[0] >= 650


def test_632_to_955_stops_after_two_calls_without_returning_a_draft(monkeypatch):
    analysis, generate, calls = _setup_loop(
        monkeypatch, [repair_quality(total_words=632), repair_quality(total_words=955)]
    )
    with pytest.raises(ReportRepairRegressionError) as caught:
        quality.generate_narrative_with_repairs("Synthetic prompt.", analysis, generate)
    error = caught.value
    assert isinstance(error, ModelServiceError) and not isinstance(error, ModelResponseError)
    assert error.reason == "word_budget_distance_increased"
    assert error.worsened_word_budget_ids == ("narrative_word_budget",)
    assert error.regressed_check_ids == ()
    assert (error.baseline_attempt_number, error.candidate_attempt_number) == (1, 2)
    assert len(calls) == 2


def test_632_to_810_can_continue_then_return_the_current_candidate(monkeypatch):
    analysis, generate, calls = _setup_loop(
        monkeypatch,
        [repair_quality(total_words=632), repair_quality(total_words=810), repair_quality(passed=True)],
    )
    _, final_quality, attempts = quality.generate_narrative_with_repairs("Synthetic prompt.", analysis, generate)
    assert attempts == len(calls) == 3
    assert final_quality["approval_gate"]["passed"]


def test_each_nonregressing_candidate_becomes_the_next_baseline(monkeypatch):
    analysis, generate, calls = _setup_loop(
        monkeypatch,
        [repair_quality(total_words=632), repair_quality(total_words=810), repair_quality(total_words=815)],
    )
    with pytest.raises(ReportRepairRegressionError) as caught:
        quality.generate_narrative_with_repairs("Synthetic prompt.", analysis, generate)
    assert len(calls) == 3
    assert (caught.value.baseline_attempt_number, caught.value.candidate_attempt_number) == (2, 3)


@pytest.mark.parametrize(
    "name", ["Selected scenario coverage", "Selected focus-area coverage", "Safety boundary assertions"]
)
@pytest.mark.parametrize("before, after", [("pass", "fail"), ("pass", "warning"), ("warning", "fail")])
def test_any_canonical_status_downgrade_stops_even_when_another_check_improves(name, before, after):
    previous = repair_quality(statuses={name: before})
    candidate = repair_quality(passed=True, statuses={name: after})
    with pytest.raises(ReportRepairRegressionError) as caught:
        _compare(previous, candidate)
    assert caught.value.reason == "check_status_regressed"
    assert len(caught.value.regressed_check_ids) == 1


@pytest.mark.parametrize("previous, candidate, stops", [(280, 270, True), (280, 280, False), (280, 290, False)])
def test_model_prose_minimum_compares_distance(previous, candidate, stops):
    before = repair_quality(model_words=previous)
    after = repair_quality(model_words=candidate)
    if stops:
        with pytest.raises(ReportRepairRegressionError) as caught:
            _compare(before, after)
        assert caught.value.reason == "word_budget_distance_increased"
        assert caught.value.worsened_word_budget_ids == ("model_prose_word_budget",)
    else:
        _compare(before, after)


def test_status_reason_precedes_distance_but_both_diagnostics_survive():
    with pytest.raises(ReportRepairRegressionError) as caught:
        _compare(repair_quality(), repair_quality(total_words=810))
    assert caught.value.reason == "check_status_regressed"
    assert caught.value.regressed_check_ids == caught.value.worsened_word_budget_ids == ("narrative_word_budget",)


@pytest.mark.parametrize("protocol_reason", ["length", "incomplete_narrative"])
def test_protocol_retry_does_not_erase_previous_complete_baseline(monkeypatch, protocol_reason):
    analysis, generate, calls = _setup_loop(
        monkeypatch,
        [repair_quality(total_words=632), repair_quality(total_words=955)],
        fail_at={2: protocol_reason},
    )
    with pytest.raises(ReportRepairRegressionError) as caught:
        quality.generate_narrative_with_repairs("Synthetic prompt.", analysis, generate)
    assert len(calls) == 3 and calls[-1][1] == "protocol_retry"
    assert (caught.value.baseline_attempt_number, caught.value.candidate_attempt_number) == (1, 3)


@pytest.mark.parametrize("reason, count", [("content_filter", 1), ("length", 3)])
def test_response_error_retry_semantics_are_unchanged(monkeypatch, reason, count):
    analysis, generate, calls = _setup_loop(monkeypatch, [], fail_at={1: reason, 2: reason, 3: reason})
    with pytest.raises(ModelResponseError) as caught:
        quality.generate_narrative_with_repairs("Synthetic prompt.", analysis, generate)
    assert caught.value.reason == reason and len(calls) == count


@pytest.mark.parametrize(
    "result, options",
    [
        ({"approval_gate": {"passed": True}}, {}),
        ({"approval_gate": {"passed": False}}, {"max_repair_attempts": 0}),
        ({"approval_gate": {"passed": False}}, {"allow_structural_repair": False}),
    ],
)
def test_terminal_first_assessment_behavior_is_unchanged(monkeypatch, result, options):
    analysis, generate, calls = _setup_loop(monkeypatch, [result])
    _, returned, attempts = quality.generate_narrative_with_repairs("Synthetic prompt.", analysis, generate, **options)
    assert returned is result and attempts == len(calls) == 1


def test_revision_protocol_retry_returns_first_complete_assessment_without_structural_repair(monkeypatch):
    analysis, generate, calls = _setup_loop(monkeypatch, [repair_quality()], fail_at={1: "length"})
    _, result, attempts = quality.generate_narrative_with_repairs(
        "Synthetic revision.", analysis, generate, allow_structural_repair=False
    )
    assert attempts == len(calls) == 2 and not result["approval_gate"]["passed"]


def test_callback_cannot_mutate_the_stored_baseline(monkeypatch):
    previous = repair_quality(total_words=632)

    def mutate(number):
        if number == 2:
            _check(previous, "Narrative word budget")["word_count"] = 2000
            previous["checks"].clear()

    analysis, generate, calls = _setup_loop(
        monkeypatch, [previous, repair_quality(total_words=955)], before_call=mutate
    )
    with pytest.raises(ReportRepairRegressionError) as caught:
        quality.generate_narrative_with_repairs("Synthetic prompt.", analysis, generate)
    assert caught.value.reason == "word_budget_distance_increased" and len(calls) == 2


@pytest.mark.parametrize("count", [None, True, -1, 100001, 700.0, "700", {}, []])
@pytest.mark.parametrize("name", ["Narrative word budget", "Model prose word budget"])
def test_invalid_word_count_is_not_treated_as_improvement(name, count):
    candidate = repair_quality()
    _check(candidate, name)["word_count"] = count
    with pytest.raises(ReportRepairRegressionError) as caught:
        _compare(repair_quality(), candidate)
    assert caught.value.reason == "invalid_quality_snapshot"


@pytest.mark.parametrize(
    "mutation",
    ["missing", "duplicate", "unknown", "unnamed", "row", "status", "checks", "status_count", "bounds", "optional"],
)
@pytest.mark.parametrize("invalid_baseline", [False, True])
def test_malformed_comparison_fails_closed_without_echoing_input(mutation, invalid_baseline):
    result = repair_quality()
    if mutation == "missing":
        result["checks"].pop()
    elif mutation == "duplicate":
        result["checks"].append(copy.deepcopy(result["checks"][0]))
    elif mutation == "unknown":
        result["checks"].append({"name": "PRIVATE response prose", "status": "pass"})
    elif mutation == "unnamed":
        result["checks"].append({"name": [], "status": "pass"})
    elif mutation == "row":
        result["checks"].append("PRIVATE response prose")
    elif mutation == "status":
        result["checks"][0]["status"] = []
    elif mutation == "checks":
        result["checks"] = None
    elif mutation == "status_count":
        _check(result, "Narrative word budget")["status"] = "warning"
    elif mutation == "bounds":
        _check(result, "Narrative word budget")["maximum"] = 801
    else:
        result["checks"].append({"name": "Selected focus-area coverage", "status": "pass"})
    previous, candidate = (result, repair_quality()) if invalid_baseline else (repair_quality(), result)
    with pytest.raises(ReportRepairRegressionError) as caught:
        _compare(previous, candidate)
    error = caught.value
    assert error.reason == "invalid_quality_snapshot"
    assert "comparison could not be validated" in str(error)
    assert "PRIVATE" not in str(error) + json.dumps(vars(error))


def test_general_findings_summary_and_body_citation_advisory_do_not_rank_candidates():
    before, after = repair_quality(), repair_quality()
    before.update(summary={"failed": 100}, body_claim_evidence={"status": "pass"})
    after.update(summary={"failed": 0}, body_claim_evidence={"status": "review_required"})
    before["checks"][0]["findings"] = [{"code": "PRIVATE", "count": 1}]
    after["checks"][0]["findings"] = [{"code": "PRIVATE", "count": 9000}]
    _compare(before, after)


@pytest.mark.parametrize("with_protocol_retry", [False, True])
def test_workflow_regression_preserves_report_and_stops_before_finalization(monkeypatch, tmp_path, with_protocol_retry):
    from src import report_workflow as workflow

    analysis, generate, calls = _setup_loop(
        monkeypatch,
        [repair_quality(total_words=632), repair_quality(total_words=955)],
        fail_at={2: "length"} if with_protocol_retry else None,
    )
    prior = {"text": "PRIVATE prior report", "audit_path": "unchanged-audit"}
    state = {"latest_report": prior, "messages": [{"content": "PRIVATE message"}], "model_client": object()}
    saved_state = copy.deepcopy(state)
    saved_state["model_client"] = state["model_client"]

    class State(dict):
        __getattr__ = dict.__getitem__

    state = State(state)
    monkeypatch.setattr(workflow, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(workflow, "validate_current_report_form", lambda: None)
    monkeypatch.setattr(workflow, "validate_model_privacy_boundary", lambda: None)
    monkeypatch.setattr(workflow, "collect_report_inputs", lambda: {})
    monkeypatch.setattr(workflow, "run_analysis_pipeline", lambda *_args, **_kwargs: analysis)
    monkeypatch.setattr(workflow, "_cloud_rag_availability_error", lambda _: None)
    monkeypatch.setattr(workflow, "build_governance_context", lambda: "Synthetic context.")
    monkeypatch.setattr(workflow, "build_report_prompt", lambda *_args, **_kwargs: "Synthetic prompt.")
    monkeypatch.setattr(workflow, "_call_governed_model", lambda prompt: generate(prompt, len(calls) + 1, bool(calls)))
    monkeypatch.setattr(
        workflow, "_finalize_report_version", lambda *_args, **_kwargs: pytest.fail("Must not finalize")
    )
    monkeypatch.setattr(workflow, "save_report_audit", lambda *_args, **_kwargs: pytest.fail("Must not write audit"))
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path / "traces"))

    response, error = workflow.generate_current_report(lambda: pytest.fail("Must not persist"))

    assert response is None and "No new report was saved" in error
    assert state == saved_state and state["latest_report"] is prior
    traces = list((tmp_path / "traces").glob("trace_*.json"))
    assert len(traces) == 1
    rendered = traces[0].read_text(encoding="utf-8")
    trace = json.loads(rendered)
    assert trace["status"] == "failed" and trace["error_code"] == "report_repair_regression"
    assert trace["metrics"]["generation_attempts"] == len(calls) == (3 if with_protocol_retry else 2)
    assert trace["metrics"]["repair_required"] is True
    assert not any(
        stage["name"] in {"governance_finalize", "audit_write", "session_persist"} for stage in trace["stages"]
    )
    assert "PRIVATE" not in rendered


def test_evaluator_keeps_safe_classification_and_actual_attempts(monkeypatch):
    from scripts import evaluate_report_generation as evaluator

    analysis, generate, calls = _setup_loop(
        monkeypatch, [repair_quality(total_words=632), repair_quality(total_words=955)]
    )
    monkeypatch.setattr(evaluator, "run_analysis_pipeline", lambda *_args: analysis)
    monkeypatch.setattr(evaluator, "build_report_prompt", lambda *_args, **_kwargs: "PRIVATE prompt.")
    monkeypatch.setattr(
        evaluator,
        "GovernedModelClient",
        lambda: SimpleNamespace(generate=lambda prompt: generate(prompt, len(calls) + 1, bool(calls))),
    )
    monkeypatch.setattr(evaluator, "apply_governance_notice", lambda _: pytest.fail("No final report"))
    scenario = {
        "id": "synthetic",
        "location": "PRIVATE place",
        "audience": "PRIVATE audience",
        "scenario": "Synthetic",
        "concerns": [],
        "timeframe": "7-day",
    }
    with pytest.raises(evaluator.ScenarioGenerationError) as caught:
        evaluator.run_scenario_with_artifacts(scenario)
    error = caught.value
    assert isinstance(error.__cause__, ReportRepairRegressionError)
    row = evaluator._failed_row(scenario, error, generation_attempts=error.generation_attempts)
    assert row["generation_attempts"] == len(calls) == 2
    assert error.code == "report_repair_regression"
    assert row["blocking_failures"][0]["name"] == "Report repair regression guard"
    assert "No new report was saved" in row["blocking_failures"][0]["detail"]
    assert row["repair_required"] and not row["repair_succeeded"] and not row["repair_exhausted"]
    assert error.__cause__.ruleset == REPAIR_GUARD_RULESET
    assert error.__cause__.worsened_word_budget_ids == ("narrative_word_budget",)
    assert "error_code" not in row and "repair_guard" not in row
    assert row["report_characters"] == 0 and not row["governed_gate_passed"]
    assert "PRIVATE" not in json.dumps(row)
