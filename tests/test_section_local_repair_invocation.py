"""Synthetic offline invocation plans; no actual capture, model or tokenizer."""

import ast
import copy
import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from scripts import section_local_repair_contract as contract
from scripts import section_local_repair_invocation as invocation
from scripts import section_local_repair_render as render
from scripts import section_local_repair_request as request
from tests.support.report_fixtures import _valid_report, section_response_for_report
from tests.test_section_local_repair_request import _record


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _render(prepared):
    return render.render_request_offline(
        prepared,
        profile_id=render.PROFILE_ID,
        model_digest=render.MODEL_DIGEST,
        model_layer_sha256=render.MODEL_LAYER_SHA256,
        template_bytes=render._TEMPLATE_BYTES,
        context_tokens=render.CONTEXT_TOKENS,
    )


def _plan(rendered, **changes):
    return invocation.prepare_invocation(
        rendered, **{"model_name": "PRIVATE fixture-model:local", "temperature": 0.25, "seed": 17, **changes}
    )


def _rehashed_request(prepared, mutate):
    payload = json.loads(prepared._payload_json)
    mutate(payload)
    encoded = _json(payload)
    return request.PreparedRequest(encoded, _hash(encoded))


@pytest.fixture(scope="module")
def materials():
    body, analysis = _valid_report()
    sections = json.loads(section_response_for_report(body, analysis))
    analysis["private_fixture"] = "PRIVATE analysis 你好 café e\u0301\r\n  keep trailing spaces  "
    sections["s02"] = "  " + sections["s02"] + "  "
    sections["s15"] += "  "
    base_record = _record(analysis, sections)
    base = contract.prepare_base(**base_record, declared_section_ids=("s07",))
    prepared = request.prepare_request(
        base,
        requested_output_tokens=2048,
        model_digest=render.MODEL_DIGEST,
        template_sha256=render.TEMPLATE_SHA256,
        context_tokens=render.CONTEXT_TOKENS,
    )
    rendered = _render(prepared)
    plan = _plan(rendered)
    return prepared, rendered, plan, analysis, sections, base_record


def _small_kwargs(**changes):
    return {
        "model": "fixture-model",
        "messages": [{"role": "system", "content": " S\r\n "}, {"role": "user", "content": " U\n  "}],
        "temperature": 0.25,
        "top_p": 0.8,
        "max_tokens": 2048,
        "stream": True,
        "seed": 17,
        **changes,
    }


def _measurement(plan, input_tokens=100):
    summary = plan.to_dict()
    return {
        "scope": "full_rendered_prompt",
        "model_digest": render.MODEL_DIGEST,
        "template_sha256": render.TEMPLATE_SHA256,
        "messages_sha256": summary["messages_sha256"],
        "context_tokens": render.CONTEXT_TOKENS,
        "rendered_prompt_sha256": summary["rendered_prompt_sha256"],
        "tokenizer_identity": "PRIVATE mock tokenizer never run",
        "input_tokens": input_tokens,
        "count_method": "verified_offline_tokenizer",
    }


def _assert_closed(value):
    assert value["eligible_for_model_dispatch"] is False
    assert value["production_acceptance"] is False
    assert value.get("effective_budget_status", value.get("status")) == "unknown"
    assert "PRIVATE" not in _json(value)


def test_exact_prospective_kwargs_preserve_full_request_and_bind_metadata(materials):
    prepared, rendered, plan, analysis, sections, base_record = materials
    kwargs = invocation.completion_kwargs_for_offline_inspection(plan)
    messages = request.messages_for_offline_count(prepared)
    assert kwargs == {
        "model": "PRIVATE fixture-model:local",
        "messages": messages,
        "temperature": 0.25,
        "top_p": 0.8,
        "max_tokens": 2048,
        "stream": True,
        "seed": 17,
    }
    summary = plan.to_dict()
    data = json.loads(prepared._payload_json)
    assert summary["profile_id"] == "ollama-chat-completions-offline-v1"
    assert summary["kwargs_sha256"] == _hash(_json(kwargs))
    assert summary["model_name_sha256"] == _hash(kwargs["model"])
    assert summary["model_name_resolution"] == "unverified_caller_label"
    assert summary["request_sha256"] == prepared._binding_sha256
    assert summary["rendering_sha256"] == rendered._binding_sha256
    assert summary["messages_sha256"] == data["messages_sha256"]
    assert summary["rendered_prompt_sha256"] == _hash(render.rendered_bytes_for_offline_count(rendered).decode("utf-8"))
    assert summary["budget_options"] == data["budget_options"]
    assert summary["generation_kind"] == "section_local_repair"
    assert summary["evidence_request_kind"] == "structural_repair"
    assert summary["output_contract"] == "section-prose-v1"
    assert summary["attempt_number"] == base_record["model_evidence"]["attempt_number"] + 1 == 2
    assert not set(kwargs) & {"generation_kind", "request_kind", "attempt_number", "output_contract", "metadata"}
    frame = messages[1]["content"].split(request._FRAMES[0] + " bytes=", 1)[1]
    size, rest = frame.split("\n", 1)
    raw_data = rest.split("\n" + request._FRAMES[1], 1)[0]
    assert int(size) == len(raw_data.encode("utf-8"))
    decoded = json.loads(raw_data)
    assert decoded["analysis"] == analysis and decoded["base_sections"] == sections
    assert sum(item["content"].count(base_record["model_evidence"]["context"]) for item in messages) == 1
    assert "PRIVATE old system" not in _json(kwargs) and "PRIVATE old user" not in _json(kwargs)
    assert "你好 café e\u0301" in messages[1]["content"]
    assert summary["ollama_runtime_equivalence"] == "unknown"
    _assert_closed(summary)


def test_accessors_return_detached_values_and_frozen_private_representation(materials):
    _, _, plan, _, _, _ = materials
    before = invocation.completion_kwargs_for_offline_inspection(plan)
    changed = invocation.completion_kwargs_for_offline_inspection(plan)
    changed["messages"][0]["content"] = "PRIVATE mutated"
    changed["max_tokens"] = 2300
    summary = plan.to_dict()
    summary["budget_options"]["requested_output_tokens"] = 2300
    summary["eligible_for_model_dispatch"] = True
    assert invocation.completion_kwargs_for_offline_inspection(plan) == before
    assert plan.to_dict()["budget_options"]["requested_output_tokens"] == 2048
    with pytest.raises(FrozenInstanceError):
        plan._seed = 18
    assert repr(plan) == "PreparedInvocation()"
    with pytest.raises(invocation.InvocationInputError, match="^invocation_not_a_prompt$"):
        str(plan)


def test_generic_runtime_rejects_invocation_before_quota_or_transport(materials, monkeypatch):
    from src import model_runtime

    calls = []

    def forbidden(*args, **kwargs):
        calls.append("unexpected quota or transport")
        pytest.fail("offline invocation reached quota or transport")

    monkeypatch.setattr(model_runtime, "acquire_model_slot", forbidden)
    fake_runtime = SimpleNamespace(last_request_capture="PRIVATE stale", _collect_stream=forbidden)
    with pytest.raises(invocation.InvocationInputError, match="^invocation_not_a_prompt$"):
        model_runtime.GovernedModelClient.generate(fake_runtime, materials[2])
    assert calls == [] and fake_runtime.last_request_capture is None


def test_supplied_mock_match_and_field_drift_are_content_free_without_capture_claim(materials):
    plan = materials[2]
    kwargs = invocation.completion_kwargs_for_offline_inspection(plan)
    match = invocation.compare_invocation_kwargs(plan, kwargs)
    assert match["status"] == "supplied_kwargs_match" and match["mismatched_fields"] == []
    assert match["reason_codes"] == []
    assert match["expected_kwargs_sha256"] == match["supplied_kwargs_sha256"]
    assert match["comparison_boundary"] == "supplied_data_only_not_authenticated_capture"
    _assert_closed(match)
    changed = copy.deepcopy(kwargs)
    changed.update(model="PRIVATE other-model", temperature=0.5, top_p=0.9, max_tokens=2300, stream=False, seed=18)
    changed["messages"][1]["content"] += " "
    result = invocation.compare_invocation_kwargs(plan, changed)
    assert result["status"] == "supplied_kwargs_mismatch"
    assert result["mismatched_fields"] == list(invocation._KWARGS_FIELDS)
    assert result["reason_codes"] == ["invocation_kwargs_mismatch"]
    assert result["expected_kwargs_sha256"] != result["supplied_kwargs_sha256"]
    _assert_closed(result)


def test_supplied_digest_validation_and_comparison_use_one_detached_snapshot(materials, monkeypatch):
    plan = materials[2]
    supplied = invocation.completion_kwargs_for_offline_inspection(plan)
    expected_digest = _hash(_json(supplied))
    canonical_json = invocation._canonical_json

    def mutate_after_serialization(value, limit):
        encoded = canonical_json(value, limit)
        if value is supplied:
            supplied["messages"][0]["role"] = "assistant"
            supplied["messages"][1]["content"] = "PRIVATE changed after snapshot"
            supplied["max_tokens"] = True
        return encoded

    monkeypatch.setattr(invocation, "_canonical_json", mutate_after_serialization)
    result = invocation.compare_invocation_kwargs(plan, supplied)
    assert supplied["max_tokens"] is True
    assert result["status"] == "supplied_kwargs_match" and result["mismatched_fields"] == []
    assert result["supplied_kwargs_sha256"] == result["expected_kwargs_sha256"] == expected_digest
    _assert_closed(result)


@pytest.mark.parametrize("change", ["crlf", "unicode", "space", "system"])
def test_supplied_message_comparison_never_normalizes_or_strips(materials, change):
    plan = materials[2]
    kwargs = invocation.completion_kwargs_for_offline_inspection(plan)
    if change == "system":
        kwargs["messages"][0]["content"] = "PRIVATE generic default system"
    elif change == "unicode":
        kwargs["messages"][1]["content"] = kwargs["messages"][1]["content"].replace("e\u0301", "é")
    elif change == "crlf":
        kwargs["messages"][1]["content"] = kwargs["messages"][1]["content"].replace("\n", "\r\n")
    else:
        kwargs["messages"][1]["content"] += " "
    result = invocation.compare_invocation_kwargs(plan, kwargs)
    assert result["mismatched_fields"] == ["messages"]
    _assert_closed(result)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"model_name": ""}, "invocation_input_invalid"),
        ({"model_name": "  "}, "invocation_input_invalid"),
        ({"model_name": " model"}, "invocation_input_invalid"),
        ({"model_name": "model "}, "invocation_input_invalid"),
        ({"model_name": "model\n"}, "invocation_input_invalid"),
        ({"model_name": "PRIVATE\ud800"}, "invocation_input_invalid"),
        ({"model_name": "界" * 86}, "invocation_limit_exceeded"),
        ({"model_name": "x" * 257}, "invocation_limit_exceeded"),
        ({"model_name": None}, "invocation_input_invalid"),
        ({"temperature": True}, "invocation_input_invalid"),
        ({"temperature": 1}, "invocation_input_invalid"),
        ({"temperature": float("nan")}, "invocation_input_invalid"),
        ({"temperature": float("inf")}, "invocation_input_invalid"),
        ({"temperature": -0.1}, "invocation_input_invalid"),
        ({"temperature": 2.01}, "invocation_input_invalid"),
        ({"seed": True}, "invocation_input_invalid"),
        ({"seed": 17.0}, "invocation_input_invalid"),
        ({"seed": -1}, "invocation_input_invalid"),
        ({"seed": 2**31}, "invocation_input_invalid"),
    ],
)
def test_invalid_explicit_options_fail_privately_before_renderer_access(changes, reason):
    with pytest.raises(invocation.InvocationInputError, match=f"^{reason}$"):
        _plan(None, **changes)


def test_project_option_boundaries_are_explicit_without_normalization():
    invocation._options("界" * 85 + "x", 0.0, 0)
    invocation._options("x" * 256, 2.0, 2**31 - 1)
    assert invocation._output_tokens(1) == 1
    assert invocation._output_tokens(2**31 - 1) == 2**31 - 1
    for value in (0, -1, True, 1.0, 2**31, None):
        with pytest.raises(invocation.InvocationInputError, match="^invocation_output_tokens_invalid$"):
            invocation._output_tokens(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"temperature": 1},
        {"temperature": True},
        {"top_p": 1},
        {"top_p": True},
        {"top_p": float("nan")},
        {"top_p": float("inf")},
        {"top_p": -0.1},
        {"max_tokens": True},
        {"max_tokens": 2048.0},
        {"max_tokens": 0},
        {"max_tokens": 2**257},
        {"stream": 1},
        {"seed": True},
        {"messages": ({"role": "system", "content": "S"}, {"role": "user", "content": "U"})},
        {"messages": [{"role": "user", "content": "U"}, {"role": "system", "content": "S"}]},
        {"messages": [{"role": "system", "content": "S"}, {"role": "assistant", "content": "U"}]},
        {"messages": [{"role": "system", "content": ""}, {"role": "user", "content": "U"}]},
        {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U", "name": "PRIVATE"}]},
    ],
)
def test_supplied_kwargs_require_exact_builtin_shapes_and_types(changes):
    with pytest.raises(invocation.InvocationInputError):
        invocation._validate_supplied_kwargs(_small_kwargs(**changes))


@pytest.mark.parametrize(
    "field",
    [
        "tools",
        "tool_choice",
        "response_format",
        "extra_body",
        "options",
        "num_ctx",
        "num_predict",
        "metadata",
        "generation_kind",
        "request_kind",
        "output_contract",
        "attempt_number",
        "max_completion_tokens",
        "stop",
    ],
)
def test_unknown_provider_or_metadata_fields_are_rejected(field):
    with pytest.raises(invocation.InvocationInputError, match="^invocation_kwargs_invalid$"):
        invocation._validate_supplied_kwargs(_small_kwargs(**{field: "PRIVATE"}))


def test_missing_fields_malformed_roots_and_cycles_reject_privately():
    for field in invocation._KWARGS_FIELDS:
        value = _small_kwargs()
        del value[field]
        with pytest.raises(invocation.InvocationInputError, match="^invocation_kwargs_invalid$"):
            invocation._validate_supplied_kwargs(value)
    cyclic = _small_kwargs()
    cyclic["messages"].append(cyclic)
    for value in (None, [], "PRIVATE", cyclic):
        with pytest.raises(invocation.InvocationInputError):
            invocation._validate_supplied_kwargs(value)


def test_builtin_subclasses_and_callbacks_are_rejected_without_executing_hooks():
    class TrapDict(dict):
        def __iter__(self):
            raise AssertionError("PRIVATE iteration executed")

    class TrapStr(str):
        def __eq__(self, other):
            raise AssertionError("PRIVATE equality executed")

    class TrapInt(int):
        def __lt__(self, other):
            raise AssertionError("PRIVATE integer comparison executed")

    class TrapFloat(float):
        def __float__(self):
            raise AssertionError("PRIVATE float hook executed")

    for value in (
        TrapDict(_small_kwargs()),
        _small_kwargs(model=TrapStr("model")),
        _small_kwargs(temperature=TrapFloat(0.25)),
        _small_kwargs(seed=TrapInt(17)),
        _small_kwargs(messages=[{"role": TrapStr("system"), "content": "S"}, {"role": "user", "content": "U"}]),
        _small_kwargs(callback=lambda: pytest.fail("callback ran")),
    ):
        with pytest.raises(invocation.InvocationInputError, match="^invocation_input_invalid$"):
            invocation._validate_supplied_kwargs(value)
    error = invocation.InvocationInputError(TrapStr("PRIVATE"))
    error.args = ("PRIVATE args",)
    error.code = TrapStr("PRIVATE code")
    assert str(error) == "invocation_input_invalid"
    assert "PRIVATE" not in repr(error)


def test_utf8_message_limit_is_exact_combined_and_reject_only():
    value = _small_kwargs()
    value["messages"][1]["content"] = "x"
    overhead = len(_json(value["messages"]).encode("utf-8")) - 1
    value["messages"][1]["content"] = "x" * (contract.MAX_MESSAGES_BYTES - overhead)
    original = copy.deepcopy(value)
    assert invocation._validate_supplied_kwargs(value) == _json(original)
    assert value == original
    value["messages"][1]["content"] += "x"
    with pytest.raises(invocation.InvocationInputError, match="^invocation_limit_exceeded$"):
        invocation._validate_supplied_kwargs(value)
    value["messages"][1]["content"] = "界" * (contract.MAX_MESSAGES_BYTES // 3)
    assert len(value["messages"][1]["content"]) < contract.MAX_MESSAGES_BYTES
    with pytest.raises(invocation.InvocationInputError, match="^invocation_limit_exceeded$"):
        invocation._validate_supplied_kwargs(value)
    value["messages"][1]["content"] = "PRIVATE\ud800"
    with pytest.raises(invocation.InvocationInputError, match="^invocation_input_invalid$"):
        invocation._validate_supplied_kwargs(value)


def test_every_public_accessor_rejects_invalid_or_stale_invocation_binding(materials):
    _, _, plan, _, _, _ = materials
    accessors = (
        lambda value: value.to_dict(),
        invocation.completion_kwargs_for_offline_inspection,
        lambda value: invocation.compare_invocation_kwargs(value, _small_kwargs()),
        invocation.assess_invocation_budget,
    )
    for changes in (
        {"_binding_sha256": "PRIVATE"},
        {"_binding_sha256": "0" * 64},
        {"_model_name": "PRIVATE changed label"},
        {"_temperature": 0.5},
        {"_seed": 18},
        {"_rendered_request": None},
    ):
        forged = replace(plan, **changes)
        for accessor in accessors:
            with pytest.raises(invocation.InvocationInputError, match="^invocation_result_invalid$"):
                accessor(forged)
    for accessor in accessors[1:]:
        with pytest.raises(invocation.InvocationInputError, match="^invocation_result_invalid$"):
            accessor({"PRIVATE": "forged plan"})


def test_rehashed_derived_messages_and_metadata_cannot_override_frozen_request(materials):
    prepared, rendered, plan, _, _, _ = materials

    def change_messages(data):
        data["messages"][0]["content"] = "PRIVATE default system override"
        data["messages_sha256"] = _hash(_json(data["messages"]))

    for mutate in (
        change_messages,
        lambda data: data.__setitem__("attempt_number", 3),
        lambda data: data.__setitem__("generation_kind", "initial"),
        lambda data: data.__setitem__("evidence_request_kind", "initial"),
        lambda data: data.__setitem__("output_contract", "markdown"),
    ):
        forged_request = _rehashed_request(prepared, mutate)
        forged_render = replace(rendered, _prepared_request=forged_request)
        with pytest.raises(invocation.InvocationInputError, match="^invocation_rendering_invalid$"):
            _plan(forged_render)
        with pytest.raises(invocation.InvocationInputError, match="^invocation_result_invalid$"):
            replace(plan, _rendered_request=forged_render).to_dict()
    false_summary = plan.to_dict()
    false_summary.pop("invocation_sha256")
    false_summary["eligible_for_model_dispatch"] = True
    with pytest.raises(invocation.InvocationInputError, match="^invocation_result_invalid$"):
        replace(plan, _binding_sha256=_hash(_json(false_summary))).to_dict()


def test_changed_valid_output_budget_requires_new_render_and_invocation_binding(materials):
    prepared, rendered, plan, _, _, _ = materials
    changed = _rehashed_request(
        prepared, lambda data: data["budget_options"].__setitem__("requested_output_tokens", 2049)
    )
    with pytest.raises(invocation.InvocationInputError, match="^invocation_rendering_invalid$"):
        _plan(replace(rendered, _prepared_request=changed))
    changed_render = _render(changed)
    with pytest.raises(invocation.InvocationInputError, match="^invocation_result_invalid$"):
        replace(plan, _rendered_request=changed_render).to_dict()
    changed_plan = _plan(changed_render)
    original_summary, changed_summary = plan.to_dict(), changed_plan.to_dict()
    assert changed_summary["messages_sha256"] == original_summary["messages_sha256"]
    assert changed_summary["rendered_prompt_sha256"] == original_summary["rendered_prompt_sha256"]
    for field in ("request_sha256", "rendering_sha256", "kwargs_sha256", "invocation_sha256"):
        assert changed_summary[field] != original_summary[field]
    assert invocation.completion_kwargs_for_offline_inspection(changed_plan)["max_tokens"] == 2049
    zero = _rehashed_request(prepared, lambda data: data["budget_options"].__setitem__("requested_output_tokens", 0))
    zero_render = _render(zero)
    assert zero.to_dict()["budget_options"]["requested_output_tokens"] == 0
    with pytest.raises(invocation.InvocationInputError, match="^invocation_output_tokens_invalid$"):
        _plan(zero_render)


@pytest.mark.parametrize("input_tokens,expected", [(100, "fits"), (8192, "exceeds")])
def test_mock_arithmetic_is_bound_to_real_profile_bytes_but_budget_stays_unknown(materials, input_tokens, expected):
    plan = materials[2]
    count = _measurement(plan, input_tokens)
    result = invocation.assess_invocation_budget(plan, exact_count=count)
    assert result["status"] == "unknown"
    assert result["reason"] == "rendering_relationship_unverified"
    assert result["invocation_sha256"] == plan._binding_sha256
    assert result["supplied_rendered_bytes_sha256"] == count["rendered_prompt_sha256"]
    assert result["supplied_measurement"]["status"] == expected
    assert result["supplied_measurement"]["reserved_total"] == input_tokens + 2048 + 1
    _assert_closed(result)


def test_missing_count_stays_unknown_and_does_not_invent_rendered_binding(materials):
    result = invocation.assess_invocation_budget(materials[2])
    assert result["supplied_measurement"]["reason"] == "missing_exact_count_binding"
    assert result["supplied_rendered_bytes_sha256"] is None
    _assert_closed(result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_digest", "c" * 64),
        ("template_sha256", "c" * 64),
        ("messages_sha256", "c" * 64),
        ("context_tokens", 8193),
    ],
)
def test_supplied_count_identity_or_messages_drift_stays_unknown(materials, field, value):
    plan = materials[2]
    count = _measurement(plan)
    count[field] = value
    result = invocation.assess_invocation_budget(plan, exact_count=count)
    assert result["supplied_measurement"]["status"] == "unknown"
    assert result["supplied_measurement"]["reason"] == "exact_count_binding_mismatch"
    _assert_closed(result)


def test_wrong_rendered_hash_old_messages_and_malformed_counts_are_rejected_privately(materials):
    plan = materials[2]
    count = _measurement(plan)
    count["rendered_prompt_sha256"] = _hash("PRIVATE fabricated rendering")
    with pytest.raises(invocation.InvocationInputError, match="^invocation_rendered_prompt_binding_mismatch$"):
        invocation.assess_invocation_budget(plan, exact_count=count)
    count = _measurement(plan)
    count["messages_sha256"] = _hash(_json(materials[5]["submitted_messages"]))
    assert invocation.assess_invocation_budget(plan, exact_count=count)["supplied_measurement"]["status"] == "unknown"
    for changes, reason in (
        ({"PRIVATE unknown field": "PRIVATE"}, "invocation_budget_input_invalid"),
        ({"input_tokens": True}, "invocation_budget_input_invalid"),
        ({"input_tokens": 2**contract.MAX_INTEGER_BITS}, "invocation_limit_exceeded"),
        ({"tokenizer_identity": "界" * 2800}, "invocation_limit_exceeded"),
    ):
        count = {**_measurement(plan), **changes}
        with pytest.raises(invocation.InvocationInputError, match=f"^{reason}$"):
            invocation.assess_invocation_budget(plan, exact_count=count)


def test_module_has_no_io_runtime_sdk_config_or_callback_surface():
    tree = ast.parse(inspect.getsource(invocation))
    imports = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports == {"__future__", "hashlib", "json", "math", "dataclasses", "scripts"}
    calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(isinstance(func, ast.Name) and func.id in {"open", "exec", "eval", "__import__"} for func in calls)
    expected = {
        invocation.prepare_invocation: {"rendered_request", "model_name", "temperature", "seed"},
        invocation.completion_kwargs_for_offline_inspection: {"invocation"},
        invocation.compare_invocation_kwargs: {"invocation", "supplied_kwargs"},
        invocation.assess_invocation_budget: {"invocation", "exact_count"},
    }
    for function, names in expected.items():
        parameters = inspect.signature(function).parameters
        assert set(parameters) == names
        assert not any(value.kind in (value.VAR_POSITIONAL, value.VAR_KEYWORD) for value in parameters.values())
