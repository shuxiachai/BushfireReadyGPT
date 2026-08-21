import hashlib
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from src.agents.report_quality_agent import ReportQualityAgent
from src.audit import (
    AuditIntegrityError,
    canonical_package_context,
    canonical_review_record,
    capture_current_audit_chain,
    capture_parent_lineage,
    immutable_package_context_hash,
    package_context_hash,
    review_record_hash,
    sha256_json,
)
from src.docx_export import create_report_docx
from src.export_register import (
    REGISTER_SNAPSHOT_FILES,
    ExportRegisterSnapshotError,
    canonical_export_register_snapshot,
    export_register_snapshot_hashes,
)
from src.governance import (
    APPROVED_STATUS,
    REVIEWED_STATUSES,
    is_review_checklist_complete,
)
from src.pdf_export import create_report_pdf
from src.report_template import append_human_signoff


def create_pilot_export_package(
    report_text,
    audit_path=None,
    review_record=None,
    package_context=None,
    parent_audit_path=None,
    register_snapshot=None,
):
    """Create a zip package for pilot review and stakeholder handover."""

    if not audit_path:
        raise AuditIntegrityError("A pilot governance package requires a verified current audit event.")
    review_record = canonical_review_record(review_record, default_status="Draft - human review required")
    if not str(report_text or ""):
        raise AuditIntegrityError("A pilot governance package cannot contain an empty report.")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    context = canonical_package_context(package_context or {})
    report_markdown = str(report_text)
    file_prefix = _file_prefix(context, timestamp)
    audit_file = Path(audit_path)
    audit_chain = capture_current_audit_chain(audit_file)
    latest_audit = audit_chain[-1]["record"]
    parent_lineage = _verified_parent_lineage(latest_audit, parent_audit_path)
    parent_audit_chain = parent_lineage[0]["chain"] if parent_lineage else []
    try:
        register_snapshot = canonical_export_register_snapshot(register_snapshot)
    except ExportRegisterSnapshotError as error:
        raise AuditIntegrityError(
            "The export is missing its complete frozen data/licence register snapshot."
        ) from error
    register_hashes = export_register_snapshot_hashes(register_snapshot)
    if latest_audit.get("export_register_hashes") != register_hashes:
        raise AuditIntegrityError("The export data/licence registers do not match the verified report snapshot.")
    audited_report_hash = latest_audit.get("report_content", {}).get("sha256")
    if audited_report_hash != hashlib.sha256(report_markdown.encode("utf-8")).hexdigest():
        raise AuditIntegrityError("The report text does not match the latest verified audit event; export was blocked.")
    if latest_audit.get("review_record_hash") != review_record_hash(review_record):
        raise AuditIntegrityError(
            "The reviewer record does not match the latest verified audit event; export was blocked."
        )
    if append_human_signoff(report_markdown, review_record) != report_markdown:
        raise AuditIntegrityError(
            "The report does not end with the deterministic Human Review Sign-off bound to its review record."
        )
    _validate_audit_context(latest_audit, context)
    exact_quality = ReportQualityAgent().run(report_markdown)
    if latest_audit.get("quality") != exact_quality:
        raise AuditIntegrityError(
            "The audit quality result does not match a fresh check of the report; export was blocked."
        )
    _validate_review_for_export(review_record, latest_audit, exact_quality, context)

    markdown_path = f"reports/{file_prefix}.md"
    pdf_path = f"reports/{file_prefix}.pdf"
    docx_path = f"reports/{file_prefix}.docx"
    markdown_bytes = report_markdown.encode("utf-8")
    pdf_bytes = create_report_pdf(report_markdown)
    docx_bytes = create_report_docx(report_markdown)
    reviewer_bytes = json.dumps(review_record, ensure_ascii=False, indent=2).encode("utf-8")

    artifact_bytes = {
        markdown_path: markdown_bytes,
        pdf_path: pdf_bytes,
        docx_path: docx_bytes,
        "governance/reviewer_signoff.json": reviewer_bytes,
        **{path: register_snapshot[path].encode("utf-8") for path in REGISTER_SNAPSHOT_FILES},
    }

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "app_name": "BushfireReadyGPT",
        "package_schema": "pilot-export-v3",
        "purpose": "Pilot review package for a draft Australian bushfire preparedness report.",
        "safety_boundary": (
            "Preparedness planning support only. Not live emergency advice, not an evacuation order, "
            "and not endorsed by any agency unless separately approved by the responsible organisation."
        ),
        "privacy": {
            "classification": "sensitive-governance-export",
            "notice": (
                "This package contains the full report and may contain reviewer identity, review notes, "
                "location and other user-provided context. Store and share it only with authorised recipients."
            ),
        },
        "context": context,
        "review_record": review_record,
        "captured_audit_head": {
            "audit_id": latest_audit.get("audit_id"),
            "record_hash": latest_audit.get("record_hash"),
        },
        "frozen_register_hashes": register_hashes,
        "included_files": [
            markdown_path,
            pdf_path,
            docx_path,
            "governance/reviewer_signoff.json",
            "governance/data_register.csv",
            "governance/data_register.md",
            "governance/licence_register.csv",
            "governance/licence_register.md",
            "governance/package_manifest.json",
        ],
        "artifact_hashes": {},
    }
    manifest["included_files"].append("governance/audit_record.json")
    artifact_bytes["governance/audit_record.json"] = audit_chain[-1]["bytes"]
    manifest["audit_chain"] = [
        {
            "path": f"governance/audit_chain/{item['path'].name}",
            "sha256": _sha256_bytes(item["bytes"]),
        }
        for item in audit_chain
    ]
    manifest["included_files"].extend(item["path"] for item in manifest["audit_chain"])
    artifact_bytes.update({f"governance/audit_chain/{item['path'].name}": item["bytes"] for item in audit_chain})
    if parent_audit_chain:
        manifest["parent_lineage"] = {
            "binding": parent_lineage[0]["binding"],
            "audit_chain": [
                {
                    "path": f"governance/parent_audit_chain/{item['path'].name}",
                    "sha256": _sha256_bytes(item["bytes"]),
                }
                for item in parent_audit_chain
            ],
        }
        parent_paths = [item["path"] for item in manifest["parent_lineage"]["audit_chain"]]
        manifest["included_files"].extend(parent_paths)
        artifact_bytes.update(
            {f"governance/parent_audit_chain/{item['path'].name}": item["bytes"] for item in parent_audit_chain}
        )
        ancestor_levels = []
        for depth, level in enumerate(parent_lineage[1:], start=2):
            base = f"governance/ancestor_audit_chains/depth_{depth}"
            entries = [
                {
                    "path": f"{base}/{item['path'].name}",
                    "sha256": _sha256_bytes(item["bytes"]),
                }
                for item in level["chain"]
            ]
            ancestor_levels.append(
                {
                    "depth": depth,
                    "binding": level["binding"],
                    "audit_chain": entries,
                }
            )
            manifest["included_files"].extend(item["path"] for item in entries)
            artifact_bytes.update({f"{base}/{item['path'].name}": item["bytes"] for item in level["chain"]})
        if ancestor_levels:
            manifest["parent_lineage"]["ancestors"] = ancestor_levels
    manifest["artifact_hashes"] = {path: _sha256_bytes(payload) for path, payload in artifact_bytes.items()}

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as package:
        package.writestr(markdown_path, markdown_bytes)
        package.writestr(pdf_path, pdf_bytes)
        package.writestr(docx_path, docx_bytes)
        for path, payload in artifact_bytes.items():
            if path not in {markdown_path, pdf_path, docx_path}:
                package.writestr(path, payload)
        package.writestr("governance/package_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    buffer.seek(0)
    return {
        "filename": f"{file_prefix}_pilot_export_package.zip",
        "content": buffer.getvalue(),
        "manifest": manifest,
    }


def _sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _verified_parent_lineage(latest_audit, parent_audit_path):
    try:
        return capture_parent_lineage(latest_audit, parent_audit_path)
    except AuditIntegrityError as error:
        if latest_audit.get("parent_audit_binding") and not parent_audit_path:
            raise AuditIntegrityError("The revision export is missing its bound parent audit chain.") from error
        raise


def _validate_audit_context(latest_audit, context):
    if latest_audit.get("package_context_hash") != package_context_hash(context):
        raise AuditIntegrityError("The export context does not match the verified report snapshot.")
    if latest_audit.get("immutable_package_context_hash") != immutable_package_context_hash(context):
        raise AuditIntegrityError("The export context changed immutable report snapshot fields.")
    if latest_audit.get("organisation_context_hash") != sha256_json(context.get("organisation_name")):
        raise AuditIntegrityError("The export organisation does not match the reviewed snapshot.")
    context_report_id = context.get("report_id")
    if context_report_id is not None and str(context_report_id) != str(latest_audit.get("report_id")):
        raise AuditIntegrityError("The export context report ID does not match the verified audit event.")
    context_version = context.get("report_version")
    if context_version is not None and context_version != latest_audit.get("report_version"):
        raise AuditIntegrityError("The export context report version does not match the verified audit event.")


def _validate_review_for_export(review_record, latest_audit, exact_quality, context):
    status = review_record.get("approval_status")
    context_status = latest_audit.get("report_status")
    if status != context_status or status != context.get("report_status"):
        raise AuditIntegrityError("The export review status does not match the latest audit event.")
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
            raise AuditIntegrityError("The reviewed export is missing required identity fields: " + ", ".join(missing))
    if status != APPROVED_STATUS:
        return
    if not is_review_checklist_complete(review_record.get("review_checklist")):
        raise AuditIntegrityError("The approved export does not contain a complete canonical review checklist.")
    if exact_quality.get("approval_gate", {}).get("passed") is not True:
        raise AuditIntegrityError("The approved export failed the structural quality gate.")
    integrity = (latest_audit.get("analysis") or {}).get("data_integrity") or {}
    if integrity.get("core_ready") is not True or integrity.get("custom_data") is not False:
        raise AuditIntegrityError("The approved export is not bound to manifest-verified bundled core data.")
    if (
        latest_audit.get("area_selection_hash") != sha256_json(None)
        and integrity.get("optional_map_state") != "bundle_verified"
    ):
        raise AuditIntegrityError("The approved export is not bound to a sidecar-verified national-map bundle.")


def _file_prefix(context, timestamp):
    location = context.get("location") or "bushfire_ready"
    slug = []
    for char in str(location).lower():
        if char.isalnum():
            slug.append(char)
        elif slug and slug[-1] != "_":
            slug.append("_")
    return f"{''.join(slug).strip('_')[:48] or 'bushfire_ready'}_{timestamp}"
