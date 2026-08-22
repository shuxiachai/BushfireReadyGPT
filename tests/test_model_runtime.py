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
