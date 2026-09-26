"""Synthetic anchored follow-up fixtures; no SDK or existing artifacts are used."""

import copy
import json
from pathlib import Path

import pytest

from scripts import evaluate_atomic_claim_deepseek as runner
from src.model_evidence import json_sha256, text_sha256
from tests.test_atomic_claim_contract import make_pack


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    root = tmp_path / "synthetic-project"
    (root / "output").mkdir(parents=True)
    monkeypatch.setattr(runner, "PROJECT_ROOT", root)
    pack, analysis, assembly = make_pack()
    cases = []
    for index in (1, 2):
        case = {
            "scenario": {"id": f"case-{index}", "location": "Synthetic locality"},
            "analysis": copy.deepcopy(analysis),
            "rag_context_assembly": copy.deepcopy(assembly),
            "analysis_sha256": json_sha256(analysis),
            "assembly_sha256": json_sha256(assembly),
        }
        case["binding_sha256"] = json_sha256(
            {key: case[key] for key in ("scenario", "analysis", "rag_context_assembly")}
        )
        cases.append(case)
    bundle = {"phase": "seen_pilot", "cases": cases}
    bundle["bundle_sha256"] = json_sha256(bundle)
    prepared = root / "output/prepared.json"
    prepared.write_text(json.dumps(bundle), encoding="utf-8")
    prepared_sha = runner.sha256_file(prepared)
    monkeypatch.setattr(runner, "FOLLOW_UP_PREPARED_SHA256", prepared_sha)
    monkeypatch.setattr(runner, "FOLLOW_UP_SYSTEM_PROMPT_SHA256", text_sha256(runner.adapter.SYSTEM_PROMPT))
    rows = []
    for case in cases:
        request = runner.adapter.build_request(case["scenario"], pack, "deepseek-v4-flash")
        request["messages"][0]["content"] = "Synthetic historical system instruction."
        raw = json.dumps({"type": "json_object", "items": []})
        bindings = {
            "analysis_sha256": case["analysis_sha256"],
            "assembly_sha256": case["assembly_sha256"],
            "case_binding_sha256": case["binding_sha256"],
            "evidence_pack_sha256": pack["evidence_pack_sha256"],
        }
        rows.append(
            {
                "case_id": case["scenario"]["id"],
                "status": "failed",
                "sdk_started": True,
                "allowance_consumed": True,
                "evidence_pack": copy.deepcopy(pack),
                **bindings,
                "assistant_content": raw,
                "assistant_content_sha256": text_sha256(raw),
                "invocation_capture": {
                    **bindings,
                    "invocation_kwargs": request,
                    "invocation_sha256": json_sha256(request),
                    "response_sha256": text_sha256(raw),
                },
            }
        )
    records = [
        {
            "schema": "atomic-selection-calls-v1",
            "event": "run_claim",
            "prepared_file_sha256": prepared_sha,
            "max_calls": 2,
            "model": "deepseek-v4-flash",
        }
    ]
    for index in range(2):
        records.extend(
            [
                {"event": "before_reservation", "sequence": index + 1, "case_index": index},
                {
                    "event": "case_complete",
                    "sequence": index + 1,
                    "case_index": index,
                    "sdk_started": True,
                    "allowance_consumed": True,
                    "status": "failed",
                },
            ]
        )
    parent_journal = runner.journal_path(prepared_sha)
    parent_journal.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    monkeypatch.setattr(runner, "FOLLOW_UP_PARENT_JOURNAL_SHA256", runner.sha256_file(parent_journal))
    parent = {
        "schema": runner.RESULT_SCHEMA,
        "valid": True,
        "production_enabled": False,
        "release_gate": {"active": False},
        "historical_input_origin": copy.deepcopy(bundle),
        "rows": rows,
        "sdk_started_count": 2,
        "allowance_consumed_count": 2,
        "journal": records,
        "summary": {"total_cases": 2, "failed_cases": 2, "not_run_cases": 0, "contract_valid_cases": 0},
    }
    parent_path = root / "output/parent-result.json"
    parent_path.write_text(json.dumps(parent), encoding="utf-8")
    monkeypatch.setattr(runner, "FOLLOW_UP_PARENT_RESULT_PATH", parent_path)
    monkeypatch.setattr(runner, "FOLLOW_UP_PARENT_RESULT_SHA256", runner.sha256_file(parent_path))
    return {
        "root": root,
        "prepared": prepared,
        "sha": prepared_sha,
        "bundle": bundle,
        "parent": parent,
        "parent_path": parent_path,
        "parent_journal": parent_journal,
    }


def args_for(frozen, output, *, follow_up=True):
    args = [
        "--prepared",
        str(frozen["prepared"]),
        "--expected-prepared-file-sha256",
        frozen["sha"],
        "--run-model",
        "--allow-external-deepseek",
        "--model",
        "deepseek-v4-flash",
        "--output",
        str(output),
    ]
    return args + (["--root-example-follow-up"] if follow_up else [])


def mock_runtime(frozen, monkeypatch, *, change_after_call=None):
    settings = {"model": "deepseek-v4-flash", "temperature": 0.2, "max_tokens": 2300, "timeout_seconds": 1}
    monkeypatch.setattr(runner.previous, "admit_environment", lambda **_: settings)
    monkeypatch.setattr(runner.previous, "load_seen_pilot", lambda *_: copy.deepcopy(frozen["bundle"]))
    monkeypatch.setattr(runner, "execution_provenance", lambda *_: {"synthetic": True})
    original = runner.run_suite
    calls = []

    def invoke(request, _pack, _binding, **_kwargs):
        calls.append(copy.deepcopy(request))
        if change_after_call:
            change_after_call()
        return {
            "status": "failed",
            "fatal_reason": None,
            "slot_acquired": True,
            "allowance_consumed": True,
            "sdk_started": True,
            "response_origin": "remote_model",
        }

    def run(*args, **kwargs):
        return original(*args, **kwargs, invoke=invoke, client_factory=lambda: pytest.fail("No SDK in synthetic tests"))

    monkeypatch.setattr(runner, "run_suite", run)
    return calls


def test_fixed_followup_metadata_bindings_and_old_path_are_preserved(frozen):
    before = frozen["parent_path"].read_bytes(), frozen["parent_journal"].read_bytes(), frozen["prepared"].read_bytes()
    meta = runner.validate_root_example_follow_up(frozen["prepared"], frozen["sha"], frozen["bundle"])
    assert meta["follow_up_id"] == "complete-root-example-v1" and meta["additional_call_ceiling"] == 2
    assert meta["old_system_prompt_sha256"] == text_sha256("Synthetic historical system instruction.")
    assert meta["system_prompt_sha256"] == text_sha256(runner.adapter.SYSTEM_PROMPT)
    assert len(meta["case_bindings"]) == 2
    assert runner.journal_path(frozen["sha"]).name == f"atomic-claim-selection-v1-{frozen['sha']}.calls.jsonl"
    assert (
        runner.follow_up_journal_path().name
        == f"atomic-claim-selection-v1-root-example-followup-{frozen['sha']}.calls.jsonl"
    )
    assert before == (
        frozen["parent_path"].read_bytes(),
        frozen["parent_journal"].read_bytes(),
        frozen["prepared"].read_bytes(),
    )


@pytest.mark.parametrize(
    "anchor", ["prepared", "parent_path", "parent_journal", "prompt", "expected_sha", "missing_parent"]
)
def test_wrong_missing_or_changed_anchor_rejects_before_new_output(frozen, monkeypatch, anchor):
    calls = mock_runtime(frozen, monkeypatch)
    expected = frozen["sha"]
    if anchor == "prompt":
        monkeypatch.setattr(runner.adapter, "SYSTEM_PROMPT", runner.adapter.SYSTEM_PROMPT + " changed")
    elif anchor == "expected_sha":
        expected = "0" * 64
    elif anchor == "missing_parent":
        frozen["parent_path"].unlink()
    else:
        with frozen[anchor].open("ab") as handle:
            handle.write(b" ")
    output = frozen["root"] / "output/rejected.json"
    args = args_for(frozen, output)
    args[args.index("--expected-prepared-file-sha256") + 1] = expected
    assert runner.main(args) == 2
    assert calls == [] and not output.exists() and not runner.follow_up_journal_path().exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "invalid_parent",
        "wrong_counts",
        "successful_parent",
        "case_order",
        "pack",
        "capture_hash",
        "model",
        "temperature",
        "user_message",
        "response_format",
        "journal",
    ],
)
def test_anchored_parent_must_meet_narrow_structural_policy(frozen, monkeypatch, mutation):
    parent = copy.deepcopy(frozen["parent"])
    row = parent["rows"][0]
    capture = row["invocation_capture"]
    if mutation == "invalid_parent":
        parent["valid"] = False
    elif mutation == "wrong_counts":
        parent["allowance_consumed_count"] = 1
    elif mutation == "successful_parent":
        parent["summary"]["contract_valid_cases"] = 1
    elif mutation == "case_order":
        parent["rows"].reverse()
    elif mutation == "pack":
        row["evidence_pack"]["passages"][0]["text"] += " changed"
    elif mutation == "capture_hash":
        capture["invocation_sha256"] = "0" * 64
    elif mutation == "journal":
        parent["journal"][-1]["status"] = "validated"
    else:
        request = capture["invocation_kwargs"]
        if mutation == "user_message":
            request["messages"][1]["content"] += " changed"
        elif mutation == "model":
            request["model"] = "another-model"
        elif mutation == "temperature":
            request["temperature"] = 0.3
        else:
            request["response_format"] = {"type": "other"}
        capture["invocation_sha256"] = json_sha256(request)
    frozen["parent_path"].write_text(json.dumps(parent), encoding="utf-8")
    monkeypatch.setattr(runner, "FOLLOW_UP_PARENT_RESULT_SHA256", runner.sha256_file(frozen["parent_path"]))
    with pytest.raises(runner.previous.ExperimentBlocked):
        runner.validate_root_example_follow_up(frozen["prepared"], frozen["sha"], frozen["bundle"])


def test_authorization_precedes_any_followup_anchor_read(frozen, monkeypatch):
    monkeypatch.setattr(runner.previous, "load_seen_pilot", lambda *_: pytest.fail("No input read before flags"))
    monkeypatch.setattr(runner, "_anchored_bytes", lambda *_: pytest.fail("No anchor read before flags"))
    output = frozen["root"] / "output/unauthorized.json"
    args = args_for(frozen, output)
    args.remove("--allow-external-deepseek")
    assert runner.main(args) == 2 and not output.exists()


def test_followup_is_one_fixed_two_call_claim_even_with_new_output(frozen, monkeypatch):
    calls = mock_runtime(frozen, monkeypatch)
    parent_bytes = frozen["parent_journal"].read_bytes()
    output = frozen["root"] / "output/followup.json"
    assert runner.main(args_for(frozen, output)) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert len(calls) == result["sdk_started_count"] == 2
    assert [json.loads(call["messages"][1]["content"])["scenario"]["id"] for call in calls] == ["case-1", "case-2"]
    assert result["follow_up"]["follow_up_id"] == "complete-root-example-v1"
    assert result["journal"][0]["parent_result_sha256"] == runner.FOLLOW_UP_PARENT_RESULT_SHA256
    assert all(check["provenance"]["follow_up"] == result["follow_up"] for check in result["provenance_checks"])
    ledger_bytes = runner.follow_up_journal_path().read_bytes()
    changed_output = frozen["root"] / "output/another-output.json"
    assert runner.main(args_for(frozen, changed_output)) == 2
    assert len(calls) == 2 and runner.follow_up_journal_path().read_bytes() == ledger_bytes
    assert frozen["parent_journal"].read_bytes() == parent_bytes
    assert runner.main(args_for(frozen, output)) == 2
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_no_flag_uses_existing_ledger_and_cannot_spend_again(frozen, monkeypatch):
    calls = mock_runtime(frozen, monkeypatch)
    monkeypatch.setattr(runner, "validate_root_example_follow_up", lambda *_: pytest.fail("No new policy without flag"))
    assert runner.main(args_for(frozen, frozen["root"] / "output/legacy.json", follow_up=False)) == 2
    assert not calls and not runner.follow_up_journal_path().exists()


def test_provenance_rechecks_parent_anchor_and_stops_next_case(frozen, monkeypatch):
    def drift():
        with frozen["parent_journal"].open("ab") as handle:
            handle.write(b" ")

    calls = mock_runtime(frozen, monkeypatch, change_after_call=drift)
    output = frozen["root"] / "output/drift.json"
    assert runner.main(args_for(frozen, output)) == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert len(calls) == 1 and result["fatal_stop_reason"] == "provenance_drift"
    assert result["rows"][1]["status"] == "not_run" and result["summary"]["total_cases"] == 2


def test_followup_cannot_request_more_than_two_calls(frozen, monkeypatch):
    monkeypatch.setattr(
        runner.previous, "admit_environment", lambda **_: pytest.fail("Argument rejected before admission")
    )
    with pytest.raises(SystemExit):
        runner.main(args_for(frozen, Path("never-created.json")) + ["--max-calls", "3"])
