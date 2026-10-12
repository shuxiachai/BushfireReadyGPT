import copy
import json
import pickle
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import streamlit as st
from openai import OpenAI

from src import model_runtime
from src.model_evidence import json_sha256, text_sha256
from src.model_limits import ModelAllowanceError
from src.model_runtime import GovernedModelClient, ModelServiceError, clean_model_output


def _completion_client(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _stream_chunk(content, finish_reason=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish_reason)]
    )


def _fail_if_rendered(*args, **kwargs):
    raise AssertionError("Ungoverned model output must not be rendered by the model client layer.")


def test_local_streaming_collects_text_without_rendering_raw_tokens(monkeypatch):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return iter([_stream_chunk("unreviewed "), _stream_chunk("model text", "stop")])

    runtime = GovernedModelClient(
        completion_client=_completion_client(create),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
    )
    monkeypatch.setattr(st, "markdown", _fail_if_rendered)

    assert runtime.generate("Generate the report") == "unreviewed model text"
    assert captured["stream"] is True
    assert captured["messages"][-1] == {"role": "user", "content": "Generate the report"}
    assert "tools" not in captured
    assert "tool_choice" not in captured


def test_streaming_protocol_disconnect_is_wrapped_for_the_ui():
    def create(**_kwargs):
        def stream():
            raise httpx.RemoteProtocolError("incomplete chunked read")
            yield

        return stream()

    runtime = GovernedModelClient(
        completion_client=_completion_client(create),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
    )

    with pytest.raises(ModelServiceError, match="stopped the response"):
        runtime.generate("Generate the report")


def test_each_generation_is_stateless_and_tool_free():
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        prompt = kwargs["messages"][-1]["content"]
        return iter([_stream_chunk(f"response for {prompt}", "stop")])

    runtime = GovernedModelClient(
        completion_client=_completion_client(create),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
    )

    assert runtime.generate("first private prompt") == "response for first private prompt"
    assert runtime.generate("second private prompt") == "response for second private prompt"
    assert len(calls) == 2
    assert all(len(call["messages"]) == 2 for call in calls)
    assert "first private prompt" not in str(calls[1]["messages"])
    assert all("tools" not in call and "tool_choice" not in call for call in calls)


def test_remote_completion_uses_same_stateless_boundary_and_cleans_output():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content="Report https://invented.example checklist_complete()\n\n\nFinal section")
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])

    runtime = GovernedModelClient(
        completion_client=_completion_client(create),
        model_name="remote-test-model",
        provider="openai",
        is_local=False,
    )

    result = runtime.generate("Generate the report")

    assert captured["stream"] is False
    assert "https://invented.example" not in result
    assert "checklist_complete" not in result
    assert "\n\n\n" not in result


def test_empty_governed_prompt_is_rejected_before_provider_call():
    runtime = GovernedModelClient(
        completion_client=_completion_client(_fail_if_rendered),
        model_name="test-model",
        is_local=True,
    )

    with pytest.raises(ValueError, match="prompt is required"):
        runtime.generate("  ")


def test_clean_model_output_handles_empty_text():
    assert clean_model_output(None) == ""


def test_empty_and_malformed_stream_chunks_are_ignored():
    chunks = [
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=[SimpleNamespace(delta=None)]),
        _stream_chunk("usable report", "stop"),
    ]
    runtime = GovernedModelClient(
        completion_client=_completion_client(lambda **_kwargs: iter(chunks)),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
    )

    assert runtime.generate("Generate the report") == "usable report"


def test_provider_response_without_usable_text_fails_closed():
    runtime = GovernedModelClient(
        completion_client=_completion_client(lambda **_kwargs: iter([_stream_chunk("", "stop")])),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
    )

    with pytest.raises(ModelServiceError, match="no usable report text"):
        runtime.generate("Generate the report")


def test_stream_has_total_deadline_and_is_closed():
    class ClosableStream:
        def __init__(self):
            self.closed = False
            self.closed_event = threading.Event()

        def __iter__(self):
            yield _stream_chunk("first")
            yield _stream_chunk("late")

        def close(self):
            self.closed = True
            self.closed_event.set()

    stream = ClosableStream()
    times = iter([0.0, 0.5, 1.1])
    runtime = GovernedModelClient(
        completion_client=_completion_client(lambda **_kwargs: stream),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
        timeout_seconds=1,
        clock=lambda: next(times),
    )

    with pytest.raises(ModelServiceError, match="total deadline"):
        runtime.generate("Generate the report")
    assert stream.closed_event.wait(0.1)
    assert stream.closed is True

    class DelayedEofStream(ClosableStream):
        def __iter__(self):
            yield _stream_chunk("apparently complete")
            time.sleep(0.03)

    delayed_stream = DelayedEofStream()
    delayed_runtime = GovernedModelClient(
        completion_client=_completion_client(lambda **_kwargs: delayed_stream),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
        timeout_seconds=0.01,
    )
    with pytest.raises(ModelServiceError, match="total deadline"):
        delayed_runtime.generate("Generate the report")
    assert delayed_stream.closed_event.wait(0.1)
    assert delayed_stream.closed is True


def test_stream_arriving_after_total_deadline_is_closed_before_iteration():
    class LateStream:
        def __init__(self):
            self.iterated = threading.Event()
            self.closed = threading.Event()

        def __iter__(self):
            self.iterated.set()
            yield _stream_chunk("must not be consumed")

        def close(self):
            self.closed.set()

    stream = LateStream()
    create_started = threading.Event()
    release_create = threading.Event()

    def create(**_kwargs):
        create_started.set()
        release_create.wait(0.5)
        return stream

    runtime = GovernedModelClient(
        completion_client=_completion_client(create),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
        timeout_seconds=0.01,
    )

    with pytest.raises(ModelServiceError, match="total deadline"):
        runtime.generate("Generate the report")

    release_create.set()
    assert stream.closed.wait(0.5)
    assert create_started.is_set()
    assert not stream.iterated.is_set()


def test_stream_total_deadline_includes_close_cleanup():
    class SlowCloseStream:
        def __init__(self):
            self.close_started = threading.Event()
            self.close_finished = threading.Event()
            self.release_close = threading.Event()

        def __iter__(self):
            yield _stream_chunk("apparently complete")

        def close(self):
            self.close_started.set()
            self.release_close.wait(0.5)
            self.close_finished.set()

    stream = SlowCloseStream()
    runtime = GovernedModelClient(
        completion_client=_completion_client(lambda **_kwargs: stream),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
        timeout_seconds=0.01,
    )

    with pytest.raises(ModelServiceError, match="total deadline"):
        runtime.generate("Generate the report")

    assert stream.close_started.wait(0.1)
    assert not stream.close_finished.is_set()
    stream.release_close.set()
    assert stream.close_finished.wait(0.1)


def test_stream_cleanup_error_does_not_discard_valid_output(caplog):
    class BrokenCloseStream:
        def __iter__(self):
            yield _stream_chunk("usable report", "stop")

        def close(self):
            raise RuntimeError("cleanup failed")

    runtime = GovernedModelClient(
        completion_client=_completion_client(lambda **_kwargs: BrokenCloseStream()),
        model_name="local-test-model",
        provider="ollama",
        is_local=True,
    )

    with caplog.at_level("DEBUG", logger="src.model_runtime"):
        assert runtime.generate("Generate the report") == "usable report"
    assert "Model stream cleanup failed (RuntimeError)" in caplog.text


def test_model_total_deadline_must_be_positive():
    with pytest.raises(ValueError, match="greater than zero"):
        GovernedModelClient(
            completion_client=_completion_client(_fail_if_rendered),
            model_name="test-model",
            is_local=True,
            timeout_seconds=0,
        )


def _prepared_kwargs(**changes):
    return {
        "model": "PRIVATE local-fixture",
        "messages": [
            {"role": "system", "content": "  PRIVATE exact system\r\n你好 café e\u0301  "},
            {"role": "user", "content": "  PRIVATE exact user\n\nkeep trailing spaces  "},
        ],
        "temperature": 0.25,
        "top_p": 0.8,
        "max_tokens": 117,
        "stream": True,
        "seed": 17,
        **changes,
    }


class _PreparedSDK:
    def __init__(self, create=None):
        self.base_url = "http://127.0.0.1:11434/v1/"
        self._client = SimpleNamespace(follow_redirects=False, trust_env=False)
        self.max_retries = 5
        self.options = []
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create or self.create))

    def with_options(self, **options):
        self.options.append(options)
        self.max_retries = options["max_retries"]
        return self

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return iter([_stream_chunk("  raw response https://private.invalid  ", "stop")])


class _PreparedSlot:
    def __init__(self, *, enabled=False):
        self.limits = SimpleNamespace(enabled=enabled)
        self.consumed = 0
        self.releases = 0
        self.released = threading.Event()

    def consume_call(self):
        self.consumed += 1

    def release(self):
        self.releases += 1
        self.released.set()


@pytest.fixture
def prepared_gate(monkeypatch):
    """Isolated test authority, never a model/budget/runtime attestation."""
    take, issue = model_runtime._new_prepared_call_gate()
    monkeypatch.setattr(model_runtime, "_take_prepared_call_admission", take)
    return issue


@pytest.fixture
def prepared_slot(monkeypatch):
    slot = _PreparedSlot()
    monkeypatch.setattr(model_runtime, "acquire_model_slot", lambda: slot)
    return slot


def _deny_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Denied calls must not acquire, configure, start, capture or transmit.")

    monkeypatch.setattr(model_runtime, "acquire_model_slot", forbidden)
    monkeypatch.setattr(model_runtime.threading, "Thread", forbidden)
    monkeypatch.setattr(model_runtime, "bind_submitted_messages", forbidden)
    monkeypatch.setattr(model_runtime, "client", SimpleNamespace(with_options=forbidden))
    return forbidden


@pytest.mark.parametrize(
    "admission", [None, True, False, {}, {"authorized": True}, {"eligible_for_model_dispatch": True}]
)
def test_prepared_default_denial_precedes_all_side_effects(monkeypatch, admission):
    class PrivateTrap:
        def __getattribute__(self, name):
            raise AssertionError("Must not inspect a denied client or plan.")

        def __str__(self):
            raise AssertionError("Must not coerce a denied plan.")

    _deny_side_effects(monkeypatch)
    executor = model_runtime.ControlledLocalModelExecutor()
    with pytest.raises(model_runtime.PreparedCallError, match="^prepared_call_not_admitted$") as caught:
        executor.execute(PrivateTrap(), admission=admission, completion_client=PrivateTrap())
    assert executor.last_request_capture is None
    assert "PRIVATE" not in repr(caught.value)


def test_prepared_production_gate_has_no_issuer_and_rejects_disconnected_tokens(monkeypatch):
    kwargs, sdk = _prepared_kwargs(), _PreparedSDK()
    _, isolated_issue = model_runtime._new_prepared_call_gate()
    isolated = isolated_issue(kwargs, sdk)
    forged = model_runtime._PreparedCallAdmission()
    _deny_side_effects(monkeypatch)
    executor = model_runtime.ControlledLocalModelExecutor()
    for admission in (isolated, forged):
        with pytest.raises(model_runtime.PreparedCallError, match="^prepared_call_not_admitted$"):
            executor.execute(kwargs, admission=admission, completion_client=sdk)
    assert sdk.options == [] and sdk.calls == []
    assert executor.last_request_capture is None


def test_prepared_capability_is_nonserializable_and_content_free(prepared_gate):
    admission = prepared_gate(_prepared_kwargs(), _PreparedSDK())
    assert repr(admission) == "<prepared-call admission>"
    for operation in (pickle.dumps, copy.copy, copy.deepcopy, json.dumps):
        with pytest.raises(TypeError):
            operation(admission)


@pytest.mark.parametrize("enabled", [False, True])
def test_prepared_exact_submission_request_budget_and_capture(prepared_gate, prepared_slot, monkeypatch, enabled):
    kwargs, sdk = _prepared_kwargs(), _PreparedSDK()
    expected = copy.deepcopy(kwargs)
    prepared_slot.limits.enabled = enabled
    monkeypatch.setattr(model_runtime, "MODEL_MAX_TOKENS", 9999)
    admission = prepared_gate(kwargs, sdk)
    executor = model_runtime.ControlledLocalModelExecutor()
    assert (
        executor.execute(kwargs, admission=admission, completion_client=sdk)
        == "  raw response https://private.invalid  "
    )
    assert sdk.calls == [expected]
    assert sdk.options == [{"max_retries": 0}]
    assert prepared_slot.consumed == prepared_slot.releases == 1
    assert executor.last_request_capture == {
        "schema": "sdk-message-binding-v1",
        "system_prompt_sha256": text_sha256(expected["messages"][0]["content"]),
        "user_prompt_sha256": text_sha256(expected["messages"][1]["content"]),
        "messages_sha256": json_sha256(expected["messages"]),
        "response_sha256": text_sha256("  raw response https://private.invalid  "),
    }
    assert executor.last_call_capture == {
        "schema": "controlled-local-sdk-call-binding-v1",
        "kwargs_sha256": json_sha256(expected),
        "response_sha256": text_sha256("  raw response https://private.invalid  "),
    }
    assert "PRIVATE" not in repr(executor.last_request_capture)
    _deny_side_effects(monkeypatch)
    with pytest.raises(model_runtime.PreparedCallError, match="^prepared_call_not_admitted$"):
        executor.execute(kwargs, admission=admission, completion_client=sdk)
    assert executor.last_request_capture is None
    assert executor.last_call_capture is None


@pytest.mark.parametrize("change", ["system", "user", "model", "max_tokens", "client", "endpoint", "http_client"])
def test_prepared_stale_capability_rejects_before_side_effects(prepared_gate, monkeypatch, change):
    kwargs, sdk = _prepared_kwargs(), _PreparedSDK()
    admission = prepared_gate(kwargs, sdk)
    if change in {"system", "user"}:
        kwargs["messages"][int(change == "user")]["content"] += " "
    elif change == "model":
        kwargs["model"] += "-changed"
    elif change == "max_tokens":
        kwargs["max_tokens"] += 1
    elif change == "client":
        sdk = _PreparedSDK()
    elif change == "endpoint":
        sdk.base_url = "http://127.0.0.1:2222/v1/"
    else:
        sdk._client = SimpleNamespace(follow_redirects=False, trust_env=False)
    _deny_side_effects(monkeypatch)
    executor = model_runtime.ControlledLocalModelExecutor()
    with pytest.raises(model_runtime.PreparedCallError, match="^prepared_call_not_admitted$"):
        executor.execute(kwargs, admission=admission, completion_client=sdk)
    assert executor.last_request_capture is None
    assert sdk.options == [] and sdk.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"model": " PRIVATE"},
        {"model": "界" * 86},
        {"model": "PRIVATE\ud800"},
        {"temperature": True},
        {"temperature": 1},
        {"temperature": float("nan")},
        {"temperature": float("inf")},
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"top_p": 0.9},
        {"top_p": True},
        {"stream": False},
        {"stream": 1},
        {"seed": True},
        {"seed": -1},
        {"seed": 2**31},
        {"max_tokens": True},
        {"max_tokens": 1.0},
        {"max_tokens": 0},
        {"max_tokens": 2**31},
        {"messages": []},
        {"messages": [{"role": "system", "content": "PRIVATE"}] * 2},
        {"messages": [{"role": "system", "content": ""}, {"role": "user", "content": "PRIVATE"}]},
        {"messages": [{"role": "system", "content": "PRIVATE"}, {"role": "user", "content": "\ud800"}]},
        {"messages": [{"role": "system", "content": "PRIVATE"}, {"role": "user", "content": "界" * 100_000}]},
        {"tools": []},
        {"extra_body": {}},
        {"metadata": {"authorized": True}},
    ],
)
def test_prepared_malformed_admitted_plan_fails_privately_before_side_effects(prepared_gate, monkeypatch, changes):
    kwargs, sdk = _prepared_kwargs(), _PreparedSDK()
    admission = prepared_gate(kwargs, sdk)
    kwargs.update(changes)
    _deny_side_effects(monkeypatch)
    executor = model_runtime.ControlledLocalModelExecutor()
    with pytest.raises(model_runtime.PreparedCallError, match="^prepared_call_plan_invalid$") as caught:
        executor.execute(kwargs, admission=admission, completion_client=sdk)
    assert "PRIVATE" not in str(caught.value) + repr(caught.value)
    assert caught.value.__suppress_context__
    assert executor.last_request_capture is None
    assert sdk.options == [] and sdk.calls == []


def test_prepared_snapshot_rejects_subclasses_missing_fields_and_cycles():
    class TrapDict(dict):
        def copy(self):
            raise AssertionError("No arbitrary copying hooks.")

    cyclic = _prepared_kwargs()
    cyclic["messages"] = [cyclic, cyclic]
    values = [None, "PRIVATE", TrapDict(_prepared_kwargs()), cyclic]
    for name in _prepared_kwargs():
        value = _prepared_kwargs()
        del value[name]
        values.append(value)
    for value in values:
        with pytest.raises(model_runtime.PreparedCallError, match="^prepared_call_plan_invalid$"):
            model_runtime._snapshot_prepared_call(value)


@pytest.mark.parametrize(
    "change", ["remote", "redirects", "trust_env", "missing_trust_env", "clone_endpoint", "clone_transport", "retries"]
)
def test_prepared_client_cannot_switch_destination_or_retain_retries(prepared_gate, prepared_slot, change):
    kwargs, sdk = _prepared_kwargs(), _PreparedSDK()
    admission = prepared_gate(kwargs, sdk)
    if change == "remote":
        sdk.base_url = "https://external.invalid/v1/"
    elif change == "redirects":
        sdk._client.follow_redirects = True
    elif change == "trust_env":
        sdk._client.trust_env = True
    elif change == "missing_trust_env":
        del sdk._client.trust_env
    else:
        configure = sdk.with_options

        def switched(**options):
            clone = configure(**options)
            if change == "clone_endpoint":
                clone.base_url = "http://127.0.0.1:2222/v1/"
            elif change == "clone_transport":
                clone._client = SimpleNamespace(follow_redirects=False, trust_env=False)
            else:
                clone.max_retries = 1
            return clone

        sdk.with_options = switched
    executor = model_runtime.ControlledLocalModelExecutor()
    with pytest.raises(model_runtime.PreparedCallError, match="^prepared_call_client_invalid$"):
        executor.execute(kwargs, admission=admission, completion_client=sdk)
    assert sdk.calls == [] and prepared_slot.consumed == 0
    assert prepared_slot.releases == (0 if change in {"remote", "redirects", "trust_env", "missing_trust_env"} else 1)
    assert executor.last_request_capture is None


def test_prepared_snapshot_is_detached_before_sdk_configuration(prepared_gate, prepared_slot):
    kwargs, sdk = _prepared_kwargs(), _PreparedSDK()
    expected = copy.deepcopy(kwargs)
    admission = prepared_gate(kwargs, sdk)
    configure = sdk.with_options

    def mutate_caller(**options):
        kwargs["messages"][0]["content"] = "PRIVATE mutated after validation"
        kwargs["max_tokens"] = 999
        return configure(**options)

    sdk.with_options = mutate_caller
    executor = model_runtime.ControlledLocalModelExecutor()
    executor.execute(kwargs, admission=admission, completion_client=sdk)
    assert sdk.calls == [expected]
    assert executor.last_call_capture["kwargs_sha256"] == json_sha256(expected)


@pytest.mark.parametrize("phase", ["configure", "create", "iterate", "quota"])
def test_prepared_failures_release_slot_and_do_not_publish_capture(prepared_gate, prepared_slot, phase):
    kwargs, sdk = _prepared_kwargs(), _PreparedSDK()
    admission = prepared_gate(kwargs, sdk)

    def fail(*args, **kwargs):
        if phase == "quota":
            raise ModelAllowanceError("PRIVATE allowance detail")
        raise RuntimeError("PRIVATE request or response detail")

    if phase == "configure":
        sdk.with_options = fail
    elif phase == "quota":
        prepared_slot.consume_call = fail
    elif phase == "create":
        sdk.chat.completions.create = fail
    else:

        def broken_stream():
            yield _stream_chunk("PRIVATE partial response")
            fail()

        sdk.chat.completions.create = lambda **kwargs: broken_stream()
    executor = model_runtime.ControlledLocalModelExecutor()
    with pytest.raises(ModelServiceError) as caught:
        executor.execute(kwargs, admission=admission, completion_client=sdk)
    assert prepared_slot.releases == 1
    assert prepared_slot.consumed == (0 if phase in {"configure", "quota"} else 1)
    assert "PRIVATE" not in str(caught.value) + repr(caught.value)
    assert executor.last_request_capture is None


@pytest.mark.parametrize("finish_reason", [None, "length", "tool_calls", "content_filter"])
def test_prepared_requires_normal_stop_and_closes_response(prepared_gate, prepared_slot, finish_reason):
    closed = threading.Event()

    class Stream:
        def __iter__(self):
            yield _stream_chunk("PRIVATE partial", finish_reason)

        def close(self):
            closed.set()

    kwargs, sdk = _prepared_kwargs(), _PreparedSDK(lambda **kwargs: Stream())
    admission = prepared_gate(kwargs, sdk)
    executor = model_runtime.ControlledLocalModelExecutor()
    with pytest.raises(ModelServiceError):
        executor.execute(kwargs, admission=admission, completion_client=sdk)
    assert closed.is_set() and prepared_slot.releases == 1
    assert executor.last_request_capture is None


def test_prepared_sdk_retries_are_disabled_even_without_allowance(prepared_gate, prepared_slot):
    attempts = []

    def handle(request):
        attempts.append(json.loads(request.content))
        return httpx.Response(500, json={"error": {"message": "PRIVATE SDK failure"}})

    http_client = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False, trust_env=False)
    sdk = OpenAI(
        api_key="offline-fixture", base_url="http://127.0.0.1:11434/v1", max_retries=4, http_client=http_client
    )
    kwargs = _prepared_kwargs()
    admission = prepared_gate(kwargs, sdk)
    executor = model_runtime.ControlledLocalModelExecutor()
    try:
        with pytest.raises(ModelServiceError, match="controlled local model request failed"):
            executor.execute(kwargs, admission=admission, completion_client=sdk)
        assert attempts == [kwargs]
        assert prepared_slot.consumed == prepared_slot.releases == 1
        assert executor.last_request_capture is None
    finally:
        sdk.close()


def test_prepared_deadline_keeps_slot_until_late_stream_is_closed(prepared_gate, prepared_slot):
    started, release, closed, iterated = (threading.Event() for _ in range(4))

    class LateStream:
        def __iter__(self):
            iterated.set()
            yield _stream_chunk("PRIVATE late response", "stop")

        def close(self):
            closed.set()

    def create(**kwargs):
        started.set()
        assert release.wait(3)
        return LateStream()

    kwargs, sdk = _prepared_kwargs(), _PreparedSDK(create)
    admission = prepared_gate(kwargs, sdk)
    executor = model_runtime.ControlledLocalModelExecutor(timeout_seconds=0.05)
    try:
        with pytest.raises(ModelServiceError, match="total deadline"):
            executor.execute(kwargs, admission=admission, completion_client=sdk)
        assert started.is_set()
        assert prepared_slot.consumed == 1 and prepared_slot.releases == 0
        assert executor.last_request_capture is None
    finally:
        release.set()
        assert prepared_slot.released.wait(3)
    assert closed.is_set() and not iterated.is_set()
    assert prepared_slot.releases == 1


def test_prepared_deadline_during_configuration_does_not_submit(prepared_gate, prepared_slot):
    started, release = threading.Event(), threading.Event()
    kwargs, sdk = _prepared_kwargs(), _PreparedSDK()
    admission = prepared_gate(kwargs, sdk)
    configure = sdk.with_options

    def blocked_configuration(**options):
        started.set()
        assert release.wait(3)
        return configure(**options)

    sdk.with_options = blocked_configuration
    executor = model_runtime.ControlledLocalModelExecutor(timeout_seconds=0.05)
    try:
        with pytest.raises(ModelServiceError, match="total deadline"):
            executor.execute(kwargs, admission=admission, completion_client=sdk)
        assert started.is_set() and prepared_slot.releases == 0
    finally:
        release.set()
        assert prepared_slot.released.wait(3)
    assert sdk.calls == [] and prepared_slot.consumed == 0
    assert prepared_slot.releases == 1


def test_prepared_thread_start_failure_releases_unowned_slot(prepared_gate, prepared_slot, monkeypatch):
    kwargs, sdk = _prepared_kwargs(), _PreparedSDK()
    admission = prepared_gate(kwargs, sdk)

    def fail_start(self):
        raise RuntimeError("thread unavailable")

    monkeypatch.setattr(model_runtime.threading.Thread, "start", fail_start)
    executor = model_runtime.ControlledLocalModelExecutor()
    with pytest.raises(RuntimeError, match="thread unavailable"):
        executor.execute(kwargs, admission=admission, completion_client=sdk)
    assert prepared_slot.releases == 1 and prepared_slot.consumed == 0
    assert sdk.options == [] and sdk.calls == []
    assert executor.last_request_capture is None
