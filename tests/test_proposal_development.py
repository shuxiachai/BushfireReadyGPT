"""Bounded proposal SDK mocks; no credentials, real files, holdout or network use."""

import copy
import hashlib
import json
import threading

import pytest

from scripts import atomic_claim_adapter as adapter
from scripts import atomic_claim_contract as contract
from scripts import evaluate_atomic_claim_deepseek as runner
from scripts import proposal_development as development
from src.model_evidence import json_sha256
from src.model_limits import ModelAllowanceError
from tests.test_atomic_claim_adapter import Slot, sdk_client, sdk_response
from tests.test_extractive_development import dataset as dataset
from tests.test_extractive_development import journal as journal
from tests.test_extractive_development import no_dotenv as no_dotenv
from tests.test_extractive_development import settings as settings


@pytest.fixture
def inputs(dataset, monkeypatch):
    source = json.dumps(dataset).encode()
    digest = hashlib.sha256(source).hexdigest()
    monkeypatch.setattr(development, "SOURCE_SHA256", digest)
    context = {
        "schema": development.CONTEXT_SCHEMA,
        "protocol": development.PROTOCOL,
        "source_dataset_sha256": digest,
        "cases": [
            {
                "id": key,
                "selected_unit_id_by_section": copy.deepcopy(value),
                "task_focus": "Draft responsibly or require evidence; local facts remain unknown.",
            }
            for key, value in development.APPLICATION_SELECTIONS.items()
        ],
    }
    return source, json.dumps(context).encode()


@pytest.fixture
def bundle(inputs):
    return development.prepare_dataset(*inputs)


def response_for(request, *, requires_only=False):
    visible = json.loads(request["messages"][1]["content"])
    items = []
    for section, ref in visible["selected_ref_by_section"].items():
        proposal = {"kind": "requires_evidence"}
        if ref is not None and not requires_only:
            refs = [ref]
            if visible["scenario"]["region"] == "Synthetic D1" and section == "7":
                refs.append(visible["catalog"][1]["passage_ref"])
            proposal.update(
                kind="draft_for_review",
                text="Proposed local review; ownership and conditions require confirmation.",
                declared_refs=refs,
            )
        items.append({"section_id": int(section), "proposal": proposal})
    return sdk_response(" \n" + json.dumps({"items": items}, indent=2) + "\n ")


def mock_invoke(request, pack, binding, **kwargs):
    return adapter.invoke_once(request, pack, binding, **kwargs, acquire_slot=Slot)


def run(bundle, settings, journal, create, **kwargs):
    return runner.run_proposal_suite(
        bundle,
        settings,
        journal,
        invoke=mock_invoke,
        client_factory=lambda: sdk_client(create),
        provenance=kwargs.pop("provenance", lambda: {}),
        **kwargs,
    )


def test_only_application_context_and_sources_enter_prompt_not_old_labels(inputs, bundle, monkeypatch):
    case = bundle["cases"][0]
    request, typed = development.build_request(case, "deepseek-v4-flash")
    visible = json.loads(request["messages"][1]["content"])
    assert set(visible) == {
        "scenario",
        "task_focus",
        "section_focus",
        "selected_ref_by_section",
        "requested_sections",
        "catalog",
        "output_json_schema",
    }
    assert visible["selected_ref_by_section"] == case["selected_ref_by_section"]
    assert typed.to_dict()["request_sha256"] == case["typed_request_sha256"]
    assert not {"expected_refs", "expected_passage_refs", "development_case"}.intersection(case)
    for forbidden in (
        "expected_refs",
        "expected_passage_refs",
        "synthetic_offline",
        "transport_capture",
        "rubric_sentinel",
    ):
        assert forbidden not in json.dumps(request)
    assert "offline" not in request["messages"][0]["content"].lower()
    source = json.loads(inputs[0])
    source["cases"][0]["expected_refs"]["7"] = ["u03"]
    raw = json.dumps(source).encode()
    context = json.loads(inputs[1])
    context["source_dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(development, "SOURCE_SHA256", context["source_dataset_sha256"])
    changed = development.prepare_dataset(raw, json.dumps(context))
    assert development.build_request(changed["cases"][0], "deepseek-v4-flash")[0] == request
    assert request["max_tokens"] == 2300 and request["temperature"] == 0.2
    assert request["response_format"] == {"type": "json_object"} and request["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert request["stream"] is False and "seed" not in request and "tools" not in request


@pytest.mark.parametrize(
    "mutation", ["extra", "wrong_source", "missing_case", "order", "map", "bool", "long_focus", "duplicate_key"]
)
def test_context_is_exact_fixed_bounded_protocol(inputs, mutation):
    context = json.loads(inputs[1])
    if mutation == "extra":
        context["rubric_sentinel"] = "private"
    elif mutation == "wrong_source":
        context["source_dataset_sha256"] = "a" * 64
    elif mutation == "missing_case":
        context["cases"].pop()
    elif mutation == "order":
        context["cases"].reverse()
    elif mutation == "map":
        context["cases"][0]["selected_unit_id_by_section"]["7"] = "u03"
    elif mutation == "bool":
        context["cases"][0]["selected_unit_id_by_section"]["7"] = True
    elif mutation == "long_focus":
        context["cases"][0]["task_focus"] = "x" * 481
    raw = json.dumps(context)
    if mutation == "duplicate_key":
        raw = raw.replace('"protocol":', '"protocol":"duplicate","protocol":', 1)
    with pytest.raises(contract.ContractError):
        development.prepare_dataset(inputs[0], raw)


def test_four_remote_mocks_bind_every_input_and_do_not_import_offline_envelope(bundle, settings, journal):
    calls = []

    def create(**request):
        calls.append(copy.deepcopy(request))
        return response_for(request)

    result = run(bundle, settings, journal, create)
    assert result["valid"] and result["schema"] == "proposal-development-results-v1"
    assert (
        result["sdk_started_count"]
        == result["allowance_consumed_count"]
        == result["ledger_reserved_count"]
        == len(calls)
        == 4
    )
    summary = result["summary"]
    assert (summary["total_cases"], summary["total_slots"], summary["evaluable_slots"]) == (4, 12, 12)
    assert summary["null_primary_slots"] == summary["nonnull_primary_slots"] == 6
    assert summary["null_requires_evidence_slots"] == summary["nonnull_draft_slots"] == 6
    assert summary["single_source_draft_slots"] == 5 and summary["multi_source_draft_slots"] == 1
    for row, case in zip(result["rows"], bundle["cases"], strict=True):
        assert row["response_origin"] == "remote_model" and row["assistant_content"].startswith(" \n")
        check = row["proposal_check"]
        assert not {"origin", "model_calls", "transport_capture", "production_enabled"}.intersection(check)
        assert check["semantic_support"] == "unknown" and check["semantic_accuracy"] is None
        assert "selection_target_check" not in row
        capture = row["invocation_capture"]
        assert capture["invocation_sha256"] == json_sha256(capture["invocation_kwargs"])
        for key in ("source_dataset_file_sha256", "app_context_file_sha256"):
            assert capture[key] == bundle[key]
        for key in ("selection_context_sha256", "typed_request_sha256", "campaign_case_binding_sha256"):
            assert capture[key] == case[key]
        assert capture["response_sha256"] == row["assistant_content_sha256"]
        assert row["metadata"]["usage"] is None and row["metadata"]["currency_cost"] is None
    assert runner.MAX_CALLS == 2 and runner.MAX_EXTRACTIVE_CALLS == runner.MAX_PROPOSAL_CALLS == 4
    with pytest.raises(runner.previous.ExperimentBlocked, match="invalid_call_budget"):
        runner.run_proposal_suite(bundle, settings, journal, provenance=lambda: {}, max_calls=5)


def test_all_requires_is_contract_valid_but_zero_of_six_draft_slots(bundle, settings, journal):
    result = run(bundle, settings, journal, lambda **request: response_for(request, requires_only=True))
    summary = result["summary"]
    assert summary["contract_valid_cases"] == 4 and summary["nonnull_draft_slots"] == 0
    assert summary["null_requires_evidence_slots"] == summary["nonnull_requires_evidence_slots"] == 6
    assert summary["nonnull_primary_slots"] == 6 and summary["unevaluable_slots"] == 0
    assert "success" not in summary and "selection_targets_agreeing" not in summary


@pytest.mark.parametrize("kind,expected_calls", [("length", 4), ("schema", 4), ("tool_calls", 1), ("transport", 1)])
def test_protocol_failure_has_no_retry_and_fatal_keeps_unrun_slots(bundle, settings, journal, kind, expected_calls):
    calls = []

    def create(**request):
        calls.append(True)
        response = response_for(request)
        if len(calls) == 1:
            if kind == "transport":
                raise RuntimeError("sensitive transport message")
            if kind == "schema":
                response.choices[0].message.content = '{"items": []}'
            else:
                response.choices[0].finish_reason = kind
        return response

    result = run(bundle, settings, journal, create)
    summary = result["summary"]
    assert len(calls) == expected_calls and summary["failed_slots"] == 3
    assert summary["not_run_slots"] == (4 - expected_calls) * 3
    assert summary["null_primary_slots"] == summary["nonnull_primary_slots"] == 6
    assert summary["evaluable_slots"] + summary["unevaluable_slots"] == 12
    assert "sensitive" not in json.dumps(result)


@pytest.mark.parametrize(
    "extra", [{"extractive_check": {}}, {"metadata": {}}, {"status": "validated"}, {"assistant_content": "forged"}]
)
def test_proposal_callback_cannot_mix_keys_or_override_transport(bundle, extra):
    response = sdk_response("{}")
    result = adapter.check_response(
        response, bundle["cases"][0]["evidence_pack"], content_validator=lambda *_: {"proposal_check": {}, **extra}
    )
    assert result["fatal_reason"] == "content_validator_boundary_rejected"
    assert result["assistant_content"] == "{}" and result["metadata"]["provider_reported_model"] == "provider-alias"


@pytest.mark.parametrize("boundary", ["length", "tool_calls", "surrogate", "refusal"])
def test_proposal_callback_only_runs_after_transport_boundaries(bundle, boundary):
    response = sdk_response("{}")
    if boundary == "surrogate":
        response.choices[0].message.content = chr(0xD800)
    elif boundary == "refusal":
        response.choices[0].message.refusal = "not permitted"
    else:
        response.choices[0].finish_reason = boundary
    checked = adapter.check_response(
        response, bundle["cases"][0]["evidence_pack"], content_validator=lambda *_: pytest.fail("must not be called")
    )
    assert checked["status"] == "failed" and "proposal_check" not in checked


def test_wrong_protocol_projection_is_fatal_after_capture(bundle, settings, journal, monkeypatch):
    monkeypatch.setattr(development, "content_validator", lambda _: lambda *_: {"extractive_check": {}})
    result = run(bundle, settings, journal, lambda **request: response_for(request))
    assert result["fatal_stop_reason"] == "projection_protocol_mismatch" and result["sdk_started_count"] == 1
    assert result["rows"][0]["invocation_capture"] and result["rows"][0]["assistant_content"]
    assert result["summary"]["failed_slots"] == 3 and result["summary"]["not_run_slots"] == 9


def test_typed_request_binding_drift_is_fatal_not_ordinary_schema_failure(bundle):
    case = bundle["cases"][0]
    request, typed = development.build_request(case, "deepseek-v4-flash")
    callback = development.content_validator(typed)
    object.__setattr__(typed, "_request_json", "{}")
    result = adapter.check_response(response_for(request), case["evidence_pack"], content_validator=callback)
    assert result["fatal_reason"] == "content_validator_failed"


def test_last_case_memory_map_drift_is_fatal_with_original_denominators(bundle, settings, journal):
    calls = []

    def create(**request):
        calls.append(True)
        response = response_for(request)
        if len(calls) == 4:
            bundle["cases"][-1]["application_selection_context"]["selected_unit_id_by_section"]["7"] = "u01"
        return response

    result = run(bundle, settings, journal, create)
    assert not result["valid"] and result["rows"][-1]["status"] == "failed"
    assert result["summary"]["evaluable_slots"] == 9 and result["summary"]["failed_slots"] == 3
    assert result["summary"]["null_primary_slots"] == result["summary"]["nonnull_primary_slots"] == 6


@pytest.mark.parametrize("failure", ["journal", "quota"])
def test_reservation_and_allowance_fail_closed_without_sdk(bundle, settings, journal, failure, monkeypatch):
    if failure == "journal":
        monkeypatch.setattr(journal, "append", lambda **_: (_ for _ in ()).throw(OSError("synthetic")))
        invoke = mock_invoke
    else:

        def invoke(request, pack, binding, **kwargs):
            return adapter.invoke_once(
                request, pack, binding, **kwargs, acquire_slot=lambda: Slot(ModelAllowanceError("synthetic"))
            )

    result = runner.run_proposal_suite(
        bundle,
        settings,
        journal,
        provenance=lambda: {},
        invoke=invoke,
        client_factory=lambda: sdk_client(lambda **_: pytest.fail("No dispatch")),
    )
    assert result["sdk_started_count"] == result["allowance_consumed_count"] == 0
    assert result["ledger_reserved_count"] == (failure == "quota")
    assert result["summary"]["failed_slots"] == 3 and result["summary"]["not_run_slots"] == 9


def test_timeout_retains_slot_ignores_late_result_and_stops_batch(bundle, settings, journal):
    started, release, slot = threading.Event(), threading.Event(), Slot()
    clock, calls, clients = [0.0], [], []

    def create(**request):
        calls.append(True)
        started.set()
        assert release.wait(2)
        return response_for(request)

    def factory():
        client = sdk_client(create)
        clients.append(client)
        return client

    def waiter(_event, _seconds):
        assert started.wait(1)
        clock[0] = 20.0
        return False

    def invoke(request, pack, binding, **kwargs):
        return adapter.invoke_once(
            request, pack, binding, **kwargs, acquire_slot=lambda: slot, clock=lambda: clock[0], waiter=waiter
        )

    result = runner.run_proposal_suite(
        bundle, settings, journal, provenance=lambda: {}, invoke=invoke, client_factory=factory
    )
    assert len(calls) == 1 and result["fatal_stop_reason"] == "timeout"
    assert result["summary"]["not_run_slots"] == 9 and result["summary"]["evaluable_slots"] == 0
    assert not slot.released.is_set() and not clients[0].closed.is_set()
    frozen = copy.deepcopy(result)
    journal.handle.close()
    release.set()
    assert slot.released.wait(1) and result == frozen


@pytest.fixture
def cli_environment(tmp_path, monkeypatch, inputs, settings):
    source, context = tmp_path / "source.json", tmp_path / "context.json"
    source.write_bytes(inputs[0])
    context.write_bytes(inputs[1])
    (tmp_path / "output").mkdir()
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "EXTRACTIVE_DATASET_PATH", source)
    monkeypatch.setattr(runner, "PROPOSAL_CONTEXT_PATH", context)
    return source, context, runner.sha256_file(source), runner.sha256_file(context)


def cli_args(environment, output):
    return [
        "--protocol",
        development.PROTOCOL,
        "--expected-dataset-sha256",
        environment[2].upper(),
        "--expected-context-sha256",
        environment[3].upper(),
        "--run-model",
        "--allow-external-deepseek",
        "--model",
        "deepseek-v4-flash",
        "--output",
        str(output),
    ]


def test_admission_before_input_read_and_cli_modes_are_exclusive(cli_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "load_proposal_dataset", lambda *_: pytest.fail("No pre-admission read"))
    args = cli_args(cli_environment, tmp_path / "none.json")
    args.remove("--run-model")
    assert runner.main(args) == 2
    for extra in (["--prepared", "wrong"], ["--root-example-follow-up"], ["--max-calls", "5"]):
        with pytest.raises(SystemExit):
            runner.main(cli_args(cli_environment, tmp_path / "none.json") + extra)
    with pytest.raises(SystemExit):
        runner.main(cli_args(cli_environment, tmp_path / "none.json") + ["--protocol", runner.EXTRACTIVE_PROTOCOL])


def test_fixed_ledger_and_output_collisions_never_reopen_allowance(cli_environment, tmp_path, monkeypatch):
    calls = []
    original = runner.run_proposal_suite
    monkeypatch.setattr(runner, "proposal_provenance", lambda *_: {})

    def create(**request):
        calls.append(True)
        return response_for(request)

    monkeypatch.setattr(
        runner,
        "run_proposal_suite",
        lambda *args, **kwargs: original(
            *args, **kwargs, invoke=mock_invoke, client_factory=lambda: sdk_client(create)
        ),
    )
    for protected in (*cli_environment[:2], runner.proposal_journal_path()):
        assert runner.main(cli_args(cli_environment, protected)) == 2
    assert calls == []
    output = tmp_path / "result.json"
    assert runner.main(cli_args(cli_environment, output)) == 0 and len(calls) == 4
    result_bytes, ledger_bytes = output.read_bytes(), runner.proposal_journal_path().read_bytes()
    assert runner.proposal_journal_path().name == "proposal-development-v1.calls.jsonl"
    assert runner.main(cli_args(cli_environment, output)) == 2 and output.read_bytes() == result_bytes
    new_output = tmp_path / "new-output.json"
    assert runner.main(cli_args(cli_environment, new_output)) == 2
    assert json.loads(new_output.read_text())["schema"] == "proposal-development-results-v1"
    assert len(calls) == 4 and runner.proposal_journal_path().read_bytes() == ledger_bytes
    assert runner.extractive_journal_path().name == "extractive-development-v1.calls.jsonl"


@pytest.mark.parametrize("drift", ["code", "context", "source", "settings"])
def test_provenance_drift_stops_after_one_submission(cli_environment, settings, journal, monkeypatch, drift):
    identity, calls = ["a" * 64], []
    monkeypatch.setattr(runner.previous, "git_provenance", lambda *_: {})
    monkeypatch.setattr(runner.previous, "dependency_identity", lambda *_: {})
    monkeypatch.setattr(runner.previous, "_source_hashes", lambda *_: {"src/mock.py": identity[0]})
    monkeypatch.setattr(runner, "sha256_file", lambda *_: identity[0])
    bundle = runner.load_proposal_dataset(*cli_environment[2:])

    def create(**request):
        calls.append(True)
        response = response_for(request)
        if drift == "code":
            identity[0] = "b" * 64
        elif drift == "settings":
            settings["timeout_seconds"] += 1
        else:
            path = cli_environment[1 if drift == "context" else 0]
            path.write_bytes(path.read_bytes() + b"\n")
        return response

    result = run(
        bundle,
        settings,
        journal,
        create,
        provenance=lambda: runner.proposal_provenance(*cli_environment[2:], settings, settings["model"]),
    )
    assert len(calls) == 1 and result["fatal_stop_reason"] == "provenance_drift"
    assert result["summary"]["not_run_slots"] == 9
