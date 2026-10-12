"""SDK mock-only diagnostic checks; sockets, subprocesses and dotenv are barred."""

import copy
import json
import logging
import socket
import subprocess
import time
from dataclasses import replace

import httpx
import pytest

from scripts import ollama_preflight as preflight
from scripts import section_local_repair_contract as contract
from scripts import section_local_repair_invocation as invocation
from scripts import section_local_repair_render as render
from scripts import section_local_repair_request as request
from tests.support.report_fixtures import _valid_report, section_response_for_report
from tests.test_section_local_repair_request import _record


@pytest.fixture(autouse=True)
def deny_external(monkeypatch):
    import dotenv

    def denied(*args, **kwargs):
        pytest.fail("External I/O was attempted during a pure preflight test")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(dotenv, "load_dotenv", denied)


@pytest.fixture(scope="module")
def prepared():
    body, analysis = _valid_report()
    sections = json.loads(section_response_for_report(body, analysis))
    analysis["private_fixture"] = "PRIVATE 你好 café e\u0301\r\n  spaces  "
    base = contract.prepare_base(**_record(analysis, sections), declared_section_ids=("s07",))
    req = request.prepare_request(
        base,
        requested_output_tokens=2300,
        margin_tokens=1,
        model_digest=render.MODEL_DIGEST,
        template_sha256=render.TEMPLATE_SHA256,
        context_tokens=render.CONTEXT_TOKENS,
    )
    rendered = render.render_request_offline(
        req,
        profile_id=render.PROFILE_ID,
        model_digest=render.MODEL_DIGEST,
        model_layer_sha256=render.MODEL_LAYER_SHA256,
        template_bytes=render._TEMPLATE_BYTES,
        context_tokens=render.CONTEXT_TOKENS,
    )
    return invocation.prepare_invocation(rendered, model_name=preflight.MODEL, temperature=0.3, seed=42)


@pytest.fixture
def plan(prepared):
    return preflight.prepare_debug_plan(prepared, origin="http://127.0.0.1:49159", run_id="a" * 32)


def debug_body(plan, **changes):
    _, _, rendered = invocation._revalidate_invocation(plan._prepared)
    data = {
        "id": "test-only",
        "object": "chat.completion",
        "created": 0,
        "model": preflight.MODEL,
        "system_fingerprint": "fp_ollama",
        "choices": [{"index": 0, "message": {"role": "", "content": ""}, "finish_reason": None}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "_debug_info": {"rendered_template": rendered.decode()},
        **changes,
    }
    return preflight.canonical(data)


def response(raw, status=200, **headers):
    return httpx.Response(status, headers={"content-type": "application/json", **headers}, stream=httpx.ByteStream(raw))


def guard(plan, handler, **changes):
    return preflight.FixedRequestTransport(
        method="POST",
        url=plan._origin + preflight.DEBUG_PATH,
        body=plan._wire,
        inner=httpx.MockTransport(handler),
        deadline=time.monotonic() + 10,
        **changes,
    )


def snapshot(plan, monkeypatch, **overrides):
    # Synthetic metadata only: no local default-system file is read in tests.
    monkeypatch.setattr(preflight, "SYSTEM_SHA256", preflight.sha(b"synthetic default system"))
    values = {
        "version": {"version": preflight.VERSION},
        "tags": {"models": [{"name": preflight.MODEL, "model": preflight.MODEL, "digest": render.MODEL_DIGEST}]},
        "show": {
            "template": "synthetic native Jinja template",
            "system": "synthetic default system",
            "parameters": "num_ctx 8192\ntemperature 0.7",
            "modelfile": "FROM C:/synthetic/sha256-" + render.MODEL_LAYER_SHA256,
            "model_info": {"general.architecture": "qwen2"},
        },
        "owner": {
            "pid": 41,
            "created_utc": "2026-10-12T00:00:00Z",
            "executable_sha256": "b" * 64,
            "listener": plan._origin,
            "in_owned_job": True,
        },
        **overrides,
    }
    return preflight.metadata_snapshot(plan, **values)


def count(plan, raw, n):
    return {
        "plan_sha256": plan._binding,
        "run_id": plan._run_id,
        "rendered_sha256": preflight.sha(preflight.decode(raw)["_debug_info"]["rendered_template"].encode()),
        "model_digest": render.MODEL_DIGEST,
        "input_tokens": n,
        "context_tokens": 8192,
        "output_tokens": 2300,
        "margin_tokens": 1,
        "runner_identity_sha256": "c" * 64,
        "count_method": "same_owned_runner_tokenize_detokenize",
    }


def test_sdk_projection_preserves_original_final_messages_and_sampling(plan):
    original = invocation.completion_kwargs_for_offline_inspection(plan._prepared)
    actual = preflight.decode(plan._wire)
    assert original["stream"] is True
    assert actual == {**original, "stream": False, "_debug_render_only": True}
    assert (
        actual["max_tokens"] == 2300
        and actual["temperature"] == 0.3
        and actual["top_p"] == 0.8
        and actual["seed"] == 42
    )
    summary = plan.to_dict()
    assert summary["wire_body_sha256"] == preflight.sha(plan._wire)
    assert summary["original_kwargs_sha256"] == plan._prepared.to_dict()["kwargs_sha256"]
    assert "PRIVATE" not in json.dumps(summary) and "PRIVATE" not in repr(plan)
    assert summary["eligible_for_model_dispatch"] is False


def test_actual_sdk_mock_capture_matches_frozen_raw_wire_and_single_use(plan):
    observed = []

    def handler(req):
        observed.append((req.method, str(req.url), req.content))
        return response(debug_body(plan))

    bounded = guard(plan, handler)
    raw = preflight.send_debug_once(plan, transport=bounded)
    assert observed == [("POST", plan._origin + preflight.DEBUG_PATH, plan._wire)]
    assert raw == debug_body(plan) and bounded.attempts == 1
    with pytest.raises(preflight.PreflightError):
        preflight.send_debug_once(plan, transport=bounded)
    assert len(observed) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 429, 500])
def test_non_200_never_retries_or_follows_redirect(plan, status):
    observed = []
    bounded = guard(
        plan, lambda req: observed.append(req) or response(b"{}", status=status, location="http://example.invalid")
    )
    with pytest.raises(preflight.PreflightError, match="^response_status_rejected$"):
        preflight.send_debug_once(plan, transport=bounded)
    assert len(observed) == bounded.attempts == 1 and bounded.response_body is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda obj: obj.__setitem__("max_tokens", 2299),
        lambda obj: obj.__setitem__("stream", True),
        lambda obj: obj.pop("_debug_render_only"),
        lambda obj: obj.__setitem__("extra_body", {"_debug_render_only": True}),
        lambda obj: obj.__setitem__("tools", []),
        lambda obj: obj["messages"][1].__setitem__("content", "PRIVATE changed request"),
    ],
)
def test_modified_or_extended_wire_is_rejected_before_transport(plan, mutation):
    value = preflight.decode(plan._wire)
    mutation(value)
    forged = replace(plan, _wire=preflight.canonical(value))
    bounded = guard(plan, lambda req: pytest.fail("Modified body reached transport"))
    with pytest.raises(preflight.PreflightError):
        preflight.send_debug_once(forged, transport=bounded)
    assert bounded.attempts == 0


@pytest.mark.parametrize(
    "raw,headers,code",
    [
        (b"x" * (preflight.MAX_RESPONSE_BYTES + 1), {}, "response_too_large"),
        (b"{}", {"content-length": str(preflight.MAX_RESPONSE_BYTES + 1)}, "response_too_large"),
        (b"{}", {"content-encoding": "gzip"}, "response_encoding_rejected"),
        (b"{}", {"content-type": "text/event-stream"}, "response_invalid"),
        (b'{"x":1,"x":2}', {}, "response_invalid"),
        (b'{"x":NaN}', {}, "response_invalid"),
    ],
    ids=["oversize", "length", "compression", "sse", "duplicate", "nan"],
)
def test_response_limits_encoding_json_are_fail_closed(plan, raw, headers, code):
    bounded = guard(plan, lambda req: response(raw, **headers))
    with pytest.raises(preflight.PreflightError, match=f"^{code}$"):
        preflight.send_debug_once(plan, transport=bounded)
    assert bounded.attempts == 1 and bounded.response_body is None


def test_deadline_is_checked_before_network(plan):
    bounded = guard(plan, lambda req: pytest.fail("Expired request reached transport"))
    bounded.deadline = time.monotonic() - 1
    with pytest.raises(preflight.PreflightError, match="^deadline_exceeded$"):
        preflight.send_debug_once(plan, transport=bounded)
    assert bounded.attempts == 1


def test_sdk_debug_logger_rejects_before_prompt_can_be_logged_or_sent(plan, caplog):
    caplog.set_level(logging.DEBUG, logger="openai._base_client")
    bounded = guard(plan, lambda req: pytest.fail("SDK debug logger allowed a request"))
    with pytest.raises(preflight.PreflightError, match="^sdk_debug_logging_enabled$"):
        preflight.send_debug_once(plan, transport=bounded)
    with pytest.raises(preflight.PreflightError, match="^sdk_debug_logging_enabled$"):
        preflight.prepare_debug_plan(plan._prepared, origin=plan._origin, run_id="b" * 32)
    assert bounded.attempts == 0 and "PRIVATE" not in caplog.text


def test_render_match_native_template_difference_and_unknown_budget_are_separate(plan, monkeypatch):
    meta = snapshot(plan, monkeypatch)
    result = preflight.assess_diagnostic(plan, before=meta, after=meta, raw_response=debug_body(plan))
    assert result["rendered_bytes_match"] is True
    assert result["selected_template_matches_manifest"] is False
    assert result["arithmetic"]["status"] == "unknown" and result["arithmetic"]["input_tokens"] is None
    assert result["admission_status"] == "rejected" and result["effective_budget_status"] == "unknown"
    assert result["generation_success"] is False and result["zero_usage_is_not_input_measurement"] is True
    assert result["eligible_for_model_dispatch"] is False and "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("n,status,remaining", [(5888, "fits", 3), (5891, "fits", 0), (5892, "exceeds", -1)])
def test_request_bound_arithmetic_never_issues_admission(plan, monkeypatch, n, status, remaining):
    meta, raw = snapshot(plan, monkeypatch), debug_body(plan)
    result = preflight.assess_diagnostic(
        plan, before=meta, after=meta, raw_response=raw, supplied_count=count(plan, raw, n)
    )
    assert result["arithmetic"]["status"] == status and result["arithmetic"]["remaining_tokens"] == remaining
    assert result["admission_status"] == "rejected" and result["eligible_for_model_dispatch"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "b" * 32),
        ("plan_sha256", "0" * 64),
        ("rendered_sha256", "0" * 64),
        ("model_digest", "0" * 64),
        ("output_tokens", 2299),
        ("context_tokens", 8193),
        ("margin_tokens", 0),
        ("count_method", "historical_5888"),
        ("input_tokens", True),
        ("input_tokens", 0),
    ],
)
def test_stale_or_rebound_count_is_rejected(plan, monkeypatch, field, value):
    meta, raw = snapshot(plan, monkeypatch), debug_body(plan)
    observation = count(plan, raw, 5888)
    observation[field] = value
    with pytest.raises(preflight.PreflightError):
        preflight.assess_diagnostic(plan, before=meta, after=meta, raw_response=raw, supplied_count=observation)


@pytest.mark.parametrize("field", ["_debug_info", "usage", "choices", "model"])
def test_missing_debug_fields_are_rejected(plan, monkeypatch, field):
    meta, data = snapshot(plan, monkeypatch), preflight.decode(debug_body(plan))
    del data[field]
    with pytest.raises(preflight.PreflightError, match="^debug_response_invalid$"):
        preflight.assess_diagnostic(plan, before=meta, after=meta, raw_response=preflight.canonical(data))


def test_wrong_render_and_generated_content_never_pass(plan, monkeypatch):
    meta = snapshot(plan, monkeypatch)
    raw = debug_body(plan, _debug_info={"rendered_template": "PRIVATE wrong render", "image_count": 0})
    result = preflight.assess_diagnostic(plan, before=meta, after=meta, raw_response=raw)
    assert result["reason"] == "render_mismatch" and result["admission_status"] == "rejected"
    data = preflight.decode(debug_body(plan))
    data["choices"][0]["message"]["content"] = "PRIVATE generated output"
    with pytest.raises(preflight.PreflightError, match="^debug_response_invalid$"):
        preflight.assess_diagnostic(plan, before=meta, after=meta, raw_response=preflight.canonical(data))


def test_metadata_missing_identity_remote_version_and_changes_fail_closed(plan, monkeypatch):
    for version in ({}, {"version": "0.32.14"}):
        with pytest.raises(preflight.PreflightError):
            snapshot(plan, monkeypatch, version=version)
    for show in ({}, {"remote_host": "https://example.invalid"}):
        with pytest.raises(preflight.PreflightError):
            snapshot(plan, monkeypatch, show=show)
    meta = snapshot(plan, monkeypatch)
    changed = copy.deepcopy(meta)
    changed["owner"]["pid"] = 42
    changed["snapshot_sha256"] = preflight.sha(
        preflight.canonical({k: v for k, v in changed.items() if k != "snapshot_sha256"})
    )
    with pytest.raises(preflight.PreflightError, match="^metadata_changed$"):
        preflight.assess_diagnostic(plan, before=meta, after=changed, raw_response=debug_body(plan))


@pytest.mark.parametrize(
    "field,value",
    [
        ("server_selected_template_sha256", "PRIVATE prompt"),
        ("selected_template_matches_manifest", True),
        ("eligible_for_model_dispatch", True),
        ("version", "0.32.14"),
        ("remote_host", "https://example.invalid"),
        ("system_sha256", "0" * 64),
    ],
)
def test_rehashed_forged_snapshot_is_not_a_validated_metadata_record(plan, monkeypatch, field, value):
    meta = snapshot(plan, monkeypatch)
    meta[field] = value
    meta["snapshot_sha256"] = preflight.sha(
        preflight.canonical({k: v for k, v in meta.items() if k != "snapshot_sha256"})
    )
    with pytest.raises(preflight.PreflightError):
        preflight.assess_diagnostic(plan, before=meta, after=meta, raw_response=debug_body(plan))


def test_rehashed_snapshot_missing_identity_field_is_rejected(plan, monkeypatch):
    meta = snapshot(plan, monkeypatch)
    del meta["version"]
    meta["snapshot_sha256"] = preflight.sha(
        preflight.canonical({k: v for k, v in meta.items() if k != "snapshot_sha256"})
    )
    with pytest.raises(preflight.PreflightError, match="^metadata_invalid$"):
        preflight.assess_diagnostic(plan, before=meta, after=meta, raw_response=debug_body(plan))


def test_successful_debug_and_fitting_arithmetic_cannot_open_existing_production_gate(plan, monkeypatch):
    import dotenv

    # src.config explicitly calls load_dotenv at import. Stub that known import
    # side effect, so this regression check never reads workstation secrets.
    with monkeypatch.context() as blocked_dotenv:
        blocked_dotenv.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
        from src.model_runtime import ControlledLocalModelExecutor, PreparedCallError

    meta, raw = snapshot(plan, monkeypatch), debug_body(plan)
    assessment = preflight.assess_diagnostic(
        plan, before=meta, after=meta, raw_response=raw, supplied_count=count(plan, raw, 5888)
    )
    executor = ControlledLocalModelExecutor()
    with pytest.raises(PreparedCallError, match="^prepared_call_not_admitted$"):
        executor.execute(invocation.completion_kwargs_for_offline_inspection(plan._prepared), admission=assessment)
    assert executor.last_request_capture is None and executor.last_call_capture is None
