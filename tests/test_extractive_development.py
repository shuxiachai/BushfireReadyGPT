"""Four-case synthetic SDK validation; no existing dataset, credentials or API use."""

import copy
import json
import threading

import pytest

from scripts import atomic_claim_adapter as adapter
from scripts import atomic_claim_contract as contract
from scripts import evaluate_atomic_claim_deepseek as runner
from scripts import extractive_development as development
from src.model_evidence import json_sha256
from tests.test_atomic_claim_adapter import Slot, sdk_client, sdk_response


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")


@pytest.fixture
def settings(monkeypatch):
    for key, value in {
        "LLM_PROVIDER": "deepseek",
        "BUSHFIRE_ALLOW_EXTERNAL_MODEL": "true",
        "DEEPSEEK_API_KEY": "synthetic-key",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "BUSHFIRE_MODEL_MAX_TOKENS": "2300",
        "BUSHFIRE_MODEL_TEMPERATURE": "0.2",
        "BUSHFIRE_MODEL_TIMEOUT_SECONDS": "10",
    }.items():
        monkeypatch.setenv(key, value)
    return runner.previous._settings("deepseek-v4-flash")


@pytest.fixture
def dataset():
    cases = []
    for index in range(1, 5):
        cases.append(
            {
                "id": f"D{index}",
                "scenario": {
                    "region": f"Synthetic D{index}",
                    "audience": "Fictional team",
                    "task_focus": "Review the supplied fictional units; local facts are unknown.",
                },
                "units": [
                    {"id": "u01", "text": "Keep equipment contacts current. Assign an owner for review."},
                    {"id": "u02", "text": "Use accessible notices. Confirm required formats locally."},
                    {"id": "u03", "text": "The archive sorts labels by year."},
                ],
                "expected_refs": {"7": ["u01"], "11": ["u02", None], "12": [None]},
            }
        )
    cases[-1]["expected_refs"] = {"7": [None], "11": [None], "12": [None]}
    return {
        "schema": development.DATASET_SCHEMA,
        "dataset_id": development.PROTOCOL,
        "data_origin": "synthetic_development",
        "section_focus": {"7": "Equipment", "11": "Communication", "12": "First aid training"},
        "cases": cases,
    }


@pytest.fixture
def bundle(dataset):
    return development.prepare_dataset(json.dumps(dataset))


@pytest.fixture
def journal(tmp_path):
    with (tmp_path / "extractive.calls.jsonl").open("x", encoding="utf-8") as handle:
        yield runner.Journal(handle)


def mock_invoke(request, pack, binding, **kwargs):
    return adapter.invoke_once(request, pack, binding, **kwargs, acquire_slot=Slot)


def response_for(request, bundle):
    visible = json.loads(request["messages"][1]["content"])
    case = next(case for case in bundle["cases"] if case["development_case"]["scenario"] == visible["scenario"])
    items = []
    for section, refs in case["expected_passage_refs"].items():
        ref = refs[0]
        items.append(
            {
                "section_id": int(section),
                "selected_passage_ref": ref,
                "selection_note": None if ref else "No unit selected; local relevance is unverified.",
                "proposal": "Proposed local review.",
                "local_unknowns": ["Who is locally responsible?"],
            }
        )
    return sdk_response(" \n" + json.dumps({"items": items}, indent=2) + "\n ")


def test_expected_labels_never_enter_sdk_request(dataset, bundle):
    case = bundle["cases"][0]
    request, typed = development.build_request(case, bundle["section_focus"], "deepseek-v4-flash")
    visible = json.loads(request["messages"][1]["content"])
    assert set(visible) == {"scenario", "section_focus", "requested_sections", "catalog", "output_json_schema"}
    assert set(visible["scenario"]) == {"region", "audience", "task_focus"}
    assert "expected_refs" not in json.dumps(request) and "expected_passage_refs" not in json.dumps(request)
    assert "synthetic_offline" not in json.dumps(request) and "offline" not in request["messages"][0]["content"].lower()
    changed = copy.deepcopy(dataset)
    changed["cases"][0]["expected_refs"]["7"] = ["u03"]
    changed_bundle = development.prepare_dataset(json.dumps(changed))
    other, _ = development.build_request(
        changed_bundle["cases"][0], changed_bundle["section_focus"], "deepseek-v4-flash"
    )
    assert request == other and case["development_case_sha256"] != changed_bundle["cases"][0]["development_case_sha256"]
    assert typed.to_dict()["evidence_pack_sha256"] == case["evidence_pack"]["evidence_pack_sha256"]


@pytest.mark.parametrize(
    "mutation", ["root_extra", "case_extra", "unit_extra", "missing_case", "wrong_id", "unknown_label", "too_long"]
)
def test_dataset_is_strict_and_bounded(dataset, mutation):
    if mutation == "root_extra":
        dataset["rubric_sentinel"] = "must not become prompt data"
    elif mutation == "case_extra":
        dataset["cases"][0]["rubric_sentinel"] = "private"
    elif mutation == "unit_extra":
        dataset["cases"][0]["units"][0]["source_url"] = "unallowed"
    elif mutation == "missing_case":
        dataset["cases"].pop()
    elif mutation == "wrong_id":
        dataset["cases"][0]["id"] = "D5"
    elif mutation == "unknown_label":
        dataset["cases"][0]["expected_refs"]["7"] = ["u99"]
    else:
        dataset["cases"][0]["units"][0]["text"] = "x" * 2201
    with pytest.raises(contract.ContractError):
        development.prepare_dataset(json.dumps(dataset))


@pytest.mark.parametrize("boundary", ["tool_calls", "length", "refusal", "unicode", "role", "index", "choices"])
def test_content_callback_never_bypasses_response_admission(bundle, boundary):
    pack = bundle["cases"][0]["evidence_pack"]
    response = sdk_response("{}")
    choice = response.choices[0]
    if boundary in {"tool_calls", "length"}:
        choice.finish_reason = boundary
    elif boundary == "refusal":
        choice.message.refusal = "Synthetic refusal"
    elif boundary == "unicode":
        choice.message.content = chr(0xD800)
    elif boundary == "role":
        choice.message.role = "user"
    elif boundary == "index":
        choice.index = True
    else:
        response.choices *= 2
    result = adapter.check_response(
        response, pack, content_validator=lambda *_: pytest.fail("Admission must run first")
    )
    assert result["status"] == "failed" and "extractive_check" not in result


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "fatal_reason",
        "assistant_content",
        "assistant_content_sha256",
        "metadata",
        "response_origin",
        "invocation_capture",
    ],
)
def test_callback_cannot_override_transport_fields(bundle, field):
    response = sdk_response("{}")
    result = adapter.check_response(
        response,
        bundle["cases"][0]["evidence_pack"],
        content_validator=lambda *_: {"extractive_check": {}, field: "forged"},
    )
    assert result["fatal_reason"] == "content_validator_boundary_rejected"
    assert result["assistant_content"] == "{}" and result["response_origin"] == "remote_model"
    assert result["metadata"]["provider_reported_model"] == "provider-alias"


def test_callback_errors_and_mutations_are_isolated(bundle):
    pack = bundle["cases"][0]["evidence_pack"]
    before = copy.deepcopy(pack)

    def mutate(_raw, detached):
        detached["passages"][0]["text"] = "mutated copy"
        return {"extractive_check": {"manual_review_required": True}}

    assert adapter.check_response(sdk_response("{}"), pack, content_validator=mutate)["status"] == "validated"
    assert pack == before
    for error in (RuntimeError("sensitive"), adapter.SelectionError("unexpected")):
        result = adapter.check_response(
            sdk_response("{}"), pack, content_validator=lambda *_: (_ for _ in ()).throw(error)
        )
        assert result["fatal_reason"] == "content_validator_failed" and "sensitive" not in json.dumps(result)
    result = adapter.check_response(
        sdk_response("{}"),
        pack,
        content_validator=lambda *_: (_ for _ in ()).throw(contract.ContractError("synthetic")),
    )
    assert result["status"] == "failed" and result["fatal_reason"] is None


def test_four_mock_calls_preserve_remote_identity_and_project_only_whitelisted_fields(bundle, settings, journal):
    calls = []

    def create(**request):
        calls.append(copy.deepcopy(request))
        return response_for(request, bundle)

    result = runner.run_extractive_suite(
        bundle, settings, journal, provenance=lambda: {}, invoke=mock_invoke, client_factory=lambda: sdk_client(create)
    )
    assert result["valid"] and result["sdk_started_count"] == result["ledger_reserved_count"] == len(calls) == 4
    assert result["summary"]["total_cases"] == result["summary"]["contract_valid_cases"] == 4
    assert result["summary"]["selection_targets_agreeing"] == 12 and result["semantic_accuracy"] is None
    for row in result["rows"]:
        assert row["response_origin"] == "remote_model" and row["assistant_content"].startswith(" \n")
        assert row["invocation_capture"]["invocation_sha256"] == json_sha256(
            row["invocation_capture"]["invocation_kwargs"]
        )
        assert "origin" not in row["extractive_check"] and "model_calls" not in row["extractive_check"]
        assert "transport_capture" not in row["extractive_check"]
        assert row["extractive_check"]["unit_complete_scope"] == "recorded_visible_passage_only"
        assert row["elapsed_seconds"] >= 0 and row["timing_scope"].startswith("invoke_once")
    assert runner.MAX_CALLS == 2 and runner.MAX_EXTRACTIVE_CALLS == 4
    with pytest.raises(runner.previous.ExperimentBlocked, match="invalid_call_budget"):
        runner.run_extractive_suite(bundle, settings, journal, provenance=lambda: {}, max_calls=5)
    with pytest.raises(runner.previous.ExperimentBlocked, match="invalid_call_budget"):
        runner.run_suite(bundle, settings, journal, provenance=lambda: {}, max_calls=4)


@pytest.mark.parametrize("first_reason,expected_calls", [("length", 4), ("tool_calls", 1)])
def test_no_retry_and_fatal_boundary_stops_remaining_cases(bundle, settings, journal, first_reason, expected_calls):
    calls = []

    def create(**request):
        calls.append(True)
        response = response_for(request, bundle)
        if len(calls) == 1:
            response.choices[0].finish_reason = first_reason
        return response

    result = runner.run_extractive_suite(
        bundle, settings, journal, provenance=lambda: {}, invoke=mock_invoke, client_factory=lambda: sdk_client(create)
    )
    assert len(calls) == expected_calls and result["summary"]["total_cases"] == 4
    assert result["summary"]["failed_cases"] == 1
    assert result["summary"]["not_run_cases"] == 4 - expected_calls


def test_last_case_memory_label_drift_fails_closed_and_target_lists_are_detached(bundle, settings, journal):
    calls = []

    def create(**request):
        calls.append(True)
        response = response_for(request, bundle)
        if len(calls) == 4:
            bundle["cases"][-1]["expected_passage_refs"]["7"] = ["forged"]
        return response

    result = runner.run_extractive_suite(
        bundle, settings, journal, provenance=lambda: {}, invoke=mock_invoke, client_factory=lambda: sdk_client(create)
    )
    assert not result["valid"] and result["rows"][-1]["status"] == "failed"
    case = result["development_input_origin"]["cases"][0]
    check = development.target_agreement(result["rows"][0], case)
    before = copy.deepcopy(check)
    case["expected_passage_refs"]["7"].append("changed-after-return")
    assert check == before


def test_late_timeout_keeps_slot_and_never_validates_or_dispatches_case_two(bundle, settings, journal):
    started, release, slot = threading.Event(), threading.Event(), Slot()
    clock, calls, callback_calls, clients = [0.0], [], [], []

    def create(**request):
        calls.append(True)
        started.set()
        assert release.wait(2)
        return response_for(request, bundle)

    def factory():
        client = sdk_client(create)
        clients.append(client)
        return client

    def waiter(_event, _seconds):
        assert started.wait(1)
        clock[0] = 20.0
        return False

    def invoke(request, pack, binding, **kwargs):
        check = kwargs.pop("content_validator")

        def observed(raw, evidence):
            callback_calls.append(True)
            return check(raw, evidence)

        return adapter.invoke_once(
            request,
            pack,
            binding,
            **kwargs,
            content_validator=observed,
            acquire_slot=lambda: slot,
            clock=lambda: clock[0],
            waiter=waiter,
        )

    result = runner.run_extractive_suite(
        bundle, settings, journal, provenance=lambda: {}, invoke=invoke, client_factory=factory
    )
    assert len(calls) == 1 and result["summary"]["not_run_cases"] == 3 and result["fatal_stop_reason"] == "timeout"
    assert not slot.released.is_set() and not clients[0].closed.is_set()
    before = copy.deepcopy(result)
    journal.handle.close()
    release.set()
    assert slot.released.wait(1) and callback_calls == []
    assert result == before


@pytest.fixture
def cli_environment(tmp_path, monkeypatch, dataset, settings):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")
    (tmp_path / "output").mkdir()
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "EXTRACTIVE_DATASET_PATH", path)
    return path, runner.sha256_file(path)


def cli_args(cli_environment, output):
    return [
        "--protocol",
        development.PROTOCOL,
        "--expected-dataset-sha256",
        cli_environment[1],
        "--run-model",
        "--allow-external-deepseek",
        "--model",
        "deepseek-v4-flash",
        "--output",
        str(output),
    ]


def test_new_protocol_is_exclusive_and_authorization_precedes_dataset_read(cli_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "load_extractive_dataset", lambda *_: pytest.fail("No read before admission"))
    args = cli_args(cli_environment, tmp_path / "not-created.json")
    args.remove("--run-model")
    assert runner.main(args) == 2
    with pytest.raises(SystemExit):
        runner.main(cli_args(cli_environment, tmp_path / "none.json") + ["--prepared", "wrong"])
    with pytest.raises(SystemExit):
        runner.main(cli_args(cli_environment, tmp_path / "none.json") + ["--root-example-follow-up"])
    with pytest.raises(SystemExit):
        runner.main(cli_args(cli_environment, tmp_path / "none.json") + ["--max-calls", "5"])


def test_fixed_ledger_never_resets_with_output_or_dataset_changes(cli_environment, tmp_path, monkeypatch, settings):
    calls = []
    original = runner.run_extractive_suite
    bundle = runner.load_extractive_dataset(cli_environment[1])
    monkeypatch.setattr(runner, "extractive_provenance", lambda *_: {"stable": True})

    def create(**request):
        calls.append(True)
        return response_for(request, bundle)

    monkeypatch.setattr(
        runner,
        "run_extractive_suite",
        lambda *args, **kwargs: original(
            *args, **kwargs, invoke=mock_invoke, client_factory=lambda: sdk_client(create)
        ),
    )
    output = tmp_path / "result.json"
    assert runner.main(cli_args(cli_environment, output)) == 0 and len(calls) == 4
    ledger = runner.extractive_journal_path()
    original_bytes = ledger.read_bytes()
    assert ledger.name == "extractive-development-v1.calls.jsonl"
    assert runner.main(cli_args(cli_environment, tmp_path / "changed-output.json")) == 2
    failed = json.loads((tmp_path / "changed-output.json").read_text(encoding="utf-8"))
    assert failed["schema"] == "extractive-development-results-v1" and failed["protocol"] == development.PROTOCOL
    with cli_environment[0].open("a", encoding="utf-8") as handle:
        handle.write("\n")
    new_identity = cli_environment[0], runner.sha256_file(cli_environment[0])
    assert runner.main(cli_args(new_identity, tmp_path / "new-hash-output.json")) == 2
    assert len(calls) == 4 and ledger.read_bytes() == original_bytes


@pytest.mark.parametrize("drift", ["expected_labels", "source"])
def test_source_or_dataset_label_drift_stops_batch(cli_environment, settings, journal, monkeypatch, drift):
    source = ["a" * 64]
    monkeypatch.setattr(runner.previous, "git_provenance", lambda *_: {"synthetic": True})
    monkeypatch.setattr(runner.previous, "dependency_identity", lambda *_: {"synthetic": True})
    monkeypatch.setattr(runner.previous, "_source_hashes", lambda *_: {"src/synthetic.py": source[0]})
    monkeypatch.setattr(runner, "sha256_file", lambda *_: source[0])
    bundle = runner.load_extractive_dataset(cli_environment[1])
    calls = []

    def create(**request):
        calls.append(True)
        response = response_for(request, bundle)
        if drift == "source":
            source[0] = "b" * 64
        else:
            data = json.loads(cli_environment[0].read_text(encoding="utf-8"))
            data["cases"][0]["expected_refs"]["7"] = ["u03"]
            cli_environment[0].write_text(json.dumps(data), encoding="utf-8")
        return response

    result = runner.run_extractive_suite(
        bundle,
        settings,
        journal,
        provenance=lambda: runner.extractive_provenance(cli_environment[1], settings, settings["model"]),
        invoke=mock_invoke,
        client_factory=lambda: sdk_client(create),
    )
    assert len(calls) == 1 and result["fatal_stop_reason"] == "provenance_drift"
    assert result["summary"]["not_run_cases"] == 3
