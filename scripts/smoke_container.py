"""Offline image smoke checks; use only on a disposable CI/demo-test volume."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
from contextlib import closing
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pypdf import PdfReader  # noqa: E402

from src import audit  # noqa: E402
from src.container_runtime import prepare_runtime  # noqa: E402
from src.corpus_bundle import validate_corpus_bundle  # noqa: E402
from src.data_artifacts import atomic_write_json  # noqa: E402
from src.governance import DRAFT_STATUS, NEEDS_REVISION_STATUS  # noqa: E402
from src.model_limits import acquire_model_slot, load_model_limits  # noqa: E402
from src.pdf_export import create_report_pdf  # noqa: E402
from src.report_template import append_human_signoff  # noqa: E402
from src.runtime_paths import runtime_path  # noqa: E402
from src.runtime_trace import MAX_TRACE_FILE_BYTES, RuntimeTrace, load_trace_summary  # noqa: E402

SMOKE_SCHEMA = "bushfire-container-persistence-smoke-v1"
SMOKE_REPORT_ID = "container-smoke-persistence"
MAX_EXPECTATIONS_BYTES = 16 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[0-9a-f]{32}\Z")


def _read_bytes(path, limit):
    """Bound fixed probe files and reject links, including linked parent directories."""
    path = Path(path)
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise RuntimeError("Smoke evidence paths cannot contain links or junctions.")
    if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > limit:
        raise RuntimeError("Smoke evidence is missing, non-regular or oversized.")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise RuntimeError("Smoke evidence exceeds its read limit.")
    return payload


def _verify_worker():
    if getattr(os, "getuid", lambda: 0)() != 10001:
        raise RuntimeError("The application smoke checks must run as the non-root worker.")
    process_status = _read_bytes(Path("/proc/1/status"), 16 * 1024).decode("utf-8")
    process_ids = {
        line.split(":", 1)[0]: line.split(":", 1)[1].split()
        for line in process_status.splitlines()
        if line.startswith(("Uid:", "Gid:"))
    }
    if process_ids != {"Uid": ["10001"] * 4, "Gid": ["10001"] * 4}:
        raise RuntimeError("The actual web process did not drop its root UID and GID.")


def _pid1_identity():
    # PID 1 is reused by Docker; Linux boot ID + start-time ticks distinguish
    # an actual restarted web process from merely rerunning this exec script.
    boot = _read_bytes(Path("/proc/sys/kernel/random/boot_id"), 128).decode("ascii").strip()
    process = _read_bytes(Path("/proc/1/stat"), 16 * 1024).decode("utf-8")
    fields = process.rpartition(")")[2].split()
    if not re.fullmatch(r"[0-9a-f-]{36}", boot) or len(fields) < 20 or not fields[19].isdigit():
        raise RuntimeError("The web process restart identity could not be verified.")
    return hashlib.sha256(f"{boot}:{fields[19]}".encode("ascii")).hexdigest()


def _require_disposable_fixture():
    if os.environ.get("BUSHFIRE_CONTAINER_SMOKE") != "true":
        raise RuntimeError("Smoke checks require BUSHFIRE_CONTAINER_SMOKE=true and a disposable volume.")
    if any(os.environ.get(name) for name in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID")):
        raise RuntimeError("These write-producing smoke checks must not run on a Railway service.")
    forbidden = (
        "BUSHFIRE_AUDIT_DIR",
        "BUSHFIRE_TRACE_DIR",
        "BUSHFIRE_SESSION_STATE_PATH",
        "BUSHFIRE_INTERACTION_LOG_PATH",
    )
    if any(os.environ.get(name, "").strip() for name in forbidden):
        raise RuntimeError("Smoke evidence must use only the disposable runtime volume without path overrides.")
    if os.environ.get("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", "").lower() not in {"", "false", "0", "no"}:
        raise RuntimeError("Smoke audit evidence requires sensitive-content storage to be disabled.")
    if os.environ.get("BUSHFIRE_TRACE_ENABLED", "true").lower() in {"false", "0", "no"}:
        raise RuntimeError("Smoke persistence checks require runtime Trace recording.")
    configured = os.environ.get("BUSHFIRE_RUNTIME_DIR", "")
    identity = os.environ.get("BUSHFIRE_RAG_CORPUS_SHA256", "")
    if not Path(configured).is_absolute() or not _SHA256.fullmatch(identity):
        raise RuntimeError("Smoke checks require an explicit runtime volume and private test-corpus identity.")
    bundle = validate_corpus_bundle(Path(configured) / "private-rag" / identity, allow_index=True)
    if bundle["manifest_sha256"] != identity or bundle["fixture_only"] is not True:
        raise RuntimeError("Smoke writes require a verified synthetic test-only corpus, never production sources.")
    if not load_model_limits().cloud:
        raise RuntimeError("The container smoke must exercise cloud quota configuration.")


def _require_fresh_evidence_volume():
    allowed = {"private-rag"}
    if any(path.name not in allowed for path in runtime_path().iterdir()):
        raise RuntimeError("The smoke volume is not fresh; existing evidence is never replaced.")


def _file_evidence(path, limit):
    return {"file": Path(path).name, "sha256": hashlib.sha256(_read_bytes(path, limit)).hexdigest()}


def _create_persistence_evidence():
    inputs = {"location": "Synthetic container test"}
    body = "# Synthetic persistence fixture\n\nNo operational use."
    draft = {"approval_status": DRAFT_STATUS}
    review = {"approval_status": NEEDS_REVISION_STATUS, "review_notes": "Synthetic persistence check."}
    with RuntimeTrace("report.generate", generation_attempts=0, report_version=1) as trace:
        with trace.stage("audit_write"):
            first = audit.save_report_audit(
                {
                    "report_id": SMOKE_REPORT_ID,
                    "report_version": 1,
                    "inputs": inputs,
                    "analysis": {},
                    "report_text": append_human_signoff(body, draft),
                    "human_review": draft,
                }
            )
            latest = audit.append_audit_event(
                first,
                "review.recorded",
                {
                    "report_id": SMOKE_REPORT_ID,
                    "report_version": 1,
                    "analysis": {},
                    "report_text": append_human_signoff(body, review),
                    "report_status": NEEDS_REVISION_STATUS,
                    "human_review": review,
                    "package_context": {
                        **inputs,
                        "report_id": SMOKE_REPORT_ID,
                        "report_version": 1,
                        "report_status": NEEDS_REVISION_STATUS,
                    },
                },
            )
            trace.add_metrics(audit_written=True)
    if trace.write_error or not trace.path:
        raise RuntimeError("The synthetic Trace could not be persisted.")
    events = []
    for path in audit.get_audit_chain_paths(latest):
        record = audit.load_and_verify_audit(path)
        events.append(
            {
                **_file_evidence(path, audit.MAX_AUDIT_FILE_BYTES),
                "audit_id": record["audit_id"],
                "record_hash": record["record_hash"],
            }
        )
    return {
        "audit": events,
        "trace": {**_file_evidence(trace.path, MAX_TRACE_FILE_BYTES), "trace_id": trace.trace_id},
    }


def _valid_file_evidence(value, *, trace=False):
    id_key = "trace_id" if trace else "audit_id"
    keys = {"file", "sha256", id_key} | (set() if trace else {"record_hash"})
    pattern = r"trace_[0-9a-f]{32}\.json" if trace else r"audit_[A-Za-z0-9_-]+\.json"
    return (
        isinstance(value, dict)
        and set(value) == keys
        and all(isinstance(item, str) for item in value.values())
        and re.fullmatch(pattern, value["file"]) is not None
        and _SHA256.fullmatch(value["sha256"]) is not None
        and _IDENTIFIER.fullmatch(value[id_key]) is not None
        and (trace or _SHA256.fullmatch(value["record_hash"]) is not None)
        and (not trace or value["file"] == f"trace_{value['trace_id']}.json")
    )


def _load_expectations(path):
    try:
        expected = json.loads(_read_bytes(path, MAX_EXPECTATIONS_BYTES).decode("utf-8"))
        if not isinstance(expected, dict) or set(expected) != {
            "schema",
            "index",
            "process_sha256",
            "audit",
            "trace",
            "quota",
        }:
            raise ValueError("shape")
        index = expected["index"]
        quota = expected["quota"]
        valid = (
            expected["schema"] == SMOKE_SCHEMA
            and isinstance(index, dict)
            and set(index) == {"manifest_sha256", "corpus_manifest_sha256", "mtime_ns"}
            and all(
                isinstance(index[key], str) and _SHA256.fullmatch(index[key])
                for key in ("manifest_sha256", "corpus_manifest_sha256")
            )
            and type(index["mtime_ns"]) is int
            and index["mtime_ns"] >= 0
            and isinstance(expected["process_sha256"], str)
            and _SHA256.fullmatch(expected["process_sha256"])
            and isinstance(expected["audit"], list)
            and len(expected["audit"]) == 2
            and all(_valid_file_evidence(event) for event in expected["audit"])
            and len({event["file"] for event in expected["audit"]}) == 2
            and _valid_file_evidence(expected["trace"], trace=True)
            and isinstance(quota, dict)
            and set(quota) == {"day", "calls"}
            and isinstance(quota["day"], str)
            and date.fromisoformat(quota["day"]).isoformat() == quota["day"]
            and type(quota["calls"]) is int
            and quota["calls"] == 1
        )
        if not valid:
            raise ValueError("fields")
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError) as error:
        raise RuntimeError("The smoke expectations are missing, malformed or outside their safety limits.") from error
    return expected


def _verify_persistence_evidence(expected):
    paths = []
    for event in expected["audit"]:
        path = runtime_path("audit") / event["file"]
        if _file_evidence(path, audit.MAX_AUDIT_FILE_BYTES) != {key: event[key] for key in ("file", "sha256")}:
            raise RuntimeError("A persisted audit event changed after the first smoke phase.")
        record = audit.load_and_verify_audit(path)
        if (
            record["audit_id"] != event["audit_id"]
            or record["record_hash"] != event["record_hash"]
            or record["report_id"] != SMOKE_REPORT_ID
        ):
            raise RuntimeError("The persisted audit event identity changed.")
        paths.append(path)
    if audit.get_audit_chain_paths(paths[-1]) != paths:
        raise RuntimeError("The persisted audit chain or authoritative head changed.")
    trace = expected["trace"]
    if _file_evidence(runtime_path("traces") / trace["file"], MAX_TRACE_FILE_BYTES) != {
        key: trace[key] for key in ("file", "sha256")
    }:
        raise RuntimeError("The persisted Trace bytes changed.")
    summary = load_trace_summary(trace_dir=runtime_path("traces"))
    if (
        summary["traces"] != 1
        or summary["invalid_files"]
        or summary["scan_truncated"]
        or summary["scan_errors"]
        or summary["recent"][0]["trace_id"] != trace["trace_id"]
        or summary["recent"][0]["status"] != "success"
    ):
        raise RuntimeError("The persisted synthetic Trace failed real schema/summary validation.")


def _read_quota(day):
    # mode=ro prevents a missing database being recreated by the verifier.
    database = load_model_limits().database
    _read_bytes(database, 1024 * 1024)
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            row = connection.execute("SELECT calls FROM daily_calls WHERE day = ?", (day,)).fetchone()
    except sqlite3.Error as error:
        raise RuntimeError("The persistent smoke quota cannot be read.") from error
    return row[0] if row and type(row[0]) is int else None


def _consume_fixture_call():
    day = datetime.now(timezone.utc).date().isoformat()
    slot = acquire_model_slot()
    try:
        slot.consume_call()
    finally:
        slot.release()
    if datetime.now(timezone.utc).date().isoformat() != day:
        raise RuntimeError("The quota probe crossed UTC midnight; repeat it on a fresh disposable volume.")
    return day


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("first", "restart"), required=True)
    args = parser.parse_args()
    _require_disposable_fixture()
    _verify_worker()
    process_identity = _pid1_identity()
    sentinel = runtime_path("container-smoke.json")
    if args.phase == "first":
        _require_fresh_evidence_volume()
        expected = None
    else:
        expected = _load_expectations(sentinel)
        if expected["process_sha256"] == process_identity:
            raise RuntimeError("Restart verification requires a different actual PID 1 process.")
        _verify_persistence_evidence(expected)
        if _read_quota(expected["quota"]["day"]) != expected["quota"]["calls"]:
            raise RuntimeError("The original daily model-call counter did not persist unchanged.")
    ready = prepare_runtime()
    manifest = Path(os.environ["BUSHFIRE_RAG_INDEX_DIR"]) / "manifest.json"
    identity = {
        "manifest_sha256": ready["rag"]["manifest_sha256"],
        "corpus_manifest_sha256": ready["rag"]["corpus_manifest_sha256"],
        "mtime_ns": manifest.stat().st_mtime_ns,
    }
    if expected and expected["index"] != identity:
        raise RuntimeError("A restart lost persistent data or overwrote the existing RAG version.")
    pdf = create_report_pdf("# Container export check\n\n**Reviewer: 测试审核员**\n\n学校防火准备。")
    extracted = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    if "测试审核员" not in extracted or "学校防火准备" not in extracted:
        raise RuntimeError("The image cannot export readable Chinese reviewer text.")
    # Exercise the real persistent quota without sending any model/network request.
    today = _consume_fixture_call()
    calls = _read_quota(today)
    expected_calls = 2 if expected and expected["quota"]["day"] == today else 1
    if calls != expected_calls:
        raise RuntimeError("The daily model-call counter did not persist across container restarts.")
    if expected is None:
        expected = {
            "schema": SMOKE_SCHEMA,
            "index": identity,
            "process_sha256": process_identity,
            **_create_persistence_evidence(),
            "quota": {"day": today, "calls": calls},
        }
        atomic_write_json(sentinel, expected)
    _verify_persistence_evidence(_load_expectations(sentinel))
    print(
        json.dumps(
            {
                "smoke": "passed",
                "phase": args.phase,
                "uid": os.getuid(),
                "rag": ready["rag"],
                "audit_events": 2,
                "trace_records": 1,
                "quota_calls": calls,
                "actual_restart_verified": args.phase == "restart",
            }
        )
    )


if __name__ == "__main__":
    main()
