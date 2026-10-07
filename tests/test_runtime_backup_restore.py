"""One synthetic, stopped-writer restore drill; never opens a real runtime tree.

This is a local recovery test, not a backup service or evidence that a Railway
volume snapshot exists. All source, capture and candidate directories are new
pytest siblings. No provider, network, credentials or real report is involved.
"""

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from scripts.check_runtime_maintenance import maintenance_snapshot
from src import audit
from src.export_register import build_export_register_snapshot
from src.governance import DRAFT_STATUS, NEEDS_REVISION_STATUS
from src.report_template import append_human_signoff
from src.runtime_trace import RuntimeTrace, load_trace_summary

DAY = "2026-10-07"
QUOTA_ROWS = [("2026-10-05", 4), ("2026-10-06", 9), (DAY, 7)]


def _tree(directory):
    return {
        path.relative_to(directory).as_posix(): (
            path.stat().st_mode,
            path.stat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None,
        )
        for path in directory.rglob("*")
    }


def _quota_rows(database):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        return connection.execute("SELECT day, calls FROM daily_calls ORDER BY day").fetchall()


def _logical_quota_hash(rows):
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


@pytest.fixture
def captured_runtime(tmp_path, monkeypatch):
    source, captured = tmp_path / "synthetic-source", tmp_path / "captured"
    source.mkdir()
    captured.mkdir()
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", str(source))
    monkeypatch.setenv("BUSHFIRE_AUDIT_DIR", str(source / "audit"))
    monkeypatch.setenv("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", "false")
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(source / "traces"))
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")
    review = {"approval_status": DRAFT_STATUS}
    payload = {
        "report_id": "synthetic-maintenance-root",
        "report_version": 1,
        "inputs": {"location": "Synthetic place"},
        "analysis": {"profile": {"state": "Queensland"}},
        "area_selection": None,
        "human_review": review,
        "report_text": append_human_signoff("# Synthetic report", review),
        "export_register_snapshot": build_export_register_snapshot(),
    }
    root_event = Path(audit.save_report_audit(payload))
    updated_review = {"approval_status": NEEDS_REVISION_STATUS, "review_notes": "Synthetic revision request"}
    parent_tip = Path(
        audit.append_audit_event(
            root_event,
            "review.recorded",
            {
                **payload,
                "human_review": updated_review,
                "report_status": NEEDS_REVISION_STATUS,
                "report_text": append_human_signoff("# Synthetic report", updated_review),
                "package_context": {
                    "location": "Synthetic place",
                    "report_id": payload["report_id"],
                    "report_version": 1,
                    "report_status": NEEDS_REVISION_STATUS,
                },
            },
        )
    )
    child_event = Path(
        audit.save_revision_audit(
            parent_tip,
            {
                **payload,
                "report_id": "synthetic-maintenance-revision",
                "report_version": 2,
                "report_text": append_human_signoff("# Synthetic revised report", review),
                "revision_request": "Synthetic wording revision",
            },
        )
    )
    with RuntimeTrace("report.revise", report_source="generated", model_boundary="local_loopback") as trace:
        with trace.stage("audit_write", report_version=2):
            pass
        trace.add_metrics(audit_written=True, generation_attempts=0)
        trace.set_outcome("success")
    with closing(sqlite3.connect(source / "model-usage.sqlite3")) as connection, connection:
        connection.execute("CREATE TABLE daily_calls (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
        connection.executemany("INSERT INTO daily_calls VALUES (?, ?)", QUOTA_ROWS)

    # Explicit capture boundary: every synthetic writer/connection has stopped.
    # Capture all durable audit/trace files, including hidden heads and revision
    # claims. Kernel guard inodes and process-owned lock records are not state
    # that can be restored to another process. Never delete them from source.
    source_before = _tree(source)
    database = source / "model-usage.sqlite3"
    copied_hashes = {}
    for path in source.rglob("*"):
        if not path.is_file() or path == database:
            continue
        if path.name.startswith(".lock_") and path.name.endswith((".lock", ".lock.guard")):
            continue
        relative = path.relative_to(source)
        target = captured / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied_hashes[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    # Use SQLite's consistent backup API; never copy a potentially live main
    # database file or discard WAL data as a production backup shortcut.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source_connection:
        source_connection.execute("PRAGMA query_only=ON")
        with closing(sqlite3.connect(captured / database.name)) as destination_connection:
            source_connection.backup(destination_connection)
    rows = _quota_rows(database)
    assert rows == QUOTA_ROWS
    assert _tree(source) == source_before
    return {
        "source": source,
        "source_before": source_before,
        "captured": captured,
        "root_event": root_event.name,
        "parent_tip": parent_tip.name,
        "child_event": child_event.name,
        "copied_hashes": copied_hashes,
        "quota_rows": rows,
        "quota_hash": _logical_quota_hash(rows),
    }


def _verify_candidate(candidate, expected):
    """Strict read-only checks for this known synthetic lineage, without recovery."""
    env = {
        "BUSHFIRE_DEPLOYMENT_MODE": "cloud",
        "BUSHFIRE_RUNTIME_DIR": str(candidate),
        "BUSHFIRE_MODEL_MAX_CONCURRENT": "1",
        "BUSHFIRE_MODEL_DAILY_CALL_LIMIT": "100",
    }
    result, code = maintenance_snapshot(day=DAY, persistent_root=candidate, minimum_calls=7, environ=env)
    assert code == 0, "Quota is unavailable, outside the candidate or below its retained high-water mark."
    rows = _quota_rows(candidate / "model-usage.sqlite3")
    assert rows == expected["quota_rows"]
    assert _logical_quota_hash(rows) == expected["quota_hash"]
    directory = candidate / "audit"
    root_path = directory / expected["root_event"]
    parent_path = directory / expected["parent_tip"]
    child_path = directory / expected["child_event"]
    root = audit.load_and_verify_audit(root_path)
    parent = audit.load_and_verify_audit(parent_path)
    child = audit.load_and_verify_audit(child_path)
    # get_audit_chain_paths validates the existing head; unlike
    # capture_current_audit_chain it does not lock, recover or repair that head.
    assert audit.get_audit_chain_paths(parent_path) == [root_path, parent_path]
    assert audit.get_audit_chain_paths(child_path) == [child_path]
    parent_binding = {
        "report_id": parent["report_id"],
        "report_version": parent["report_version"],
        "audit_id": parent["audit_id"],
        "record_hash": parent["record_hash"],
        "report_content_sha256": parent["report_content"]["sha256"],
        "governed_body_hash": parent["governed_body_hash"],
    }
    assert root["parent_audit_binding"] is None and parent["parent_audit_binding"] is None
    assert child["parent_report_id"] == parent["report_id"]
    assert child["parent_audit_binding"] == parent_binding
    assert child["report_version"] == parent["report_version"] + 1
    claim = json.loads(audit._revision_claim_path(directory, parent).read_text(encoding="utf-8"))
    assert claim["state"] == "committed" and claim["parent"] == parent_binding
    assert claim["child"] == {
        "report_id": child["report_id"],
        "report_version": child["report_version"],
        "audit_id": child["audit_id"],
        "record_hash": child["record_hash"],
        "audit_file": child_path.name,
    }
    # File hashes retain all captured ancestors, metadata and trace bytes;
    # quota comparison is logical because SQLite backup can change layout.
    observed = {
        path.relative_to(candidate).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in candidate.rglob("*")
        if path.is_file() and path.name != "model-usage.sqlite3"
    }
    assert observed == expected["copied_hashes"]
    traces = load_trace_summary(trace_dir=candidate / "traces")
    assert traces["traces"] == 1 and traces["invalid_files"] == 0 and traces["success_rate"] == 1.0


def test_synthetic_stopped_writer_backup_restores_complete_lineage_and_quota(captured_runtime, tmp_path, monkeypatch):
    captured = captured_runtime
    candidate = tmp_path / "fresh-candidate"
    assert not candidate.exists()
    shutil.copytree(captured["captured"], candidate)
    assert list((candidate / "audit").glob(".head_*.json"))
    assert list((candidate / "audit").glob(".revision_*.json"))
    assert not list(candidate.rglob("*.lock*"))
    before = _tree(candidate)
    monkeypatch.setattr(
        audit, "_recover_unique_report_head", lambda *args: pytest.fail("Read-only proof must not recover")
    )
    monkeypatch.setattr(audit, "_report_lock", lambda *args: pytest.fail("Read-only proof must not create guard files"))
    _verify_candidate(candidate, captured)
    assert _tree(candidate) == before
    assert _tree(captured["source"]) == captured["source_before"]


@pytest.mark.parametrize(
    "damage",
    [
        "missing_head",
        "tampered_head",
        "missing_ancestor",
        "tampered_ancestor",
        "missing_revision_claim",
        "tampered_lineage",
        "lower_quota",
        "historical_quota_loss",
        "unavailable_quota",
        "missing_trace",
    ],
)
def test_incomplete_candidate_is_rejected_without_repair(captured_runtime, tmp_path, damage):
    captured = captured_runtime
    candidate = tmp_path / "damaged-candidate"
    shutil.copytree(captured["captured"], candidate)
    directory = candidate / "audit"
    if damage == "missing_head":
        audit._head_path(directory, "synthetic-maintenance-root").unlink()
    elif damage == "tampered_head":
        audit._head_path(directory, "synthetic-maintenance-revision").write_text("{}", encoding="utf-8")
    elif damage == "missing_ancestor":
        (directory / captured["root_event"]).unlink()
    elif damage == "tampered_ancestor":
        (directory / captured["root_event"]).write_text("{}", encoding="utf-8")
    elif damage == "missing_revision_claim":
        next(directory.glob(".revision_*.json")).unlink()
    elif damage == "tampered_lineage":
        path = directory / captured["child_event"]
        record = json.loads(path.read_text(encoding="utf-8"))
        record["parent_audit_binding"]["record_hash"] = "0" * 64
        record.pop("record_hash")
        record["record_hash"] = audit.sha256_json(record)
        path.write_text(json.dumps(record), encoding="utf-8")
        # Keep the forged head coherent so the cross-report binding must fail.
        head_path = audit._head_path(directory, record["report_id"])
        head = json.loads(head_path.read_text(encoding="utf-8"))
        head["record_hash"] = record["record_hash"]
        head_path.write_text(json.dumps(head), encoding="utf-8")
    elif damage == "lower_quota":
        with closing(sqlite3.connect(candidate / "model-usage.sqlite3")) as connection, connection:
            connection.execute("UPDATE daily_calls SET calls=6 WHERE day=?", (DAY,))
    elif damage == "historical_quota_loss":
        with closing(sqlite3.connect(candidate / "model-usage.sqlite3")) as connection, connection:
            connection.execute("DELETE FROM daily_calls WHERE day=?", ("2026-10-06",))
    elif damage == "unavailable_quota":
        (candidate / "model-usage.sqlite3").unlink()
    else:
        next((candidate / "traces").glob("trace_*.json")).unlink()
    before = _tree(candidate)
    with pytest.raises((AssertionError, audit.AuditIntegrityError, OSError)):
        _verify_candidate(candidate, captured)
    assert _tree(candidate) == before
    assert _tree(captured["source"]) == captured["source_before"]
