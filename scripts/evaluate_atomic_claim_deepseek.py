"""Two-case, at-most-two-call private JSON experiment; never a report or UI gate."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import atomic_claim_adapter as adapter  # noqa: E402
from scripts import evaluate_body_evidence_deepseek as previous  # noqa: E402
from scripts.atomic_claim_contract import build_evidence_pack  # noqa: E402
from scripts.evaluation_artifacts import sha256_file  # noqa: E402
from src.model_evidence import json_sha256, text_sha256  # noqa: E402

RESULT_SCHEMA = "atomic-selection-deepseek-results-v1"
MAX_CALLS = 2
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
    if type(max_calls) is not int or not 1 <= max_calls <= MAX_CALLS:
        raise previous.ExperimentBlocked("invalid_call_budget")
    if bundle.get("phase") != "seen_pilot" or len(bundle.get("cases", [])) != 2:
        raise previous.ExperimentBlocked("two_seen_cases_required")
    if settings["model"] != "deepseek-v4-flash" or settings["temperature"] != 0.2 or settings["max_tokens"] != 2300:
        raise previous.ExperimentBlocked("fixed_atomic_request_configuration_required")
    client_factory = client_factory or (lambda: adapter.create_sdk(settings))
    result = {
        "schema": RESULT_SCHEMA,
        **_flags(),
        "started_at_utc": _now(),
        "rows": [],
        "valid": True,
        "historical_input_origin": copy.deepcopy(bundle),
        "execution_configuration": copy.deepcopy(settings),
        "max_calls": max_calls,
        "provenance_checks": [],
        "response_origin": "unavailable",
        "capture_boundary": "application_sdk_invocation_not_wire_or_provider_receipt",
    }
    baseline, fatal, reservations = None, None, 0

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
        if fatal is None:
            try:
                _case_binding(case)
                pack = build_evidence_pack(case["analysis"], case["rag_context_assembly"])
                request = adapter.build_request(case["scenario"], pack, settings["model"])
                binding = {
                    "case_binding_sha256": case["binding_sha256"],
                    "analysis_sha256": case["analysis_sha256"],
                    "assembly_sha256": case["assembly_sha256"],
                    "evidence_pack_sha256": pack["evidence_pack_sha256"],
                    "invocation_sha256": json_sha256(request),
                }
                try:
                    journal.append(event="before_reservation", sequence=reservations + 1, case_index=index)
                except Exception:
                    raise previous.ExperimentBlocked("journal_write_failed") from None
                reservations += 1
                row.update(
                    evidence_pack=pack,
                    **invoke(
                        request,
                        pack,
                        binding,
                        timeout_seconds=settings["timeout_seconds"],
                        client_factory=client_factory,
                    ),
                )
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
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--expected-prepared-file-sha256", required=True)
    parser.add_argument("--run-model", action="store_true")
    parser.add_argument("--allow-external-deepseek", action="store_true")
    parser.add_argument(
        "--root-example-follow-up",
        action="store_true",
        help="Use the fixed, anchored complete-root-example follow-up allowance once.",
    )
    parser.add_argument("--model", required=True, choices=["deepseek-v4-flash"])
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS, choices=[1, 2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        settings = previous.admit_environment(
            run_model=args.run_model, allow_external_deepseek=args.allow_external_deepseek, model_arg=args.model
        )
        bundle = previous.load_seen_pilot(args.prepared, args.expected_prepared_file_sha256)
        follow_up = (
            validate_root_example_follow_up(args.prepared, args.expected_prepared_file_sha256, bundle)
            if args.root_example_follow_up
            else None
        )
        ledger = follow_up_journal_path() if follow_up else journal_path(args.expected_prepared_file_sha256)

        def provenance():
            current = execution_provenance(args.prepared, args.expected_prepared_file_sha256, settings, args.model)
            if follow_up:
                current["follow_up"] = validate_root_example_follow_up(
                    args.prepared, args.expected_prepared_file_sha256, bundle
                )
            return current

        if args.output.resolve() in {args.prepared.resolve(), ledger.resolve()}:
            raise previous.ExperimentBlocked("output_path_collision")
        with args.output.open("x", encoding="utf-8") as output:
            try:
                with ledger.open("x", encoding="utf-8") as handle:
                    journal = Journal(handle)
                    journal.append(
                        event="run_claim",
                        prepared_file_sha256=args.expected_prepared_file_sha256.lower(),
                        max_calls=args.max_calls,
                        model=args.model,
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
                    result = run_suite(
                        bundle,
                        settings,
                        journal,
                        max_calls=args.max_calls,
                        provenance=provenance,
                    )
                    result["journal_path"] = str(ledger)
                    if follow_up:
                        result["follow_up"] = follow_up
            except Exception as error:
                result = {
                    "schema": RESULT_SCHEMA,
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
