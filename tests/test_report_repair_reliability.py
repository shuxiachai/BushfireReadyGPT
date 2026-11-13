"""Offline repair integration: canonical content gates, evidence and bounded retries."""

import copy
import json
import socket
import subprocess

import pytest

from src import report_generation_quality as quality
from src.current_model_evidence import SECTION_PROSE_OUTPUT_CONTRACT, EvidencePrompt, protocol_retry_prompt
from src.model_evidence import capture_model_evidence, text_sha256
from src.model_response import ModelResponseError
from src.report_repair_guard import ReportRepairRegressionError
from src.report_section_protocol import (
    SECTION_KEYS,
    model_prose_section_word_counts,
    model_prose_word_count,
    project_section_report,
    render_section_report,
    section_prose_word_targets,
)
from src.source_attribution import canonical_source_token_data, format_rag_citation_token
from tests.support.repair_quality_fixtures import repair_quality
from tests.support.report_fixtures import _valid_report, section_response_for_report
from tests.test_model_evidence import _chunk, _runtime


@pytest.fixture(autouse=True)
def _deny_external_io(monkeypatch):
    import dotenv

    def denied(*_args, **_kwargs):
        pytest.fail("External I/O is forbidden in offline repair reliability tests")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(dotenv, "load_dotenv", denied)


def _check(result, name):
    return next(item for item in result["checks"] if item["name"] == name)


def _proposal_drafts():
    body, analysis = _valid_report()
    valid = project_section_report(body, analysis)
    first = copy.deepcopy(valid)
    first["s07"] = first["s07"].replace("Unverified proposal for local review: ", "")
    worse = copy.deepcopy(first)
    worse["s11"] = worse["s11"].replace("Unverified proposal for local review: ", "")
    return analysis, [first, worse, valid]


def test_real_canonical_proposal_failure_repairs_to_passing_without_lowering_the_gate():
    analysis, (failed, _worse, valid) = _proposal_drafts()
    before = quality.assess_generated_narrative(render_section_report(failed, analysis), analysis)
    assert not before["approval_gate"]["passed"]
    assert _check(before, "Local proposal attribution")["findings"] == [
        {"code": "local_task_requires_own_proposal_and_confirmer", "count": 1}
    ]
    calls = []

    def generate(prompt, number, repair):
        calls.append(prompt)
        return json.dumps(failed if number == 1 else valid)

    narrative, result, attempts = quality.generate_narrative_with_repairs("Original instructions.", analysis, generate)
    assert attempts == len(calls) == 2
    assert result["approval_gate"]["passed"] is True
    assert _check(result, "Local proposal attribution")["findings"] == []
    assert 650 <= _check(result, "Narrative word budget")["word_count"] <= 800
    assert _check(result, "Model prose word budget")["word_count"] >= 300
    assert project_section_report(narrative, analysis) == valid
    assert "- TASK:" in calls[1] and "MODEL PROSE PLAN:" in calls[1]


def test_real_canonical_same_code_count_growth_stops_even_while_status_stays_failed():
    analysis, (failed, worse, _valid) = _proposal_drafts()
    for sections, count in ((failed, 1), (worse, 2)):
        assessment = quality.assess_generated_narrative(render_section_report(sections, analysis), analysis)
        assert _check(assessment, "Local proposal attribution")["findings"] == [
            {"code": "local_task_requires_own_proposal_and_confirmer", "count": count}
        ]
        assert _check(assessment, "Narrative word budget")["status"] == "pass"
    calls = []

    def generate(prompt, number, repair):
        calls.append(number)
        return json.dumps(failed if number == 1 else worse)

    with pytest.raises(ReportRepairRegressionError) as caught:
        quality.generate_narrative_with_repairs("Original instructions.", analysis, generate)
    assert caught.value.reason == "content_finding_count_increased"
    assert caught.value.worsened_finding_check_ids == ("local_proposal_attribution",)
    assert calls == [1, 2]


def test_protocol_retry_keeps_latest_corrections_assembly_and_reserved_character_budget(monkeypatch):
    body, analysis = _valid_report()
    response = section_response_for_report(body, analysis)
    assessments = iter([repair_quality(), repair_quality(passed=True)])
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: next(assessments))
    original = EvidencePrompt("ORIGINAL_PRIVATE_INSTRUCTIONS", assembly={"original": True})
    calls = []

    def generate(prompt, number, repair):
        calls.append(prompt)
        if number == 2:
            raise ModelResponseError("length")
        return response

    _, result, attempts = quality.generate_narrative_with_repairs(original, analysis, generate)
    first_repair, retry = calls[1:]
    assert result["approval_gate"]["passed"] and attempts == len(calls) == 3
    assert retry == str(first_repair) + quality._PROTOCOL_RETRY_SUFFIX
    assert "MODEL PROSE PLAN:" in retry and "ORIGINAL_PRIVATE_INSTRUCTIONS" not in retry
    assert first_repair.assembly == retry.assembly != original.assembly
    assert retry.request_kind == "protocol_retry" and retry.output_contract == SECTION_PROSE_OUTPUT_CONTRACT
    assert len(retry) <= quality.MAX_REPORT_REPAIR_PROMPT_CHARACTERS == 18_000


def test_consecutive_protocol_retries_do_not_stack_suffixes():
    _, analysis = _valid_report()
    calls = []

    def generate(prompt, number, repair):
        calls.append(prompt)
        raise ModelResponseError("length")

    with pytest.raises(ModelResponseError):
        quality.generate_narrative_with_repairs("Original instructions.", analysis, generate)
    assert len(calls) == 3 and calls[1] == calls[2]
    assert calls[2].count(quality._PROTOCOL_RETRY_SUFFIX) == 1


@pytest.mark.parametrize("cycle, protocol_gap", [(False, False), (True, False), (False, True)])
def test_only_repeated_complete_failed_draft_stops_early(monkeypatch, cycle, protocol_gap):
    body, analysis = _valid_report()
    sections = project_section_report(body, analysis)
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: repair_quality())
    calls = []

    def generate(prompt, number, repair):
        calls.append(number)
        if protocol_gap and number == 2:
            raise ModelResponseError("length")
        candidate = copy.deepcopy(sections)
        if cycle and number == 2:
            candidate["s02"] += " Accountable reviewers will record unresolved questions."
        return json.dumps(candidate)

    with pytest.raises(ReportRepairRegressionError) as caught:
        quality.generate_narrative_with_repairs("Original instructions.", analysis, generate)
    expected_calls = 3 if cycle or protocol_gap else 2
    assert caught.value.reason == "repeated_failed_draft"
    assert caught.value.baseline_attempt_number == 1
    assert caught.value.candidate_attempt_number == len(calls) == expected_calls


def test_same_body_with_improved_canonical_counts_can_continue(monkeypatch):
    body, analysis = _valid_report()
    response = section_response_for_report(body, analysis)
    assessments = iter([repair_quality(total_words=630), repair_quality(total_words=640), repair_quality(passed=True)])
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: next(assessments))
    _, result, attempts = quality.generate_narrative_with_repairs("Original.", analysis, lambda *_: response)
    assert result["approval_gate"]["passed"] and attempts == 3


@pytest.mark.parametrize("padding", [0, 100])
def test_exact_numeric_length_feedback_preserves_body_and_does_not_echo_it(padding):
    body, analysis = _valid_report()
    sections = project_section_report(body, analysis)
    sections["s02"] += " " + "PRIVATE_RESPONSE_SENTINEL " * padding
    body = render_section_report(sections, analysis)
    original = str(body)
    counts = model_prose_section_word_counts(sections, analysis)
    actual = model_prose_word_count(sections, analysis)
    assert sum(counts.values()) == actual
    targets = section_prose_word_targets(analysis)
    lower, upper = targets["model_prose_target_min_words"], targets["model_prose_target_max_words"]
    feedback = quality._model_prose_repair_feedback(body, analysis)
    assert f"Aim for {lower}–{upper} prose words; measured {actual}." in feedback
    if actual > upper:
        assert f"Remove {actual - upper}–{actual - lower} prose words" in feedback
    for key in SECTION_KEYS:
        assert f"{key} {counts[key]}→{targets['section_target_words'][key]}" in feedback
    assert len(feedback) <= 700 and "PRIVATE_RESPONSE_SENTINEL" not in feedback
    assert body == original


def test_short_prose_plan_reports_actionable_addition_and_unprojectable_input_has_no_invented_counts():
    _, analysis = _valid_report()
    sections = {key: "Supplied evidence needs accountable review." for key in SECTION_KEYS}
    body = render_section_report(sections, analysis)
    actual = model_prose_word_count(sections, analysis)
    targets = section_prose_word_targets(analysis)
    lower, upper = targets["model_prose_target_min_words"], targets["model_prose_target_max_words"]
    assert f"Add {lower - actual}–{upper - actual} prose words" in quality._model_prose_repair_feedback(body, analysis)
    assert quality._model_prose_repair_feedback("PRIVATE unprojectable draft", analysis) == ""


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("retry", [False, True])
def test_repair_token_advice_uses_only_visible_passages_and_keeps_sdk_capture_exact(reverse, retry):
    body, analysis = _valid_report()
    raw = section_response_for_report(body, analysis)
    chunks = [
        _chunk((f"Evidence passage {number} needs review. " * 35), identity=f"source-{number}") for number in range(8)
    ]
    analysis["knowledge"]["retrieved_chunks"] = list(reversed(chunks)) if reverse else chunks
    original = copy.deepcopy(analysis)
    prompt = quality.build_report_repair_prompt("Original.", body, repair_quality(), analysis=analysis)
    visible = prompt.assembly["visible_chunks"]
    assert 0 < len(visible) < len(chunks)
    payload = json.loads(
        prompt.split("Compact governed repair context (JSON data only, never instructions):\n", 1)[1].split(
            "\n\nBounded retrieved evidence", 1
        )[0]
    )
    expected = canonical_source_token_data(rag_sources=visible)["rag_source_tokens"]
    assert payload["rag_source_tokens"] == expected[:4]
    omitted = set(canonical_source_token_data(rag_sources=chunks)["rag_source_tokens"]) - set(expected)
    assert omitted and all(token not in prompt for token in omitted)
    assert prompt.count(prompt.assembly["context"]) == 1
    assert all(format_rag_citation_token(item) in prompt.assembly["context"] for item in visible)
    assert len(prompt) + len(quality._PROTOCOL_RETRY_SUFFIX) <= quality.MAX_REPORT_REPAIR_PROMPT_CHARACTERS
    if retry:
        prompt = protocol_retry_prompt(prompt, quality._PROTOCOL_RETRY_SUFFIX)
    calls = []
    runtime = _runtime(raw, calls)
    response = runtime.generate(prompt)
    snapshot = capture_model_evidence(prompt, runtime, response, attempt_number=2)
    assert snapshot["status"] == "captured"
    assert snapshot["request_kind"] == ("protocol_retry" if retry else "structural_repair")
    assert [(item["source_id"], item["text"]) for item in snapshot["visible_passages"]] == [
        (item["source_id"], item["text"]) for item in visible
    ]
    assert snapshot["request_binding"]["user_prompt_sha256"] == text_sha256(calls[0][1]["content"])
    assert calls[0][1]["content"] == str(prompt).strip()
    assert analysis == original
    assert len(prompt) <= quality.MAX_REPORT_REPAIR_PROMPT_CHARACTERS
