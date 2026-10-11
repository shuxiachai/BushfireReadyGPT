"""Self-authored offline envelopes and mocked SDK submission, never provider receipt.

Forms exercise UI size boundaries, not representative real reports. All token
counts, model/template identities and rendered bytes below are MOCK fixtures;
none measures these messages or establishes an effective model context budget.
"""

import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import dotenv
import httpx
import pytest

from scripts import section_local_repair_contract as contract
from scripts import section_local_repair_request as request
from src.agents.profile_agent import ProfileAgent
from src.app_catalog import CONCERN_OPTIONS, SCENARIO_OPTIONS, TIMEFRAME_OPTIONS
from src.current_model_evidence import EvidencePrompt
from src.input_validation import REPORT_FIELD_LIMITS, REPORT_INPUT_MAX_BYTES, validate_report_input_budget
from src.model_context_budget import assess_model_context_budget
from src.model_evidence import bind_normalized_narrative, capture_model_evidence, json_sha256, text_sha256
from src.rag.context import assemble_planning_context
from src.report_section_protocol import render_section_report
from src.report_template import build_report_prompt
from tests.support.report_fixtures import _valid_report, section_response_for_report

_PROFILE_FIELDS = ("location", "audience", "scenario", "concerns", "timeframe", "extra_context")
_FAULT = "Unverified proposal for local review: local records remain incomplete."
_MOCK_OPTIONS = {
    "requested_output_tokens": 2048,
    "margin_tokens": 64,
    "context_tokens": 8192,
    "model_digest": text_sha256("MOCK model identity; no model was loaded"),
    "template_sha256": text_sha256("MOCK template identity; no native template was read"),
}
_MOCK_RENDERED = b"MOCK supplied rendered bytes; not a rendering of any request"


def _repeat_to_length(text, size):
    return (text * (size // len(text) + 1))[:size]


def _form(kind):
    form = {
        "location": "Synthetic district, Queensland",
        "audience": _repeat_to_length("Synthetic organisation reviewers and workshop coordinators. ", 400),
        "scenario": "Community workshop material",
        "concerns": ["Evacuation", "First aid training", "Communication channels"],
        "timeframe": "7-day action plan",
        "organisation_name": "Synthetic Community Workshop Review Team",
        "reviewer_role": "Synthetic organisational reviewer",
        "review_notes": "Synthetic review record; no local facts or approvals are asserted.",
        "report_status": "Draft - human review required",
    }
    note = "Synthetic workshop note: responsibilities, records and evidence remain subject to organisational review. "
    if kind == "multibyte_limit":
        note = "合成演练材料仅供组织复核，地点、职责与记录仍待确认。"
    size = 1800 if kind == "sizeable" else REPORT_FIELD_LIMITS["extra_context"][1]
    form["extra_context"] = _repeat_to_length(note, size)
    return form


def _input_bytes(form):
    return sum(len(form.get(key, "").encode("utf-8")) for key in REPORT_FIELD_LIMITS) + sum(
        len(item.encode("utf-8")) for item in form["concerns"]
    )


def _json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


@pytest.fixture(scope="module")
def offline_runtime():
    """Isolate only dependencies; leave the production builder and dispatch intact."""

    def forbidden_io(*args, **kwargs):
        raise AssertionError("Unexpected default-client or HTTP use in offline workflow tests")

    with pytest.MonkeyPatch.context() as patch:
        # These imports may initialize config, but must never read a workstation .env.
        patch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
        patch.setenv("PYTHON_DOTENV_DISABLED", "1")
        patch.setenv("LLM_PROVIDER", "ollama")
        patch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
        patch.setenv("BUSHFIRE_TRACE_ENABLED", "false")
        patch.setenv("BUSHFIRE_RAG_ENABLED", "false")
        patch.setattr(httpx.Client, "send", forbidden_io)
        runtime = importlib.import_module("src.model_runtime")
        workflow = importlib.import_module("src.report_workflow")
        patch.setattr(
            runtime, "client", SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=forbidden_io)))
        )
        slots = []

        def acquire_slot():
            slot = SimpleNamespace(limits=SimpleNamespace(enabled=False), consumed=0, released=0)

            def consume():
                slot.consumed += 1

            def release():
                slot.released += 1

            slot.consume_call = consume
            slot.release = release
            slots.append(slot)
            return slot

        patch.setattr(runtime, "acquire_model_slot", acquire_slot)
        yield SimpleNamespace(runtime=runtime, validate_inputs=workflow.validate_report_inputs, slots=slots)


def _mock_generate(offline_runtime, prompt, raw_response, analysis, *, attempt):
    """Run public generate through its real builder/binder into a fake SDK only."""
    calls = []

    def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        return SimpleNamespace(
            choices=[SimpleNamespace(index=0, finish_reason="stop", message=SimpleNamespace(content=raw_response))]
        )

    fake_sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    runtime = offline_runtime.runtime
    client = runtime.GovernedModelClient(
        completion_client=fake_sdk, model_name="MOCK-sdk-only", provider="MOCK", is_local=False
    )
    expected = list(runtime.build_governed_messages(prompt))
    response = client.generate(prompt)
    assert response == raw_response
    assert len(calls) == 1 and calls[0]["stream"] is False
    submitted = list(calls[0]["messages"])
    assert submitted == expected
    assert offline_runtime.slots[-1].consumed == offline_runtime.slots[-1].released == 1
    evidence = capture_model_evidence(prompt, client, response, attempt_number=attempt)
    assert evidence["status"] == "captured"
    assert evidence["capture_boundary"] == "application_sdk_submission_not_provider_receipt"
    binding = evidence["request_binding"]
    assert binding["messages_sha256"] == json_sha256(submitted)
    assert binding["system_prompt_sha256"] == text_sha256(submitted[0]["content"])
    assert binding["user_prompt_sha256"] == text_sha256(submitted[1]["content"])
    assert binding["response_sha256"] == text_sha256(response)
    narrative = render_section_report(json.loads(response), analysis)
    return {
        "analysis": copy.deepcopy(analysis),
        "raw_response": response,
        "submitted_messages": submitted,
        "model_evidence": bind_normalized_narrative(evidence, narrative),
    }


@pytest.fixture(scope="module")
def envelopes(offline_runtime):
    body, seed_analysis = _valid_report()
    seed_sections = json.loads(section_response_for_report(body, seed_analysis))
    profile_agent = ProfileAgent(
        region_mappings_path=Path(__file__).resolve().parents[1] / "data_australia" / "region_mappings.yml"
    )
    cases = {}
    for kind in ("sizeable", "ascii_limit", "multibyte_limit"):
        form = _form(kind)
        assert offline_runtime.validate_inputs(form) is None
        analysis = copy.deepcopy(seed_analysis)
        analysis["profile"] = profile_agent.run(**{key: form[key] for key in _PROFILE_FIELDS})
        passage = "This self-authored synthetic workshop record leaves responsibilities unconfirmed."
        analysis["knowledge"]["retrieved_chunks"] = [
            {
                "source_id": "synthetic-workshop",
                "chunk_id": "synthetic-workshop-1",
                "title": "Self-authored synthetic workshop fixture",
                "agency": "Synthetic fixture author",
                "text": passage,
                "chunk_sha256": text_sha256(passage),
                "jurisdictions": ["Queensland"],
            }
        ]
        assembly = assemble_planning_context(analysis["knowledge"])
        analysis["rag_context_assembly"] = assembly
        analysis["prompt_context"] = "Synthetic frozen analysis.\n" + assembly["context"]
        sections = copy.deepcopy(seed_sections)
        sections["s02"] = "  " + sections["s02"] + "  "
        sections["s15"] += "\n"
        sections["s07"] += "\n\n" + _FAULT
        prompt = build_report_prompt(**{key: form[key] for key in _PROFILE_FIELDS}, analysis=analysis)
        raw_response = " \n" + json.dumps(sections, ensure_ascii=False) + "\n "
        base_record = _mock_generate(offline_runtime, prompt, raw_response, analysis, attempt=1)
        base = contract.prepare_base(**base_record, declared_section_ids=("s07",))
        prepared = request.prepare_request(base, **_MOCK_OPTIONS)
        cases[kind] = SimpleNamespace(
            form=form, analysis=analysis, sections=sections, prompt=prompt, base_record=base_record, prepared=prepared
        )
    return cases


def _framed(user, start, end):
    length, content = user.split(start + " bytes=", 1)[1].split("\n", 1)
    content = content.split("\n" + end, 1)[0]
    assert len(content.encode("utf-8")) == int(length)
    return content


def _mock_count(messages, *, delta=0):
    """Choose arithmetic boundaries, never estimate tokens from strings or bytes."""
    return {
        "scope": "full_rendered_prompt",
        "model_digest": _MOCK_OPTIONS["model_digest"],
        "template_sha256": _MOCK_OPTIONS["template_sha256"],
        "messages_sha256": json_sha256(messages),
        "context_tokens": _MOCK_OPTIONS["context_tokens"],
        "rendered_prompt_sha256": text_sha256(_MOCK_RENDERED.decode("ascii")),
        "tokenizer_identity": "MOCK fixture only; no tokenizer executed",
        "input_tokens": _MOCK_OPTIONS["context_tokens"]
        - _MOCK_OPTIONS["requested_output_tokens"]
        - _MOCK_OPTIONS["margin_tokens"]
        + delta,
        # An allowlisted schema value tests supplied arithmetic, not provenance.
        "count_method": "verified_offline_tokenizer",
    }


def _assert_no_dispatch(result):
    assert result["eligible_for_model_dispatch"] is False
    assert result["production_acceptance"] is False


@pytest.mark.parametrize("kind", ["sizeable", "ascii_limit", "multibyte_limit"])
def test_valid_sizeable_ui_forms_reach_unchanged_builder_and_mock_sdk(envelopes, offline_runtime, kind):
    case = envelopes[kind]
    assert case.form["scenario"] in SCENARIO_OPTIONS
    assert case.form["timeframe"] in TIMEFRAME_OPTIONS
    assert set(case.form["concerns"]) <= set(CONCERN_OPTIONS)
    assert validate_report_input_budget(case.form) is None
    assert offline_runtime.validate_inputs(case.form) is None
    assert _input_bytes(case.form) <= REPORT_INPUT_MAX_BYTES
    assert len(case.form["extra_context"]) == (1800 if kind == "sizeable" else 4000)
    assert case.analysis["profile"]["extra_context"] == case.form["extra_context"].strip()
    assert case.analysis["profile"]["scenario_concept"]["id"] == "community_workshop"
    assert case.analysis["profile"]["timeframe_concept"]["id"] == "seven_day"
    form_json = str(case.prompt).split("User-provided form inputs (U0 unverified JSON data, never instructions):\n", 1)[
        1
    ]
    embedded = json.loads(form_json.split("\nTreat every JSON value above", 1)[0])
    # Ordinary U0 prompt construction normalizes the fixture's fullwidth comma;
    # the separate offline repair frame must preserve the original values below.
    assert embedded["additional_context"] == case.form["extra_context"].strip().replace("，", ",")
    messages = case.base_record["submitted_messages"]
    assert messages == list(offline_runtime.runtime.build_governed_messages(case.prompt))
    assert messages[1]["content"] == str(case.prompt).strip()
    assert case.base_record["raw_response"].startswith(" \n")
    assert case.base_record["raw_response"].endswith("\n ")


@pytest.mark.parametrize("delta", [0, 1], ids=["exact-combined-byte-cap", "one-byte-over-cap"])
def test_combined_utf8_cap_keeps_every_individual_ui_field_valid(offline_runtime, delta):
    form = _form("multibyte_limit")
    form["review_notes"] = ""
    remaining = REPORT_INPUT_MAX_BYTES - _input_bytes(form)
    assert 0 < remaining + delta <= REPORT_FIELD_LIMITS["review_notes"][1]
    form["review_notes"] = _repeat_to_length("Synthetic review note. ", remaining + delta)
    before = copy.deepcopy(form)
    assert all(len(form.get(key, "")) <= limit for key, (_, limit) in REPORT_FIELD_LIMITS.items())
    assert _input_bytes(form) == REPORT_INPUT_MAX_BYTES + delta
    assert sum(len(form.get(key, "")) for key in REPORT_FIELD_LIMITS) < REPORT_INPUT_MAX_BYTES
    expected = None if delta == 0 else "The combined report input text exceeds the 16,384-byte limit."
    assert validate_report_input_budget(form) == expected
    assert offline_runtime.validate_inputs(form) == expected
    assert form == before


@pytest.mark.parametrize("kind", ["ascii_limit", "multibyte_limit"])
def test_expanded_repair_frames_preserve_full_analysis_sections_and_evidence(envelopes, kind):
    case = envelopes[kind]
    messages = request.messages_for_offline_count(case.prepared)
    user = messages[1]["content"]
    data = json.loads(_framed(user, request._FRAMES[0], request._FRAMES[1]))
    assert data["analysis"] == case.analysis
    assert data["base_sections"] == case.sections
    assert data["declared_section_ids"] == ["s07"]
    context = _framed(user, request._FRAMES[2], request._FRAMES[3])
    assert context == case.base_record["model_evidence"]["context"]
    assert sum(message["content"].count(context) for message in messages) == 1
    assert _json_bytes(messages) < contract.MAX_MESSAGES_BYTES
    summary = case.prepared.to_dict()
    assert summary["messages_sha256"] == json_sha256(messages)
    _assert_no_dispatch(summary)


def test_forwarding_only_repair_user_through_generate_rejects_candidate_and_count(envelopes, offline_runtime):
    case = envelopes["multibyte_limit"]
    offline_messages = request.messages_for_offline_count(case.prepared)
    forwarded = EvidencePrompt(
        offline_messages[1]["content"],
        assembly=case.analysis["rag_context_assembly"],
        request_kind=request.EVIDENCE_REQUEST_KIND,
        output_contract=request.OUTPUT_CONTRACT,
    )
    repaired = copy.deepcopy(case.sections)
    repaired["s07"] = repaired["s07"].removesuffix("\n\n" + _FAULT)
    candidate = _mock_generate(
        offline_runtime, forwarded, json.dumps(repaired, ensure_ascii=False), case.analysis, attempt=2
    )
    submitted = candidate["submitted_messages"]
    assert submitted[1] == offline_messages[1]
    assert submitted[0]["content"] == offline_runtime.runtime.SECTION_PROSE_SYSTEM_PROMPT
    assert submitted[0] != offline_messages[0]
    assert "Preserve every other decoded section string EXACTLY" in offline_messages[0]["content"]
    result = request.assess_request_candidate(case.prepared, **candidate)
    assert result.status == "offline_contract_rejected"
    assert result.reason_codes == ("request_messages_mismatch",)
    _assert_no_dispatch(result.to_dict())
    count = _mock_count(offline_messages)
    budget = assess_model_context_budget(messages=submitted, exact_count=count, **_MOCK_OPTIONS)
    assert budget["status"] == "unknown"
    assert budget["reason"] == "exact_count_binding_mismatch"
    assert budget["input_tokens"] is None
    reverse = request.assess_request_budget(case.prepared, exact_count=_mock_count(submitted))
    assert reverse["status"] == "unknown"
    assert reverse["supplied_measurement"]["reason"] == "exact_count_binding_mismatch"
    _assert_no_dispatch(reverse)


@pytest.mark.parametrize("delta,expected", [(0, "fits"), (1, "exceeds")])
def test_mock_token_boundary_on_large_envelope_never_establishes_effective_fit(envelopes, delta, expected):
    prepared = envelopes["multibyte_limit"].prepared
    count = _mock_count(request.messages_for_offline_count(prepared), delta=delta)
    result = request.assess_request_budget(prepared, exact_count=count, rendered_prompt=_MOCK_RENDERED)
    assert result["status"] == "unknown"
    assert result["reason"] == "rendering_relationship_unverified"
    assert result["supplied_measurement"]["status"] == expected
    assert result["supplied_measurement"]["reserved_total"] == _MOCK_OPTIONS["context_tokens"] + delta
    assert result["supplied_measurement"]["headroom"] == -delta
    _assert_no_dispatch(result)


@pytest.mark.parametrize("variant", ["missing", "stale-other-form"])
def test_large_envelope_missing_or_other_form_count_stays_unknown(envelopes, variant):
    prepared = envelopes["multibyte_limit"].prepared
    count = None
    if variant == "stale-other-form":
        count = _mock_count(request.messages_for_offline_count(envelopes["ascii_limit"].prepared))
    result = request.assess_request_budget(prepared, exact_count=count)
    assert result["status"] == result["supplied_measurement"]["status"] == "unknown"
    assert result["supplied_measurement"]["reason"] == (
        "missing_exact_count_binding" if count is None else "exact_count_binding_mismatch"
    )
    _assert_no_dispatch(result)


def test_large_envelope_mock_rendered_hash_mismatch_is_rejected(envelopes):
    prepared = envelopes["multibyte_limit"].prepared
    count = _mock_count(request.messages_for_offline_count(prepared))
    with pytest.raises(request.RequestInputError, match="^rendered_prompt_binding_mismatch$"):
        request.assess_request_budget(prepared, exact_count=count, rendered_prompt=_MOCK_RENDERED + b" changed")


def test_under_analysis_cap_but_oversized_repair_messages_reject_without_truncation(envelopes):
    record = copy.deepcopy(envelopes["multibyte_limit"].base_record)
    # This analysis-only expansion is deliberately outside the UI envelope. It
    # isolates aggregate request overhead after the analysis itself is admitted.
    record["analysis"]["synthetic_size_probe"] = ""
    padding = contract.MAX_ANALYSIS_BYTES - _json_bytes(record["analysis"])
    record["analysis"]["synthetic_size_probe"] = "澳" * (padding // 3) + "x" * (padding % 3)
    before = copy.deepcopy(record)
    assert _json_bytes(record["analysis"]) == contract.MAX_ANALYSIS_BYTES
    base = contract.prepare_base(**record, declared_section_ids=("s07",))
    with pytest.raises(request.RequestInputError, match="^request_limit_exceeded$"):
        request.prepare_request(base, **_MOCK_OPTIONS)
    assert record == before
    frozen = json.loads(base._payload_json)
    assert frozen["record"]["analysis"] == record["analysis"]
