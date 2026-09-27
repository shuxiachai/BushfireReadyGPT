"""Fixed D2/D3 remote chain coordinator; no retries, semantic grading or reports."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from scripts import atomic_claim_adapter as adapter
from scripts import atomic_claim_contract as contract
from scripts import evaluate_body_evidence_deepseek as previous
from scripts import extractive_development as selection
from scripts import proposal_development as proposal
from scripts import selection_proposal_bridge as bridge
from scripts.evaluation_artifacts import sha256_file
from src.model_evidence import json_sha256, text_sha256

PROTOCOL = "selection-proposal-chain-v1"
RESULT_SCHEMA = "selection-proposal-chain-results-v1"
SOURCE_SHA256 = "c621a7d64c3fe3fea5d5f176160f6f54cc1ea93c18ca4031051000f1503ed2fd"
CASE_IDS = ("D2", "D3")
STAGES = ("selection", "proposal")
MAX_CALLS = 4
CAPTURE_BOUNDARY = "application_sdk_invocation_not_wire_or_provider_receipt"
_CASE_FIELDS = (
    "scenario",
    "analysis",
    "rag_context_assembly",
    "analysis_sha256",
    "assembly_sha256",
    "binding_sha256",
    "evidence_pack",
)
_CHAIN_FIELDS = (
    "case_id",
    "evidence_pack_sha256",
    "selection_request_sha256",
    "selection_raw_sha256",
    "derived_selection_sha256",
    "proposal_request_sha256",
    "handoff_sha256",
    "proposal_raw_sha256",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _blocked(code):
    raise previous.ExperimentBlocked(code)


def prepare_dataset(raw):
    raw = raw.encode("utf-8") if isinstance(raw, str) else raw
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        _blocked("chain_source_hash_mismatch")
    source = selection.prepare_dataset(raw)
    cases = [
        {key: copy.deepcopy(case[key]) for key in _CASE_FIELDS}
        for case in source["cases"]
        if case["scenario"]["id"] in CASE_IDS
    ]
    bundle = {
        "protocol": PROTOCOL,
        "source_dataset_file_sha256": SOURCE_SHA256,
        "section_focus": copy.deepcopy(source["section_focus"]),
        "cases": cases,
    }
    bundle["bundle_sha256"] = json_sha256(bundle)
    return bundle


def load_dataset(path, expected_sha256):
    if not isinstance(expected_sha256, str) or expected_sha256.lower() != SOURCE_SHA256:
        _blocked("chain_fixed_source_hash_required")
    return prepare_dataset(Path(path).read_bytes())


def validate_prepared(bundle):
    contract._keys(bundle, {"protocol", "source_dataset_file_sha256", "section_focus", "cases", "bundle_sha256"})
    if (
        bundle["protocol"] != PROTOCOL
        or bundle["source_dataset_file_sha256"] != SOURCE_SHA256
        or [case["scenario"]["id"] for case in bundle["cases"]] != list(CASE_IDS)
        or bundle["bundle_sha256"]
        != json_sha256({key: value for key, value in bundle.items() if key != "bundle_sha256"})
    ):
        _blocked("chain_input_binding_drift")
    contract._keys(bundle["section_focus"], {"7", "11", "12"})
    for case in bundle["cases"]:
        contract._keys(case, set(_CASE_FIELDS))
        if (
            case["analysis_sha256"] != json_sha256(case["analysis"])
            or case["assembly_sha256"] != json_sha256(case["rag_context_assembly"])
            or case["binding_sha256"] != json_sha256({key: case[key] for key in _CASE_FIELDS[:3]})
            or case["evidence_pack"] != contract.build_evidence_pack(case["analysis"], case["rag_context_assembly"])
        ):
            _blocked("chain_input_binding_drift")


def build_selection_request(case, section_focus, model):
    # Only the original scenario and pack enter the existing request builder.
    minimal = {
        "development_case": {"scenario": {key: value for key, value in case["scenario"].items() if key != "id"}},
        "evidence_pack": case["evidence_pack"],
    }
    return selection.build_request(minimal, section_focus, model)


def build_proposal_request(case, section_focus, handoff, model):
    rebuilt = bridge._revalidate_handoff(handoff, handoff.to_dict()["handoff_sha256"])
    task = rebuilt.to_dict()["proposal_request"]
    scenario = {key: value for key, value in case["scenario"].items() if key != "id"}
    visible = {
        "scenario": scenario,
        "task_focus": scenario["task_focus"],
        "section_focus": copy.deepcopy(section_focus),
        **{
            key: task[key] for key in ("selected_ref_by_section", "requested_sections", "catalog", "output_json_schema")
        },
    }
    request = {
        "model": model,
        "messages": [
            {"role": "system", "content": proposal.REMOTE_INSTRUCTIONS},
            {"role": "user", "content": json.dumps(visible, ensure_ascii=False, sort_keys=True)},
        ],
        "response_format": {"type": "json_object"},
        "extra_body": {"thinking": {"type": "disabled"}},
        "max_tokens": 2300,
        "temperature": 0.2,
        "top_p": 0.8,
        "stream": False,
    }
    return request, rebuilt._proposal_request


def execution_provenance(root, path, expected_sha256, settings, model):
    bundle = load_dataset(path, expected_sha256)
    if previous._settings(model) != settings:
        _blocked("execution_configuration_drift")
    files = (
        "scripts/atomic_claim_adapter.py",
        "scripts/evaluate_atomic_claim_deepseek.py",
        "scripts/selection_proposal_development.py",
        "scripts/selection_proposal_bridge.py",
        "scripts/proposal_development.py",
        "scripts/proposal_evidence_contract.py",
        "scripts/extractive_development.py",
        "scripts/extractive_basis_prototype.py",
        "scripts/atomic_claim_contract.py",
        "scripts/evaluate_body_evidence_deepseek.py",
        "scripts/evaluation_artifacts.py",
    )
    return {
        "git": previous.git_provenance(root),
        "dependencies": previous.dependency_identity(root),
        "source_files_sha256": {
            **previous._source_hashes(root),
            **{name: sha256_file(Path(root) / name) for name in files},
        },
        "settings": copy.deepcopy(settings),
        "source_dataset_file_sha256": bundle["source_dataset_file_sha256"],
        "bundle_sha256": bundle["bundle_sha256"],
    }


def empty_result(code=None, *, settings=None, max_calls=MAX_CALLS):
    rows = [
        {
            "case_id": case_id,
            "status": "not_run",
            "error_code": code,
            "chain_integrity_valid": False,
            "selection_binding_valid": False,
            "stages": [
                {
                    "stage": stage,
                    "case_id": case_id,
                    "status": "not_run",
                    "error_code": code,
                    "slot_acquired": False,
                    "sdk_started": False,
                    "allowance_consumed": False,
                    "response_origin": "unavailable",
                    "invocation_capture": None,
                }
                for stage in STAGES
            ],
        }
        for case_id in CASE_IDS
    ]
    result = {
        "schema": RESULT_SCHEMA,
        "protocol": PROTOCOL,
        "data_origin": "synthetic_development",
        "production_enabled": False,
        "release_gate": {"active": False},
        "semantic_accuracy": None,
        "full_report_coverage": "not_evaluated",
        "currency_cost": None,
        "valid": False,
        "started_at_utc": _now(),
        "fatal_stop_reason": code,
        "error_code": code,
        "execution_configuration": copy.deepcopy(settings),
        "max_calls": max_calls,
        "rows": rows,
        "ledger_reserved_count": 0,
        "provenance_checks": [],
        "quota_checks": [],
        "quota_initial": None,
        "journal": [],
        "capture_boundary": CAPTURE_BOUNDARY,
        "request_origin_attestation": "application_sdk_capture_only_not_provider_attestation",
        "response_origin": "unavailable",
    }
    return _finish(result)


def _finish(result):
    rows = result["rows"]
    stages = [stage for row in rows for stage in row["stages"]]
    counts = dict.fromkeys(
        (
            "selected_slots",
            "null_primary_slots",
            "nonnull_primary_slots",
            "null_requires_evidence_slots",
            "nonnull_requires_evidence_slots",
            "nonnull_draft_slots",
            "single_source_draft_slots",
            "multi_source_draft_slots",
            "evaluable_slots",
        ),
        0,
    )
    for row in rows:
        mapping = row.get("selected_ref_by_section", {}) if row["selection_binding_valid"] else {}
        counts["selected_slots"] += len(mapping)
        counts["null_primary_slots"] += sum(ref is None for ref in mapping.values())
        counts["nonnull_primary_slots"] += sum(ref is not None for ref in mapping.values())
        if row["status"] != "validated" or not row["chain_integrity_valid"]:
            continue
        for item in row["chain_check"]["proposal_review"]["items"]:
            counts["evaluable_slots"] += 1
            draft = item["proposal"]
            if mapping[str(item["section_id"])] is None:
                counts["null_requires_evidence_slots"] += 1
            elif draft["kind"] == "requires_evidence":
                counts["nonnull_requires_evidence_slots"] += 1
            else:
                counts["nonnull_draft_slots"] += 1
                counts[
                    "single_source_draft_slots" if len(draft["declared_refs"]) == 1 else "multi_source_draft_slots"
                ] += 1
    result.update(
        completed_at_utc=_now(),
        **{
            f"{key}_count": sum(stage[key] is True for stage in stages)
            for key in (
                "slot_acquired",
                "sdk_started",
                "allowance_consumed",
            )
        },
        response_origin="remote_model"
        if any(stage["response_origin"] == "remote_model" for stage in stages)
        else "unavailable",
        summary={
            "total_cases": 2,
            "total_slots": 6,
            "planned_stages": 4,
            "contract_valid_cases": sum(row["status"] == "validated" and row["chain_integrity_valid"] for row in rows),
            "failed_cases": sum(row["status"] == "failed" for row in rows),
            "not_run_cases": sum(row["status"] == "not_run" for row in rows),
            "validated_stages": sum(stage["status"] == "validated" for stage in stages),
            "failed_stages": sum(stage["status"] == "failed" for stage in stages),
            "not_run_stages": sum(stage["status"] == "not_run" for stage in stages),
            "failed_slots": 3 * sum(row["status"] == "failed" for row in rows),
            "not_run_slots": 3 * sum(row["status"] == "not_run" for row in rows),
            **counts,
            "unselected_slots": 6 - counts["selected_slots"],
            "unevaluable_slots": 6 - counts["evaluable_slots"],
            "interpretation": "structure_and_declared_dependencies_only_not_semantic_accuracy",
            "semantic_support": "unknown",
            "dependency_completeness": "unknown",
            "semantic_accuracy": None,
            "manual_raw_response_review": "not_performed",
        },
    )
    return result


def _case_scene(bundle, case):
    return {
        "scenario": copy.deepcopy(case["scenario"]),
        "section_focus": copy.deepcopy(bundle["section_focus"]),
        "source_dataset_file_sha256": bundle["source_dataset_file_sha256"],
        "case_binding_sha256": case["binding_sha256"],
        "evidence_pack_sha256": case["evidence_pack"]["evidence_pack_sha256"],
    }


def _binding(bundle, case, stage, request, typed, parent=None, handoff=None):
    binding = {
        "protocol": PROTOCOL,
        "case_id": case["scenario"]["id"],
        "stage": stage,
        **{key: case[key] for key in ("analysis_sha256", "assembly_sha256")},
        **{key: value for key, value in _case_scene(bundle, case).items() if key not in {"scenario", "section_focus"}},
        "case_scene_sha256": json_sha256(_case_scene(bundle, case)),
        "typed_request_sha256": typed.to_dict()["request_sha256"],
        "invocation_sha256": json_sha256(request),
    }
    if parent is not None:
        binding.update(
            parent_selection_invocation_sha256=parent["invocation_capture"]["invocation_sha256"],
            parent_selection_raw_sha256=parent["assistant_content_sha256"],
            handoff_sha256=handoff.to_dict()["handoff_sha256"],
            derived_selection_sha256=handoff.to_dict()["derived_selection_sha256"],
        )
    return binding


def _verify_record(record, request, pack, binding, validator):
    if record.get("stage") != binding["stage"] or record.get("case_id") != binding["case_id"]:
        _blocked("chain_capture_binding_mismatch")
    if record.get("sdk_started") is not True:
        if not record.get("fatal_reason"):
            _blocked("chain_missing_sdk_capture")
        return
    capture = record.get("invocation_capture")
    if (
        type(capture) is not dict
        or capture.get("schema") != "atomic-sdk-invocation-v1"
        or capture.get("boundary") != CAPTURE_BOUNDARY
        or any(capture.get(key) != value for key, value in binding.items())
        or capture.get("invocation_kwargs") != request
        or capture.get("invocation_sha256") != json_sha256(capture.get("invocation_kwargs"))
        or record.get("evidence_pack") != pack
    ):
        _blocked("chain_capture_binding_mismatch")
    raw = record.get("assistant_content")
    raw_sha = text_sha256(raw) if isinstance(raw, str) else None
    if capture.get("response_sha256") != raw_sha or record.get("assistant_content_sha256") != raw_sha:
        _blocked("chain_response_binding_mismatch")
    if record.get("status") == "validated":
        expected_key = "extractive_check" if record["stage"] == "selection" else "proposal_check"
        other_key = "proposal_check" if record["stage"] == "selection" else "extractive_check"
        if (
            any(record.get(key) is not True for key in ("slot_acquired", "sdk_started", "allowance_consumed"))
            or record.get("inflight_unknown") is not False
            or record.get("fatal_reason") is not None
            or record.get("finish_reason") != "stop"
            or record.get("choices_count") != 1
            or record.get("response_origin") != "remote_model"
            or other_key in record
            or not isinstance(raw, str)
        ):
            _blocked("chain_sdk_admission_mismatch")
        try:
            expected = validator(raw, pack)
        except Exception:
            _blocked("chain_revalidation_failed")
        if set(expected) != {expected_key} or record.get(expected_key) != expected[expected_key]:
            _blocked("chain_projection_mismatch")
    elif not record.get("fatal_reason") and not (
        record.get("error_code") == "contract_rejected"
        or (record.get("error_code") == "incomplete_or_nontext_response" and record.get("finish_reason") == "length")
    ):
        _blocked("chain_unexpected_response_boundary")


class _Guards:
    def __init__(self, bundle, settings, result, provenance, usage_snapshot):
        self.bundle, self.settings, self.result = bundle, settings, result
        self.frozen_bundle, self.frozen_settings = copy.deepcopy(bundle), copy.deepcopy(settings)
        self.provenance, self.usage_snapshot = provenance, usage_snapshot
        self.baseline, self.frozen_records, self.parent_checks = None, [], []

    def _local(self):
        validate_prepared(self.bundle)
        if self.bundle != self.frozen_bundle or self.settings != self.frozen_settings:
            _blocked("chain_input_binding_drift")
        if any(record != frozen for record, frozen in self.frozen_records):
            _blocked("chain_parent_record_drift")
        for check in self.parent_checks:
            check()

    def check(self, label):
        try:
            self._local()
            current = self.provenance()
            if self.baseline is None:
                self.baseline = copy.deepcopy(current)
            if current != self.baseline:
                _blocked("provenance_drift")
            self._quota(label)
            self._local()
        except Exception as error:
            code = error.code if isinstance(error, previous.ExperimentBlocked) else "provenance_drift"
            self.result["provenance_checks"].append({"at": label, "stable": False, "error_code": code})
            _blocked(code)
        self.result["provenance_checks"].append({"at": label, "stable": True, "provenance": current})

    def _quota(self, label):
        try:
            snapshot = copy.deepcopy(self.usage_snapshot())
            if (
                snapshot.get("status") != "ready"
                or type(snapshot.get("calls")) is not int
                or not 0 <= snapshot["calls"] < 2**63
                or date.fromisoformat(snapshot["day"]).isoformat() != snapshot["day"]
                or snapshot.get("process_daily_call_limit") != MAX_CALLS
                or snapshot.get("process_concurrency_limit") != 1
            ):
                _blocked("chain_quota_unavailable")
            initial = self.result["quota_initial"]
            consumed = sum(
                stage["allowance_consumed"] is True for row in self.result["rows"] for stage in row["stages"]
            )
            if initial is None:
                if snapshot["calls"] + self.result["max_calls"] > snapshot["process_daily_call_limit"]:
                    _blocked("chain_quota_insufficient")
                self.result["quota_initial"] = copy.deepcopy(snapshot)
            elif snapshot != {**initial, "calls": initial["calls"] + consumed}:
                _blocked("chain_quota_day_or_count_drift")
            self.result["quota_checks"].append({"at": label, "stable": True, "snapshot": snapshot})
        except Exception as error:
            code = error.code if isinstance(error, previous.ExperimentBlocked) else "chain_quota_unavailable"
            self.result["quota_checks"].append({"at": label, "stable": False, "error_code": code})
            _blocked(code)


def _execute_stage(result, record, request, typed, pack, binding, module, journal, settings, invoke, client_factory):
    if result["ledger_reserved_count"] >= result["max_calls"]:
        _blocked("batch_budget_exhausted")
    sequence = result["ledger_reserved_count"] + 1
    try:
        journal.append(
            event="before_reservation",
            protocol=PROTOCOL,
            sequence=sequence,
            case_index=CASE_IDS.index(record["case_id"]),
            stage=record["stage"],
        )
    except Exception:
        _blocked("journal_write_failed")
    result["ledger_reserved_count"] = sequence
    validator = module.content_validator(typed)
    started = time.monotonic()
    record.update(evidence_pack=copy.deepcopy(pack), expected_binding=copy.deepcopy(binding))
    record.update(
        invoke(
            copy.deepcopy(request),
            copy.deepcopy(pack),
            copy.deepcopy(binding),
            timeout_seconds=settings["timeout_seconds"],
            client_factory=client_factory,
            content_validator=validator,
        )
    )
    record.update(
        elapsed_seconds=round(time.monotonic() - started, 6),
        timing_scope="invoke_once_slot_sdk_validation_cleanup_or_timeout",
    )
    _verify_record(record, request, pack, binding, validator)


def _journal_complete(result, record, journal):
    try:
        journal.append(
            event="stage_complete",
            protocol=PROTOCOL,
            sequence=result["ledger_reserved_count"],
            case_index=CASE_IDS.index(record["case_id"]),
            stage=record["stage"],
            **{key: record[key] for key in ("slot_acquired", "sdk_started", "allowance_consumed", "status")},
            fatal_reason=record.get("fatal_reason"),
        )
    except Exception:
        _blocked("journal_write_failed")


def _check_handoff_view(row, handoff, expected_sha256):
    rebuilt = bridge._revalidate_handoff(handoff, expected_sha256).to_dict()
    if (
        row.get("handoff_sha256") != expected_sha256
        or row.get("selected_ref_by_section") != rebuilt["proposal_request"]["selected_ref_by_section"]
    ):
        _blocked("chain_parent_record_drift")


def _run_case(bundle, case, row, result, guards, settings, journal, invoke, client_factory):
    row["case_scene"] = _case_scene(bundle, case)
    pack = case["evidence_pack"]
    parent = handoff = selection_typed = None
    for stage_index, stage in enumerate(STAGES):
        record = row["stages"][stage_index]
        label = f"{row['case_id']}_{stage}"
        guards.check(f"before_{label}")
        if stage == "selection":
            request, typed = build_selection_request(case, bundle["section_focus"], settings["model"])
            selection_typed, module = typed, selection
        else:
            request, typed = build_proposal_request(case, bundle["section_focus"], handoff, settings["model"])
            module = proposal
        binding = _binding(bundle, case, stage, request, typed, parent, handoff)
        try:
            _execute_stage(
                result, record, request, typed, pack, binding, module, journal, settings, invoke, client_factory
            )
            guards.frozen_records.append((record, copy.deepcopy(record)))
            guards.check(f"after_{label}")
            if record.get("fatal_reason"):
                _blocked(record["fatal_reason"])
            if record["status"] == "validated":
                if stage == "selection":
                    handoff = bridge.prepare_proposal(
                        row["case_id"], pack, selection_typed, record["assistant_content"]
                    )
                    row["selected_ref_by_section"] = handoff.to_dict()["proposal_request"]["selected_ref_by_section"]
                    row["handoff_sha256"] = handoff.to_dict()["handoff_sha256"]
                    row["selection_binding_valid"] = True
                    parent = record
                    guards.parent_checks.append(
                        lambda h=handoff, digest=row["handoff_sha256"]: _check_handoff_view(row, h, digest)
                    )
                else:
                    complete = bridge.complete_proposal(
                        handoff,
                        record["assistant_content"],
                        expected_handoff_sha256=row["handoff_sha256"],
                    ).to_dict()
                    row["chain_check"] = {
                        **{key: complete[key] for key in _CHAIN_FIELDS},
                        "case_scene_sha256": binding["case_scene_sha256"],
                        "selection_invocation_sha256": parent["invocation_capture"]["invocation_sha256"],
                        "proposal_invocation_sha256": record["invocation_capture"]["invocation_sha256"],
                        "proposal_review": complete["proposal_review"],
                    }
            _journal_complete(result, record, journal)
        except Exception as error:
            code = error.code if isinstance(error, previous.ExperimentBlocked) else "chain_internal_failure"
            record.update(status="failed", error_code=code, fatal_reason=code)
            raise previous.ExperimentBlocked(code) from None
        if record["status"] != "validated":
            row.update(status="failed", error_code=record.get("error_code"))
            row["stages"][1]["error_code"] = (
                "selection_not_validated" if stage == "selection" else row["stages"][1].get("error_code")
            )
            return
    row.update(status="validated", error_code=None, chain_integrity_valid=True)


def invalidate_result(result, code, *, finalization=False):
    """Retain SDK evidence while excluding chains whose batch integrity is lost."""
    result.update(valid=False, fatal_stop_reason=result.get("fatal_stop_reason") or code, error_code=code)
    if finalization:
        result["finalization_error"] = code
    for row in result["rows"]:
        row.update(chain_integrity_valid=False, selection_binding_valid=False, chain_integrity_error=code)
        if row["status"] == "validated":
            row.update(status="failed", error_code=code)
    return _finish(result)


def run_suite(
    bundle,
    settings,
    journal,
    *,
    provenance,
    usage_snapshot,
    client_factory,
    max_calls=MAX_CALLS,
    invoke=adapter.invoke_once,
):
    result = empty_result(settings=settings, max_calls=max_calls)
    result.update(valid=True, development_input_origin=copy.deepcopy(bundle))
    guards = _Guards(bundle, settings, result, provenance, usage_snapshot)
    active_row = None
    started = time.monotonic()
    try:
        if type(max_calls) is not int or not 1 <= max_calls <= MAX_CALLS:
            _blocked("invalid_call_budget")
        if any(
            settings.get(key) != value
            for key, value in {
                "model": "deepseek-v4-flash",
                "temperature": 0.2,
                "max_tokens": 2300,
                "sdk_max_retries": 0,
                "top_p_submitted": 0.8,
                "thinking": "disabled",
            }.items()
        ):
            _blocked("fixed_atomic_request_configuration_required")
        guards.check("start")
        for case, row in zip(bundle["cases"], result["rows"], strict=True):
            active_row = row
            _run_case(bundle, case, row, result, guards, settings, journal, invoke, client_factory)
        guards.check("end")
    except Exception as error:
        code = error.code if isinstance(error, previous.ExperimentBlocked) else "chain_internal_failure"
        result.update(valid=False, fatal_stop_reason=code, error_code=code)
        if (
            code.startswith("chain_")
            or code == "journal_write_failed"
            or any(not check["stable"] for check in result["provenance_checks"])
        ):
            invalidate_result(result, code)
        if active_row is not None:
            active_row.update(status="failed", error_code=code)
        for row in result["rows"]:
            for record in row["stages"]:
                if record["status"] == "not_run" and record["error_code"] is None:
                    record["error_code"] = code
        # Always attempt a final drift check, including failures after the last SDK call.
        try:
            guards.check("end_after_failure")
        except Exception as end_error:
            end_code = end_error.code if isinstance(end_error, previous.ExperimentBlocked) else "provenance_drift"
            invalidate_result(result, end_code)
    result.update(
        journal=copy.deepcopy(journal.entries),
        elapsed_seconds=round(time.monotonic() - started, 6),
        timing_scope="chain_including_provenance_and_local_validation",
    )
    return _finish(result)
