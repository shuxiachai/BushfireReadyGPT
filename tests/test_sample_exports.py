import json
import warnings
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts import verify_sample_exports
from scripts.verify_sample_exports import sha256_bytes, verify_sample_package
from src.audit import sha256_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = PROJECT_ROOT / "examples" / "v0.3.0"
SAMPLE_PACKAGE = SAMPLE_DIR / "cairns-council-pilot-package.zip"


def _sample_entries():
    with ZipFile(SAMPLE_PACKAGE) as archive:
        return {item.filename: archive.read(item) for item in archive.infolist()}


def _write_package(tmp_path, entries):
    package_path = tmp_path / "sample.zip"
    with ZipFile(package_path, "w", ZIP_DEFLATED) as archive:
        for path, payload in entries.items():
            archive.writestr(path, payload)
    return package_path


def _replace_manifest(entries, manifest):
    entries["governance/package_manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()


def _parent_binding(record):
    return {
        "report_id": record["report_id"],
        "report_version": record["report_version"],
        "audit_id": record["audit_id"],
        "record_hash": record["record_hash"],
        "report_content_sha256": record["report_content"]["sha256"],
        "governed_body_hash": record["governed_body_hash"],
    }


def _package_with_parent_lineage():
    entries = _sample_entries()
    manifest = json.loads(entries["governance/package_manifest.json"])
    parent_record = json.loads(entries["governance/audit_record.json"])
    parent_binding = _parent_binding(parent_record)
    parent_path = "governance/parent_audit_chain/" + Path(manifest["audit_chain"][0]["path"]).name
    parent_payload = entries["governance/audit_record.json"]
    parent_sha = sha256_bytes(parent_payload)

    child_record = dict(parent_record)
    child_record.update(
        {
            "audit_id": "verifier-child-audit",
            "report_id": "verifier-child-report",
            "report_version": 2,
            "parent_report_id": parent_record["report_id"],
            "parent_audit_binding": parent_binding,
        }
    )
    child_record["record_hash"] = sha256_json(
        {key: value for key, value in child_record.items() if key != "record_hash"}
    )
    child_payload = json.dumps(child_record, ensure_ascii=False, indent=2).encode()
    child_sha = sha256_bytes(child_payload)
    current_path = manifest["audit_chain"][0]["path"]
    entries["governance/audit_record.json"] = child_payload
    entries[current_path] = child_payload
    entries[parent_path] = parent_payload

    manifest["context"]["report_id"] = child_record["report_id"]
    manifest["context"]["report_version"] = child_record["report_version"]
    manifest["captured_audit_head"] = {
        "audit_id": child_record["audit_id"],
        "record_hash": child_record["record_hash"],
    }
    manifest["audit_chain"][0]["sha256"] = child_sha
    manifest["parent_lineage"] = {
        "binding": parent_binding,
        "audit_chain": [{"path": parent_path, "sha256": parent_sha}],
    }
    manifest["included_files"].append(parent_path)
    manifest["artifact_hashes"]["governance/audit_record.json"] = child_sha
    manifest["artifact_hashes"][current_path] = child_sha
    manifest["artifact_hashes"][parent_path] = parent_sha
    _replace_manifest(entries, manifest)
    return entries, manifest


def test_committed_v030_showcase_exports_are_internally_consistent():
    result = verify_sample_package(
        SAMPLE_PACKAGE,
        standalone_dir=SAMPLE_DIR,
        require_current_policy=False,
    )

    assert result["package_schema"] == "pilot-export-v3"
    assert result["included_files"] == 11
    assert result["verified_hashes"] == 10
    assert result["pdf_pages"] >= 1
    assert result["report_id"]
    assert result["current_policy"] is False
    assert result["rag_index_manifest_sha256"] == "aa8e42d3d7837ee3927b21108cedf5f6553332f92ba89e9f70caa2852febedd2"
    assert result["model_provider"] == "ollama"
    assert result["model_name"] == "bushfire-ready-qwen"
    assert result["model_endpoint_boundary"] == "local_loopback"


def test_historical_v030_showcase_is_not_accepted_as_the_current_policy_sample():
    with pytest.raises(ValueError, match="historical"):
        verify_sample_package(
            SAMPLE_PACKAGE,
            standalone_dir=SAMPLE_DIR,
        )


def test_verifier_rejects_testzip_reported_corruption(monkeypatch):
    monkeypatch.setattr(verify_sample_exports.ZipFile, "testzip", lambda _archive: "reports/corrupt.pdf")

    with pytest.raises(ValueError, match="corrupt ZIP entry"):
        verify_sample_package(SAMPLE_PACKAGE, require_current_policy=False)


def test_verifier_rejects_duplicate_and_unsafe_zip_paths(tmp_path):
    entries = _sample_entries()
    duplicate_path = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with ZipFile(duplicate_path, "w", ZIP_DEFLATED) as archive:
            for path, payload in entries.items():
                archive.writestr(path, payload)
            first_path = next(iter(entries))
            archive.writestr(first_path, entries[first_path])

    with pytest.raises(ValueError, match="duplicate ZIP entries"):
        verify_sample_package(duplicate_path, require_current_policy=False)

    entries["../outside.txt"] = b"unsafe"
    unsafe_path = _write_package(tmp_path, entries)
    with pytest.raises(ValueError, match="unsafe ZIP path"):
        verify_sample_package(unsafe_path, require_current_policy=False)


def test_verifier_requires_hash_coverage_for_every_non_manifest_entry(tmp_path):
    entries = _sample_entries()
    manifest = json.loads(entries["governance/package_manifest.json"])
    manifest["artifact_hashes"].pop(next(path for path in manifest["artifact_hashes"] if path.endswith(".pdf")))
    _replace_manifest(entries, manifest)

    with pytest.raises(ValueError, match="does not cover every"):
        verify_sample_package(_write_package(tmp_path, entries), require_current_policy=False)


def test_verifier_rejects_an_audit_chain_that_does_not_begin_at_its_root(tmp_path):
    entries = _sample_entries()
    manifest = json.loads(entries["governance/package_manifest.json"])
    audit_record = json.loads(entries["governance/audit_record.json"])
    audit_record.update(
        {
            "previous_audit_id": "missing-parent",
            "previous_record_hash": "a" * 64,
            "previous_audit_file": "missing-parent.json",
        }
    )
    audit_record["record_hash"] = sha256_json(
        {key: value for key, value in audit_record.items() if key != "record_hash"}
    )
    audit_payload = json.dumps(audit_record, ensure_ascii=False, indent=2).encode()
    audit_chain_path = manifest["audit_chain"][0]["path"]
    entries["governance/audit_record.json"] = audit_payload
    entries[audit_chain_path] = audit_payload
    audit_sha = sha256_bytes(audit_payload)
    manifest["captured_audit_head"]["record_hash"] = audit_record["record_hash"]
    manifest["audit_chain"][0]["sha256"] = audit_sha
    manifest["artifact_hashes"]["governance/audit_record.json"] = audit_sha
    manifest["artifact_hashes"][audit_chain_path] = audit_sha
    _replace_manifest(entries, manifest)

    with pytest.raises(ValueError, match="does not begin at its root"):
        verify_sample_package(_write_package(tmp_path, entries), require_current_policy=False)


def test_verifier_accepts_bound_parent_lineage_and_rejects_a_binding_mismatch(tmp_path):
    entries, manifest = _package_with_parent_lineage()
    package_path = _write_package(tmp_path, entries)

    result = verify_sample_package(package_path, require_current_policy=False)
    assert result["report_id"] == "verifier-child-report"

    manifest["parent_lineage"]["binding"]["record_hash"] = "b" * 64
    _replace_manifest(entries, manifest)
    with pytest.raises(ValueError, match="immediate parent lineage"):
        verify_sample_package(_write_package(tmp_path, entries), require_current_policy=False)


@pytest.mark.parametrize(
    ("target", "expected_format"),
    (("_verify_pdf", "PDF"), ("_verify_docx", "DOCX")),
)
def test_verifier_scans_rendered_exports_for_internal_prompt_markers(monkeypatch, target, expected_format):
    entries = _sample_entries()
    markdown_path = next(path for path in entries if path.startswith("reports/") and path.endswith(".md"))
    leaked_text = entries[markdown_path].decode() + "\n<retrieved-official-evidence>"
    monkeypatch.setattr(verify_sample_exports, target, lambda _payload: (1, leaked_text))

    with pytest.raises(ValueError, match=expected_format):
        verify_sample_package(SAMPLE_PACKAGE, require_current_policy=False)


def test_verifier_scans_governance_text_for_internal_prompt_markers(tmp_path):
    entries = _sample_entries()
    manifest = json.loads(entries["governance/package_manifest.json"])
    path = "governance/internal-notes.md"
    payload = b"Original governed report request: private prompt"
    entries[path] = payload
    manifest["included_files"].append(path)
    manifest["artifact_hashes"][path] = sha256_bytes(payload)
    _replace_manifest(entries, manifest)

    with pytest.raises(ValueError, match="governance/internal-notes.md"):
        verify_sample_package(_write_package(tmp_path, entries), require_current_policy=False)
