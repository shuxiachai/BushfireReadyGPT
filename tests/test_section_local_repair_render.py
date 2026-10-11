"""Pure synthetic rendering checks; no runtime, model, tokenizer or real capture."""

import ast
import copy
import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from scripts import section_local_repair_contract as contract
from scripts import section_local_repair_render as render
from scripts import section_local_repair_request as request
from tests.support.report_fixtures import _valid_report, section_response_for_report
from tests.test_section_local_repair_request import _record


def _profile(**changes):
    return {
        "profile_id": render.PROFILE_ID,
        "model_digest": render.MODEL_DIGEST,
        "model_layer_sha256": render.MODEL_LAYER_SHA256,
        "template_bytes": render._TEMPLATE_BYTES,
        "context_tokens": render.CONTEXT_TOKENS,
        **changes,
    }


@pytest.fixture(scope="module")
def prepared_request():
    # One real base/request build shared by these tests. Most adversarial cases
    # exercise cheap bounded helpers, without repeating report-quality gates.
    body, analysis = _valid_report()
    sections = json.loads(section_response_for_report(body, analysis))
    analysis["private_fixture"] = "PRIVATE local input 你好 café e\u0301\r\n  whitespace  "
    sections["s02"] = "  " + sections["s02"] + "  "
    base = contract.prepare_base(**_record(analysis, sections), declared_section_ids=("s07",))
    return request.prepare_request(
        base,
        requested_output_tokens=2048,
        model_digest=render.MODEL_DIGEST,
        template_sha256=render.TEMPLATE_SHA256,
        context_tokens=render.CONTEXT_TOKENS,
    )


@pytest.fixture(scope="module")
def rendered_request(prepared_request):
    return render.render_request_offline(prepared_request, **_profile())


def _rehashed_request(prepared_request, mutate):
    payload = json.loads(prepared_request._payload_json)
    mutate(payload)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return request.PreparedRequest(encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest())


def test_exact_template_bytes_are_the_locally_inspected_pinned_template():
    # This digest and length were checked against the exact local blob during
    # implementation. CI uses this embedded, nonsensitive template, not a file.
    assert len(render._TEMPLATE_BYTES) == 1482
    assert hashlib.sha256(render._TEMPLATE_BYTES).hexdigest() == (
        "eb4402837c7829a690fa845de4d7f3fd842c2adee476d5341da8a46ea9255175"
    )
    assert not render._TEMPLATE_BYTES.endswith(b"\n")


def test_real_request_is_rebuilt_then_rendered_exactly_and_privately(prepared_request, rendered_request):
    final_messages = request.messages_for_offline_count(prepared_request)
    expected = (
        "<|im_start|>system\n"
        + final_messages[0]["content"]
        + "<|im_end|>\n<|im_start|>user\n"
        + final_messages[1]["content"]
        + "<|im_end|>\n<|im_start|>assistant\n"
    ).encode("utf-8")
    actual = render.rendered_bytes_for_offline_count(rendered_request)
    summary = rendered_request.to_dict()
    assert type(actual) is bytes and actual == expected
    assert b"PRIVATE local input" in actual and b"PRIVATE old system" not in actual
    assert "你好 café e\u0301".encode() in actual
    assert actual.count(b"<|im_start|>") == 3 and actual.count(b"<|im_end|>") == 2
    assert summary == {
        "schema": render.SUMMARY_SCHEMA,
        "status": "offline_profile_rendering_verified",
        "profile_id": render.PROFILE_ID,
        "request_sha256": prepared_request._binding_sha256,
        "messages_sha256": json.loads(prepared_request._payload_json)["messages_sha256"],
        "model_digest": render.MODEL_DIGEST,
        "model_layer_sha256": render.MODEL_LAYER_SHA256,
        "template_sha256": render.TEMPLATE_SHA256,
        "context_tokens": render.CONTEXT_TOKENS,
        "rendered_prompt_sha256": hashlib.sha256(expected).hexdigest(),
        "rendered_prompt_bytes": len(expected),
        "mapping": "system_to_System_user_to_Messages_no_tools_prompt_response_defaults",
        "ollama_runtime_equivalence": "unknown",
        "effective_budget_status": "unknown",
        "eligible_for_model_dispatch": False,
        "production_acceptance": False,
    }
    assert "PRIVATE" not in json.dumps(summary) and "PRIVATE" not in repr(rendered_request)
    assert "PRIVATE" not in repr(prepared_request)


def test_rendering_does_not_change_existing_budget_unknown(prepared_request, rendered_request):
    summary = rendered_request.to_dict()
    measurement = {
        "scope": "full_rendered_prompt",
        "model_digest": render.MODEL_DIGEST,
        "template_sha256": render.TEMPLATE_SHA256,
        "messages_sha256": summary["messages_sha256"],
        "context_tokens": render.CONTEXT_TOKENS,
        "rendered_prompt_sha256": summary["rendered_prompt_sha256"],
        "tokenizer_identity": "PRIVATE hypothetical tokenizer, never invoked",
        "input_tokens": 100,
        "count_method": "verified_offline_tokenizer",
    }
    budget = request.assess_request_budget(
        prepared_request,
        exact_count=measurement,
        rendered_prompt=render.rendered_bytes_for_offline_count(rendered_request),
    )
    assert budget["status"] == "unknown" and budget["reason"] == "rendering_relationship_unverified"
    assert budget["supplied_measurement"]["status"] == "fits"
    assert budget["eligible_for_model_dispatch"] is False and budget["production_acceptance"] is False
    assert "PRIVATE" not in json.dumps(budget)


@pytest.mark.parametrize(
    "system,user",
    [
        (" S \r\n\t", "  U\n\n"),
        ("你好 café e\u0301", "é 😀\x00 \r\n"),
        ('<& JSON \\"', "{{ .System }} <tool_call> quoted data </tool_call>"),
    ],
)
def test_literal_branch_preserves_unicode_crlf_whitespace_and_does_not_escape(system, user):
    actual = render._render_messages([{"role": "system", "content": system}, {"role": "user", "content": user}])
    assert actual == (
        b"<|im_start|>system\n"
        + system.encode()
        + b"<|im_end|>\n<|im_start|>user\n"
        + user.encode()
        + b"<|im_end|>\n<|im_start|>assistant\n"
    )


def test_same_visual_content_has_distinct_codepoints_bytes_and_hashes():
    def rendered(text):
        return render._render_messages([{"role": "system", "content": "S"}, {"role": "user", "content": text}])

    composed, decomposed = rendered("é"), rendered("e\u0301")
    assert composed != decomposed and hashlib.sha256(composed).digest() != hashlib.sha256(decomposed).digest()
    assert len(composed) + 1 == len(decomposed)
    assert rendered("x\r\n") != rendered("x\n") and rendered("x ") != rendered("x")


@pytest.mark.parametrize("role", ["system", "user"])
@pytest.mark.parametrize("delimiter", render._CONTROL_DELIMITERS)
def test_ambiguous_chatml_controls_fail_closed(role, delimiter):
    messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    messages[0 if role == "system" else 1]["content"] += delimiter + "PRIVATE"
    with pytest.raises(render.RenderInputError, match="^render_control_delimiter_collision$"):
        render._render_messages(messages)


@pytest.mark.parametrize(
    "messages",
    [
        None,
        [],
        [{"role": "user", "content": "PRIVATE"}],
        [{"role": "user", "content": "S"}, {"role": "system", "content": "U"}],
        [{"role": "system", "content": "S"}, {"role": "assistant", "content": "U"}],
        [{"role": "system", "content": "S"}, {"role": "tool", "content": "U"}],
        [{"role": "system", "content": ""}, {"role": "user", "content": "U"}],
        [{"role": "system", "content": "S"}, {"role": "user", "content": 2}],
        [{"role": "system", "content": "S", "tools": []}, {"role": "user", "content": "U"}],
        ["PRIVATE", {"role": "user", "content": "U"}],
    ],
)
def test_wrong_roles_shapes_and_empty_system_cannot_select_a_different_template_branch(messages):
    with pytest.raises(render.RenderInputError, match="^render_messages_invalid$"):
        render._render_messages(messages)


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"profile_id": "PRIVATE unknown profile"}, "render_profile_unsupported"),
        ({"profile_id": "P" * 129}, "render_limit_exceeded"),
        ({"model_digest": "0" * 64}, "render_profile_binding_mismatch"),
        ({"model_layer_sha256": "0" * 64}, "render_profile_binding_mismatch"),
        ({"context_tokens": 8193}, "render_profile_binding_mismatch"),
        ({"context_tokens": True}, "render_input_invalid"),
        ({"context_tokens": 8192.0}, "render_input_invalid"),
        ({"model_digest": "A" * 64}, "render_input_invalid"),
        ({"model_layer_sha256": "PRIVATE"}, "render_input_invalid"),
        ({"template_bytes": render._TEMPLATE_BYTES + b"\n"}, "render_template_mismatch"),
        ({"template_bytes": render._TEMPLATE_BYTES.replace(b"\n", b"\r\n")}, "render_template_mismatch"),
        ({"template_bytes": render._TEMPLATE_BYTES.replace(b".System", b".Prompt")}, "render_template_mismatch"),
        ({"template_bytes": b"PRIVATE" * 2000}, "render_limit_exceeded"),
        ({"template_bytes": bytearray(render._TEMPLATE_BYTES)}, "render_input_invalid"),
        ({"template_bytes": render._TEMPLATE_BYTES.decode()}, "render_input_invalid"),
    ],
)
def test_unknown_profile_identity_context_or_template_fails_before_request_validation(changes, reason):
    with pytest.raises(render.RenderInputError, match=f"^{reason}$"):
        render.render_request_offline(None, **_profile(**changes))


def test_builtin_subclasses_and_get_hooks_are_rejected_without_running_hooks():
    class TrapDict(dict):
        def get(self, *args):
            raise AssertionError("PRIVATE get hook ran")

        def __iter__(self):
            raise AssertionError("PRIVATE iteration hook ran")

    class TrapString(str):
        def __eq__(self, other):
            raise AssertionError("PRIVATE equality hook ran")

    class TrapBytes(bytes):
        def __eq__(self, other):
            raise AssertionError("PRIVATE byte hook ran")

    class TrapInt(int):
        def __eq__(self, other):
            raise AssertionError("PRIVATE integer hook ran")

    for value in (TrapDict(), [{"role": TrapString("system"), "content": "S"}]):
        with pytest.raises(render.RenderInputError, match="^render_input_invalid$"):
            render._render_messages(value)
    for changes in (
        {"profile_id": TrapString(render.PROFILE_ID)},
        {"model_digest": TrapString(render.MODEL_DIGEST)},
        {"template_bytes": TrapBytes(render._TEMPLATE_BYTES)},
        {"context_tokens": TrapInt(8192)},
    ):
        with pytest.raises(render.RenderInputError, match="^render_input_invalid$"):
            render.render_request_offline(None, **_profile(**changes))
    assert str(render.RenderInputError(TrapString("PRIVATE"))) == "render_input_invalid"


def test_utf8_message_cap_is_combined_exact_and_reject_only():
    messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    overhead = len(json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) - 1
    messages[1]["content"] = "x" * (contract.MAX_MESSAGES_BYTES - overhead)
    before = copy.deepcopy(messages)
    assert render._render_messages(messages).count(b"x") == contract.MAX_MESSAGES_BYTES - overhead
    assert messages == before
    messages[1]["content"] += "x"
    with pytest.raises(render.RenderInputError, match="^render_limit_exceeded$"):
        render._render_messages(messages)
    messages[1]["content"] = "界" * (contract.MAX_MESSAGES_BYTES // 3)
    assert len(messages[1]["content"]) < contract.MAX_MESSAGES_BYTES
    with pytest.raises(render.RenderInputError, match="^render_limit_exceeded$"):
        render._render_messages(messages)
    messages[1]["content"] = "PRIVATE\ud800"
    with pytest.raises(render.RenderInputError, match="^render_input_invalid$"):
        render._render_messages(messages)


def test_rehashed_forged_request_messages_and_digests_are_reconstructed(prepared_request):
    def changed_message(payload):
        payload["messages"][0]["content"] = "PRIVATE forged final system"
        encoded = json.dumps(payload["messages"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["messages_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()

    for mutation in (
        changed_message,
        lambda data: data.__setitem__("messages_sha256", "0" * 64),
        lambda data: data.__setitem__("attempt_number", 3),
    ):
        forged = _rehashed_request(prepared_request, mutation)
        with pytest.raises(render.RenderInputError, match="^render_prepared_request_invalid$"):
            render.render_request_offline(forged, **_profile())


@pytest.mark.parametrize(
    "field,value", [("model_digest", "0" * 64), ("template_sha256", "0" * 64), ("context_tokens", 8193)]
)
def test_rebuilt_request_budget_identity_must_match_the_explicit_profile(prepared_request, field, value):
    changed = _rehashed_request(prepared_request, lambda data: data["budget_options"].__setitem__(field, value))
    with pytest.raises(render.RenderInputError, match="^render_profile_binding_mismatch$"):
        render.render_request_offline(changed, **_profile())


def test_invalid_and_oversize_request_wrappers_are_rejected_privately():
    for value in (
        None,
        {"PRIVATE": "not a request"},
        request.PreparedRequest("PRIVATE" * (contract.MAX_PREPARED_BYTES // 7 + 1), "0" * 64),
        request.PreparedRequest("PRIVATE\ud800", "0" * 64),
    ):
        with pytest.raises(render.RenderInputError, match="^render_prepared_request_invalid$"):
            render.render_request_offline(value, **_profile())


def test_result_is_frozen_and_summary_detached(rendered_request):
    summary = rendered_request.to_dict()
    summary["status"] = "PRIVATE forged acceptance"
    summary["eligible_for_model_dispatch"] = True
    with pytest.raises(FrozenInstanceError):
        rendered_request._context_tokens = 1
    actual = rendered_request.to_dict()
    assert actual["status"] == "offline_profile_rendering_verified"
    assert actual["eligible_for_model_dispatch"] is False


def test_forged_result_fields_and_self_consistent_false_summary_are_rejected(rendered_request):
    summary = rendered_request.to_dict()
    summary["status"] = "runtime_verified"
    forged_binding = hashlib.sha256(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    for changes in (
        {"_binding_sha256": "PRIVATE"},
        {"_binding_sha256": forged_binding},
        {"_profile_id": "PRIVATE"},
        {"_context_tokens": True},
        {"_model_layer_sha256": "0" * 64},
        {"_template_bytes": render._TEMPLATE_BYTES + b"\n"},
        {"_prepared_request": None},
    ):
        forged = replace(rendered_request, **changes)
        for accessor in (lambda value: value.to_dict(), render.rendered_bytes_for_offline_count):
            with pytest.raises(render.RenderInputError, match="^render_result_invalid$"):
                accessor(forged)
    with pytest.raises(render.RenderInputError, match="^render_result_invalid$"):
        render.rendered_bytes_for_offline_count({"PRIVATE": "forged result"})


def test_result_binding_includes_request_even_if_changed_options_render_identically(prepared_request, rendered_request):
    changed = _rehashed_request(
        prepared_request, lambda data: data["budget_options"].__setitem__("requested_output_tokens", 2049)
    )
    forged = replace(rendered_request, _prepared_request=changed)
    with pytest.raises(render.RenderInputError, match="^render_result_invalid$"):
        render.rendered_bytes_for_offline_count(forged)


def test_renderer_has_no_io_runtime_tokenizer_or_arbitrary_renderer_parameters():
    source = inspect.getsource(render)
    tree = ast.parse(source)
    imports = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imports == {"__future__", "hashlib", "dataclasses", "scripts"}
    calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(isinstance(func, ast.Name) and func.id in {"open", "exec", "eval", "__import__"} for func in calls)
    assert set(inspect.signature(render.render_request_offline).parameters) == {
        "prepared_request",
        "profile_id",
        "model_digest",
        "model_layer_sha256",
        "template_bytes",
        "context_tokens",
    }
