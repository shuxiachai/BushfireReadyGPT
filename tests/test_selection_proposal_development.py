"""Offline causal-chain SDK checks; no real credentials, quota DB or API access."""

import copy
import hashlib
import json
import threading

import pytest

from scripts import atomic_claim_adapter as adapter
from scripts import evaluate_atomic_claim_deepseek as runner
from scripts import selection_proposal_development as chain
from src.model_evidence import json_sha256, text_sha256
from src.model_limits import ModelAllowanceError
from tests.test_atomic_claim_adapter import Slot, sdk_client, sdk_response
from tests.test_extractive_development import dataset as dataset
from tests.test_extractive_development import journal as journal
from tests.test_extractive_development import no_dotenv as no_dotenv
from tests.test_extractive_development import settings as settings


@pytest.fixture
def raw_source(dataset, monkeypatch):
    raw = json.dumps(dataset).encode()
    monkeypatch.setattr(chain, "SOURCE_SHA256", hashlib.sha256(raw).hexdigest())
    return raw


@pytest.fixture
def bundle(raw_source):
    return chain.prepare_dataset(raw_source)


def response_for(request, *, requires_only=False, selection_null=False):
    visible = json.loads(request["messages"][1]["content"])
    if "selected_ref_by_section" in visible:
        items = []
        for section, ref in visible["selected_ref_by_section"].items():
            proposal = {"kind": "requires_evidence"}
            if ref is not None and not requires_only:
                proposal = {"kind": "draft_for_review", "text": "Independent review required.", "declared_refs": [ref]}
            items.append({"section_id": int(section), "proposal": proposal})
    else:
        refs = [visible["catalog"][0]["passage_ref"], visible["catalog"][1]["passage_ref"], None]
        if selection_null:
            refs = [None] * 3
        items = [
            {
                "section_id": section,
                "selected_passage_ref": ref,
                "selection_note": None if ref else "SELECTION_NOTE_SENTINEL",
                "proposal": "SELECTION_PROPOSAL_SENTINEL",
                "local_unknowns": ["SELECTION_UNKNOWN_SENTINEL"],
            }
            for section, ref in zip((7, 11, 12), refs, strict=True)
        ]
    return sdk_response(" \n" + json.dumps({"items": items}, indent=2) + "\n ")


class Harness:
    def __init__(self, create=response_for):
        self.calls, self.consumed, self.create = [], 0, create
        self.day, self.status, self.error = "2026-09-27", "ready", None

    def snapshot(self):
        return {
            "status": self.status,
            "day": self.day,
            "calls": self.consumed,
            "process_daily_call_limit": 4,
            "process_concurrency_limit": 1,
        }

    def slot(self):
        owner = self

        class CountedSlot(Slot):
            def consume_call(self):
                super().consume_call()
                owner.consumed += 1

        return CountedSlot(self.error)

    def factory(self):
        def create(**request):
            self.calls.append(copy.deepcopy(request))
            return self.create(request)

        return sdk_client(create)

    def invoke(self, request, pack, binding, **kwargs):
        return adapter.invoke_once(request, pack, binding, **kwargs, acquire_slot=self.slot)

    def run(self, bundle, settings, journal, **kwargs):
        return chain.run_suite(
            bundle,
            settings,
            journal,
            provenance=kwargs.pop("provenance", lambda: {}),
            usage_snapshot=kwargs.pop("usage_snapshot", self.snapshot),
            client_factory=self.factory,
            invoke=kwargs.pop("invoke", self.invoke),
            **kwargs,
        )


def assert_denominators(result):
    assert [row["case_id"] for row in result["rows"]] == ["D2", "D3"]
    assert [stage["stage"] for row in result["rows"] for stage in row["stages"]] == ["selection", "proposal"] * 2
    summary = result["summary"]
    assert (summary["total_cases"], summary["total_slots"], summary["planned_stages"]) == (2, 6, 4)
    assert summary["evaluable_slots"] + summary["unevaluable_slots"] == 6


def test_two_actual_stages_use_original_scene_and_only_validated_selection(bundle, settings, journal):
    harness = Harness()
    result = harness.run(bundle, settings, journal)
    assert result["valid"] and result["schema"] == chain.RESULT_SCHEMA
    assert_denominators(result)
    assert result["sdk_started_count"] == result["allowance_consumed_count"] == result["ledger_reserved_count"] == 4
    assert len(harness.calls) == 4
    assert result["summary"]["contract_valid_cases"] == 2
    assert result["summary"]["null_primary_slots"] == 2
    assert result["summary"]["nonnull_primary_slots"] == result["summary"]["nonnull_draft_slots"] == 4
    assert result["summary"]["evaluable_slots"] == 6
    assert result["quota_initial"]["calls"] == 0 and result["quota_checks"][-1]["snapshot"]["calls"] == 4
    for row, case in zip(result["rows"], bundle["cases"], strict=True):
        selection, proposal = row["stages"]
        first, second = [stage["invocation_capture"] for stage in row["stages"]]
        first_body, second_body = [
            json.loads(capture["invocation_kwargs"]["messages"][1]["content"]) for capture in (first, second)
        ]
        assert first_body["scenario"] == second_body["scenario"]
        assert first_body["section_focus"] == second_body["section_focus"] == bundle["section_focus"]
        assert second_body["task_focus"] == case["scenario"]["task_focus"]
        assert "SENTINEL" in selection["assistant_content"] and "SENTINEL" not in json.dumps(second_body)
        assert second_body["selected_ref_by_section"] == row["selected_ref_by_section"]
        assert second["parent_selection_invocation_sha256"] == first["invocation_sha256"]
        assert second["parent_selection_raw_sha256"] == text_sha256(selection["assistant_content"])
        assert second["handoff_sha256"] == row["handoff_sha256"]
        assert second["case_scene_sha256"] == json_sha256(row["case_scene"])
        assert second["response_sha256"] == text_sha256(proposal["assistant_content"])
        for forbidden in ("evaluation_origin", "model_calls", "transport_capture", "renderer"):
            assert forbidden not in row["chain_check"]
        assert row["chain_check"]["proposal_review"]["semantic_support"] == "unknown"
    assert "expected_refs" not in json.dumps(bundle)
    assert "expected_refs" not in json.dumps(harness.calls)


def test_all_null_from_model_changes_denominators_without_filling_previous_targets(bundle, settings, journal):
    result = Harness(lambda request: response_for(request, selection_null=True)).run(bundle, settings, journal)
    assert result["summary"]["null_primary_slots"] == 6
    assert result["summary"]["nonnull_primary_slots"] == 0
    assert result["summary"]["nonnull_draft_slots"] == 0
    assert result["summary"]["null_requires_evidence_slots"] == 6
    assert "selection_targets_agreeing" not in json.dumps(result)


@pytest.mark.parametrize(
    "stage,kind,calls",
    [
        (0, "schema", 3),
        (0, "length", 3),
        (1, "schema", 4),
        (0, "tool_calls", 1),
        (1, "transport", 2),
        (0, "refusal", 1),
    ],
)
def test_ordinary_failure_skips_proposal_while_fatal_stops_batch(bundle, settings, journal, stage, kind, calls):
    harness = Harness()

    def create(request):
        response = response_for(request)
        if len(harness.calls) == stage + 1:
            if kind == "schema":
                response.choices[0].message.content = '{"items":[]}'
            elif kind == "transport":
                raise RuntimeError("SECRET_TRANSPORT_TEXT")
            elif kind == "refusal":
                response.choices[0].message.refusal = "not allowed"
            else:
                response.choices[0].finish_reason = kind
        return response

    harness.create = create
    result = harness.run(bundle, settings, journal)
    assert len(harness.calls) == calls
    assert_denominators(result)
    assert result["rows"][0]["status"] == "failed"
    assert result["rows"][1]["status"] == ("validated" if kind in {"schema", "length"} else "not_run")
    if stage == 0:
        assert result["rows"][0]["stages"][1]["status"] == "not_run"
    assert "SECRET_TRANSPORT_TEXT" not in json.dumps(result)


@pytest.mark.parametrize("damage", ["request", "raw", "projection", "parent", "case", "pack", "admission", "inflight"])
def test_actual_capture_and_projection_rechecked_not_status_only(bundle, settings, journal, damage):
    harness = Harness()

    def invoke(request, pack, binding, **kwargs):
        record = harness.invoke(request, pack, binding, **kwargs)
        if binding["stage"] == "proposal":
            capture = record["invocation_capture"]
            if damage == "request":
                capture["invocation_kwargs"]["messages"][1]["content"] = "{}"
                capture["invocation_sha256"] = json_sha256(capture["invocation_kwargs"])
            elif damage == "raw":
                record["assistant_content"] += " "
            elif damage == "projection":
                record["proposal_check"]["semantic_support"] = "supported"
            elif damage == "parent":
                capture["parent_selection_invocation_sha256"] = "a" * 64
            elif damage == "case":
                capture["case_scene_sha256"] = "a" * 64
            elif damage == "pack":
                record["evidence_pack"] = bundle["cases"][1]["evidence_pack"]
            elif damage == "admission":
                record["allowance_consumed"] = False
            else:
                record["inflight_unknown"] = True
        return record

    result = harness.run(bundle, settings, journal, invoke=invoke)
    assert not result["valid"] and len(harness.calls) == 2
    assert result["rows"][0]["stages"][1]["assistant_content"]
    assert result["summary"]["evaluable_slots"] == 0
    assert result["rows"][1]["status"] == "not_run"


@pytest.mark.parametrize("when,damage", [(1, "source"), (4, "source"), (4, "settings"), (4, "provenance")])
def test_after_last_stage_drift_keeps_capture_but_invalidates_chain(bundle, settings, journal, when, damage):
    identity = ["a"]
    harness = Harness()

    def create(request):
        response = response_for(request)
        if len(harness.calls) == when:
            if damage == "source":
                bundle["cases"][-1]["scenario"]["task_focus"] += " changed"
            elif damage == "settings":
                settings["timeout_seconds"] += 1
            else:
                identity[0] = "b"
        return response

    harness.create = create
    result = harness.run(bundle, settings, journal, provenance=lambda: {"identity": identity[0]})
    assert not result["valid"] and len(harness.calls) == when
    assert result["summary"]["evaluable_slots"] == 0
    assert result["summary"]["contract_valid_cases"] == 0
    active = result["rows"][1 if when == 4 else 0]
    assert active["status"] == "failed" and active["stages"][1 if when == 4 else 0]["invocation_capture"]


@pytest.mark.parametrize("damage", ["day", "count", "unavailable"])
def test_quota_drift_stops_without_resetting_or_retry(bundle, settings, journal, damage):
    harness = Harness()

    def create(request):
        response = response_for(request)
        if damage == "day":
            harness.day = "2026-09-28"
        elif damage == "count":
            harness.consumed += 1
        else:
            harness.status = "unavailable"
        return response

    harness.create = create
    result = harness.run(bundle, settings, journal)
    assert not result["valid"] and len(harness.calls) == 1
    assert result["fatal_stop_reason"].startswith("chain_quota_")
    assert_denominators(result)


@pytest.mark.parametrize("failure", ["reservation", "completion", "quota", "initial_provenance"])
def test_journal_and_preflight_failure_preserve_planned_denominators(bundle, settings, journal, monkeypatch, failure):
    harness = Harness()
    original = journal.append

    def append(**entry):
        if failure == "reservation" or entry["event"] == "stage_complete":
            raise OSError("sensitive log error")
        return original(**entry)

    if failure in {"reservation", "completion"}:
        monkeypatch.setattr(journal, "append", append)
    if failure == "quota":
        harness.error = ModelAllowanceError("quota error")
    provenance = (lambda: (_ for _ in ()).throw(OSError("private"))) if failure == "initial_provenance" else lambda: {}
    result = harness.run(bundle, settings, journal, provenance=provenance)
    assert not result["valid"]
    assert len(harness.calls) == (failure == "completion")
    assert result["ledger_reserved_count"] == (failure in {"completion", "quota"})
    if failure == "completion":
        assert result["rows"][0]["stages"][0]["assistant_content"]
    assert_denominators(result)
    assert result["summary"]["evaluable_slots"] == 0


def test_timeout_keeps_resource_until_worker_finishes_and_result_is_frozen(bundle, settings, journal):
    started, release, slot = threading.Event(), threading.Event(), Slot()
    clock, clients = [0.0], []
    harness = Harness()

    def create(request):
        started.set()
        assert release.wait(2)
        return response_for(request)

    harness.create = create

    def factory():
        client = harness.factory()
        clients.append(client)
        return client

    def waiter(_event, _seconds):
        assert started.wait(1)
        clock[0] = 20.0
        return False

    def invoke(request, pack, binding, **kwargs):
        harness.consumed += 1
        return adapter.invoke_once(
            request, pack, binding, **kwargs, acquire_slot=lambda: slot, clock=lambda: clock[0], waiter=waiter
        )

    result = chain.run_suite(
        bundle,
        settings,
        journal,
        provenance=lambda: {},
        usage_snapshot=harness.snapshot,
        client_factory=factory,
        invoke=invoke,
    )
    assert result["fatal_stop_reason"] == "timeout" and len(harness.calls) == 1
    assert not slot.released.is_set() and not clients[0].closed.is_set()
    assert result["summary"]["not_run_stages"] == 3
    frozen = copy.deepcopy(result)
    release.set()
    assert slot.released.wait(1) and result == frozen


@pytest.fixture
def cli_environment(tmp_path, monkeypatch, raw_source, settings):
    source = tmp_path / "source.json"
    source.write_bytes(raw_source)
    (tmp_path / "output").mkdir()
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "EXTRACTIVE_DATASET_PATH", source)
    monkeypatch.setattr(chain, "execution_provenance", lambda *_: {})
    return source


def cli_args(output):
    return [
        "--protocol",
        chain.PROTOCOL,
        "--expected-dataset-sha256",
        chain.SOURCE_SHA256,
        "--run-model",
        "--allow-external-deepseek",
        "--model",
        "deepseek-v4-flash",
        "--output",
        str(output),
    ]


def test_cli_auth_precedes_source_read_and_other_context_arguments_rejected(cli_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(chain, "load_dataset", lambda *_: pytest.fail("source must not be read"))
    args = cli_args(tmp_path / "result.json")
    args.remove("--run-model")
    assert runner.main(args) == 2
    for extra in (
        ["--prepared", "wrong"],
        ["--root-example-follow-up"],
        ["--max-calls", "5"],
        ["--expected-context-sha256", "a" * 64],
    ):
        with pytest.raises(SystemExit):
            runner.main(cli_args(tmp_path / "none.json") + extra)


def test_fixed_ledger_never_reopens_when_output_changes(cli_environment, tmp_path, monkeypatch):
    harness = Harness()
    monkeypatch.setattr(runner, "chain_usage_snapshot", harness.snapshot)
    monkeypatch.setattr(adapter, "create_sdk", lambda _: harness.factory())
    original = chain.run_suite
    monkeypatch.setattr(chain, "run_suite", lambda *args, **kwargs: original(*args, **kwargs, invoke=harness.invoke))
    for protected in (cli_environment, runner.chain_journal_path()):
        assert runner.main(cli_args(protected)) == 2
    assert harness.calls == []
    output = tmp_path / "first.json"
    assert runner.main(cli_args(output)) == 0
    ledger = runner.chain_journal_path().read_bytes()
    first = output.read_bytes()
    assert runner.main(cli_args(output)) == 2 and output.read_bytes() == first
    another = tmp_path / "other.json"
    assert runner.main(cli_args(another)) == 2
    result = json.loads(another.read_text(encoding="utf-8"))
    assert_denominators(result)
    assert result["summary"]["not_run_stages"] == 4
    assert runner.chain_journal_path().read_bytes() == ledger and len(harness.calls) == 4


def test_run_claim_fsync_failure_keeps_four_stage_placeholders(cli_environment, tmp_path, monkeypatch):
    monkeypatch.setattr(runner.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("private")))
    output = tmp_path / "result.json"
    assert runner.main(cli_args(output)) == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert_denominators(result)
    assert result["ledger_reserved_count"] == result["sdk_started_count"] == 0
    assert result["summary"]["not_run_stages"] == 4


def test_budget_is_hard_four_and_lower_ceiling_cannot_complete_case(bundle, settings, journal):
    harness = Harness()
    result = harness.run(bundle, settings, journal, max_calls=1)
    assert not result["valid"] and len(harness.calls) == 1
    assert result["summary"]["evaluable_slots"] == 0
    assert result["fatal_stop_reason"] == "batch_budget_exhausted"
    assert runner.MAX_CALLS == 2 and runner.MAX_EXTRACTIVE_CALLS == runner.MAX_PROPOSAL_CALLS == 4


@pytest.mark.parametrize("mutation", ["end_provenance", "completed_parent", "current_raw", "current_capture"])
def test_guard_callbacks_cannot_change_admitted_or_completed_records(bundle, settings, journal, monkeypatch, mutation):
    harness = Harness()
    records, original = [], chain._verify_record

    def verify(record, *args):
        original(record, *args)
        records.append(record)

    monkeypatch.setattr(chain, "_verify_record", verify)
    checks = [0]

    def provenance():
        checks[0] += 1
        if mutation == "end_provenance" and checks[0] == 10:
            return {"code": "changed"}
        if mutation == "completed_parent" and checks[0] == 6:
            records[0]["assistant_content"] += " "
        if mutation == "current_raw" and checks[0] == 3:
            records[0]["assistant_content"] += " "
        if mutation == "current_capture" and checks[0] == 3:
            records[0]["invocation_capture"]["case_scene_sha256"] = "a" * 64
        return {"code": "initial"}

    result = harness.run(bundle, settings, journal, provenance=provenance)
    assert not result["valid"]
    assert result["summary"]["contract_valid_cases"] == result["summary"]["evaluable_slots"] == 0
    assert (
        len(harness.calls)
        == {"end_provenance": 4, "completed_parent": 2, "current_raw": 1, "current_capture": 1}[mutation]
    )
    assert result["rows"][0]["stages"][0]["invocation_capture"]


def test_completion_callback_mutation_fails_before_next_sdk(bundle, settings, journal, monkeypatch):
    harness, records = Harness(), []
    original_verify, original_append = chain._verify_record, journal.append

    def verify(record, *args):
        original_verify(record, *args)
        records.append(record)

    def append(**entry):
        original_append(**entry)
        if entry["event"] == "stage_complete":
            records[-1]["assistant_content"] += " "

    monkeypatch.setattr(chain, "_verify_record", verify)
    monkeypatch.setattr(journal, "append", append)
    result = harness.run(bundle, settings, journal)
    assert not result["valid"] and len(harness.calls) == 1
    assert result["fatal_stop_reason"] == "chain_parent_record_drift"


def test_ledger_close_failure_preserves_four_sdk_records(cli_environment, tmp_path, monkeypatch):
    from pathlib import Path

    harness = Harness()
    monkeypatch.setattr(runner, "chain_usage_snapshot", harness.snapshot)
    monkeypatch.setattr(adapter, "create_sdk", lambda _: harness.factory())
    original_run, original_open = chain.run_suite, Path.open
    monkeypatch.setattr(
        chain, "run_suite", lambda *args, **kwargs: original_run(*args, **kwargs, invoke=harness.invoke)
    )

    class BrokenClose:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()
            raise OSError("private close failure")

    def open_path(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return BrokenClose(handle) if path == runner.chain_journal_path() else handle

    monkeypatch.setattr(Path, "open", open_path)
    output = tmp_path / "result.json"
    assert runner.main(cli_args(output)) == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert_denominators(result)
    assert len(harness.calls) == result["sdk_started_count"] == result["ledger_reserved_count"] == 4
    assert all(
        stage["assistant_content"] and stage["invocation_capture"] for row in result["rows"] for stage in row["stages"]
    )
    assert result["summary"]["evaluable_slots"] == 0 and result["finalization_error"] == "run_or_journal_failed"


@pytest.mark.parametrize("after_transport", [False, True])
def test_configuration_and_late_drift_after_transport_invalidate_all_chains(bundle, settings, journal, after_transport):
    harness, checks = Harness(), [0]

    def create(request):
        if after_transport and len(harness.calls) == 3:
            raise RuntimeError("private transport error")
        return response_for(request)

    def provenance():
        checks[0] += 1
        if checks[0] == (8 if after_transport else 10):
            raise runner.previous.ExperimentBlocked("execution_configuration_drift")
        return {}

    harness.create = create
    result = harness.run(bundle, settings, journal, provenance=provenance)
    assert not result["valid"] and len(harness.calls) == (3 if after_transport else 4)
    assert result["summary"]["contract_valid_cases"] == result["summary"]["evaluable_slots"] == 0
    assert any(check.get("error_code") == "execution_configuration_drift" for check in result["provenance_checks"])
