import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import assess_model_context_budget as cli
from src.model_context_budget import VERIFICATION_BOUNDARY, assess_model_context_budget
from src.model_evidence import json_sha256, text_sha256

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _request():
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "private input"}]
    model = "a" * 64
    template = "b" * 64
    return {
        "messages": messages,
        "model_digest": model,
        "template_sha256": template,
        "context_tokens": 8192,
        "requested_output_tokens": 2300,
        "exact_count": {
            "scope": "full_rendered_prompt",
            "model_digest": model,
            "template_sha256": template,
            "messages_sha256": json_sha256(messages),
            "context_tokens": 8192,
            "rendered_prompt_sha256": "c" * 64,
            "tokenizer_identity": "llama.cpp 1234 / tokenizer digest",
            "input_tokens": 6917,
            "count_method": "llama_cpp_tokenize",
        },
    }


def test_exact_count_exceeds_and_hides_raw_prompt():
    request = _request()
    result = assess_model_context_budget(**request)
    assert result["status"] == "exceeds"
    assert result["headroom"] == -1026 and result["reserved_total"] == 9218
    assert result["verification_boundary"] == VERIFICATION_BOUNDARY
    assert "private input" not in json.dumps(result)
    assert result["tokenizer_identity_sha256"] == text_sha256(request["exact_count"]["tokenizer_identity"])
    assert "tokenizer_identity" not in result
    assert request["exact_count"]["tokenizer_identity"] not in json.dumps(result)


def test_exact_boundary_fits():
    request = _request()
    request["exact_count"]["input_tokens"] = 5891
    result = assess_model_context_budget(**request)
    assert result["status"] == "fits" and result["headroom"] == 0


def _assert_unknown(result, reason):
    assert result["status"] == "unknown" and result["reason"] == reason
    assert result["input_tokens"] is None
    assert result["reserved_total"] is None and result["headroom"] is None


@pytest.mark.parametrize("omitted", [False, True])
def test_missing_count_never_fits(omitted):
    request = _request()
    if omitted:
        del request["exact_count"]
    else:
        request["exact_count"] = None
    _assert_unknown(assess_model_context_budget(**request), "missing_exact_count_binding")


@pytest.mark.parametrize("field", list(_request()["exact_count"]))
def test_any_missing_required_exact_field_is_unknown(field):
    request = _request()
    del request["exact_count"][field]
    _assert_unknown(assess_model_context_budget(**request), "missing_exact_count_binding")


@pytest.mark.parametrize("field", ["model_digest", "template_sha256", "context_tokens"])
def test_missing_request_identity_is_unknown(field):
    request = _request()
    del request[field]
    _assert_unknown(assess_model_context_budget(**request), "missing_context_binding")


@pytest.mark.parametrize(
    "key, value",
    [
        ("messages_sha256", "d" * 64),
        ("model_digest", "d" * 64),
        ("template_sha256", "d" * 64),
        ("context_tokens", 8193),
    ],
)
def test_changed_provenance_binding_is_unknown(key, value):
    request = _request()
    request["exact_count"][key] = value
    result = assess_model_context_budget(**request)
    _assert_unknown(result, "exact_count_binding_mismatch")


@pytest.mark.parametrize(
    "field, value",
    [
        ("messages", [{"role": "user", "content": "changed actual input"}]),
        ("model_digest", "d" * 64),
        ("template_sha256", "d" * 64),
        ("context_tokens", 8193),
    ],
)
def test_changed_actual_request_is_unknown(field, value):
    request = _request()
    request[field] = value
    _assert_unknown(assess_model_context_budget(**request), "exact_count_binding_mismatch")


def test_messages_hash_preserves_actual_whitespace():
    request = _request()
    original_hash = request["exact_count"]["messages_sha256"]
    request["messages"][1]["content"] += "  \n"
    result = assess_model_context_budget(**request)
    _assert_unknown(result, "exact_count_binding_mismatch")
    assert result["messages_sha256"] == json_sha256(request["messages"])
    assert result["messages_sha256"] != original_hash


@pytest.mark.parametrize("scope", ["user_message", "message_content_only", "PRIVATE_SCOPE_SENTINEL"])
def test_only_full_rendered_prompt_scope_can_fit(scope):
    request = _request()
    request["exact_count"].update(input_tokens=1, scope=scope)
    result = assess_model_context_budget(**request)
    _assert_unknown(result, "unsupported_exact_count_scope")
    assert "PRIVATE_SCOPE_SENTINEL" not in json.dumps(result)


def test_missing_or_unsupported_evidence_is_unknown():
    request = _request()
    request["exact_count"] = {"count_method": "character_estimate"}
    _assert_unknown(assess_model_context_budget(**request), "missing_exact_count_binding")
    request = _request()
    request["exact_count"]["count_method"] = "character_estimate"
    _assert_unknown(assess_model_context_budget(**request), "unsupported_count_method")


@pytest.mark.parametrize("partial", [False, True])
def test_free_text_metadata_never_leaks(partial):
    request = _request()
    request["exact_count"].update(
        count_method="PRIVATE_METHOD_SENTINEL",
        tokenizer_identity="PRIVATE_IDENTITY_SENTINEL",
        input_tokens=1,
    )
    if partial:
        del request["exact_count"]["model_digest"]
    result = assess_model_context_budget(**request)
    _assert_unknown(result, "missing_exact_count_binding" if partial else "unsupported_count_method")
    assert result["count_method"] is None
    assert result["tokenizer_identity_sha256"] == text_sha256("PRIVATE_IDENTITY_SENTINEL")
    assert "PRIVATE_" not in json.dumps(result)


def test_supplied_verified_offline_method_can_fit_without_authenticating_measurement():
    request = _request()
    request["exact_count"].update(count_method="verified_offline_tokenizer", input_tokens=1)
    result = assess_model_context_budget(**request)
    assert result["status"] == "fits" and result["headroom"] == 5890
    assert "does not authenticate" in result["verification_boundary"]


@pytest.mark.parametrize("field", ["requested_output_tokens", "margin_tokens", "context_tokens"])
@pytest.mark.parametrize("value", [True, False, -1, 1.0, "1", float("nan"), float("inf"), [], {}])
def test_malformed_top_level_counts_raise(field, value):
    request = _request()
    request[field] = value
    with pytest.raises(ValueError):
        assess_model_context_budget(**request)


@pytest.mark.parametrize("field", ["input_tokens", "context_tokens"])
@pytest.mark.parametrize("value", [True, False, -1, 1.0, "1", float("nan"), float("inf"), None, [], {}])
@pytest.mark.parametrize("partial", [False, True])
def test_malformed_present_exact_counts_raise_even_when_incomplete(field, value, partial):
    request = _request()
    if partial:
        request["exact_count"] = {}
    request["exact_count"][field] = value
    with pytest.raises(ValueError):
        assess_model_context_budget(**request)


@pytest.mark.parametrize("field", ["model_digest", "template_sha256"])
@pytest.mark.parametrize("value", [True, 1, {}, "not-a-hash", "A" * 64, "a" * 63])
def test_invalid_request_hashes_raise(field, value):
    request = _request()
    request[field] = value
    with pytest.raises(ValueError):
        assess_model_context_budget(**request)


@pytest.mark.parametrize("field", ["model_digest", "template_sha256", "messages_sha256", "rendered_prompt_sha256"])
@pytest.mark.parametrize("value", [True, None, {}, "not-a-hash", "A" * 64, "a" * 63])
@pytest.mark.parametrize("partial", [False, True])
def test_invalid_present_hashes_raise_even_when_incomplete(field, value, partial):
    request = _request()
    if partial:
        request["exact_count"] = {}
    request["exact_count"][field] = value
    with pytest.raises(ValueError):
        assess_model_context_budget(**request)


@pytest.mark.parametrize("field", ["scope", "count_method", "tokenizer_identity"])
@pytest.mark.parametrize(
    "value", [None, True, 1, {"raw_prompt": "PRIVATE_SENTINEL"}, "", "  ", "private\ntext", "x" * 257]
)
@pytest.mark.parametrize("partial", [False, True])
def test_invalid_present_metadata_raises_even_when_incomplete(field, value, partial):
    request = _request()
    if partial:
        request["exact_count"] = {}
    request["exact_count"][field] = value
    with pytest.raises(ValueError):
        assess_model_context_budget(**request)


def test_unexpected_exact_fields_are_rejected_without_echoing_key():
    request = _request()
    request["exact_count"]["PRIVATE_KEY"] = "PRIVATE_VALUE"
    with pytest.raises(ValueError) as error:
        assess_model_context_budget(**request)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("invalid", [True, 1, [], "PRIVATE_SENTINEL"])
def test_exact_count_must_be_an_object(invalid):
    request = _request()
    request["exact_count"] = invalid
    with pytest.raises(ValueError):
        assess_model_context_budget(**request)


@pytest.mark.parametrize("invalid", [None, "PRIVATE_SENTINEL", [{}], [{"role": 1, "content": "private"}]])
def test_messages_must_have_typed_role_content_objects(invalid):
    request = _request()
    request["messages"] = invalid
    with pytest.raises(ValueError):
        assess_model_context_budget(**request)


@pytest.mark.parametrize("partial", [False, True])
def test_assessment_never_mutates_request(partial):
    request = _request()
    if partial:
        del request["exact_count"]["scope"]
    before = copy.deepcopy(request)
    assess_model_context_budget(**request)
    assert request == before


def test_cli_main_reads_local_json_and_prints_only_assessment(tmp_path, capsys):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_request()), encoding="utf-8")
    assert cli.main([str(path)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert result["status"] == "exceeds" and "private input" not in captured.out


@pytest.mark.parametrize("arguments", [[], ["--PRIVATE_UNKNOWN_ARG"], ["PRIVATE_PATH", "PRIVATE_EXTRA_ARG"]])
def test_cli_invalid_arguments_never_echo_input(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "assessment error: invalid_arguments\n"


def test_cli_missing_path_never_echoes_filename(tmp_path, capsys):
    assert cli.main([str(tmp_path / "PRIVATE_MISSING_PATH.json")]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "assessment error: invalid_input\n"


@pytest.mark.parametrize(
    "payload",
    [
        b"PRIVATE_NOT_JSON",
        b"\xffPRIVATE_INVALID_ENCODING",
        b"[]",
        b"{}",
        b'{"PRIVATE_UNEXPECTED_KEY":"PRIVATE_VALUE"}',
    ],
)
def test_cli_invalid_json_request_never_echoes_content_or_path(tmp_path, capsys, payload):
    path = tmp_path / "PRIVATE_REQUEST_PATH.json"
    path.write_bytes(payload)
    assert cli.main([str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "assessment error: invalid_input\n"


@pytest.mark.parametrize(
    "field, value",
    [
        ("PRIVATE_UNEXPECTED_KEY", "PRIVATE_VALUE"),
        ("count_method", {"raw_prompt": "PRIVATE_SENTINEL"}),
        ("tokenizer_identity", ""),
    ],
)
def test_cli_invalid_exact_metadata_never_echoes_content(tmp_path, capsys, field, value):
    request = _request()
    request["exact_count"][field] = value
    path = tmp_path / "PRIVATE_REQUEST_PATH.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    assert cli.main([str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "assessment error: invalid_input\n"


def test_cli_unexpected_validation_error_text_is_not_echoed(tmp_path, capsys, monkeypatch):
    def fail(**kwargs):
        raise ValueError("PRIVATE_EXCEPTION_TEXT")

    monkeypatch.setattr(cli, "assess_model_context_budget", fail)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_request()), encoding="utf-8")
    assert cli.main([str(path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "assessment error: invalid_input\n"


def test_real_cli_entrypoint_is_offline_and_prints_only_assessment(tmp_path):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_request()), encoding="utf-8")
    runner = """
import runpy, sys
class BlockImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'dotenv', 'openai', 'httpx', 'requests'} or fullname in {
            'src.config', 'src.model_runtime', 'src.container_runtime', 'src.audit', 'src.runtime_trace'
        }:
            raise AssertionError('Forbidden offline assessor import')
sys.meta_path.insert(0, BlockImports())
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    # Match test_runtime_maintenance: select an existing supported Python for
    # this stdlib-only entrypoint if the test venv has startup diagnostics.
    interpreter = os.environ.get("BUSHFIRE_TEST_CLI_PYTHON", sys.executable)
    completed = subprocess.run(
        [interpreter, "-B", "-c", runner, str(PROJECT_ROOT / "scripts/assess_model_context_budget.py"), str(path)],
        cwd=tmp_path,
        timeout=15,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0 and completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["status"] == "exceeds" and "private input" not in completed.stdout
