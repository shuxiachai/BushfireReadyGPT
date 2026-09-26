"""Synthetic SDK responses and event-synchronised deadlines; never real API calls."""

import copy
import json
import threading
from types import SimpleNamespace

import pytest

from scripts import atomic_claim_adapter as adapter
from scripts import atomic_claim_contract as contract
from scripts import evaluate_atomic_claim_deepseek as runner
from src.model_evidence import json_sha256, text_sha256
from src.model_limits import ModelAllowanceError
from tests.test_atomic_claim_contract import make_pack


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")


@pytest.fixture
def settings(monkeypatch):
    for name, value in {
        "LLM_PROVIDER": "deepseek",
        "BUSHFIRE_ALLOW_EXTERNAL_MODEL": "true",
        "DEEPSEEK_API_KEY": "synthetic-key",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "BUSHFIRE_MODEL_MAX_TOKENS": "2300",
        "BUSHFIRE_MODEL_TEMPERATURE": "0.2",
        "BUSHFIRE_MODEL_TIMEOUT_SECONDS": "10",
    }.items():
        monkeypatch.setenv(name, value)
    return runner.previous._settings("deepseek-v4-flash")


def selection(pack, *, quote=None, ref=None, sections=(7, 11, 12)):
    return {
        "schema": adapter.WIRE_SCHEMA,
        "evidence_pack_sha256": pack["evidence_pack_sha256"],
        "items": [
            {
                "id": f"s{section}",
                "section_id": section,
                "basis": {
                    "kind": "claim",
                    "text": "For review only.",
                    "evidence": {"passage_ref": ref or pack["passages"][0]["passage_ref"], "quote": quote},
                }
                if quote is not None
                else {"kind": "abstention", "reason": "No suitable section evidence."},
                "local_proposal": "Proposed owner review, not confirmed locally.",
            }
            for section in sections
        ],
    }


def sdk_response(raw, **overrides):
    message = SimpleNamespace(
        role="assistant",
        content=raw,
        tool_calls=None,
        function_call=None,
        refusal=None,
        reasoning_content="DO_NOT_PERSIST_REASONING",
    )
    choice = SimpleNamespace(index=0, finish_reason="stop", message=message)
    response = SimpleNamespace(choices=[choice], model="provider-alias", system_fingerprint=None, usage=None)
    for key, value in overrides.items():
        setattr(response, key, value)
    return response


class Slot:
    def __init__(self, error=None):
        self.error, self.consumed = error, False
        self.released = threading.Event()

    def consume_call(self):
        if self.error:
            raise self.error
        self.consumed = True

    def release(self):
        self.released.set()


def sdk_client(create):
    closed = threading.Event()
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=closed.set, closed=closed
    )


def binding_for(request, pack):
    return {
        "case_binding_sha256": "a" * 64,
        "analysis_sha256": "b" * 64,
        "assembly_sha256": "c" * 64,
        "evidence_pack_sha256": pack["evidence_pack_sha256"],
        "invocation_sha256": json_sha256(request),
    }


@pytest.fixture
def bundle():
    _, analysis, assembly = make_pack()
    cases = []
    for index in (1, 2):
        case = {
            "scenario": {"id": f"synthetic-{index}", "location": "Synthetic locality"},
            "analysis": copy.deepcopy(analysis),
            "rag_context_assembly": copy.deepcopy(assembly),
            "analysis_sha256": json_sha256(analysis),
            "assembly_sha256": json_sha256(assembly),
        }
        case["binding_sha256"] = json_sha256(
            {key: case[key] for key in ("scenario", "analysis", "rag_context_assembly")}
        )
        cases.append(case)
    return {"phase": "seen_pilot", "cases": cases}


@pytest.fixture
def journal(tmp_path):
    with (tmp_path / "atomic.calls.jsonl").open("x", encoding="utf-8") as handle:
        yield runner.Journal(handle)


def test_exact_request_json_mode_and_single_complete_pack():
    pack, *_ = make_pack()
    request = adapter.build_request({"id": "synthetic"}, pack, "deepseek-v4-flash")
    assert json.loads(request["messages"][1]["content"])["evidence_pack"] == pack
    assert request["response_format"] == {"type": "json_object"}
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
    assert (request["max_tokens"], request["temperature"], request["top_p"], request["stream"]) == (
        2300,
        0.2,
        0.8,
        False,
    )
    assert "tools" not in request and "seed" not in request
    assert "quote_start" not in request["messages"][0]["content"]


def test_prompt_complete_root_example_matches_v1_after_synthetic_substitution():
    pack, *_ = make_pack()
    example = json.loads(adapter.ROOT_EXAMPLE_JSON)
    assert set(example) == {"schema", "evidence_pack_sha256", "items"}
    assert example["schema"] == adapter.WIRE_SCHEMA == "atomic-claim-selection-v1"
    assert [item["section_id"] for item in example["items"]] == [7, 11, 12]
    assert all(set(item) == {"id", "section_id", "basis", "local_proposal"} for item in example["items"])
    assert adapter.SYSTEM_PROMPT.count(adapter.ROOT_EXAMPLE_JSON) == 1
    assert "NOT your output object" in adapter.SYSTEM_PROMPT
    assert "Replace EVERY angle-bracket placeholder" in adapter.SYSTEM_PROMPT
    assert "CURRENT supplied" in adapter.SYSTEM_PROMPT
    example["evidence_pack_sha256"] = pack["evidence_pack_sha256"]
    passage = pack["passages"][0]
    first = example["items"][0]["basis"]
    first["text"] = "Organisers should review routes unless official advice changes."
    first["evidence"] = {"passage_ref": passage["passage_ref"], "quote": passage["text"]}
    for item in example["items"]:
        item["local_proposal"] = "Proposed local owner review; confirmation is required."
        if item["basis"]["kind"] == "abstention":
            item["basis"]["reason"] = "No suitable evidence for this section in the synthetic fixture."
    assert "<" not in json.dumps(example)
    checked = adapter.validate_selection(json.dumps(example), pack)
    assert checked["requested_section_coverage_complete"] and checked["quote_binding_exercised"]
    assert checked["contract_check"]["contract_valid"] and checked["contract_check"]["reference_binding_valid"]


def test_api_type_and_items_root_still_fails_without_schema_and_hash():
    pack, *_ = make_pack()
    wrong_root = {"type": "json_object", "items": selection(pack)["items"]}
    raw = json.dumps(wrong_root)
    with pytest.raises(contract.ContractError, match="missing or unknown fields"):
        adapter.validate_selection(raw, pack)
    checked = adapter.check_response(sdk_response(raw), pack)
    assert checked["finish_reason"] == "stop" and checked["status"] == "failed"
    assert checked["error_code"] == "contract_rejected" and "canonical_payload" not in checked
    assert checked["assistant_content"] == raw
    assert set(json.loads(checked["assistant_content"])) == {"type", "items"}


@pytest.mark.parametrize("text,quote", [("aaa", "aa"), ("review review", "review")])
def test_overlapping_and_nonoverlapping_duplicate_quotes_fail(text, quote):
    pack, *_ = make_pack([text])
    with pytest.raises(adapter.SelectionError, match="quote_ambiguous"):
        adapter.validate_selection(json.dumps(selection(pack, quote=quote)), pack)


def test_lookup_never_switches_passage_and_other_sources_do_not_affect_uniqueness():
    pack, *_ = make_pack(["Selected shared passage.", "Other shared passage."])
    with pytest.raises(adapter.SelectionError, match="quote_not_found"):
        adapter.validate_selection(json.dumps(selection(pack, quote="Other")), pack)
    result = adapter.validate_selection(json.dumps(selection(pack, quote="shared passage.")), pack)
    assert result["canonical_payload"]["items"][0]["basis"]["evidence"]["quote_start"] == len("Selected ")


@pytest.mark.parametrize("quote", [" Café", "CAFÉ", "Cafe\u0301"])
def test_quotes_are_not_trimmed_casefolded_or_unicode_normalized(quote):
    pack, *_ = make_pack(["Café 🏡 task."])
    with pytest.raises(adapter.SelectionError, match="quote_not_found"):
        adapter.validate_selection(json.dumps(selection(pack, quote=quote)), pack)


def test_emoji_codepoint_offsets_are_derived_and_revalidated():
    pack, *_ = make_pack(["家🏡 task."])
    result = adapter.validate_selection(json.dumps(selection(pack, quote="🏡 task")), pack)
    evidence = result["canonical_payload"]["items"][0]["basis"]["evidence"]
    assert (evidence["quote_start"], evidence["quote_end"]) == (1, 7)
    assert result["canonical_payload_sha256"] == json_sha256(result["canonical_payload"])
    assert result["binding_origin"] == "application_derived_exact_unique_quote"


@pytest.mark.parametrize("mutation", ["offset", "source", "pack_hash", "ref", "abstention_evidence", "duplicate_key"])
def test_selection_cannot_override_binding_or_smuggle_fields(mutation):
    pack, *_ = make_pack()
    payload = selection(pack, quote="Organisers")
    evidence = payload["items"][0]["basis"]["evidence"]
    if mutation == "offset":
        evidence["quote_start"] = 0
    elif mutation == "source":
        evidence["source_id"] = "invented"
    elif mutation == "pack_hash":
        payload["evidence_pack_sha256"] = "0" * 64
    elif mutation == "ref":
        evidence["passage_ref"] = "unknown"
    elif mutation == "abstention_evidence":
        payload["items"][0]["basis"] = {"kind": "abstention", "reason": "None", "evidence": evidence}
    raw = json.dumps(payload)
    if mutation == "duplicate_key":
        raw = raw.replace('"schema":', '"schema":"duplicate", "schema":', 1)
    with pytest.raises((adapter.SelectionError, contract.ContractError)):
        adapter.validate_selection(raw, pack)


def test_original_contract_rejection_cannot_be_promoted(monkeypatch):
    pack, *_ = make_pack()
    monkeypatch.setattr(
        contract, "parse_and_validate", lambda *_: (_ for _ in ()).throw(contract.ContractError("synthetic"))
    )
    result = adapter.check_response(sdk_response(json.dumps(selection(pack))), pack)
    assert result["status"] == "failed" and result["error_code"] == "contract_rejected"


def test_real_envelope_preserves_content_and_never_copies_offline_claims():
    pack, *_ = make_pack()
    payload = selection(pack, sections=(7,))
    payload["items"][0]["local_proposal"] = "https://example.test/path\nA second line."
    raw = " \n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n "
    result = adapter.check_response(sdk_response(raw), pack)
    assert result["assistant_content"] == raw and result["assistant_content_sha256"] == text_sha256(raw)
    assert result["response_origin"] == "remote_model" and result["status"] == "validated"
    assert result["requested_section_coverage_complete"] is False and result["quote_binding_exercised"] is False
    assert "synthetic_offline" not in json.dumps(result) and "DO_NOT_PERSIST_REASONING" not in json.dumps(result)
    assert set(result["contract_check"]) == adapter.PROJECTION_FIELDS
    full = adapter.check_response(sdk_response(json.dumps(selection(pack))), pack)
    assert full["requested_section_coverage_complete"] and full["quote_binding_exercised"] is False


@pytest.mark.parametrize("signal", ["tool_calls", "function_call", "content_filter"])
def test_finish_signals_alone_are_fatal(signal):
    pack, *_ = make_pack()
    response = sdk_response(json.dumps(selection(pack)))
    response.choices[0].finish_reason = signal
    result = adapter.check_response(response, pack)
    assert result["fatal_reason"] and result["finish_reason"] == signal and result["choices_count"] == 1


def test_multiple_choices_with_tool_signal_or_message_refusal_are_fatal():
    pack, *_ = make_pack()
    response = sdk_response("{}")
    response.choices.append(SimpleNamespace(index=1, finish_reason="tool_calls", message=SimpleNamespace()))
    result = adapter.check_response(response, pack)
    assert result["fatal_reason"] and result["choices_count"] == 2
    response = sdk_response("{}")
    response.choices[0].message.refusal = "Synthetic refusal"
    assert adapter.check_response(response, pack)["fatal_reason"]


@pytest.mark.parametrize("change", ["length", "role", "index", "nontext", "many", "bad_json"])
def test_nonfatal_protocol_or_contract_errors_are_not_accepted(change):
    pack, *_ = make_pack()
    response = sdk_response(json.dumps(selection(pack)))
    choice = response.choices[0]
    if change == "length":
        choice.finish_reason = "length"
    elif change == "role":
        choice.message.role = "user"
    elif change == "index":
        choice.index = True
    elif change == "nontext":
        choice.message.content = [{"text": "unaccepted"}]
    elif change == "many":
        response.choices *= 2
    else:
        choice.message.content = "fenced or malformed JSON"
    result = adapter.check_response(response, pack)
    assert result["status"] == "failed" and result["fatal_reason"] is None


def test_usage_is_provider_reported_allowlisted_and_missing_is_null():
    response = sdk_response("{}")
    assert adapter.response_metadata(response)["usage"] is None
    response.usage = SimpleNamespace(
        prompt_tokens=12,
        completion_tokens=True,
        total_tokens=-1,
        prompt_cache_hit_tokens="4",
        prompt_tokens_details=SimpleNamespace(cached_tokens=3),
    )
    result = adapter.response_metadata(response)
    assert result["provider_reported_model"] == "provider-alias" and result["immutable_model_digest"] is None
    assert result["usage"]["prompt_tokens"] == 12 and result["usage"]["completion_tokens"] is None
    assert result["usage"]["total_tokens"] is None and result["usage"]["prompt_cache_hit_tokens"] is None
    assert result["usage"]["prompt_tokens_details.cached_tokens"] == 3 and result["currency_cost"] is None


def test_independent_sdk_options(settings):
    calls = {}
    transport = SimpleNamespace(close=lambda: None)
    adapter.create_sdk(
        settings,
        sdk_factory=lambda **kwargs: calls.setdefault("sdk", kwargs),
        http_factory=lambda **kwargs: (calls.setdefault("http", kwargs), transport)[1],
    )
    assert calls["http"] == {"verify": True, "trust_env": False, "follow_redirects": False}
    assert calls["sdk"]["max_retries"] == 0 and calls["sdk"]["base_url"] == "https://api.deepseek.com"


@pytest.mark.parametrize("mutation", ["prompt", "pack"])
def test_binding_drift_prevents_sdk_start(mutation):
    pack, *_ = make_pack()
    request = adapter.build_request({"id": "test"}, pack, "deepseek-v4-flash")
    binding = binding_for(request, pack)
    if mutation == "prompt":
        request["messages"][0]["content"] += " changed"
    else:
        pack["passages"][0]["text"] += " changed"
    slot = Slot()
    result = adapter.invoke_once(
        request,
        pack,
        binding,
        timeout_seconds=2,
        acquire_slot=lambda: slot,
        client_factory=lambda: sdk_client(lambda **_: pytest.fail("No SDK after drift")),
    )
    assert result["fatal_reason"] == "input_binding_drift" and not result["sdk_started"]
    assert slot.released.is_set()


def test_successful_sdk_capture_binds_exact_kwargs_raw_response_and_pack():
    pack, *_ = make_pack()
    request = adapter.build_request({"id": "test"}, pack, "deepseek-v4-flash")
    raw, sent, slot = json.dumps(selection(pack), indent=2), [], Slot()
    client = sdk_client(lambda **kwargs: (sent.append(copy.deepcopy(kwargs)), sdk_response(raw))[1])
    result = adapter.invoke_once(
        request,
        pack,
        binding_for(request, pack),
        timeout_seconds=2,
        acquire_slot=lambda: slot,
        client_factory=lambda: client,
    )
    capture = result["invocation_capture"]
    assert capture["invocation_kwargs"] == sent[0] == request
    assert capture["invocation_sha256"] == json_sha256(sent[0])
    assert capture["response_sha256"] == text_sha256(raw)
    assert capture["evidence_pack_sha256"] == pack["evidence_pack_sha256"]
    assert result["slot_acquired"] and result["allowance_consumed"] and result["sdk_started"]
    assert slot.released.is_set() and client.closed.is_set()


def test_timeout_holds_slot_ignores_late_result_and_stops_second_case(bundle, settings, journal):
    started, unblock, slot = threading.Event(), threading.Event(), Slot()
    clock_value, clients, calls = [0.0], [], []

    def create(**request):
        calls.append(request)
        pack = json.loads(request["messages"][1]["content"])["evidence_pack"]
        started.set()
        assert unblock.wait(2)
        return sdk_response(json.dumps(selection(pack)))

    def factory():
        client = sdk_client(create)
        clients.append(client)
        return client

    def wait_for_deadline(_done, _remaining):
        assert started.wait(1)
        clock_value[0] = 20.0
        return False

    def invoke(request, pack, binding, **kwargs):
        return adapter.invoke_once(
            request,
            pack,
            binding,
            **kwargs,
            acquire_slot=lambda: slot,
            clock=lambda: clock_value[0],
            waiter=wait_for_deadline,
        )

    result = runner.run_suite(bundle, settings, journal, provenance=lambda: {}, invoke=invoke, client_factory=factory)
    assert len(calls) == result["sdk_started_count"] == 1
    assert result["fatal_stop_reason"] == "timeout" and result["rows"][1]["status"] == "not_run"
    assert result["rows"][0]["inflight_unknown"] and not slot.released.is_set() and not clients[0].closed.is_set()
    before = copy.deepcopy(result)
    count = len(journal.entries)
    journal.handle.close()
    unblock.set()
    assert slot.released.wait(1) and clients[0].closed.is_set()
    assert result == before and len(journal.entries) == count
    assert result["rows"][0]["invocation_capture"]["response_sha256"] is None


def suite_invoke(request, pack, binding, **kwargs):
    return adapter.invoke_once(request, pack, binding, **kwargs, acquire_slot=Slot)


def test_two_case_budget_and_length_failure_continue_without_repair(bundle, settings, journal):
    calls = []

    def create(**request):
        calls.append(request)
        pack = json.loads(request["messages"][1]["content"])["evidence_pack"]
        response = sdk_response(json.dumps(selection(pack)))
        if len(calls) == 1:
            response.choices[0].finish_reason = "length"
        return response

    result = runner.run_suite(
        bundle, settings, journal, provenance=lambda: {}, invoke=suite_invoke, client_factory=lambda: sdk_client(create)
    )
    assert result["sdk_started_count"] == result["ledger_reserved_count"] == 2 and len(calls) == 2
    assert result["rows"][0]["finish_reason"] == "length" and result["rows"][1]["status"] == "validated"
    assert result["summary"]["total_cases"] == 2 and result["summary"]["failed_cases"] == 1
    assert result["summary"]["quote_binding_exercised_cases"] == 0


def test_quota_failure_is_fatal_and_counted_before_sdk(bundle, settings, journal):
    slot = Slot(ModelAllowanceError("Synthetic quota denial"))

    def invoke(request, pack, binding, **kwargs):
        return adapter.invoke_once(request, pack, binding, **kwargs, acquire_slot=lambda: slot)

    result = runner.run_suite(
        bundle,
        settings,
        journal,
        provenance=lambda: {},
        invoke=invoke,
        client_factory=lambda: sdk_client(lambda **_: pytest.fail("Quota prevented SDK")),
    )
    assert result["fatal_stop_reason"] == "shared_model_allowance" and result["sdk_started_count"] == 0
    assert result["ledger_reserved_count"] == result["slot_acquired_count"] == 1
    assert result["allowance_consumed_count"] == 0 and result["summary"]["not_run_cases"] == 1


def test_journal_failure_precedes_any_reservation(bundle, settings, journal, monkeypatch):
    monkeypatch.setattr(journal, "append", lambda **_: (_ for _ in ()).throw(OSError("Synthetic journal error")))
    result = runner.run_suite(
        bundle,
        settings,
        journal,
        provenance=lambda: {},
        invoke=lambda *_args, **_kwargs: pytest.fail("No worker before durable journal"),
    )
    assert result["fatal_stop_reason"] == "journal_write_failed" and result["ledger_reserved_count"] == 0
    assert result["sdk_started_count"] == 0 and result["summary"]["not_run_cases"] == 1


def test_provenance_drift_prevents_case_dispatch(bundle, settings, journal):
    checks = iter([{"source": "original"}, {"source": "changed"}])
    result = runner.run_suite(
        bundle,
        settings,
        journal,
        provenance=lambda: next(checks, {"source": "changed"}),
        invoke=lambda *_args, **_kwargs: pytest.fail("No SDK after provenance drift"),
    )
    assert result["fatal_stop_reason"] == "provenance_drift" and result["sdk_started_count"] == 0
    assert result["summary"]["not_run_cases"] == 2


def test_unauthorized_cli_does_not_read_prepared_or_construct_sdk(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.previous, "load_seen_pilot", lambda *_: pytest.fail("No reads before authorization"))
    assert (
        runner.main(
            [
                "--prepared",
                "unused",
                "--expected-prepared-file-sha256",
                "a" * 64,
                "--model",
                "deepseek-v4-flash",
                "--output",
                str(tmp_path / "never.json"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "never.json").exists()


@pytest.mark.parametrize("field,value", [("DEEPSEEK_API_KEY", ""), ("DEEPSEEK_BASE_URL", "https://bad.example")])
def test_host_and_key_failure_precede_any_client(settings, monkeypatch, tmp_path, field, value):
    monkeypatch.setenv(field, value)
    monkeypatch.setattr(runner.previous, "load_seen_pilot", lambda *_: pytest.fail("Invalid admission reached input"))
    assert (
        runner.main(
            [
                "--prepared",
                "unused",
                "--expected-prepared-file-sha256",
                "a" * 64,
                "--run-model",
                "--allow-external-deepseek",
                "--model",
                "deepseek-v4-flash",
                "--output",
                str(tmp_path / "never.json"),
            ]
        )
        == 2
    )


def test_no_overwrite_and_durable_namespace_cannot_reset_budget(settings, bundle, monkeypatch, tmp_path):
    monkeypatch.setattr(runner.previous, "admit_environment", lambda **_: settings)
    monkeypatch.setattr(runner.previous, "load_seen_pilot", lambda *_: bundle)
    ledger, output = tmp_path / "claim.calls.jsonl", tmp_path / "result.json"
    monkeypatch.setattr(runner, "journal_path", lambda _: ledger)
    monkeypatch.setattr(runner, "run_suite", lambda *_args, **_kwargs: pytest.fail("No calls for existing paths"))
    args = [
        "--prepared",
        "synthetic",
        "--expected-prepared-file-sha256",
        "a" * 64,
        "--run-model",
        "--allow-external-deepseek",
        "--model",
        "deepseek-v4-flash",
        "--output",
        str(output),
    ]
    output.write_text("preserve", encoding="utf-8")
    assert runner.main(args) == 2 and output.read_text(encoding="utf-8") == "preserve"
    assert not ledger.exists()
    ledger.write_text("existing claim", encoding="utf-8")
    args[-1] = str(tmp_path / "another-result.json")
    assert runner.main(args) == 2 and ledger.read_text(encoding="utf-8") == "existing claim"


@pytest.mark.parametrize(
    "signal", ["tool_calls", "function_call", "content_filter", "message_tool", "message_function", "refusal"]
)
def test_invalid_unicode_preserves_fatal_boundary_and_stops_batch(bundle, settings, journal, signal):
    calls = []

    def create(**request):
        calls.append(request)
        response = sdk_response(chr(0xD800))
        choice = response.choices[0]
        if signal == "message_tool":
            choice.message.tool_calls = [{"type": "function"}]
        elif signal == "message_function":
            choice.message.function_call = {}
        elif signal == "refusal":
            choice.message.refusal = "Synthetic refusal"
        else:
            choice.finish_reason = signal
        return response

    result = runner.run_suite(
        bundle, settings, journal, provenance=lambda: {}, invoke=suite_invoke, client_factory=lambda: sdk_client(create)
    )
    assert len(calls) == result["sdk_started_count"] == result["ledger_reserved_count"] == 1
    assert result["fatal_stop_reason"] == "unexpected_tool_function_or_refusal"
    assert result["rows"][0]["error_code"] == "invalid_utf8_response"
    assert result["rows"][0]["assistant_content_sha256"] is None
    assert result["rows"][1]["status"] == "not_run"
    assert result["summary"]["total_cases"] == 2
    assert result["summary"]["failed_cases"] == result["summary"]["not_run_cases"] == 1
