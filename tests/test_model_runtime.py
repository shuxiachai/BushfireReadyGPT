import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import streamlit as st

from src.model_runtime import GovernedModelClient, ModelServiceError, clean_model_output


def _completion_client(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _stream_chunk(content):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


def _fail_if_rendered(*args, **kwargs):
    raise AssertionError("Ungoverned model output must not be rendered by the model client layer.")


def test_local_streaming_collects_text_without_rendering_raw_tokens(monkeypatch):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return iter([_stream_chunk("unreviewed "), _stream_chunk("model text")])

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
        return iter([_stream_chunk(f"response for {prompt}")])

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
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

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
        _stream_chunk("usable report"),
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
        completion_client=_completion_client(lambda **_kwargs: iter([SimpleNamespace(choices=[])])),
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
            yield _stream_chunk("usable report")

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
