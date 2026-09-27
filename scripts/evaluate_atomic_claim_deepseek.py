"""Bounded private JSON experiments; never a report or production gate."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import atomic_claim_adapter as adapter  # noqa: E402
from scripts import evaluate_body_evidence_deepseek as previous  # noqa: E402
from scripts import selection_proposal_development as chain  # noqa: E402
from scripts.atomic_claim_contract import build_evidence_pack  # noqa: E402
from scripts.evaluation_artifacts import sha256_file  # noqa: E402
from src.model_evidence import json_sha256, text_sha256  # noqa: E402

RESULT_SCHEMA = "atomic-selection-deepseek-results-v1"
MAX_CALLS = 2
MAX_EXTRACTIVE_CALLS = 4
MAX_PROPOSAL_CALLS = 4
EXTRACTIVE_PROTOCOL = "extractive-development-v1"
PROPOSAL_PROTOCOL = "proposal-development-v1"
EXTRACTIVE_DATASET_PATH = PROJECT_ROOT / "data_australia/rag/extractive_development_v1.json"
PROPOSAL_CONTEXT_PATH = PROJECT_ROOT / "data_australia/rag/proposal_development_v1.json"
FOLLOW_UP_ID = "complete-root-example-v1"
FOLLOW_UP_PREPARED_SHA256 = "75f08bbca7909d3e3a65e2ba93adffacc0ff0ae7e640b69bff1f772af98a13c5"
FOLLOW_UP_PARENT_RESULT_PATH = PROJECT_ROOT / "output/atomic-claim-selection-results-20260926-a.json"
FOLLOW_UP_PARENT_RESULT_SHA256 = "f1d0eb8e6fc47c458e3cfdfe6b7083c228effcf7114dfc65da504d0b3a9e327d"
FOLLOW_UP_PARENT_JOURNAL_SHA256 = "4156a0b7d3c0a060a4555864e90791c5c8a281f9226b301c19e81ffc0d7e56c0"
FOLLOW_UP_SYSTEM_PROMPT_SHA256 = "72b77b5f54f3e1febbaf25783dee1488b0a0904e9e29a800de6db5a61cfe14b5"
_JOURNAL_KEYS = {
    "event",
    "sequence",
    "case_index",
    "max_calls",
    "prepared_file_sha256",
    "model",
    "slot_acquired",
    "sdk_started",
    "allowance_consumed",
    "status",
    "fatal_reason",
    "follow_up_id",
    "parent_result_sha256",
    "parent_journal_sha256",
    "system_prompt_sha256",
    "protocol",
    "dataset_file_sha256",
    "app_context_file_sha256",
    "stage",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _flags():
    return {
        "production_enabled": False,
        "release_gate": {"active": False},
        "semantic_accuracy": None,
        "full_report_coverage": "not_evaluated",
        "currency_cost": None,
    }


class Journal:
    def __init__(self, handle):
        self.handle, self.entries = handle, []

    def append(self, **entry):
        if set(entry) - _JOURNAL_KEYS:
            raise previous.ExperimentBlocked("journal_fields_rejected")
        record = {"schema": "atomic-selection-calls-v1", "at_utc": _now(), **entry}
        self.handle.write(json.dumps(record, sort_keys=True) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.entries.append(record)


def journal_path(prepared_sha256):
    return PROJECT_ROOT / "output" / f"atomic-claim-selection-v1-{prepared_sha256.lower()}.calls.jsonl"


def follow_up_journal_path():
    return (
        PROJECT_ROOT
        / "output"
        / f"atomic-claim-selection-v1-root-example-followup-{FOLLOW_UP_PREPARED_SHA256}.calls.jsonl"
    )


def _anchored_bytes(path, digest):
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise previous.ExperimentBlocked("follow_up_anchor_unavailable") from error
    if hashlib.sha256(raw).hexdigest() != digest:
        raise previous.ExperimentBlocked("follow_up_anchor_mismatch")
    return raw


def _parent_case_binding(row, case):
    _case_binding(case)
    pack = build_evidence_pack(case["analysis"], case["rag_context_assembly"])
    expected = {
        "analysis_sha256": case["analysis_sha256"],
        "assembly_sha256": case["assembly_sha256"],
        "case_binding_sha256": case["binding_sha256"],
        "evidence_pack_sha256": pack["evidence_pack_sha256"],
    }
    capture = row.get("invocation_capture") or {}
    if (
        row.get("case_id") != case["scenario"]["id"]
        or row.get("evidence_pack") != pack
        or row.get("status") != "failed"
        or row.get("sdk_started") is not True
        or row.get("allowance_consumed") is not True
        or any(row.get(key) != value for key, value in expected.items() if key != "evidence_pack_sha256")
        or any(capture.get(key) != value for key, value in expected.items())
    ):
        raise previous.ExperimentBlocked("follow_up_parent_case_binding_mismatch")
    old_request = capture.get("invocation_kwargs")
    if not isinstance(old_request, dict) or json_sha256(old_request) != capture.get("invocation_sha256"):
        raise previous.ExperimentBlocked("follow_up_parent_invocation_mismatch")
    messages = old_request.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or not isinstance(messages[0], dict)
        or not isinstance(messages[0].get("content"), str)
    ):
        raise previous.ExperimentBlocked("follow_up_parent_messages_invalid")
    old_prompt_hash = text_sha256(messages[0]["content"])
    current = adapter.build_request(case["scenario"], pack, "deepseek-v4-flash")
    changed = copy.deepcopy(old_request)
    changed["messages"][0]["content"] = adapter.SYSTEM_PROMPT
    if changed != current or old_prompt_hash == FOLLOW_UP_SYSTEM_PROMPT_SHA256:
        raise previous.ExperimentBlocked("follow_up_requires_only_system_prompt_change")
    response = row.get("assistant_content")
    if (
        not isinstance(response, str)
        or text_sha256(response) != row.get("assistant_content_sha256")
        or capture.get("response_sha256") != row.get("assistant_content_sha256")
    ):
        raise previous.ExperimentBlocked("follow_up_parent_response_binding_mismatch")
    return {
        "case_id": case["scenario"]["id"],
        **expected,
        "parent_invocation_sha256": capture["invocation_sha256"],
        "invocation_sha256": json_sha256(current),
        "old_system_prompt_sha256": old_prompt_hash,
    }


def validate_root_example_follow_up(prepared_path, expected_sha256, bundle):
    """One fixed authorized follow-up, never a general reset or caller-chosen run id."""
    if (
        expected_sha256.lower() != FOLLOW_UP_PREPARED_SHA256
        or text_sha256(adapter.SYSTEM_PROMPT) != FOLLOW_UP_SYSTEM_PROMPT_SHA256
    ):
        raise previous.ExperimentBlocked("follow_up_policy_anchor_mismatch")
    prepared = json.loads(_anchored_bytes(prepared_path, FOLLOW_UP_PREPARED_SHA256))
    parent = json.loads(_anchored_bytes(FOLLOW_UP_PARENT_RESULT_PATH, FOLLOW_UP_PARENT_RESULT_SHA256))
    parent_ledger = journal_path(FOLLOW_UP_PREPARED_SHA256)
    ledger = [
        json.loads(line)
        for line in _anchored_bytes(parent_ledger, FOLLOW_UP_PARENT_JOURNAL_SHA256).splitlines()
        if line.strip()
    ]
    if (
        prepared != bundle
        or parent.get("schema") != RESULT_SCHEMA
        or parent.get("valid") is not True
        or parent.get("historical_input_origin") != bundle
        or parent.get("journal") != ledger
        or parent.get("production_enabled") is not False
        or parent.get("release_gate") != {"active": False}
    ):
        raise previous.ExperimentBlocked("follow_up_parent_origin_mismatch")
    counts = {"sdk_started_count": 2, "allowance_consumed_count": 2}
    summary = parent.get("summary") or {}
    if (
        any(type(parent.get(key)) is not int or parent[key] != value for key, value in counts.items())
        or any(
            type(summary.get(key)) is not int or summary[key] != value
            for key, value in {
                "total_cases": 2,
                "failed_cases": 2,
                "not_run_cases": 0,
                "contract_valid_cases": 0,
            }.items()
        )
        or not isinstance(parent.get("rows"), list)
        or len(parent["rows"]) != 2
        or bundle.get("phase") != "seen_pilot"
        or len(bundle.get("cases", [])) != 2
        or not ledger
        or ledger[0].get("event") != "run_claim"
        or ledger[0].get("prepared_file_sha256") != FOLLOW_UP_PREPARED_SHA256
    ):
        raise previous.ExperimentBlocked("follow_up_parent_counts_or_journal_mismatch")
    bindings = [_parent_case_binding(row, case) for row, case in zip(parent["rows"], bundle["cases"])]
    old_hashes = {item["old_system_prompt_sha256"] for item in bindings}
    if len(old_hashes) != 1:
        raise previous.ExperimentBlocked("follow_up_parent_prompt_mismatch")
    return {
        "follow_up_id": FOLLOW_UP_ID,
        "parent_result_sha256": FOLLOW_UP_PARENT_RESULT_SHA256,
        "parent_journal_sha256": FOLLOW_UP_PARENT_JOURNAL_SHA256,
        "prepared_file_sha256": FOLLOW_UP_PREPARED_SHA256,
        "prepared_bundle_sha256": bundle["bundle_sha256"],
        "old_system_prompt_sha256": bindings[0]["old_system_prompt_sha256"],
        "system_prompt_sha256": FOLLOW_UP_SYSTEM_PROMPT_SHA256,
        "case_bindings": bindings,
        "additional_call_ceiling": MAX_CALLS,
    }


def execution_provenance(path, digest, settings, model):
    inherited = previous.execution_provenance(path, digest, settings, model_arg=model)
    files = (
        "scripts/atomic_claim_adapter.py",
        "scripts/evaluate_atomic_claim_deepseek.py",
        "scripts/atomic_claim_contract.py",
        "scripts/evaluate_body_evidence_deepseek.py",
        "scripts/evaluate_body_evidence_ab.py",
        "scripts/evaluation_artifacts.py",
    )
    return {
        **inherited,
        "atomic_execution_files_sha256": {name: sha256_file(PROJECT_ROOT / name) for name in files},
        "wire_schema": adapter.WIRE_SCHEMA,
        "requested_sections": adapter.SECTIONS,
    }


def extractive_journal_path():
    return PROJECT_ROOT / "output/extractive-development-v1.calls.jsonl"


def proposal_journal_path():
    return PROJECT_ROOT / "output/proposal-development-v1.calls.jsonl"


def chain_journal_path():
    return PROJECT_ROOT / "output/selection-proposal-chain-v1.calls.jsonl"


def chain_usage_snapshot():
    from src.model_limits import load_model_limits, read_model_usage

    limits = load_model_limits()
    return {
        **read_model_usage(limits=limits),
        "process_daily_call_limit": limits.daily_calls,
        "process_concurrency_limit": limits.concurrency,
        "quota_database_path_sha256": text_sha256(str(limits.database)),
    }


def load_proposal_dataset(expected_source_sha256, expected_context_sha256):
    from scripts import proposal_development as development

    source_sha, context_sha = expected_source_sha256.lower(), expected_context_sha256.lower()
    if source_sha != development.SOURCE_SHA256 or not adapter.contract._hash(context_sha):
        raise previous.ExperimentBlocked("proposal_input_hash_required")
    source, context = EXTRACTIVE_DATASET_PATH.read_bytes(), PROPOSAL_CONTEXT_PATH.read_bytes()
    if hashlib.sha256(source).hexdigest() != source_sha or hashlib.sha256(context).hexdigest() != context_sha:
        raise previous.ExperimentBlocked("proposal_input_hash_mismatch")
    return development.prepare_dataset(source, context)


def proposal_provenance(source_sha256, context_sha256, settings, model):
    from scripts import proposal_development as development

    bundle = load_proposal_dataset(source_sha256, context_sha256)
    if previous._settings(model) != settings:
        raise previous.ExperimentBlocked("execution_configuration_drift")
    files = (
        "scripts/atomic_claim_adapter.py",
        "scripts/evaluate_atomic_claim_deepseek.py",
        "scripts/proposal_development.py",
        "scripts/proposal_evidence_contract.py",
        "scripts/extractive_development.py",
        "scripts/extractive_basis_prototype.py",
        "scripts/atomic_claim_contract.py",
        "scripts/evaluate_body_evidence_deepseek.py",
        "scripts/evaluation_artifacts.py",
    )
    return {
        "git": previous.git_provenance(PROJECT_ROOT),
        "dependencies": previous.dependency_identity(PROJECT_ROOT),
        "source_files_sha256": {
            **previous._source_hashes(PROJECT_ROOT),
            **{name: sha256_file(PROJECT_ROOT / name) for name in files},
        },
        "settings": copy.deepcopy(settings),
        "source_dataset_path": str(EXTRACTIVE_DATASET_PATH),
        "app_context_path": str(PROPOSAL_CONTEXT_PATH),
        "source_dataset_file_sha256": bundle["source_dataset_file_sha256"],
        "app_context_file_sha256": bundle["app_context_file_sha256"],
        "case_identities": [
            {
                "id": case["scenario"]["id"],
                **{
                    key: case[key]
                    for key in (
                        "selection_context_sha256",
                        "typed_request_sha256",
                        "campaign_case_binding_sha256",
                    )
                },
                "pack_sha256": case["evidence_pack"]["evidence_pack_sha256"],
                "invocation_sha256": json_sha256(development.build_request(case, model)[0]),
            }
            for case in bundle["cases"]
        ],
    }


def load_extractive_dataset(expected_sha256):
    from scripts import extractive_development as development

    expected = expected_sha256.lower()
    if not adapter.contract._hash(expected):
        raise previous.ExperimentBlocked("expected_dataset_hash_required")
    raw = EXTRACTIVE_DATASET_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise previous.ExperimentBlocked("development_dataset_hash_mismatch")
    return development.prepare_dataset(raw)


def extractive_provenance(expected_sha256, settings, model):
    from scripts import extractive_development as development

    bundle = load_extractive_dataset(expected_sha256)
    if previous._settings(model) != settings:
        raise previous.ExperimentBlocked("execution_configuration_drift")
    files = (
        "scripts/atomic_claim_adapter.py",
        "scripts/evaluate_atomic_claim_deepseek.py",
        "scripts/extractive_development.py",
        "scripts/extractive_basis_prototype.py",
        "scripts/atomic_claim_contract.py",
        "scripts/evaluate_body_evidence_deepseek.py",
        "scripts/evaluation_artifacts.py",
    )
    return {
        "git": previous.git_provenance(PROJECT_ROOT),
        "dependencies": previous.dependency_identity(PROJECT_ROOT),
        "source_files_sha256": {
            **previous._source_hashes(PROJECT_ROOT),
            **{name: sha256_file(PROJECT_ROOT / name) for name in files},
        },
        "settings": copy.deepcopy(settings),
        "dataset_path": str(EXTRACTIVE_DATASET_PATH),
        "dataset_file_sha256": bundle["dataset_file_sha256"],
        "dataset_sha256": bundle["dataset_sha256"],
        "case_identities": [
            {
                "id": case["scenario"]["id"],
                "case_sha256": case["development_case_sha256"],
                "scenario_sha256": json_sha256(case["development_case"]["scenario"]),
                "expected_refs_sha256": json_sha256(case["development_case"]["expected_refs"]),
                "pack_sha256": case["evidence_pack"]["evidence_pack_sha256"],
                "request_sha256": json_sha256(development.build_request(case, bundle["section_focus"], model)[0]),
            }
            for case in bundle["cases"]
        ],
    }


def _case_binding(case):
    if (
        json_sha256(case["analysis"]) != case["analysis_sha256"]
        or json_sha256(case["rag_context_assembly"]) != case["assembly_sha256"]
        or json_sha256({key: case[key] for key in ("scenario", "analysis", "rag_context_assembly")})
        != case["binding_sha256"]
    ):
        raise previous.ExperimentBlocked("frozen_case_binding_drift")


def run_suite(
    bundle, settings, journal, *, provenance, max_calls=MAX_CALLS, invoke=adapter.invoke_once, client_factory=None
):
    return _run_case_loop(
        bundle,
        settings,
        journal,
        provenance=provenance,
        max_calls=max_calls,
        invoke=invoke,
        client_factory=client_factory,
    )


def run_extractive_suite(
    bundle,
    settings,
    journal,
    *,
    provenance,
    max_calls=MAX_EXTRACTIVE_CALLS,
    invoke=adapter.invoke_once,
    client_factory=None,
):
    return _run_case_loop(
        bundle,
        settings,
        journal,
        provenance=provenance,
        max_calls=max_calls,
        invoke=invoke,
        client_factory=client_factory,
        development_mode=True,
    )


def run_proposal_suite(
    bundle,
    settings,
    journal,
    *,
    provenance,
    max_calls=MAX_PROPOSAL_CALLS,
    invoke=adapter.invoke_once,
    client_factory=None,
):
    return _run_case_loop(
        bundle,
        settings,
        journal,
        provenance=provenance,
        max_calls=max_calls,
        invoke=invoke,
        client_factory=client_factory,
        development_mode=True,
        proposal_mode=True,
    )


def _development_end_failure(bundle, development):
    try:
        development.validate_prepared(bundle)
    except Exception:
        return "development_input_drift"
    return None


def _prepare_case_request(bundle, case, model, development, proposal_mode):
    if development is None:
        pack = build_evidence_pack(case["analysis"], case["rag_context_assembly"])
        return pack, adapter.build_request(case["scenario"], pack, model), {}, {}
    development.validate_prepared(bundle)
    pack = copy.deepcopy(case["evidence_pack"])
    request, typed_request = (
        development.build_request(case, model)
        if proposal_mode
        else development.build_request(case, bundle["section_focus"], model)
    )
    extra_binding = {}
    if proposal_mode:
        extra_binding = {
            **{key: bundle[key] for key in ("source_dataset_file_sha256", "app_context_file_sha256")},
            **{
                key: case[key]
                for key in ("selection_context_sha256", "typed_request_sha256", "campaign_case_binding_sha256")
            },
        }
    return pack, request, {"content_validator": development.content_validator(typed_request)}, extra_binding


def _finish_development_row(row, bundle, case, development, proposal_mode, started):
    development.validate_prepared(bundle)
    expected_check = "proposal_check" if proposal_mode else "extractive_check"
    other_check = "extractive_check" if proposal_mode else "proposal_check"
    if row["status"] == "validated" and (type(row.get(expected_check)) is not dict or other_check in row):
        raise previous.ExperimentBlocked("projection_protocol_mismatch")
    row["elapsed_seconds"] = round(time.monotonic() - started, 6)
    row["timing_scope"] = "invoke_once_slot_sdk_validation_cleanup_or_timeout"
    if not proposal_mode:
        row["selection_target_check"] = development.target_agreement(row, case)


def _development_module(development_mode, proposal_mode):
    if proposal_mode:
        from scripts import proposal_development

        return proposal_development
    if development_mode:
        from scripts import extractive_development

        return extractive_development
    return None


def _run_case_loop(
    bundle,
    settings,
    journal,
    *,
    provenance,
    max_calls,
    invoke,
    client_factory,
    development_mode=False,
    proposal_mode=False,
):
    maximum = MAX_PROPOSAL_CALLS if proposal_mode else MAX_EXTRACTIVE_CALLS if development_mode else MAX_CALLS
    if type(max_calls) is not int or not 1 <= max_calls <= maximum:
        raise previous.ExperimentBlocked("invalid_call_budget")
    development = _development_module(development_mode, proposal_mode)

    if development_mode:
        development.validate_prepared(bundle)
    elif bundle.get("phase") != "seen_pilot" or len(bundle.get("cases", [])) != 2:
        raise previous.ExperimentBlocked("two_seen_cases_required")
    if settings["model"] != "deepseek-v4-flash" or settings["temperature"] != 0.2 or settings["max_tokens"] != 2300:
        raise previous.ExperimentBlocked("fixed_atomic_request_configuration_required")
    client_factory = client_factory or (lambda: adapter.create_sdk(settings))
    result = {
        "schema": development.PROTOCOL.replace("-v1", "-results-v1") if development_mode else RESULT_SCHEMA,
        **_flags(),
        "started_at_utc": _now(),
        "rows": [],
        "valid": True,
        "development_input_origin" if development_mode else "historical_input_origin": copy.deepcopy(bundle),
        "execution_configuration": copy.deepcopy(settings),
        "max_calls": max_calls,
        "provenance_checks": [],
        "response_origin": "unavailable",
        "capture_boundary": "application_sdk_invocation_not_wire_or_provider_receipt",
    }
    baseline, fatal, reservations = None, None, 0
    batch_started = time.monotonic() if development_mode else None
    application_contexts = (
        [copy.deepcopy(case["application_selection_context"]) for case in bundle["cases"]] if proposal_mode else None
    )

    def check(label):
        nonlocal baseline, fatal
        try:
            current = provenance()
            if baseline is None:
                baseline = current
            stable = current == baseline
        except Exception:
            current, stable = {"error_code": "provenance_check_failed"}, False
        result["provenance_checks"].append({"at": label, "stable": stable, "provenance": current})
        if not stable:
            fatal = fatal or "provenance_drift"
            result["valid"] = False
        return stable

    check("start")
    for index, case in enumerate(bundle["cases"]):
        check(f"before_case_{index}")
        if reservations >= max_calls:
            fatal = fatal or "batch_budget_exhausted"
        row = {
            "case_id": case["scenario"]["id"],
            "status": "not_run",
            "slot_acquired": False,
            "sdk_started": False,
            "allowance_consumed": False,
            "response_origin": "unavailable",
            "error_code": fatal,
            "analysis_sha256": case["analysis_sha256"],
            "assembly_sha256": case["assembly_sha256"],
            "case_binding_sha256": case["binding_sha256"],
        }
        if proposal_mode:
            row["application_selection_context"] = application_contexts[index]
        if fatal is None:
            try:
                _case_binding(case)
                pack, request, invoke_options, extra_binding = _prepare_case_request(
                    bundle,
                    case,
                    settings["model"],
                    development,
                    proposal_mode,
                )
                binding = {
                    "case_binding_sha256": case["binding_sha256"],
                    "analysis_sha256": case["analysis_sha256"],
                    "assembly_sha256": case["assembly_sha256"],
                    "evidence_pack_sha256": pack["evidence_pack_sha256"],
                    "invocation_sha256": json_sha256(request),
                    **extra_binding,
                }
                try:
                    journal.append(event="before_reservation", sequence=reservations + 1, case_index=index)
                except Exception:
                    raise previous.ExperimentBlocked("journal_write_failed") from None
                reservations += 1
                call_started = time.monotonic() if development_mode else None
                row.update(
                    evidence_pack=pack,
                    **invoke(
                        request,
                        pack,
                        binding,
                        timeout_seconds=settings["timeout_seconds"],
                        client_factory=client_factory,
                        **invoke_options,
                    ),
                )
                if development_mode:
                    _finish_development_row(row, bundle, case, development, proposal_mode, call_started)
                fatal = row.get("fatal_reason")
                try:
                    journal.append(
                        event="case_complete",
                        sequence=reservations,
                        case_index=index,
                        slot_acquired=row["slot_acquired"],
                        sdk_started=row["sdk_started"],
                        allowance_consumed=row["allowance_consumed"],
                        status=row["status"],
                        fatal_reason=fatal,
                    )
                except Exception:
                    fatal = "journal_write_failed"
            except Exception as error:
                fatal = error.code if isinstance(error, previous.ExperimentBlocked) else "case_setup_or_dispatch_failed"
                row.update(status="failed", error_code=fatal)
        result["rows"].append(row)
        check(f"after_case_{index}")
    check("end")
    if development_mode:
        end_failure = _development_end_failure(bundle, development)
        fatal = fatal or end_failure
    rows = result["rows"]
    result.update(
        completed_at_utc=_now(),
        fatal_stop_reason=fatal,
        ledger_reserved_count=reservations,
        slot_acquired_count=sum(row["slot_acquired"] for row in rows),
        sdk_started_count=sum(row["sdk_started"] for row in rows),
        allowance_consumed_count=sum(row["allowance_consumed"] for row in rows),
        journal=copy.deepcopy(journal.entries),
        response_origin="remote_model"
        if any(row["response_origin"] == "remote_model" for row in rows)
        else "unavailable",
        summary={
            "total_cases": 2,
            "failed_cases": sum(row["status"] == "failed" for row in rows),
            "not_run_cases": sum(row["status"] == "not_run" for row in rows),
            "contract_valid_cases": sum(row["status"] == "validated" for row in rows),
            "all_requested_sections_contract_valid_cases": sum(
                row.get("requested_section_coverage_complete", False) for row in rows
            ),
            "quote_binding_exercised_cases": sum(row.get("quote_binding_exercised", False) for row in rows),
        },
    )
    if fatal:
        result["valid"] = False
    if development_mode:
        result.update(
            protocol=development.PROTOCOL,
            data_origin="synthetic_development",
            summary=development.summarize(rows),
            elapsed_seconds=round(time.monotonic() - batch_started, 6),
            timing_scope="case_loop_including_provenance_and_local_validation",
        )
    return result


def _validate_protocol_args(parser, args):
    development_mode = args.protocol in {EXTRACTIVE_PROTOCOL, PROPOSAL_PROTOCOL, chain.PROTOCOL}
    if development_mode:
        if (
            args.prepared
            or args.expected_prepared_file_sha256
            or args.root_example_follow_up
            or not args.expected_dataset_sha256
        ):
            parser.error("development requires --expected-dataset-sha256; prepared/follow-up arguments are forbidden")
        if (args.protocol == PROPOSAL_PROTOCOL) != bool(args.expected_context_sha256):
            parser.error("only proposal development requires --expected-context-sha256")
    elif (
        not args.prepared
        or not args.expected_prepared_file_sha256
        or args.expected_dataset_sha256
        or args.expected_context_sha256
    ):
        parser.error("atomic selection requires prepared arguments without dataset/context arguments")
    maximum = {
        EXTRACTIVE_PROTOCOL: MAX_EXTRACTIVE_CALLS,
        PROPOSAL_PROTOCOL: MAX_PROPOSAL_CALLS,
        chain.PROTOCOL: chain.MAX_CALLS,
    }.get(args.protocol, MAX_CALLS)
    args.max_calls = maximum if args.max_calls is None else args.max_calls
    if not 1 <= args.max_calls <= maximum:
        parser.error(f"--max-calls must be between 1 and {maximum} for this protocol")
    return development_mode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--protocol",
        default=adapter.WIRE_SCHEMA,
        choices=[adapter.WIRE_SCHEMA, EXTRACTIVE_PROTOCOL, PROPOSAL_PROTOCOL, chain.PROTOCOL],
    )
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--expected-prepared-file-sha256")
    parser.add_argument("--expected-dataset-sha256")
    parser.add_argument("--expected-context-sha256")
    parser.add_argument("--run-model", action="store_true")
    parser.add_argument("--allow-external-deepseek", action="store_true")
    parser.add_argument(
        "--root-example-follow-up",
        action="store_true",
        help="Use the fixed, anchored complete-root-example follow-up allowance once.",
    )
    parser.add_argument("--model", required=True, choices=["deepseek-v4-flash"])
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    development_mode = _validate_protocol_args(parser, args)
    proposal_mode = args.protocol == PROPOSAL_PROTOCOL
    chain_mode = args.protocol == chain.PROTOCOL
    try:
        settings = previous.admit_environment(
            run_model=args.run_model,
            allow_external_deepseek=args.allow_external_deepseek,
            model_arg=args.model,
            **({"dotenv_loader": lambda *_args, **_kwargs: False} if chain_mode else {}),
        )
        bundle = (
            chain.load_dataset(EXTRACTIVE_DATASET_PATH, args.expected_dataset_sha256)
            if chain_mode
            else load_proposal_dataset(args.expected_dataset_sha256, args.expected_context_sha256)
            if proposal_mode
            else load_extractive_dataset(args.expected_dataset_sha256)
            if development_mode
            else previous.load_seen_pilot(args.prepared, args.expected_prepared_file_sha256)
        )
        follow_up = (
            validate_root_example_follow_up(args.prepared, args.expected_prepared_file_sha256, bundle)
            if args.root_example_follow_up
            else None
        )
        ledger = (
            chain_journal_path()
            if chain_mode
            else proposal_journal_path()
            if proposal_mode
            else extractive_journal_path()
            if development_mode
            else follow_up_journal_path()
            if follow_up
            else journal_path(args.expected_prepared_file_sha256)
        )

        def provenance():
            if chain_mode:
                return chain.execution_provenance(
                    PROJECT_ROOT, EXTRACTIVE_DATASET_PATH, args.expected_dataset_sha256, settings, args.model
                )
            if proposal_mode:
                return proposal_provenance(
                    args.expected_dataset_sha256, args.expected_context_sha256, settings, args.model
                )
            if development_mode:
                return extractive_provenance(args.expected_dataset_sha256, settings, args.model)
            current = execution_provenance(args.prepared, args.expected_prepared_file_sha256, settings, args.model)
            if follow_up:
                current["follow_up"] = validate_root_example_follow_up(
                    args.prepared, args.expected_prepared_file_sha256, bundle
                )
            return current

        input_path = EXTRACTIVE_DATASET_PATH if development_mode else args.prepared
        protected = {input_path.resolve(), ledger.resolve()}
        if proposal_mode:
            protected.add(PROPOSAL_CONTEXT_PATH.resolve())
        if args.output.resolve() in protected:
            raise previous.ExperimentBlocked("output_path_collision")
        with args.output.open("x", encoding="utf-8") as output:
            result = None
            try:
                with ledger.open("x", encoding="utf-8") as handle:
                    journal = Journal(handle)
                    journal.append(
                        event="run_claim",
                        max_calls=args.max_calls,
                        model=args.model,
                        **(
                            {
                                "protocol": args.protocol,
                                "dataset_file_sha256": args.expected_dataset_sha256.lower(),
                            }
                            if development_mode
                            else {"prepared_file_sha256": args.expected_prepared_file_sha256.lower()}
                        ),
                        **({"app_context_file_sha256": args.expected_context_sha256.lower()} if proposal_mode else {}),
                        **(
                            {
                                key: follow_up[key]
                                for key in (
                                    "follow_up_id",
                                    "parent_result_sha256",
                                    "parent_journal_sha256",
                                    "system_prompt_sha256",
                                )
                            }
                            if follow_up
                            else {}
                        ),
                    )
                    run = (
                        chain.run_suite
                        if chain_mode
                        else run_proposal_suite
                        if proposal_mode
                        else run_extractive_suite
                        if development_mode
                        else run_suite
                    )
                    result = run(
                        bundle,
                        settings,
                        journal,
                        max_calls=args.max_calls,
                        provenance=provenance,
                        **(
                            {
                                "client_factory": lambda: adapter.create_sdk(settings),
                                "usage_snapshot": chain_usage_snapshot,
                            }
                            if chain_mode
                            else {}
                        ),
                    )
                    result["journal_path"] = str(ledger)
                    if follow_up:
                        result["follow_up"] = follow_up
            except Exception as error:
                code = error.code if isinstance(error, previous.ExperimentBlocked) else "run_or_journal_failed"
                if chain_mode and result is not None:
                    result = chain.invalidate_result(result, code, finalization=True)
                elif chain_mode:
                    result = chain.empty_result(code, settings=settings, max_calls=args.max_calls)
                else:
                    result = {
                        "schema": args.protocol.replace("-v1", "-results-v1") if development_mode else RESULT_SCHEMA,
                        **(
                            {"protocol": args.protocol, "data_origin": "synthetic_development"}
                            if development_mode
                            else {}
                        ),
                        **_flags(),
                        "valid": False,
                        "error_code": error.code
                        if isinstance(error, previous.ExperimentBlocked)
                        else "run_or_journal_failed",
                    }
            json.dump(result, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    except Exception as error:
        code = error.code if isinstance(error, previous.ExperimentBlocked) else "preflight_or_output_failed"
        print(f"Atomic selection experiment stopped: {code}", file=sys.stderr)
        return 2
    print(f"Atomic selection artifact written; valid={result['valid']}; production_enabled=false")
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
