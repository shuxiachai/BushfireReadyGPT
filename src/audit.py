"""Append-only, privacy-minimised audit events for governed reports."""

import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.agents.report_quality_agent import ReportQualityAgent
from src.export_register import (
    REGISTER_SNAPSHOT_FILES,
    build_export_register_snapshot,
    canonical_export_register_snapshot,
    export_register_snapshot_hashes,
)
from src.governance import (
    APPROVED_STATUS,
    DRAFT_STATUS,
    HUMAN_REVIEW_CHECKLIST,
    REPORT_STATUSES,
    REVIEWED_STATUSES,
    build_review_checklist_snapshot,
    is_review_checklist_complete,
)
from src.report_template import build_human_signoff, remove_human_signoff

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = PROJECT_ROOT / "chat_history" / "audit"
AUDIT_SCHEMA = "government-pilot-v4"
AUDIT_LOCK_STALE_SECONDS = 5 * 60
PACKAGE_CONTEXT_FIELDS = (
    "pilot_mode",
    "organisation_name",
    "location",
    "audience",
    "scenario",
    "report_status",
    "selected_map_area",
    "model_provider",
    "model_name",
    "model_endpoint_boundary",
    "report_id",
    "report_version",
)
IMMUTABLE_PACKAGE_CONTEXT_FIELDS = (
    "pilot_mode",
    "location",
    "audience",
    "scenario",
    "selected_map_area",
    "model_provider",
    "model_name",
    "model_endpoint_boundary",
    "report_id",
    "report_version",
)
REVIEW_RECORD_FIELDS = (
    "approval_status",
    "reviewer_name",
    "reviewer_role",
    "review_date",
    "organisation_name",
    "review_notes",
    "review_checklist",
    "review_checklist_complete",
    "identity_verification",
)
REVIEW_RECORD_INPUT_FIELDS = (*REVIEW_RECORD_FIELDS, "updated_at")


class AuditIntegrityError(RuntimeError):
    """Raised when an audit event or its hash chain cannot be verified."""


def save_report_audit(payload):
    """Create the append-only first event for a report version."""

    return _save_report_audit(payload, allow_parent=False)


def _save_report_audit(payload, *, allow_parent):
    """Write one report root; only the revision transaction may bind a parent."""

    if not isinstance(payload, dict):
        raise TypeError("Audit payload must be a dictionary.")
    report_version = payload.get("report_version")
    if not _is_positive_report_version(report_version):
        raise AuditIntegrityError("A governed report version must be a positive integer.")
    if not allow_parent and (
        payload.get("parent_report_id") not in (None, "") or payload.get("parent_audit_binding") not in (None, {})
    ):
        raise AuditIntegrityError("Parent lineage can only be created by the governed revision transaction.")
    review_record = canonical_review_record(payload.get("human_review"), default_status=DRAFT_STATUS)
    report_status = payload.get("report_status") or DRAFT_STATUS
    if report_status != DRAFT_STATUS or review_record.get("approval_status") != DRAFT_STATUS:
        raise AuditIntegrityError("A newly created report audit must start in Draft status.")
    register_snapshot = canonical_export_register_snapshot(
        payload.get("export_register_snapshot")
        if payload.get("export_register_snapshot") is not None
        else build_export_register_snapshot()
    )
    normalized_payload = {
        **payload,
        "report_status": DRAFT_STATUS,
        "human_review": review_record,
        "export_register_snapshot": register_snapshot,
    }
    report_text = str(normalized_payload.get("report_text") or "")
    _validate_exact_human_signoff(report_text, review_record)
    report_id = str(normalized_payload.get("report_id") or uuid4().hex)
    quality = _validated_report_quality(report_text, normalized_payload)
    package_context = _validated_creation_context(
        normalized_payload,
        report_id,
        report_version,
    )
    event = {
        "audit_schema": AUDIT_SCHEMA,
        "audit_id": uuid4().hex,
        "event_type": "report.created",
        "recorded_at": _utc_now(),
        "previous_audit_id": None,
        "previous_record_hash": None,
        "previous_audit_file": None,
        "app_name": "BushfireReadyGPT",
        "report_id": report_id,
        "report_version": report_version,
        "parent_report_id": normalized_payload.get("parent_report_id"),
        "parent_audit_binding": normalized_payload.get("parent_audit_binding"),
        "report_source": normalized_payload.get("report_source"),
        "revision_request_present": bool(normalized_payload.get("revision_request")),
        "report_content": _content_fingerprint(report_text),
        "governed_body_hash": sha256_text(remove_human_signoff(report_text)),
        "inputs_hash": sha256_json(
            normalized_payload.get("inputs") if isinstance(normalized_payload.get("inputs"), dict) else {}
        ),
        "area_selection_hash": sha256_json(
            normalized_payload.get("area_selection")
            if isinstance(normalized_payload.get("area_selection"), dict)
            else None
        ),
        "inputs": _minimal_inputs(normalized_payload.get("inputs")),
        "analysis": _minimal_analysis(normalized_payload.get("analysis")),
        "quality": quality,
        "grounding_evaluation_hash": sha256_json(
            normalized_payload.get("grounding_evaluation")
            if isinstance(normalized_payload.get("grounding_evaluation"), dict)
            else {}
        ),
        "model_provider": normalized_payload.get("model_provider"),
        "model_name": normalized_payload.get("model_name"),
        "model_endpoint_boundary": normalized_payload.get("model_endpoint_boundary"),
        "external_model_acknowledged_at": normalized_payload.get("external_model_acknowledged_at"),
        "report_status": package_context.get("report_status"),
        "human_review": _minimal_review(review_record),
        "review_record_hash": review_record_hash(review_record),
        "package_context_hash": package_context_hash(package_context),
        "immutable_package_context_hash": immutable_package_context_hash(package_context),
        "organisation_context_hash": sha256_json(package_context.get("organisation_name")),
        "export_register_hashes": export_register_snapshot_hashes(register_snapshot),
        "source_payload_hash": sha256_json(normalized_payload),
        "privacy": _privacy_metadata(),
    }
    if _include_sensitive_content():
        event["sensitive_payload"] = normalized_payload
    audit_dir = _audit_dir()
    with _report_lock(audit_dir, report_id):
        existing = _recover_unique_report_head(audit_dir, report_id)
        if existing is not None:
            existing_record, existing_path, _recovered = existing
            if existing_record.get("event_type") == "report.created" and existing_record.get(
                "source_payload_hash"
            ) == event.get("source_payload_hash"):
                return str(existing_path)
            raise AuditIntegrityError(f"An audit head already exists for report {report_id}.")
        new_path = _write_event(event, report_id, audit_dir=audit_dir)
        try:
            record = load_and_verify_audit(new_path)
            _write_head(audit_dir, record, Path(new_path))
        except (AuditIntegrityError, OSError, TypeError, ValueError):
            _best_effort_unlink(new_path)
            raise
        return new_path


def save_revision_audit(parent_path, payload):
    """Create one child report while atomically claiming the verified parent head."""

    if not isinstance(payload, dict):
        raise TypeError("Revision audit payload must be a dictionary.")
    if "parent_audit_binding" in payload:
        raise AuditIntegrityError("Parent audit binding is derived internally, not supplied by callers.")
    parent_path = Path(parent_path).resolve()
    if parent_path.parent != _audit_dir():
        raise AuditIntegrityError("Revision parent is outside the authoritative audit directory.")
    initial_parent = load_and_verify_audit(parent_path)
    parent_report_id = str(initial_parent.get("report_id") or "")
    with _report_lock(parent_path.parent, parent_report_id):
        parent = load_and_verify_audit(parent_path)
        _recover_unique_report_head(parent_path.parent, parent_report_id)
        _assert_current_head(parent_path.parent, parent, parent_path)
        supplied_parent_id = payload.get("parent_report_id")
        if supplied_parent_id is not None and str(supplied_parent_id) != parent_report_id:
            raise AuditIntegrityError("Revision parent report ID does not match its audit event.")
        child_report_id = str(payload.get("report_id") or "")
        if not child_report_id or child_report_id == parent_report_id:
            raise AuditIntegrityError("A governed revision requires a new, explicit child report ID.")
        parent_version = parent.get("report_version")
        child_version = payload.get("report_version")
        if (
            not isinstance(parent_version, int)
            or isinstance(parent_version, bool)
            or not isinstance(child_version, int)
            or isinstance(child_version, bool)
            or child_version != parent_version + 1
        ):
            raise AuditIntegrityError("A governed revision version must be exactly one greater than its parent.")
        try:
            child_register_hashes = export_register_snapshot_hashes(payload.get("export_register_snapshot"))
        except ValueError as error:
            raise AuditIntegrityError(
                "A governed revision requires its complete frozen export-register snapshot."
            ) from error
        if child_register_hashes != parent.get("export_register_hashes"):
            raise AuditIntegrityError("A governed revision cannot change its frozen data and licence registers.")
        parent_binding = {
            "report_id": parent_report_id,
            "report_version": parent.get("report_version"),
            "audit_id": parent.get("audit_id"),
            "record_hash": parent.get("record_hash"),
            "report_content_sha256": parent.get("report_content", {}).get("sha256"),
            "governed_body_hash": parent.get("governed_body_hash"),
        }
        claim_path = _revision_claim_path(parent_path.parent, parent)
        if claim_path.exists():
            recovered_child = _recover_revision_claim(
                claim_path,
                parent_path.parent,
                parent_binding,
            )
            if recovered_child is not None:
                if _revision_child_matches_payload(
                    recovered_child,
                    payload,
                    parent_binding,
                ):
                    return str(recovered_child)
                raise AuditIntegrityError(
                    f"This parent report version has already produced a governed revision ({recovered_child.name})."
                )
        _atomic_write_json(
            claim_path,
            {
                "state": "pending",
                "recorded_at": _utc_now(),
                "parent": parent_binding,
            },
        )
        try:
            child_path = _save_report_audit(
                {
                    **payload,
                    "parent_report_id": parent_report_id,
                    "parent_audit_binding": parent_binding,
                },
                allow_parent=True,
            )
        except (AuditIntegrityError, OSError, TypeError, ValueError):
            _best_effort_unlink(claim_path)
            raise
        child = load_and_verify_audit(child_path)
        try:
            _commit_revision_claim(claim_path, parent_binding, child, child_path)
        except OSError:
            # The child event is already durable and uniquely protected by the
            # pending claim. Return it so the workflow can persist its report
            # snapshot; the next access will finish the idempotent claim commit.
            return child_path
        return child_path


def append_audit_event(previous_path, event_type, payload):
    """Append a verified event without modifying any existing audit file."""

    if event_type != "review.recorded":
        raise AuditIntegrityError("Only the review.recorded audit transition is supported.")
    if not isinstance(payload, dict) or "report_text" not in payload:
        raise AuditIntegrityError("Audit append payload must bind the resulting report text.")
    review_record = canonical_review_record(payload.get("human_review"))
    report_status = payload.get("report_status")
    if report_status != review_record.get("approval_status"):
        raise AuditIntegrityError("Review and audit report statuses must match exactly.")
    normalized_payload = {
        **payload,
        "report_status": report_status,
        "human_review": review_record,
    }
    previous_path = Path(previous_path).resolve()
    if previous_path.parent != _audit_dir():
        raise AuditIntegrityError(
            "Configured audit directory changed; refusing to create a broken cross-directory chain."
        )
    initial_previous = load_and_verify_audit(previous_path)
    report_id = str(initial_previous.get("report_id") or "")
    if not report_id:
        raise AuditIntegrityError("Previous audit event has no report ID.")
    with _report_lock(previous_path.parent, report_id):
        previous = load_and_verify_audit(previous_path)
        recovered = _recover_unique_report_head(previous_path.parent, report_id)
        if recovered is not None:
            recovered_record, recovered_path, _was_recovered = recovered
            if (
                _was_recovered
                and recovered_path != previous_path
                and _event_matches_retry(
                    recovered_record,
                    normalized_payload,
                )
            ):
                return str(recovered_path)
        _assert_current_head(previous_path.parent, previous, previous_path)
        payload_report_id = normalized_payload.get("report_id")
        if payload_report_id is not None and str(payload_report_id) != report_id:
            raise AuditIntegrityError("Audit append report ID does not match the previous event.")
        previous_version = previous.get("report_version")
        payload_version = normalized_payload.get("report_version", previous_version)
        if payload_version != previous_version:
            raise AuditIntegrityError("Audit append report version does not match the previous event.")
        context_hashes = _validated_append_context(previous, normalized_payload)

        report_text = str(normalized_payload.get("report_text") or "")
        _validate_exact_human_signoff(report_text, review_record)
        governed_body_hash = sha256_text(remove_human_signoff(report_text))
        if governed_body_hash != previous.get("governed_body_hash"):
            raise AuditIntegrityError("A review event may change only the Human Review Sign-off section.")
        quality = _validated_report_quality(report_text, normalized_payload)
        _validate_review_transition(review_record, quality, previous)
        event = {
            "audit_schema": AUDIT_SCHEMA,
            "audit_id": uuid4().hex,
            "event_type": str(event_type),
            "recorded_at": _utc_now(),
            "previous_audit_id": previous["audit_id"],
            "previous_record_hash": previous["record_hash"],
            "previous_audit_file": previous_path.name,
            "app_name": "BushfireReadyGPT",
            "report_id": report_id,
            "report_version": previous_version,
            "parent_report_id": previous.get("parent_report_id"),
            "parent_audit_binding": previous.get("parent_audit_binding"),
            "report_content": _content_fingerprint(report_text),
            "governed_body_hash": governed_body_hash,
            "inputs_hash": previous.get("inputs_hash"),
            "area_selection_hash": previous.get("area_selection_hash"),
            "inputs": previous.get("inputs", {}),
            "analysis": previous.get("analysis", {}),
            "quality": quality,
            "grounding_evaluation_hash": previous.get("grounding_evaluation_hash"),
            "model_provider": previous.get("model_provider"),
            "model_name": previous.get("model_name"),
            "model_endpoint_boundary": previous.get("model_endpoint_boundary"),
            "external_model_acknowledged_at": previous.get("external_model_acknowledged_at"),
            "report_status": report_status,
            "human_review": _minimal_review(review_record),
            "review_record_hash": review_record_hash(review_record),
            **context_hashes,
            "export_register_hashes": previous.get("export_register_hashes"),
            "source_payload_hash": sha256_json(normalized_payload),
            "privacy": _privacy_metadata(),
        }
        if _include_sensitive_content():
            event["sensitive_payload"] = normalized_payload
        new_path = _write_event(event, report_id, audit_dir=previous_path.parent)
        try:
            record = load_and_verify_audit(new_path)
            _write_head(previous_path.parent, record, Path(new_path))
        except (AuditIntegrityError, OSError, TypeError, ValueError):
            _best_effort_unlink(new_path)
            raise
        return new_path


def load_and_verify_audit(path, verify_chain=True, _seen=None):
    """Load an audit event and verify its hash and, by default, its local chain."""

    audit_path = Path(path).resolve()
    try:
        record = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AuditIntegrityError(f"Audit event could not be read: {audit_path}") from error
    validate_audit_record(record)
    if not verify_chain or not record.get("previous_audit_file"):
        return record

    seen = set(_seen or ())
    if audit_path in seen:
        raise AuditIntegrityError("Audit event chain contains a cycle.")
    seen.add(audit_path)
    previous_name = str(record["previous_audit_file"])
    if Path(previous_name).name != previous_name:
        raise AuditIntegrityError("Audit chain contains an invalid previous filename.")
    previous_path = (audit_path.parent / previous_name).resolve()
    if previous_path.parent != audit_path.parent:
        raise AuditIntegrityError("Audit chain escapes its configured directory.")
    previous = load_and_verify_audit(previous_path, verify_chain=True, _seen=seen)
    if previous.get("audit_id") != record.get("previous_audit_id"):
        raise AuditIntegrityError("Audit chain previous ID does not match.")
    if previous.get("record_hash") != record.get("previous_record_hash"):
        raise AuditIntegrityError("Audit chain previous hash does not match.")
    return record


def get_audit_chain_paths(latest_path):
    """Return verified audit paths from the creation event to the latest event."""

    current = Path(latest_path).resolve()
    latest_record = load_and_verify_audit(current)
    _assert_current_head(current.parent, latest_record, current)
    newest_to_oldest = []
    seen = set()
    while True:
        if current in seen:
            raise AuditIntegrityError("Audit event chain contains a cycle.")
        seen.add(current)
        record = load_and_verify_audit(current, verify_chain=False)
        newest_to_oldest.append(current)
        previous_name = record.get("previous_audit_file")
        if not previous_name:
            break
        if Path(str(previous_name)).name != str(previous_name):
            raise AuditIntegrityError("Audit chain contains an invalid previous filename.")
        current = (current.parent / str(previous_name)).resolve()
    load_and_verify_audit(latest_path)
    return list(reversed(newest_to_oldest))


def capture_current_audit_chain(latest_path):
    """Capture verified current-chain bytes under the same per-report lock as append."""

    return _capture_authoritative_audit_chain(latest_path, require_current=True)


def capture_audit_chain_at_event(latest_path):
    """Capture an authoritative historical chain ending at one bound event."""

    return _capture_authoritative_audit_chain(latest_path, require_current=False)


def capture_parent_lineage(child_record, immediate_parent_path):
    """Capture and verify every ancestor chain bound by a revision event."""

    validate_audit_record(child_record)
    binding = child_record.get("parent_audit_binding")
    if not binding:
        if immediate_parent_path:
            raise AuditIntegrityError("A root report cannot claim an unbound parent audit path.")
        return []
    if not immediate_parent_path:
        raise AuditIntegrityError("The revision is missing its immediate parent audit path.")

    levels = []
    seen = set()
    next_path = Path(immediate_parent_path).resolve()
    while binding:
        audit_id = str(binding.get("audit_id") or "")
        if not audit_id or audit_id in seen:
            raise AuditIntegrityError("Revision lineage contains a missing or cyclic audit ID.")
        seen.add(audit_id)
        chain = capture_audit_chain_at_event(next_path)
        parent = chain[-1]["record"]
        if binding != _parent_binding_for_record(parent):
            raise AuditIntegrityError("The revision parent audit chain does not match its lineage binding.")
        levels.append({"binding": binding, "chain": chain})
        binding = parent.get("parent_audit_binding")
        if binding:
            next_path = _find_bound_audit_event(binding)
    return levels


def _capture_authoritative_audit_chain(latest_path, *, require_current):
    latest_path = Path(latest_path).resolve()
    if latest_path.parent != _audit_dir():
        raise AuditIntegrityError("Audit event is outside the currently configured authoritative audit directory.")
    initial = load_and_verify_audit(latest_path)
    report_id = str(initial.get("report_id") or "")
    with _report_lock(latest_path.parent, report_id):
        if require_current:
            _recover_unique_report_head(latest_path.parent, report_id)
            paths = get_audit_chain_paths(latest_path)
        else:
            paths = _historical_chain_paths(latest_path)
        captured = []
        previous = None
        for path in paths:
            try:
                payload_bytes = path.read_bytes()
                record = json.loads(payload_bytes.decode("utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise AuditIntegrityError(f"Audit event changed or became unreadable: {path}") from error
            validate_audit_record(record)
            if previous is not None and (
                record.get("previous_audit_id") != previous.get("audit_id")
                or record.get("previous_record_hash") != previous.get("record_hash")
            ):
                raise AuditIntegrityError("Audit chain changed while it was captured.")
            captured.append({"path": path, "bytes": payload_bytes, "record": record})
            previous = record
        if require_current:
            _assert_current_head(latest_path.parent, captured[-1]["record"], latest_path)
        return captured


def _historical_chain_paths(latest_path):
    current = Path(latest_path).resolve()
    newest_to_oldest = []
    seen = set()
    while True:
        if current in seen:
            raise AuditIntegrityError("Audit event chain contains a cycle.")
        seen.add(current)
        record = load_and_verify_audit(current, verify_chain=False)
        newest_to_oldest.append(current)
        previous_name = record.get("previous_audit_file")
        if not previous_name:
            break
        if Path(str(previous_name)).name != str(previous_name):
            raise AuditIntegrityError("Audit chain contains an invalid previous filename.")
        current = (current.parent / str(previous_name)).resolve()
        if current.parent != latest_path.parent:
            raise AuditIntegrityError("Audit chain escapes its configured directory.")
    load_and_verify_audit(latest_path)
    return list(reversed(newest_to_oldest))


def _parent_binding_for_record(record):
    return {
        "report_id": record.get("report_id"),
        "report_version": record.get("report_version"),
        "audit_id": record.get("audit_id"),
        "record_hash": record.get("record_hash"),
        "report_content_sha256": record.get("report_content", {}).get("sha256"),
        "governed_body_hash": record.get("governed_body_hash"),
    }


def _find_bound_audit_event(binding):
    matches = []
    for candidate in _audit_dir().glob("audit_*.json"):
        try:
            record = load_and_verify_audit(candidate, verify_chain=False)
        except AuditIntegrityError:
            continue
        if _parent_binding_for_record(record) == binding:
            matches.append(candidate.resolve())
    if len(matches) != 1:
        raise AuditIntegrityError("Revision lineage could not resolve exactly one authoritative ancestor event.")
    return matches[0]


def sha256_json(value):
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def sha256_text(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def canonical_package_context(context):
    """Return the exact allow-listed context represented by an audit event."""

    if not isinstance(context, dict):
        raise AuditIntegrityError("Package context must be a dictionary.")
    unknown_fields = sorted(set(context) - set(PACKAGE_CONTEXT_FIELDS))
    if unknown_fields:
        raise AuditIntegrityError("Package context contains unsupported fields: " + ", ".join(unknown_fields))
    canonical = {field: context.get(field) for field in PACKAGE_CONTEXT_FIELDS}
    selected = canonical.get("selected_map_area")
    if selected is None or selected == {}:
        canonical["selected_map_area"] = None
    elif not isinstance(selected, dict):
        raise AuditIntegrityError("Package context selected_map_area must be a dictionary or null.")
    return canonical


def package_context_hash(context):
    """Hash the canonical, version-scoped fields used to label an export package."""

    return sha256_json(canonical_package_context(context))


def immutable_package_context_hash(context):
    """Hash context fields that must not change during review of one report version."""

    canonical = canonical_package_context(context)
    return sha256_json({field: canonical.get(field) for field in IMMUTABLE_PACKAGE_CONTEXT_FIELDS})


def canonical_review_record(review_record, default_status=None):
    if review_record is None:
        review_record = {}
    if not isinstance(review_record, dict):
        raise AuditIntegrityError("Review record must be a dictionary.")
    unknown_fields = sorted(set(review_record) - set(REVIEW_RECORD_INPUT_FIELDS))
    if unknown_fields:
        raise AuditIntegrityError("Review record contains unsupported fields: " + ", ".join(unknown_fields))
    status = review_record.get("approval_status") or default_status
    if status not in REPORT_STATUSES:
        raise AuditIntegrityError("Review record contains an unknown or missing approval status.")
    checklist = _canonical_review_checklist(review_record.get("review_checklist"))
    canonical = {field: review_record.get(field) for field in REVIEW_RECORD_FIELDS}
    canonical["approval_status"] = status
    canonical["review_checklist"] = checklist
    canonical["review_checklist_complete"] = is_review_checklist_complete(checklist)
    return canonical


def _canonical_review_checklist(checklist):
    if checklist is None:
        checklist = []
    if not isinstance(checklist, list):
        raise AuditIntegrityError("Review checklist must be a list of canonical items.")
    expected_ids = {item["id"] for item in HUMAN_REVIEW_CHECKLIST}
    checked = {}
    for item in checklist:
        if not isinstance(item, dict):
            raise AuditIntegrityError("Review checklist contains a malformed item.")
        item_id = item.get("id")
        if item_id not in expected_ids or item_id in checked:
            raise AuditIntegrityError("Review checklist contains an unknown or duplicate item.")
        checked[item_id] = item.get("checked") is True
    return build_review_checklist_snapshot(lambda item_id: checked.get(item_id, False))


def validate_audit_record(record):
    """Validate one in-memory v4 audit record and return it unchanged."""

    if not isinstance(record, dict) or record.get("audit_schema") != AUDIT_SCHEMA:
        raise AuditIntegrityError(
            "Audit event schema is missing, legacy, or unsupported; regenerate the governed report."
        )
    expected_hash = sha256_json({key: value for key, value in record.items() if key != "record_hash"})
    if record.get("record_hash") != expected_hash:
        raise AuditIntegrityError("Audit event hash verification failed.")

    report_content = record.get("report_content")
    analysis = record.get("analysis")
    if not isinstance(report_content, dict) or not isinstance(analysis, dict):
        raise AuditIntegrityError("Audit event contains malformed report or analysis bindings.")
    required_hashes = {
        "record_hash": record.get("record_hash"),
        "report_content.sha256": report_content.get("sha256"),
        "governed_body_hash": record.get("governed_body_hash"),
        "inputs_hash": record.get("inputs_hash"),
        "area_selection_hash": record.get("area_selection_hash"),
        "analysis.analysis_hash": analysis.get("analysis_hash"),
        "review_record_hash": record.get("review_record_hash"),
        "package_context_hash": record.get("package_context_hash"),
        "immutable_package_context_hash": record.get("immutable_package_context_hash"),
        "organisation_context_hash": record.get("organisation_context_hash"),
        "source_payload_hash": record.get("source_payload_hash"),
    }
    missing = [name for name, value in required_hashes.items() if not _is_sha256(value)]
    if missing:
        raise AuditIntegrityError("Audit event is missing required v4 snapshot bindings: " + ", ".join(missing))
    grounding_hash = record.get("grounding_evaluation_hash")
    if grounding_hash is not None and not _is_sha256(grounding_hash):
        raise AuditIntegrityError("Audit event has an invalid grounding-evaluation binding.")
    register_hashes = record.get("export_register_hashes")
    if (
        not isinstance(register_hashes, dict)
        or set(register_hashes) != set(REGISTER_SNAPSHOT_FILES)
        or any(not _is_sha256(register_hashes.get(path)) for path in REGISTER_SNAPSHOT_FILES)
    ):
        raise AuditIntegrityError("Audit event has an invalid frozen data/licence register binding.")
    if not str(record.get("audit_id") or "").strip():
        raise AuditIntegrityError("Audit event has no audit ID.")
    if not str(record.get("event_type") or "").strip():
        raise AuditIntegrityError("Audit event has no event type.")
    if not str(record.get("report_id") or "").strip():
        raise AuditIntegrityError("Audit event has no report ID.")
    if not _is_positive_report_version(record.get("report_version")):
        raise AuditIntegrityError("Audit event report version must be a positive integer.")
    if record.get("report_status") not in REPORT_STATUSES:
        raise AuditIntegrityError("Audit event contains an unknown report status.")
    _validate_parent_binding(record)
    return record


def _validate_parent_binding(record):
    parent_report_id = record.get("parent_report_id")
    binding = record.get("parent_audit_binding")
    if not parent_report_id:
        if binding not in (None, {}):
            raise AuditIntegrityError("Root audit event contains an unexpected parent binding.")
        return
    if not isinstance(binding, dict) or str(binding.get("report_id")) != str(parent_report_id):
        raise AuditIntegrityError("Revision audit event has an invalid parent report binding.")
    for field in ("record_hash", "report_content_sha256", "governed_body_hash"):
        if not _is_sha256(binding.get(field)):
            raise AuditIntegrityError(f"Revision audit parent binding has an invalid {field}.")
    if not str(binding.get("audit_id") or "").strip():
        raise AuditIntegrityError("Revision audit parent binding has no audit ID.")


def _validated_report_quality(report_text, payload):
    quality = ReportQualityAgent().run(report_text)
    supplied = payload.get("quality")
    if supplied is not None and supplied != quality:
        raise AuditIntegrityError("Supplied report quality does not match a fresh deterministic check.")
    return quality


def _validate_review_transition(review_record, quality, previous):
    status = review_record["approval_status"]
    if status in REVIEWED_STATUSES:
        missing = [
            label
            for key, label in (
                ("organisation_name", "organisation / department"),
                ("reviewer_name", "reviewer name"),
                ("reviewer_role", "reviewer role"),
            )
            if not str(review_record.get(key) or "").strip()
        ]
        if missing:
            raise AuditIntegrityError("Reviewed audit event is missing required identity fields: " + ", ".join(missing))
    if status != APPROVED_STATUS:
        return
    if not is_review_checklist_complete(review_record.get("review_checklist")):
        raise AuditIntegrityError("Approved audit event requires the complete canonical checklist.")
    if quality.get("approval_gate", {}).get("passed") is not True:
        raise AuditIntegrityError("Approved audit event failed the structural quality gate.")
    integrity = (previous.get("analysis") or {}).get("data_integrity") or {}
    if integrity.get("core_ready") is not True or integrity.get("custom_data") is not False:
        raise AuditIntegrityError("Approved audit event requires manifest-verified bundled core data.")
    if (
        previous.get("area_selection_hash") != sha256_json(None)
        and integrity.get("optional_map_state") != "bundle_verified"
    ):
        raise AuditIntegrityError("Approved audit event requires a sidecar-verified national-map bundle.")


def _validate_exact_human_signoff(report_text, review_record):
    heading = "## Human Review Sign-off"
    expected_suffix = f"\n\n{build_human_signoff(review_record)}\n"
    heading_count = sum(1 for line in str(report_text).splitlines() if line.strip() == heading)
    if heading_count != 1 or not str(report_text).endswith(expected_suffix):
        raise AuditIntegrityError(
            "A review event must end with exactly one deterministic Human Review Sign-off section."
        )


def _validated_creation_context(payload, report_id, report_version):
    derived = canonical_package_context(_derive_package_context(payload, report_id, report_version))
    supplied = payload.get("package_context")
    if supplied is not None:
        supplied = canonical_package_context(supplied)
        if supplied != derived:
            raise AuditIntegrityError(
                "Package context does not match the report input, model, review and geography snapshot."
            )
    return derived


def _validated_append_context(previous, payload):
    supplied = payload.get("package_context")
    if supplied is None:
        raise AuditIntegrityError("A review audit event must include its complete canonical package context.")

    context = canonical_package_context(supplied)
    immutable_hash = immutable_package_context_hash(context)
    if immutable_hash != previous.get("immutable_package_context_hash"):
        raise AuditIntegrityError(
            "Package context changed immutable report inputs, geography, model or identity fields."
        )

    review = payload.get("human_review")
    review = review if isinstance(review, dict) else {}
    review_status = review.get("approval_status")
    payload_status = payload.get("report_status")
    if (
        review_status != payload_status
        or context.get("report_status") != payload_status
        or payload_status not in REPORT_STATUSES
    ):
        raise AuditIntegrityError("Package context report status does not match the review event.")

    review_organisation = review.get("organisation_name")
    if str(review_organisation or "").strip():
        if context.get("organisation_name") != review_organisation:
            raise AuditIntegrityError("Package context organisation does not match the review event.")
    elif sha256_json(context.get("organisation_name")) != previous.get("organisation_context_hash"):
        raise AuditIntegrityError("Package context organisation changed without a bound review organisation.")

    return {
        "package_context_hash": package_context_hash(context),
        "immutable_package_context_hash": immutable_hash,
        "organisation_context_hash": sha256_json(context.get("organisation_name")),
    }


def _is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_positive_report_version(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _derive_package_context(payload, report_id, report_version):
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    review = payload.get("human_review") if isinstance(payload.get("human_review"), dict) else {}
    return {
        "pilot_mode": inputs.get("pilot_mode"),
        "organisation_name": review.get("organisation_name") or inputs.get("organisation_name"),
        "location": inputs.get("location"),
        "audience": inputs.get("audience"),
        "scenario": inputs.get("scenario"),
        "report_status": review.get("approval_status") or payload.get("report_status"),
        "selected_map_area": payload.get("area_selection") if isinstance(payload.get("area_selection"), dict) else None,
        "model_provider": payload.get("model_provider"),
        "model_name": payload.get("model_name"),
        "model_endpoint_boundary": payload.get("model_endpoint_boundary"),
        "report_id": report_id,
        "report_version": report_version,
    }


def _write_event(event, report_id, audit_dir=None):
    audit_dir = Path(audit_dir).resolve() if audit_dir is not None else _audit_dir()
    audit_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    output_path = audit_dir / f"audit_{timestamp}_{_slugify(report_id)}_{uuid4().hex[:8]}.json"
    event = dict(event)
    event["record_hash"] = sha256_json(event)
    _atomic_write_json(output_path, event)
    return str(output_path)


def _audit_dir():
    configured = os.environ.get("BUSHFIRE_AUDIT_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else Path(AUDIT_DIR).resolve()


def _head_path(audit_dir, report_id):
    return Path(audit_dir) / f".head_{_slugify(report_id)}.json"


def _revision_claim_path(audit_dir, parent_record):
    report_id = _slugify(parent_record.get("report_id"))
    report_version = _slugify(parent_record.get("report_version"))
    return Path(audit_dir) / f".revision_{report_id}_v{report_version}.json"


def _recover_revision_claim(claim_path, audit_dir, parent_binding):
    """Finish an interrupted claim, or release a stale claim with no child."""

    try:
        claim = json.loads(Path(claim_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuditIntegrityError("Revision claim is unreadable or malformed.") from error
    claim_parent = claim.get("parent") if isinstance(claim, dict) else None
    if (
        not isinstance(claim_parent, dict)
        or str(claim_parent.get("report_id") or "") != str(parent_binding.get("report_id") or "")
        or claim_parent.get("report_version") != parent_binding.get("report_version")
    ):
        raise AuditIntegrityError("Revision claim does not match the verified parent report.")
    state = claim.get("state")
    if state == "committed":
        return _verified_claim_child(claim, audit_dir, claim_parent)
    if state != "pending":
        raise AuditIntegrityError("Revision claim has an unknown state.")

    candidates = []
    for candidate in Path(audit_dir).glob("audit_*.json"):
        try:
            record = load_and_verify_audit(candidate)
        except AuditIntegrityError:
            continue
        if record.get("event_type") == "report.created" and record.get("parent_audit_binding") == claim_parent:
            candidates.append((candidate.resolve(), record))
    if len(candidates) > 1:
        raise AuditIntegrityError("Revision recovery found multiple children for one parent report version.")
    if candidates:
        child_path, child = candidates[0]
        _commit_revision_claim(claim_path, claim_parent, child, child_path)
        return child_path

    try:
        age_seconds = max(0.0, time.time() - Path(claim_path).stat().st_mtime)
    except OSError as error:
        raise AuditIntegrityError("Revision claim disappeared during recovery.") from error
    if age_seconds < AUDIT_LOCK_STALE_SECONDS:
        raise AuditIntegrityError("A revision transaction is still pending; retry after its recovery window.")
    _best_effort_unlink(claim_path)
    if Path(claim_path).exists():
        raise AuditIntegrityError("A stale revision claim could not be released safely.")
    return None


def _verified_claim_child(claim, audit_dir, parent_binding):
    child_claim = claim.get("child")
    if not isinstance(child_claim, dict):
        raise AuditIntegrityError("Committed revision claim has no child binding.")
    filename = str(child_claim.get("audit_file") or "")
    if not filename or Path(filename).name != filename:
        raise AuditIntegrityError("Committed revision claim has an invalid child filename.")
    child_path = (Path(audit_dir) / filename).resolve()
    if child_path.parent != Path(audit_dir).resolve():
        raise AuditIntegrityError("Committed revision child escapes the audit directory.")
    child = load_and_verify_audit(child_path)
    expected = {
        "report_id": child.get("report_id"),
        "report_version": child.get("report_version"),
        "audit_id": child.get("audit_id"),
        "record_hash": child.get("record_hash"),
        "audit_file": child_path.name,
    }
    if (
        child.get("event_type") != "report.created"
        or child.get("parent_audit_binding") != parent_binding
        or child_claim != expected
    ):
        raise AuditIntegrityError("Committed revision child binding failed verification.")
    return child_path


def _revision_child_matches_payload(child_path, payload, parent_binding):
    try:
        review_record = canonical_review_record(
            payload.get("human_review"),
            default_status=DRAFT_STATUS,
        )
        register_snapshot = canonical_export_register_snapshot(payload.get("export_register_snapshot"))
        expected_payload = {
            **payload,
            "parent_report_id": parent_binding.get("report_id"),
            "parent_audit_binding": parent_binding,
            "report_status": DRAFT_STATUS,
            "human_review": review_record,
            "export_register_snapshot": register_snapshot,
        }
        child = load_and_verify_audit(child_path)
    except (AuditIntegrityError, OSError, TypeError, ValueError):
        return False
    return child.get("event_type") == "report.created" and child.get("source_payload_hash") == sha256_json(
        expected_payload
    )


def _commit_revision_claim(claim_path, parent_binding, child, child_path):
    _atomic_write_json(
        claim_path,
        {
            "state": "committed",
            "recorded_at": _utc_now(),
            "parent": parent_binding,
            "child": {
                "report_id": child.get("report_id"),
                "report_version": child.get("report_version"),
                "audit_id": child.get("audit_id"),
                "record_hash": child.get("record_hash"),
                "audit_file": Path(child_path).name,
            },
        },
    )


def _event_matches_retry(record, normalized_payload):
    try:
        review = canonical_review_record(normalized_payload.get("human_review"))
        context = canonical_package_context(normalized_payload.get("package_context"))
        report_text = str(normalized_payload.get("report_text") or "")
        quality = _validated_report_quality(report_text, normalized_payload)
    except (AuditIntegrityError, TypeError, ValueError):
        return False
    return (
        record.get("event_type") == "review.recorded"
        and str(record.get("report_id")) == str(normalized_payload.get("report_id"))
        and record.get("report_version") == normalized_payload.get("report_version")
        and record.get("report_status") == normalized_payload.get("report_status")
        and record.get("report_content", {}).get("sha256") == sha256_text(report_text)
        and record.get("governed_body_hash") == sha256_text(remove_human_signoff(report_text))
        and record.get("review_record_hash") == review_record_hash(review)
        and record.get("package_context_hash") == package_context_hash(context)
        and record.get("quality") == quality
    )


def _recover_unique_report_head(audit_dir, report_id):
    """Recover a unique linear audit tip and reject orphaned or forked graphs."""

    audit_dir = Path(audit_dir).resolve()
    report_id = str(report_id)
    events = _load_report_audit_events(audit_dir, report_id)
    head_path = _head_path(audit_dir, report_id)
    if not events:
        if head_path.exists():
            raise AuditIntegrityError("Audit head exists without a corresponding report event.")
        return None

    by_id, roots, successors = _build_report_audit_graph(events)
    if len(roots) != 1:
        raise AuditIntegrityError("Audit graph must contain exactly one creation event.")
    root_path, root = roots[0]
    if root.get("event_type") != "report.created":
        raise AuditIntegrityError("Audit graph root is not a report.created event.")
    _validate_report_audit_bindings(events, by_id, root)
    tip_path, tip = _walk_report_audit_graph(root_path, root, successors, len(events))

    expected_head = {
        "report_id": tip.get("report_id"),
        "report_version": tip.get("report_version"),
        "audit_id": tip.get("audit_id"),
        "record_hash": tip.get("record_hash"),
        "audit_file": tip_path.name,
    }
    current_head = _read_audit_head(head_path)
    recovered = current_head != expected_head
    if recovered:
        _write_head(audit_dir, tip, tip_path)
    return tip, tip_path, recovered


def _load_report_audit_events(audit_dir, report_id):
    slug_marker = f"_{_slugify(report_id)}_"
    events = []
    for candidate in audit_dir.glob("audit_*.json"):
        try:
            raw_record = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            if slug_marker in candidate.name:
                raise AuditIntegrityError(
                    f"Audit graph contains an unreadable event for report {report_id}."
                ) from error
            continue
        if not isinstance(raw_record, dict) or str(raw_record.get("report_id")) != report_id:
            continue
        validate_audit_record(raw_record)
        events.append((candidate.resolve(), raw_record))
    return events


def _build_report_audit_graph(events):
    by_id = {}
    roots = []
    successors = {}
    for path, record in events:
        audit_id = record.get("audit_id")
        if audit_id in by_id:
            raise AuditIntegrityError("Audit graph contains a duplicate audit ID.")
        by_id[audit_id] = (path, record)
        previous_id = record.get("previous_audit_id")
        if previous_id is None:
            roots.append((path, record))
        else:
            successors.setdefault(previous_id, []).append((path, record))
    return by_id, roots, successors


def _validate_report_audit_bindings(events, by_id, root):
    for path, record in events:
        previous_id = record.get("previous_audit_id")
        if previous_id is None:
            continue
        parent_entry = by_id.get(previous_id)
        if parent_entry is None:
            raise AuditIntegrityError("Audit graph contains an orphan event.")
        parent_path, parent = parent_entry
        if (
            record.get("previous_record_hash") != parent.get("record_hash")
            or record.get("previous_audit_file") != parent_path.name
            or record.get("report_version") != root.get("report_version")
        ):
            raise AuditIntegrityError("Audit graph contains a broken predecessor binding.")


def _walk_report_audit_graph(root_path, root, successors, event_count):
    visited = set()
    tip_path, tip = root_path, root
    while True:
        audit_id = tip.get("audit_id")
        if audit_id in visited:
            raise AuditIntegrityError("Audit graph contains a cycle.")
        visited.add(audit_id)
        next_events = successors.get(audit_id, [])
        if len(next_events) > 1:
            raise AuditIntegrityError("Audit graph contains multiple successors for one event.")
        if not next_events:
            break
        tip_path, tip = next_events[0]
    if len(visited) != event_count:
        raise AuditIntegrityError("Audit graph contains a disconnected event or cycle.")
    return tip_path, tip


def _read_audit_head(head_path):
    try:
        return json.loads(head_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _write_head(audit_dir, record, event_path):
    head_path = _head_path(audit_dir, record.get("report_id"))
    payload = {
        "report_id": record.get("report_id"),
        "report_version": record.get("report_version"),
        "audit_id": record.get("audit_id"),
        "record_hash": record.get("record_hash"),
        "audit_file": Path(event_path).name,
    }
    _atomic_write_json(head_path, payload, sort_keys=True)


def _atomic_write_json(path, payload, *, sort_keys=False):
    """Durably replace a small audit JSON file and clean all staging debris."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except OSError:
        pass
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(
                payload,
                file,
                ensure_ascii=False,
                indent=2,
                sort_keys=sort_keys,
                default=str,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _fsync_directory(directory):
    """Persist directory metadata where the host OS exposes directory fsync."""

    flags = getattr(os, "O_RDONLY", 0)
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _best_effort_unlink(path):
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _assert_current_head(audit_dir, record, event_path):
    head_path = _head_path(audit_dir, record.get("report_id"))
    try:
        head = json.loads(head_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuditIntegrityError(
            "Audit head is missing or unreadable; refusing a potentially forked append."
        ) from error
    expected = {
        "report_id": record.get("report_id"),
        "report_version": record.get("report_version"),
        "audit_id": record.get("audit_id"),
        "record_hash": record.get("record_hash"),
        "audit_file": Path(event_path).name,
    }
    if head != expected:
        raise AuditIntegrityError("Audit append target is no longer the current report head.")


@contextmanager
def _report_lock(audit_dir, report_id, timeout_seconds=5.0):
    audit_dir = Path(audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)
    lock_path = audit_dir / f".lock_{_slugify(report_id)}.lock"
    deadline = time.monotonic() + timeout_seconds
    descriptor = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            try:
                stale = time.time() - lock_path.stat().st_mtime > AUDIT_LOCK_STALE_SECONDS
            except OSError:
                stale = False
            if stale:
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise AuditIntegrityError("Timed out waiting for the report audit lock.") from error
            time.sleep(0.05)
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        descriptor = None
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _include_sensitive_content():
    return os.environ.get("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _privacy_metadata():
    sensitive = _include_sensitive_content()
    return {
        "classification": "sensitive-governance-metadata",
        "contains_full_report_text": sensitive,
        "contains_reviewer_name": sensitive,
        "contains_free_text_notes": sensitive,
        "retention_policy": "Locally retained until removed under the operator's retention policy.",
    }


def _content_fingerprint(text):
    return {"sha256": sha256_text(text), "character_count": len(text)}


def _minimal_inputs(inputs):
    values = inputs if isinstance(inputs, dict) else {}
    concerns = values.get("concerns") if isinstance(values.get("concerns"), list) else []
    return {
        "pilot_mode": values.get("pilot_mode"),
        "scenario": values.get("scenario"),
        "timeframe": values.get("timeframe"),
        "concerns": concerns,
        "location_present": bool(str(values.get("location") or "").strip()),
        "audience_present": bool(str(values.get("audience") or "").strip()),
        "extra_context_present": bool(str(values.get("extra_context") or "").strip()),
        "organisation_present": bool(str(values.get("organisation_name") or "").strip()),
        "reviewer_name_present": bool(str(values.get("reviewer_name") or "").strip()),
    }


def _minimal_analysis(analysis):
    values = analysis if isinstance(analysis, dict) else {}
    profile = values.get("profile") if isinstance(values.get("profile"), dict) else {}
    community = values.get("community") if isinstance(values.get("community"), dict) else {}
    geography = community.get("geography_reference")
    geography = geography if isinstance(geography, dict) else {}
    risk_context = values.get("risk_context") if isinstance(values.get("risk_context"), dict) else {}
    evidence = values.get("evidence_confidence")
    minimal_evidence = []
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        minimal_evidence.append(
            {
                key: item.get(key)
                for key in (
                    "code",
                    "evidence_class",
                    "confidence_boundary",
                    "required_review",
                )
                if item.get(key) is not None
            }
        )
    matched_rule_ids = risk_context.get("matched_rule_ids", [])
    matched_rule_ids = matched_rule_ids if isinstance(matched_rule_ids, list) else []
    data_integrity = values.get("data_integrity")
    data_integrity = data_integrity if isinstance(data_integrity, dict) else {}
    knowledge = values.get("knowledge")
    knowledge = knowledge if isinstance(knowledge, dict) else {}
    retrieved_chunks = knowledge.get("retrieved_chunks")
    retrieved_chunks = retrieved_chunks if isinstance(retrieved_chunks, list) else []
    minimal_retrieval = [
        {
            key: item.get(key)
            for key in (
                "source_id",
                "chunk_id",
                "chunk_sha256",
                "page",
                "score",
                "fusion_score",
                "dense_score",
                "lexical_score",
                "dense_rank",
                "lexical_rank",
                "retrieval_mode",
                "rerank_reasons",
            )
            if item.get(key) is not None
        }
        for item in retrieved_chunks
        if isinstance(item, dict)
    ]
    return {
        "profile": {"state": profile.get("state")},
        "community": {
            "matched_location_present": bool(community.get("matched_location")),
            "selected_asgs_area_present": bool(geography.get("selected_asgs_area")),
        },
        "risk_context": {
            "matched_rule_count": len(matched_rule_ids),
            "matched_rule_ids_hash": sha256_json(matched_rule_ids),
        },
        "evidence_confidence": minimal_evidence,
        "data_integrity": {
            "core_ready": data_integrity.get("core_ready"),
            "custom_data": data_integrity.get("custom_data"),
            "optional_map_state": data_integrity.get("optional_map_state"),
        },
        "knowledge": {
            "status": knowledge.get("status"),
            "query_sha256": knowledge.get("query_sha256"),
            "embedding_model": knowledge.get("embedding_model"),
            "retrieval_mode": knowledge.get("retrieval_mode"),
            "dense_weight": knowledge.get("dense_weight"),
            "lexical_weight": knowledge.get("lexical_weight"),
            "index_manifest_sha256": knowledge.get("index_manifest_sha256"),
            "retrieved_chunks": minimal_retrieval,
        },
        "resolved_data_paths": values.get("resolved_data_paths", {}),
        "data_provenance": values.get("data_provenance", {}),
        "analysis_hash": sha256_json(values),
    }


def _minimal_review(review):
    values = review if isinstance(review, dict) else {}
    checklist = values.get("review_checklist")
    checklist_items = checklist if isinstance(checklist, list) else []
    canonical_ids = {item["id"] for item in HUMAN_REVIEW_CHECKLIST}
    minimal_checklist = [
        {
            "id": item.get("id"),
            "checked": item.get("checked") is True,
        }
        for item in checklist_items
        if isinstance(item, dict) and item.get("id") in canonical_ids
    ]
    return {
        "approval_status": values.get("approval_status"),
        "reviewer_role": values.get("reviewer_role"),
        "organisation_name": values.get("organisation_name"),
        "review_date": values.get("review_date"),
        "review_checklist": minimal_checklist,
        "review_checklist_complete": values.get("review_checklist_complete") is True,
        "identity_verification": values.get("identity_verification"),
        "reviewer_name_present": bool(str(values.get("reviewer_name") or "").strip()),
        "review_notes_present": bool(str(values.get("review_notes") or "").strip()),
    }


def review_record_hash(review):
    """Bind the exact review record to the audit without storing its private free text."""

    return sha256_json(canonical_review_record(review))


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slugify(value):
    cleaned = []
    for char in str(value).lower():
        if char.isalnum():
            cleaned.append(char)
        elif cleaned and cleaned[-1] != "_":
            cleaned.append("_")
    return "".join(cleaned).strip("_")[:80] or "unknown"
