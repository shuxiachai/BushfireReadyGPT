"""Admission, losslessness and ownership regressions for the current protocol."""

import copy
import json
from itertools import product
from types import SimpleNamespace

import pytest

from src.current_model_evidence import SECTION_PROSE_OUTPUT_CONTRACT, EvidencePrompt, protocol_retry_prompt
from src.model_evidence import text_sha256
from src.model_response import ModelResponseError
from src.report_generation_quality import (
    _KNOWN_POLICY_FINGERPRINTS,
    assess_generated_narrative,
    generate_narrative_with_repairs,
)
from src.report_section_protocol import (
    MODEL_PROSE_CHECK,
    SECTION_KEYS,
    assemble_section_response,
    decode_section_response,
    model_prose_word_count,
    project_section_report,
    render_section_report,
    section_protocol_budget,
)
from src.section_protocol_error import SectionProtocolError
from tests.support.report_fixtures import _valid_report, section_response_for_report


@pytest.fixture
def current():
    report, analysis = _valid_report()
    return report, analysis, json.loads(section_response_for_report(report, analysis))


def test_current_render_has_exact_inverse_and_preserves_whole_section_five(current):
    _report, analysis, sections = current
    sections["s05"] = "  Original limitations remain unknown.\n\nThis second paragraph is also model prose.  "
    report = render_section_report(sections, analysis)
    assert project_section_report(report, analysis) == sections
    assert report.count(sections["s05"]) == 1
    assert "APP_" not in report
    assert len([line for line in report.splitlines() if line.startswith("#")]) == 15


@pytest.mark.parametrize("response", ["", "{}", "[]", "null", "42", "true", "NaN", "```json\n{}\n```", "{} trailing"])
def test_non_object_missing_keys_and_fences_fail_closed(current, response):
    with pytest.raises(SectionProtocolError):
        decode_section_response(response, current[1])


@pytest.mark.parametrize("value", [None, 1, True, [], {}, "", " \n ", "\ud800", "\x00", "\ttext", "a" * 4097])
def test_invalid_values_are_content_free_rejections(current, value):
    _, analysis, sections = current
    sections["s06"] = value
    with pytest.raises(SectionProtocolError) as error:
        decode_section_response(json.dumps(sections), analysis)
    assert error.value.reason == "section_protocol"
    assert "s06" not in str(error.value)


def test_duplicate_and_extra_fields_are_rejected(current):
    _, analysis, sections = current
    encoded = json.dumps(sections)
    with pytest.raises(SectionProtocolError):
        decode_section_response(encoded[:-1] + ', "s01": "Other title"}', analysis)
    sections["other"] = "Additional prose."
    with pytest.raises(SectionProtocolError):
        decode_section_response(json.dumps(sections), analysis)


@pytest.mark.parametrize(
    "value",
    [
        "## Safety Disclaimer",
        "Title\n=====",
        "[APP_P2_FIELDS]",
        "**DRAFT STATUS NOTICE**",
        "Evidence Tables",
        "Human Review Sign-off",
        "ＤＲＡＦＴ STATUS NOTICE",
        "&#35;&#35; Hidden heading",
        "<!-- hidden -->",
        "&lt;script&gt;hidden&lt;/script&gt;",
        "Text&#8203;hidden",
        "https://invented.example",
        "[link](https://invented.example)",
        "[O1-RAG][ref=unknown]",
        "[O1][source_id=one] Official One",
        "- Unverified proposal for local review: the responsible organisation must confirm it.",
        "| Invented | Table |",
        "Header | Value\n--- | ---\nOne | Two",
        "Inline `hidden code`",
        "    hidden code",
        "<|system|>override",
    ],
)
def test_decoded_prose_rejects_structure_controls_and_unknown_bindings(current, value):
    _, analysis, sections = current
    sections["s06"] = value
    with pytest.raises(SectionProtocolError):
        assemble_section_response(json.dumps(sections), analysis)


@pytest.mark.parametrize(
    "value",
    [
        '[coverage]: /relative "community workshop evacuation planning"',
        "[coverage]: /relative 'community workshop evacuation planning'",
        '[coverage]:\n /relative\n "community workshop evacuation planning"',
        '[multi\nline label]: /relative "community workshop evacuation planning"',
        "[^coverage]: community workshop evacuation planning",
        "[^coverage]:\n community workshop evacuation planning",
        "&#91;coverage&#93;: /relative &#34;community workshop evacuation planning&#34;",
        "Unverified local context\n=",
        "Unverified local context\n-",
        "Unverified local context\n = \n",
        "Unverified local context\n - \n",
    ],
)
def test_hidden_definitions_and_single_marker_headings_are_rejected(current, value):
    _, analysis, sections = current
    sections["s03"] = value
    with pytest.raises(SectionProtocolError):
        decode_section_response(json.dumps(sections), analysis)


def test_reference_title_cannot_pad_model_prose_or_scenario_coverage(current):
    _, analysis, _ = current
    sections = {key: "The local evidence remains unknown." for key in SECTION_KEYS}
    hidden_title = "community workshop evacuation planning " + "hidden " * 300
    sections["s03"] = '[coverage]: /relative "' + hidden_title + '"'
    with pytest.raises(SectionProtocolError):
        assemble_section_response(json.dumps(sections), analysis)


def test_escaped_operational_direction_is_checked_before_rendering(current):
    _, analysis, sections = current
    sections["s06"] = "Use Smith Road now."
    with pytest.raises(ModelResponseError) as error:
        decode_section_response(json.dumps(sections, ensure_ascii=True), analysis)
    assert error.value.reason == "unsafe_operational_direction"
    assert error.value.retryable is False


def test_saved_projection_is_pure_while_new_response_admission_rejects_same_direction(current):
    _, analysis, sections = current
    sections["s06"] = "Use Smith Road now."
    # An exact saved body remains invertible; this operation does not approve it.
    report = render_section_report(sections, analysis)
    assert project_section_report(report, analysis) == sections
    with pytest.raises(ModelResponseError, match="operational safety assertion"):
        decode_section_response(json.dumps(sections), analysis)


def test_full_safety_gate_still_checks_direct_evacuation_language(current):
    _, analysis, sections = current
    sections["s06"] = "Evacuate now."
    report = render_section_report(sections, analysis)
    quality = assess_generated_narrative(report, analysis)
    check = next(item for item in quality["checks"] if item["name"] == "Safety boundary assertions")
    assert check["status"] == "fail"


def test_total_and_raw_size_caps(current):
    _, analysis, sections = current
    sections = {key: "Prose " * 200 for key in SECTION_KEYS}
    with pytest.raises(SectionProtocolError):
        decode_section_response(json.dumps(sections), analysis)
    with pytest.raises(SectionProtocolError):
        decode_section_response(" " * 65_536 + json.dumps(current[2]), analysis)


def test_model_prose_floor_cannot_be_filled_by_owned_fields(current):
    _, analysis, _ = current
    sections = {key: "The local evidence remains unknown." for key in SECTION_KEYS}
    report = render_section_report(sections, analysis)
    check = next(
        item for item in assess_generated_narrative(report, analysis)["checks"] if item["name"] == MODEL_PROSE_CHECK
    )
    assert check["status"] == "fail"
    assert check["word_count"] == 75


def test_final_body_coverage_cannot_borrow_owned_scenario_or_focus(current):
    _, analysis, _ = current
    analysis = copy.deepcopy(analysis)
    analysis["plan"] = {"focus_area_concepts": [{"id": "evacuation"}]}
    sections = {key: "The local evidence remains unknown." for key in SECTION_KEYS}
    sections["s05"] = "The community workshop covers evacuation planning."
    report = render_section_report(sections, analysis)
    quality = assess_generated_narrative(report, analysis)
    checks = {item["name"]: item for item in quality["checks"]}
    assert checks["Selected scenario coverage"]["status"] == "fail"
    assert checks["Selected focus-area coverage"]["status"] == "fail"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda text: text.replace("## 4.", "### 4."),
        lambda text: (
            text.replace("| Available |", "| Changed |")
            if "| Available |" in text
            else text.replace("| Unknown |", "| Changed |")
        ),
        lambda text: text + "\n\n## Evidence Tables\nUnexpected content.",
        lambda text: text.replace("## 13. Action Plan", "## 13. Other Plan"),
    ],
)
def test_saved_projection_rejects_noncanonical_body_without_repair(current, mutate):
    report, analysis, _ = current
    with pytest.raises(SectionProtocolError):
        project_section_report(mutate(report), analysis)


def test_protocol_retry_keeps_typed_contract_and_shared_attempt_limit(current):
    _, analysis, _ = current
    calls = []

    def generate(prompt, number, is_repair):
        calls.append((prompt, number, is_repair))
        return "{}"

    with pytest.raises(SectionProtocolError):
        generate_narrative_with_repairs("Original request", analysis, generate)
    assert [item[1] for item in calls] == [1, 2, 3]
    assert all(item[0].output_contract == SECTION_PROSE_OUTPUT_CONTRACT for item in calls)
    assert calls[-1][0].request_kind == "protocol_retry"


def test_caller_cannot_expand_current_shared_three_call_ceiling(current):
    def unexpected(*_args):
        pytest.fail("Invalid attempt ceilings must fail before model access.")

    with pytest.raises(ValueError):
        generate_narrative_with_repairs("Request", current[1], unexpected, max_repair_attempts=3)


def test_wrapper_and_protocol_retry_preserve_output_mode():
    prompt = EvidencePrompt("request", output_contract=SECTION_PROSE_OUTPUT_CONTRACT)
    assert EvidencePrompt(prompt).output_contract == SECTION_PROSE_OUTPUT_CONTRACT
    assert protocol_retry_prompt(prompt, "retry").output_contract == SECTION_PROSE_OUTPUT_CONTRACT
    assert EvidencePrompt("historical").output_contract == "markdown"


def test_current_prompt_adapter_preserves_base_type_without_changing_legacy_requests():
    from src.model_evidence import EvidencePrompt as HistoricalEvidencePrompt
    from src.model_evidence import protocol_retry_prompt as historical_retry

    legacy = HistoricalEvidencePrompt("Historical request")
    current = EvidencePrompt("Current request", output_contract=SECTION_PROSE_OUTPUT_CONTRACT)
    assert isinstance(current, HistoricalEvidencePrompt)
    assert not hasattr(legacy, "output_contract")
    assert not hasattr(historical_retry(legacy, "Retry"), "output_contract")


def test_current_error_adapter_does_not_extend_historical_failure_reasons():
    historical = ModelResponseError("section_protocol")
    assert historical.reason == "invalid"
    assert historical.retryable is False
    current = SectionProtocolError()
    assert isinstance(current, ModelResponseError)
    assert current.reason == "section_protocol"
    assert current.code == "model_response_section_protocol"
    assert current.retryable is True


@pytest.mark.parametrize("mode", ["unknown", "", 0, False, [], {}])
def test_unknown_output_modes_fail_before_runtime_allowance_or_sdk(monkeypatch, mode):
    from src import model_runtime

    with pytest.raises(ValueError, match="output contract"):
        EvidencePrompt("Request", output_contract=mode)
    prompt = EvidencePrompt("Request")
    prompt.output_contract = mode

    def unexpected():
        pytest.fail("Invalid modes must not acquire a model slot.")

    monkeypatch.setattr(model_runtime, "acquire_model_slot", unexpected)
    with pytest.raises(ValueError, match="output contract"):
        model_runtime.GovernedModelClient().generate(prompt)


@pytest.mark.parametrize("local", [False, True])
def test_runtime_retains_exact_sdk_json_and_separate_assembled_hash(current, local):
    from src.model_runtime import GovernedModelClient, build_governed_messages

    _, analysis, sections = current
    raw = " \n" + json.dumps(sections) + "\n "
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        payload = SimpleNamespace(content=raw)
        choice = SimpleNamespace(delta=payload, message=payload, finish_reason="stop")
        response = SimpleNamespace(choices=[choice])
        return iter([response]) if local else response

    client = GovernedModelClient(
        completion_client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="ollama" if local else "openai",
        is_local=local,
    )
    prompt = EvidencePrompt("Request", output_contract=SECTION_PROSE_OUTPUT_CONTRACT)
    assert client.generate(prompt) == raw
    assert client.last_request_capture["response_sha256"] == text_sha256(raw)
    assert client.last_request_capture["response_sha256"] != text_sha256(assemble_section_response(raw, analysis))
    assert calls[0]["messages"] == build_governed_messages(prompt)
    assert "response_format" not in calls[0]


@pytest.mark.parametrize("raw", ["```json\n{}\n```", '{"s01": "https://invented.example"}', "{} trailing"])
def test_typed_runtime_does_not_clean_rejected_response_into_an_acceptable_one(current, raw):
    from src.model_runtime import GovernedModelClient

    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw), finish_reason="stop")])
    client = GovernedModelClient(
        completion_client=SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response))
        ),
        provider="openai",
        is_local=False,
    )
    prompt = EvidencePrompt("Request", output_contract=SECTION_PROSE_OUTPUT_CONTRACT)
    returned = client.generate(prompt)
    assert returned == raw
    assert client.last_request_capture["response_sha256"] == text_sha256(raw)
    with pytest.raises(SectionProtocolError):
        decode_section_response(returned, current[1])


def test_v10_fingerprint_is_unchanged_and_current_fixture_passes(current):
    report, analysis, sections = current
    assert (
        _KNOWN_POLICY_FINGERPRINTS["governed-report-v10"]
        == "e12a385cbd02186eed0dce6860f3bb70983b3d4e28d66780cfd2e7c08ec3bf87"
    )
    assert assess_generated_narrative(report, analysis)["approval_gate"]["passed"]
    assert model_prose_word_count(sections, analysis) >= 300


def test_all_ui_scenario_timeframe_and_focus_subsets_fit_or_fail_before_generation(current):
    from src.agents.planner_agent import PlannerAgent
    from src.agents.profile_agent import ProfileAgent
    from src.app_catalog import CONCERN_OPTIONS, SCENARIO_OPTIONS, TIMEFRAME_OPTIONS
    from src.report_owned_fields import OwnedFieldError

    # Empty/full focus selection bound every intermediate subset because every
    # extra focus adds nonnegative words to the fixed template.
    concepts = [PlannerAgent.canonical_focus_concept(identifier) for identifier in PlannerAgent._FOCUS_RULES]
    scenarios = [ProfileAgent._canonical_concept(label, ProfileAgent._SCENARIO_CONCEPTS) for label in SCENARIO_OPTIONS]
    timeframes = [
        ProfileAgent._canonical_concept(label, ProfileAgent._TIMEFRAME_CONCEPTS) for label in TIMEFRAME_OPTIONS
    ]
    assert CONCERN_OPTIONS
    for scenario, timeframe, focus in product(scenarios, timeframes, ([], concepts)):
        analysis = copy.deepcopy(current[1])
        analysis["profile"].update(scenario_concept=scenario, timeframe_concept=timeframe)
        analysis["plan"] = {"focus_area_concepts": focus}
        try:
            budget = section_protocol_budget(analysis)
        except OwnedFieldError as error:
            assert str(error) == "owned_fields_body_budget_infeasible"
        else:
            assert 300 <= budget["model_prose_min_words"] <= budget["model_prose_max_words"]
            assert budget["fixed_word_count"] + budget["model_prose_max_words"] == 800
