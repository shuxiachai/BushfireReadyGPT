import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

from src import report_generation_quality as quality
from src.model_response import ModelResponseError, ModelServiceError, validate_narrative_ending
from src.model_runtime import GovernedModelClient
from src.runtime_trace import RuntimeTrace


def _chunk(content=None, reason=None, **payload):
    return SimpleNamespace(
        choices=[SimpleNamespace(index=0, finish_reason=reason, delta=SimpleNamespace(content=content, **payload))]
    )


def _completion(content="Complete report.", reason="stop", **payload):
    return SimpleNamespace(
        choices=[SimpleNamespace(index=0, finish_reason=reason, message=SimpleNamespace(content=content, **payload))]
    )


class _Client:
    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.options = []
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **options):
        self.options.append(options)
        return self

    def create(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        return self.result() if callable(self.result) else self.result


@pytest.fixture(autouse=True)
def isolated_limits(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("BUSHFIRE_MODEL_MAX_CONCURRENT", "1")
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "100")


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls", "function_call", None, "other", ""])
def test_non_stop_responses_are_never_accepted(stream, reason, caplog):
    private = "PRIVATE SYNTHETIC MODEL BODY"
    result = iter([_chunk(private), _chunk(reason=reason)]) if stream else _completion(private, reason)
    provider = _Client(result)
    runtime = GovernedModelClient(completion_client=provider, is_local=stream)
    with pytest.raises(ModelResponseError) as captured:
        runtime.generate("PRIVATE SYNTHETIC PROMPT")
    expected = "missing" if reason is None else "invalid" if reason in {"other", ""} else reason
    assert captured.value.reason == expected
    assert provider.calls == 1
    assert private not in str(captured.value)
    assert private not in caplog.text
    assert "PRIVATE SYNTHETIC PROMPT" not in caplog.text


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("field", ["tool_calls", "function_call", "refusal"])
def test_stop_does_not_hide_disallowed_tool_or_refusal_payload(stream, field):
    payload = {field: "PRIVATE PAYLOAD"}
    result = iter([_chunk("text", "stop", **payload)]) if stream else _completion(**payload)
    runtime = GovernedModelClient(completion_client=_Client(result), is_local=stream)
    with pytest.raises(ModelResponseError) as captured:
        runtime.generate("prompt")
    assert captured.value.reason == ("content_filter" if field == "refusal" else field)


@pytest.mark.parametrize(
    "chunks",
    [
        [],
        [_chunk("unfinished")],
        [_chunk("complete", "stop"), _chunk("after stop")],
        [_chunk("complete", "stop"), _chunk(reason="stop")],
        [SimpleNamespace(choices=[SimpleNamespace(index=1)])],
        [SimpleNamespace(choices=[SimpleNamespace(), SimpleNamespace()])],
        [_chunk(["not text"], "stop")],
    ],
)
def test_malformed_stream_is_rejected(chunks):
    runtime = GovernedModelClient(completion_client=_Client(iter(chunks)), is_local=True)
    with pytest.raises(ModelResponseError):
        runtime.generate("prompt")


def test_usage_only_trailer_after_stop_is_accepted_and_closed():
    class Stream:
        closed = False

        def __iter__(self):
            yield _chunk("Complete ")
            yield _chunk("report.", "stop")
            yield SimpleNamespace(choices=[], usage=SimpleNamespace(total_tokens=10))

        def close(self):
            self.closed = True

    stream = Stream()
    runtime = GovernedModelClient(completion_client=_Client(stream), is_local=True)
    assert runtime.generate("prompt") == "Complete report."
    assert stream.closed


def test_protocol_disconnect_after_stop_still_rejects_response():
    def broken():
        yield _chunk("Complete report.", "stop")
        raise httpx.RemoteProtocolError("PRIVATE TRANSPORT DETAIL")

    runtime = GovernedModelClient(completion_client=_Client(broken()), is_local=True, provider="ollama")
    with pytest.raises(ModelServiceError, match="stopped the response"):
        runtime.generate("prompt")


def test_finish_reason_trace_is_content_free_and_preserves_unknown_as_invalid(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path / "traces"))
    runtime = GovernedModelClient(
        completion_client=_Client(_completion("PRIVATE BODY", "PRIVATE REASON")), is_local=False
    )
    with RuntimeTrace("report.generate") as trace:
        with pytest.raises(ModelResponseError):
            runtime.generate("PRIVATE PROMPT")
    payload = json.loads((tmp_path / "traces" / f"trace_{trace.trace_id}.json").read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert "PRIVATE" not in serialized
    assert payload["stages"][0]["metrics"]["model_finish_reason"] == "invalid"
    assert payload["stages"][0]["error_code"] == "model_response_invalid"


@pytest.mark.parametrize("stream", [False, True])
def test_unexpected_provider_failure_is_content_free_and_not_retryable(stream):
    def broken():
        if stream:

            def chunks():
                yield _chunk("PRIVATE BODY", "stop")
                raise ValueError("PRIVATE DIAGNOSTIC")

            return chunks()
        raise ValueError("PRIVATE DIAGNOSTIC")

    runtime = GovernedModelClient(completion_client=_Client(broken), is_local=stream)
    with pytest.raises(ModelResponseError) as captured:
        runtime.generate("PRIVATE PROMPT")
    assert captured.value.reason == "invalid"
    assert not captured.value.retryable
    assert "PRIVATE" not in str(captured.value)


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(choices=[]),
        SimpleNamespace(choices=None),
        SimpleNamespace(choices=[SimpleNamespace(), SimpleNamespace()]),
        SimpleNamespace(choices=[SimpleNamespace(index=1, finish_reason="stop")]),
        _completion(["malformed content"]),
    ],
)
def test_malformed_non_stream_response_is_not_accepted(response):
    runtime = GovernedModelClient(completion_client=_Client(response), is_local=False)
    with pytest.raises(ModelResponseError):
        runtime.generate("prompt")


def test_truncation_cannot_make_a_tool_response_retryable():
    runtime = GovernedModelClient(
        completion_client=_Client(_completion(reason="length", tool_calls=["private call"])), is_local=False
    )
    with pytest.raises(ModelResponseError) as captured:
        runtime.generate("prompt")
    assert captured.value.reason == "tool_calls"
    assert not captured.value.retryable


@pytest.mark.parametrize(
    "ending", ["pending current", "pending current\n\n## Evidence Tables\nA full appendix.", "pending current\n---"]
)
def test_actual_cairns_bad_case_shape_cannot_hide_behind_appendices(ending):
    narrative = "## 15. Safety Disclaimer\nEvery proposed place is an unverified candidate " + ending
    with pytest.raises(ModelResponseError, match="Disclaimer appears unfinished"):
        validate_narrative_ending(narrative)


@pytest.mark.parametrize("ending", ["Full sentence.", "**Full sentence.**", "“Full sentence.”", "- Full sentence."])
def test_normal_markdown_sentence_ending_is_accepted(ending):
    validate_narrative_ending("## 15. Safety Disclaimer\n" + ending)


def _analysis():
    return {"data": {"sources": [{"id": "first", "name": "First source"}, {"id": "second", "name": "Second source"}]}}


def _stub_quality(monkeypatch):
    monkeypatch.setattr(quality, "_normalise_generation_response", lambda text, _analysis: text)
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: {"approval_gate": {"passed": True}})


@pytest.mark.parametrize("reason", ["content_filter", "tool_calls", "function_call", "missing", "invalid"])
def test_unrecoverable_response_is_not_retried(monkeypatch, reason):
    _stub_quality(monkeypatch)
    calls = []

    def generate(*args):
        calls.append(args)
        raise ModelResponseError(reason)

    with pytest.raises(ModelResponseError):
        quality.generate_narrative_with_repairs("prompt", _analysis(), generate)
    assert len(calls) == 1


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", ["length", "incomplete_narrative"])
def test_recoverable_responses_use_shared_three_call_ceiling_and_no_partial_text(
    monkeypatch, tmp_path, failure, stream
):
    _stub_quality(monkeypatch)
    reason = "length" if failure == "length" else "stop"
    partial = "## 15. Safety Disclaimer\nPRIVATE partial ending"
    provider = _Client(lambda: iter([_chunk(partial, reason)]) if stream else _completion(partial, reason))
    runtime = GovernedModelClient(completion_client=provider, is_local=stream)
    with pytest.raises(ModelResponseError):
        quality.generate_narrative_with_repairs("Original safe prompt", _analysis(), lambda p, *_: runtime.generate(p))
    assert provider.calls == 3
    assert all(options == {"max_retries": 0} for options in provider.options)
    assert len({request["max_tokens"] for request in provider.requests}) == 1
    assert "Rewrite the entire report" in provider.requests[1]["messages"][-1]["content"]
    assert all("PRIVATE" not in request["messages"][-1]["content"] for request in provider.requests)
    with closing(sqlite3.connect(tmp_path / "model-usage.sqlite3")) as connection:
        assert connection.execute("SELECT SUM(calls) FROM daily_calls").fetchone()[0] == 3


def test_daily_quota_blocks_rewrite_without_extra_provider_call(monkeypatch, tmp_path):
    _stub_quality(monkeypatch)
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "1")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"index": 0, "finish_reason": "length", "message": {"content": "partial"}}]},
        )

    with OpenAI(api_key="test-only", http_client=httpx.Client(transport=httpx.MockTransport(handle))) as sdk:
        runtime = GovernedModelClient(completion_client=sdk, is_local=False, provider="deepseek")
        with pytest.raises(ModelServiceError, match="daily model-call allowance"):
            quality.generate_narrative_with_repairs("prompt", _analysis(), lambda p, *_: runtime.generate(p))
    assert len(requests) == 1
    with closing(sqlite3.connect(tmp_path / "model-usage.sqlite3")) as connection:
        assert connection.execute("SELECT SUM(calls) FROM daily_calls").fetchone()[0] == 1


def test_length_then_structural_failure_share_one_budget_and_can_recover(monkeypatch):
    _stub_quality(monkeypatch)
    assessments = iter([{"approval_gate": {"passed": False}}, {"approval_gate": {"passed": True}}])
    monkeypatch.setattr(quality, "assess_generated_narrative", lambda *_: next(assessments))
    monkeypatch.setattr(quality, "build_report_repair_prompt", lambda *_args, **_kwargs: "structure repair")
    calls = []

    def generate(prompt, attempt, repair):
        calls.append((prompt, attempt, repair))
        if attempt == 1:
            raise ModelResponseError("length")
        return "## 15. Safety Disclaimer\nA completed safety sentence."

    _, result, attempts = quality.generate_narrative_with_repairs("prompt", _analysis(), generate)
    assert attempts == 3
    assert result["approval_gate"]["passed"]
    assert [call[2] for call in calls] == [False, True, True]
    assert calls[-1][0] == "structure repair"


def test_obvious_incomplete_sentence_is_rewritten_not_silently_patched(monkeypatch):
    _stub_quality(monkeypatch)
    calls = []
    partial = "## 15. Safety Disclaimer\nEvery candidate remains pending current"
    complete = "## 15. Safety Disclaimer\nAll proposed places need current verification and human approval."

    def generate(prompt, attempt, repair):
        calls.append((prompt, attempt, repair))
        return partial if attempt == 1 else complete

    result, _, attempts = quality.generate_narrative_with_repairs("prompt", _analysis(), generate)
    assert attempts == 2
    assert result == complete
    assert "pending current" not in calls[1][0]
    assert "Rewrite the entire report" in calls[1][0]


def test_disabled_repair_has_no_hidden_protocol_retry(monkeypatch):
    _stub_quality(monkeypatch)
    provider = _Client(_completion(reason="length"))
    runtime = GovernedModelClient(completion_client=provider, is_local=False)
    with pytest.raises(ModelResponseError):
        quality.generate_narrative_with_repairs(
            "prompt", _analysis(), lambda p, *_: runtime.generate(p), max_repair_attempts=0
        )
    assert provider.calls == 1


def test_new_response_admission_does_not_relabel_historical_quality_policy():
    assert quality.CURRENT_POLICY == "governed-report-v6"
    assert quality.QUALITY_POLICY_FINGERPRINT == "b3d65d227d308192329af0e11624e15db0061ec26c62e116723b5e7a4e364745"


def test_successful_finish_reason_is_recorded_without_content(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path / "traces"))
    runtime = GovernedModelClient(completion_client=_Client(_completion("PRIVATE BODY")), is_local=False)
    with RuntimeTrace("report.revise") as trace:
        assert runtime.generate("PRIVATE PROMPT") == "PRIVATE BODY"
    payload = json.loads((tmp_path / "traces" / f"trace_{trace.trace_id}.json").read_text(encoding="utf-8"))
    assert "PRIVATE" not in json.dumps(payload)
    assert payload["stages"][0]["metrics"]["model_finish_reason"] == "stop"
    assert payload["stages"][0]["status"] == "success"
