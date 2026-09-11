"""Exercise real audit/Trace/SQLite persistence on disposable synthetic volumes."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts import smoke_container as smoke
from src import audit, corpus_bundle, model_limits


@pytest.fixture
def fixture_volume(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith(("BUSHFIRE_", "RAILWAY_")):
            monkeypatch.delenv(name)
    source = tmp_path / "image-corpus"
    bundle = corpus_bundle.create_test_corpus_bundle(source)
    volume = tmp_path / "volume"
    installed = volume / "private-rag" / bundle["manifest_sha256"]
    corpus_bundle.install_corpus_bundle(source, installed)
    index = installed / "index"
    index.mkdir()
    (index / "manifest.json").write_text('{"synthetic_index":true}', encoding="utf-8")
    for name, value in {
        "BUSHFIRE_CONTAINER_SMOKE": "true",
        "BUSHFIRE_DEPLOYMENT_MODE": "cloud",
        "BUSHFIRE_RUNTIME_DIR": str(volume),
        "BUSHFIRE_RAG_CORPUS_SHA256": bundle["manifest_sha256"],
        "BUSHFIRE_RAG_INDEX_DIR": str(index),
        "BUSHFIRE_TRACE_ENABLED": "true",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(audit, "AUDIT_DIR", audit._DEFAULT_AUDIT_DIR)
    monkeypatch.setattr(smoke, "_verify_worker", lambda: None)
    monkeypatch.setattr(smoke.os, "getuid", lambda: 10001, raising=False)
    process = {"identity": "a" * 64}
    monkeypatch.setattr(smoke, "_pid1_identity", lambda: process["identity"])
    ready = {
        "rag": {
            "status": "ready",
            "manifest_sha256": "b" * 64,
            "corpus_manifest_sha256": bundle["manifest_sha256"],
        }
    }
    prepares = []

    def prepare():
        prepares.append(True)
        return deepcopy(ready)

    monkeypatch.setattr(smoke, "prepare_runtime", prepare)

    def run(phase):
        monkeypatch.setattr(sys, "argv", ["smoke_container.py", "--phase", phase])
        smoke.main()

    return SimpleNamespace(
        volume=volume,
        sentinel=volume / "container-smoke.json",
        installed=installed,
        index=index,
        ready=ready,
        process=process,
        prepares=prepares,
        run=run,
    )


def _evidence_bytes(fixture):
    return {
        str(path.relative_to(fixture.volume)): path.read_bytes()
        for directory in (fixture.volume / "audit", fixture.volume / "traces")
        for path in directory.iterdir()
        if path.is_file()
    }


def _first(fixture):
    fixture.run("first")
    fixture.process["identity"] = "c" * 64
    return smoke._load_expectations(fixture.sentinel)


def test_first_and_restart_verify_real_audit_trace_and_quota_without_rewriting_old_evidence(fixture_volume, capsys):
    expected = _first(fixture_volume)
    evidence = _evidence_bytes(fixture_volume)
    sentinel = fixture_volume.sentinel.read_bytes()
    assert len(expected["audit"]) == 2
    assert smoke._read_quota(expected["quota"]["day"]) == 1
    assert b"Synthetic container test" not in sentinel
    assert b"Synthetic persistence check" not in sentinel
    fixture_volume.run("restart")
    assert smoke._read_quota(expected["quota"]["day"]) == 2
    assert _evidence_bytes(fixture_volume) == evidence
    assert fixture_volume.sentinel.read_bytes() == sentinel
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [output["actual_restart_verified"] for output in outputs] == [False, True]
    assert all(output["audit_events"] == 2 and output["trace_records"] == 1 for output in outputs)


def test_old_evidence_is_readable_by_an_independent_python_process(fixture_volume):
    _first(fixture_volume)
    before = _evidence_bytes(fixture_volume)
    script = (
        "from scripts.smoke_container import _load_expectations, _verify_persistence_evidence, _read_quota; "
        "from src.runtime_paths import runtime_path; "
        "expected = _load_expectations(runtime_path('container-smoke.json')); "
        "_verify_persistence_evidence(expected); "
        "assert _read_quota(expected['quota']['day']) == 1; print('verified')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=smoke.PROJECT_ROOT, capture_output=True, text=True, timeout=30, check=True
    )
    assert result.stdout.strip() == "verified"
    assert _evidence_bytes(fixture_volume) == before


def test_restart_refuses_same_pid1_before_any_probe_writes(fixture_volume):
    fixture_volume.run("first")
    expected = smoke._load_expectations(fixture_volume.sentinel)
    with pytest.raises(RuntimeError, match="different actual PID 1"):
        fixture_volume.run("restart")
    assert len(fixture_volume.prepares) == 1
    assert smoke._read_quota(expected["quota"]["day"]) == 1


def test_restart_phase_cannot_be_replayed_to_add_more_fixture_calls(fixture_volume):
    expected = _first(fixture_volume)
    fixture_volume.run("restart")
    with pytest.raises(RuntimeError, match="did not persist unchanged"):
        fixture_volume.run("restart")
    assert smoke._read_quota(expected["quota"]["day"]) == 2


def test_restart_on_next_utc_day_preserves_the_old_day_and_counts_the_new_day(fixture_volume, monkeypatch):
    expected = _first(fixture_volume)

    class NextDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=1)

    monkeypatch.setattr(smoke, "datetime", NextDay)
    monkeypatch.setattr(model_limits, "datetime", NextDay)
    fixture_volume.run("restart")
    assert smoke._read_quota(expected["quota"]["day"]) == 1
    assert smoke._read_quota(NextDay.now().date().isoformat()) == 1


@pytest.mark.parametrize("item", ["audit", "trace", "quota", "head"])
def test_missing_persistent_record_fails_without_recreating_it(fixture_volume, item):
    expected = _first(fixture_volume)
    if item == "audit":
        path = fixture_volume.volume / "audit" / expected["audit"][0]["file"]
    elif item == "trace":
        path = fixture_volume.volume / "traces" / expected["trace"]["file"]
    elif item == "head":
        path = fixture_volume.volume / "audit" / ".head_container_smoke_persistence.json"
    else:
        path = fixture_volume.volume / "model-usage.sqlite3"
    path.unlink()
    with pytest.raises((RuntimeError, OSError)):
        fixture_volume.run("restart")
    assert not path.exists()
    assert len(fixture_volume.prepares) == 1


@pytest.mark.parametrize("item", ["audit", "trace", "quota", "index_hash", "index_mtime"])
def test_changed_persistent_evidence_fails_before_incrementing_quota(fixture_volume, item):
    expected = _first(fixture_volume)
    if item in {"audit", "trace"}:
        entry = expected["audit"][0] if item == "audit" else expected["trace"]
        directory = "audit" if item == "audit" else "traces"
        path = fixture_volume.volume / directory / entry["file"]
        path.write_bytes(path.read_bytes() + b" ")
    elif item == "quota":
        with closing(sqlite3.connect(fixture_volume.volume / "model-usage.sqlite3")) as connection, connection:
            connection.execute("UPDATE daily_calls SET calls = 0")
    elif item == "index_hash":
        fixture_volume.ready["rag"]["manifest_sha256"] = "d" * 64
    else:
        path = fixture_volume.index / "manifest.json"
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 10_000_000))
    with pytest.raises(RuntimeError):
        fixture_volume.run("restart")
    assert smoke._read_quota(expected["quota"]["day"]) == (0 if item == "quota" else 1)


def test_matching_trace_file_hash_does_not_bypass_real_trace_schema_validation(fixture_volume):
    expected = _first(fixture_volume)
    path = fixture_volume.volume / "traces" / expected["trace"]["file"]
    path.write_text('{"invalid_trace":true}', encoding="utf-8")
    expected["trace"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    fixture_volume.sentinel.write_text(json.dumps(expected), encoding="utf-8")
    with pytest.raises(RuntimeError, match="schema/summary"):
        fixture_volume.run("restart")


def test_matching_audit_hashes_do_not_bypass_real_audit_schema_validation(fixture_volume):
    expected = _first(fixture_volume)
    event = expected["audit"][0]
    path = fixture_volume.volume / "audit" / event["file"]
    record = json.loads(path.read_bytes())
    record["analysis"] = []
    record["record_hash"] = audit.sha256_json({key: value for key, value in record.items() if key != "record_hash"})
    path.write_text(json.dumps(record), encoding="utf-8")
    event["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    event["record_hash"] = record["record_hash"]
    fixture_volume.sentinel.write_text(json.dumps(expected), encoding="utf-8")
    with pytest.raises(audit.AuditIntegrityError, match="malformed report or analysis"):
        fixture_volume.run("restart")


@pytest.mark.parametrize(
    "value",
    [None, [], {}, "not-json", "[" * 2000 + "0" + "]" * 2000],
    ids=["null", "list", "empty-object", "invalid-json", "deep-nesting"],
)
def test_malformed_expectations_fail_closed(fixture_volume, value):
    _first(fixture_volume)
    fixture_volume.sentinel.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="expectations"):
        fixture_volume.run("restart")


@pytest.mark.parametrize(
    "filename", ["../outside.json", "/etc/passwd", "C:/outside.json", "audit_x/../../outside.json"]
)
def test_expectations_cannot_redirect_audit_reads(fixture_volume, filename):
    expected = _first(fixture_volume)
    expected["audit"][0]["file"] = filename
    fixture_volume.sentinel.write_text(json.dumps(expected), encoding="utf-8")
    with pytest.raises(RuntimeError, match="expectations"):
        fixture_volume.run("restart")


def test_oversized_expectations_are_rejected_without_unbounded_read(fixture_volume):
    expected = _first(fixture_volume)
    original = fixture_volume.sentinel.read_bytes()
    fixture_volume.sentinel.write_bytes(original + b" " * (smoke.MAX_EXPECTATIONS_BYTES - len(original)))
    assert smoke._load_expectations(fixture_volume.sentinel) == expected
    fixture_volume.sentinel.write_bytes(b" " * (smoke.MAX_EXPECTATIONS_BYTES + 1))
    with pytest.raises(RuntimeError, match="oversized"):
        fixture_volume.run("restart")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BUSHFIRE_CONTAINER_SMOKE", "false"),
        ("RAILWAY_PROJECT_ID", "synthetic-deployed-project"),
        ("BUSHFIRE_AUDIT_DIR", "outside-audit"),
        ("BUSHFIRE_TRACE_DIR", "outside-traces"),
        ("BUSHFIRE_AUDIT_INCLUDE_SENSITIVE_CONTENT", "true"),
        ("BUSHFIRE_TRACE_ENABLED", "false"),
        ("BUSHFIRE_DEPLOYMENT_MODE", "local"),
        ("BUSHFIRE_RUNTIME_DIR", "relative-volume"),
        ("BUSHFIRE_RAG_CORPUS_SHA256", "../../outside"),
    ],
)
def test_nonisolated_configuration_is_refused_before_writes(fixture_volume, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        fixture_volume.run("first")
    assert not fixture_volume.sentinel.exists()
    assert not fixture_volume.prepares
    assert not (fixture_volume.volume / "model-usage.sqlite3").exists()


def test_nonfixture_bundle_is_rejected_even_with_smoke_flag(fixture_volume, monkeypatch):
    manifest_path = fixture_volume.installed / corpus_bundle.BUNDLE_MANIFEST
    manifest = json.loads(manifest_path.read_bytes())
    manifest.update(
        fixture_only=False,
        usage_intent="private_research_noncommercial",
        source_terms_acknowledged=True,
        source_index_manifest_sha256="e" * 64,
    )
    manifest.pop("manifest_sha256")
    manifest = corpus_bundle._with_hash(manifest)
    manifest_path.write_bytes(corpus_bundle._canonical(manifest))
    target = fixture_volume.installed.with_name(manifest["manifest_sha256"])
    fixture_volume.installed.rename(target)
    monkeypatch.setenv("BUSHFIRE_RAG_CORPUS_SHA256", manifest["manifest_sha256"])
    assert corpus_bundle.validate_corpus_bundle(target, allow_index=True)["fixture_only"] is False
    with pytest.raises(RuntimeError, match="test-only corpus"):
        fixture_volume.run("first")
    assert not fixture_volume.prepares


def test_first_phase_never_overwrites_existing_runtime_data(fixture_volume):
    existing = fixture_volume.volume / "operator-report.md"
    existing.write_bytes(b"Existing record, not smoke data")
    with pytest.raises(RuntimeError, match="not fresh"):
        fixture_volume.run("first")
    assert existing.read_bytes() == b"Existing record, not smoke data"
    assert not fixture_volume.prepares


def test_pid1_identity_uses_boot_and_start_ticks_not_reused_pid(monkeypatch):
    boot = b"11111111-1111-1111-1111-111111111111\n"
    fields = ["S"] + ["0"] * 18 + ["100"]

    def read(path, limit):
        return boot if path.name == "boot_id" else ("1 (worker (with spaces)) " + " ".join(fields)).encode()

    monkeypatch.setattr(smoke, "_read_bytes", read)
    first = smoke._pid1_identity()
    assert smoke._pid1_identity() == first
    fields[19] = "101"
    assert smoke._pid1_identity() != first


@pytest.mark.parametrize("uid", [0, 10002])
def test_smoke_worker_rejects_wrong_effective_uid(monkeypatch, uid):
    monkeypatch.setattr(smoke.os, "getuid", lambda: uid, raising=False)
    with pytest.raises(RuntimeError, match="non-root worker"):
        smoke._verify_worker()


@pytest.mark.parametrize("gid", ["10001", "0"])
def test_worker_checks_all_web_process_uid_and_gid_fields(monkeypatch, gid):
    monkeypatch.setattr(smoke.os, "getuid", lambda: 10001, raising=False)
    payload = ("Uid:\t10001\t10001\t10001\t10001\nGid:\t" + "\t".join([gid] * 4) + "\n").encode()
    monkeypatch.setattr(smoke, "_read_bytes", lambda path, limit: payload)
    if gid == "10001":
        smoke._verify_worker()
    else:
        with pytest.raises(RuntimeError, match="web process"):
            smoke._verify_worker()
