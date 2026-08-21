from types import SimpleNamespace

import httpx
import pytest
import streamlit as st

from src.assistants import assistant as assistant_module
from src.assistants.assistant import (
    THREAD_LAST_USED,
    THREAD_MESSAGES,
    Assistant,
    ModelServiceError,
    prune_thread_messages,
    replace_thread_messages,
)


class BoundaryAssistant(Assistant):
    def initialize_instructions(self):
        return "Test system instructions"


def _fail_if_rendered(*args, **kwargs):
    raise AssertionError("Ungoverned model output must not be rendered by the model client layer.")


def test_streaming_completion_collects_text_without_rendering_raw_tokens(monkeypatch):
    instance = object.__new__(BoundaryAssistant)
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="unreviewed "))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="model text"))]),
    ]
    instance._create_completion = lambda messages, stream=False, allow_tools=True: iter(chunks)
    monkeypatch.setattr(st, "empty", _fail_if_rendered)

    assert instance._stream_text_completion([{"role": "user", "content": "prompt"}]) == ("unreviewed model text")


def test_streaming_protocol_disconnect_is_wrapped_for_the_ui():
    instance = object.__new__(BoundaryAssistant)

    def disconnected(*_args, **_kwargs):
        def stream():
            raise httpx.RemoteProtocolError("incomplete chunked read")
            yield

        return stream()

    instance._create_completion = disconnected

    with pytest.raises(ModelServiceError, match="stopped the response"):
        instance._stream_text_completion([{"role": "user", "content": "prompt"}])


def test_thread_cache_prunes_expired_entries_and_bounds_message_count(monkeypatch):
    THREAD_MESSAGES.clear()
    THREAD_LAST_USED.clear()
    monkeypatch.setattr(assistant_module, "THREAD_TTL_SECONDS", 10)
    monkeypatch.setattr(assistant_module, "THREAD_MAX_COUNT", 2)
    monkeypatch.setattr(assistant_module, "THREAD_MAX_MESSAGES", 2)

    THREAD_MESSAGES.update({"expired": [], "older": [], "newer": []})
    THREAD_LAST_USED.update({"expired": 80.0, "older": 95.0, "newer": 99.0})
    prune_thread_messages(now=100.0)
    replace_thread_messages(
        "newer",
        [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
        ],
    )

    assert "expired" not in THREAD_MESSAGES
    assert len(THREAD_MESSAGES) <= 2
    assert [item["content"] for item in THREAD_MESSAGES["newer"]] == ["two", "three"]

    THREAD_MESSAGES.clear()
    THREAD_LAST_USED.clear()


def test_non_streaming_completion_does_not_render_before_workflow_governance(monkeypatch):
    thread_id = "test-no-raw-render"
    THREAD_MESSAGES.pop(thread_id, None)
    instance = object.__new__(BoundaryAssistant)
    instance.assistant = SimpleNamespace(instructions="System", tools=[])
    instance.function_dict = {}
    instance._create_completion = lambda messages, stream=False, allow_tools=True: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="unreviewed model text"))]
    )
    monkeypatch.setattr(assistant_module, "IS_LOCAL_LLM", False)
    monkeypatch.setattr(st, "markdown", _fail_if_rendered)

    try:
        text, run_id, tool_outputs = instance.get_assistant_response("prompt", thread_id)
    finally:
        THREAD_MESSAGES.pop(thread_id, None)

    assert text == "unreviewed model text"
    assert run_id is None
    assert tool_outputs == []


def test_governed_completion_does_not_expose_or_execute_legacy_tools(monkeypatch):
    thread_id = "test-governed-no-tools"
    THREAD_MESSAGES.pop(thread_id, None)
    instance = object.__new__(BoundaryAssistant)
    instance.assistant = SimpleNamespace(instructions="System", tools=[{"type": "function"}])
    instance.function_dict = {"checklist_update": _fail_if_rendered}
    captured = {}
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="checklist_update", arguments='{"checklist":"private"}'),
    )

    def completion(messages, stream=False, allow_tools=True):
        captured["allow_tools"] = allow_tools
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="governed text",
                        tool_calls=[tool_call],
                    )
                )
            ]
        )

    instance._create_completion = completion
    monkeypatch.setattr(assistant_module, "IS_LOCAL_LLM", False)

    try:
        text, _run_id, tool_outputs = instance.get_assistant_response(
            "report prompt",
            thread_id,
            allow_tools=False,
        )
    finally:
        THREAD_MESSAGES.pop(thread_id, None)

    assert captured["allow_tools"] is False
    assert text == "governed text"
    assert tool_outputs == []
