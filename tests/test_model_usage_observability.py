"""Read-only production quota visibility; no model calls or production data."""

import json
import sqlite3
import stat
import sys
from contextlib import closing
from datetime import datetime
from types import SimpleNamespace

import pytest

from scripts import start_container
from src import model_limits

DAY = "2026-09-12"


@pytest.fixture
def usage(monkeypatch, tmp_path):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", str(tmp_path / "usage"))
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "100")
    monkeypatch.setattr(
        model_limits, "datetime", SimpleNamespace(now=lambda zone: datetime(2026, 9, 12, 2, 0, tzinfo=zone))
    )
    return model_limits.load_model_limits()


def _create(limits, rows=()):
    limits.database.parent.mkdir(parents=True)
    with closing(sqlite3.connect(limits.database)) as connection, connection:
        connection.execute("CREATE TABLE daily_calls (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
        connection.executemany("INSERT INTO daily_calls VALUES (?, ?)", rows)


def _files(directory):
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir() if path.is_file()}


def test_missing_database_is_not_initialized_not_zero_and_creates_nothing(usage):
    assert model_limits.read_model_usage(DAY) == {"status": "not_initialized", "day": DAY, "calls": None}
    assert not usage.database.parent.exists()


def test_missing_day_in_valid_database_is_zero_without_mutation(usage):
    _create(usage, [("2026-09-11", 81)])
    before = _files(usage.database.parent)
    assert model_limits.read_model_usage(DAY) == {"status": "ready", "day": DAY, "calls": 0}
    assert _files(usage.database.parent) == before


def test_reads_only_selected_day_with_read_only_uri_query_only_and_no_sidecars(usage, monkeypatch):
    _create(usage, [("2026-09-11", 81), (DAY, 3), ("2026-09-13", 19)])
    before = _files(usage.database.parent)
    actual_connect = sqlite3.connect
    observed = []
    statements = []

    def connect(database, **kwargs):
        assert database == usage.database.as_uri() + "?mode=ro"
        assert kwargs == {"uri": True, "timeout": 1.0}
        connection = actual_connect(database, **kwargs)
        connection.set_trace_callback(statements.append)
        observed.append(connection)
        return connection

    monkeypatch.setattr(model_limits.sqlite3, "connect", connect)
    assert model_limits.read_model_usage(DAY) == {"status": "ready", "day": DAY, "calls": 3}
    assert statements[0] == "PRAGMA query_only=ON"
    assert statements[-1] == "SELECT calls FROM daily_calls WHERE day = '2026-09-12'"
    assert all(not statement.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "BEGIN")) for statement in statements)
    assert all("2026-09-11" not in statement and "2026-09-13" not in statement for statement in statements)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        observed[0].execute("SELECT 1")
    assert _files(usage.database.parent) == before


@pytest.mark.parametrize("value", ["", "20260912", "2026-9-12", "2026-02-30", "2026-09-12T00:00Z", "secret';--", 1])
def test_rejects_invalid_day_before_filesystem_or_sql_access(usage, value):
    with pytest.raises(ValueError, match="canonical UTC date") as error:
        model_limits.read_model_usage(value)
    assert "secret" not in str(error.value)
    assert not usage.database.parent.exists()


@pytest.mark.parametrize("payload", [b"", b"SECRET-CORRUPT-PAYLOAD" * 10, b"SQLite format 3\x00" + b"\x00" * 200])
def test_corrupted_database_is_bounded_unavailable_without_repair_or_error_disclosure(usage, payload):
    usage.database.parent.mkdir()
    usage.database.write_bytes(payload)
    before = _files(usage.database.parent)
    result = model_limits.read_model_usage(DAY)
    assert result == {"status": "unavailable", "day": DAY, "calls": None}
    assert "SECRET" not in json.dumps(result) and str(usage.database) not in json.dumps(result)
    assert _files(usage.database.parent) == before


@pytest.mark.parametrize("counter", [-1, 1.25, "SECRET-INVALID-COUNTER"])
def test_invalid_counter_is_unavailable_without_leaking_value(usage, counter):
    _create(usage, [(DAY, counter)])
    before = _files(usage.database.parent)
    assert model_limits.read_model_usage(DAY) == {"status": "unavailable", "day": DAY, "calls": None}
    assert _files(usage.database.parent) == before


@pytest.mark.parametrize(
    "schema",
    [
        "CREATE TABLE unrelated (value TEXT)",
        "CREATE TABLE daily_calls (day TEXT, calls INTEGER NOT NULL)",
        "CREATE VIEW daily_calls AS SELECT '2026-09-12' AS day, 12 AS calls",
    ],
)
def test_missing_or_changed_schema_is_not_silently_initialized_or_trusted(usage, schema):
    usage.database.parent.mkdir()
    with closing(sqlite3.connect(usage.database)) as connection:
        connection.execute(schema)
    before = _files(usage.database.parent)
    assert model_limits.read_model_usage(DAY) == {"status": "unavailable", "day": DAY, "calls": None}
    assert _files(usage.database.parent) == before


def test_wal_database_is_not_opened_or_treated_as_a_stale_checkpoint(usage, monkeypatch):
    _create(usage, [(DAY, 2)])
    with closing(sqlite3.connect(usage.database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    before = _files(usage.database.parent)

    def forbidden(*args, **kwargs):
        pytest.fail("WAL read must not create SQLite shared-memory files or ignore uncheckpointed rows")

    monkeypatch.setattr(model_limits.sqlite3, "connect", forbidden)
    assert model_limits.read_model_usage(DAY) == {"status": "unavailable", "day": DAY, "calls": None}
    assert _files(usage.database.parent) == before


def test_directory_and_oversized_database_are_unavailable_without_opening_sqlite(usage, monkeypatch):
    usage.database.mkdir(parents=True)
    assert model_limits.read_model_usage(DAY)["status"] == "unavailable"
    usage.database.rmdir()
    usage.database.write_bytes(b"X" * 101)
    monkeypatch.setattr(model_limits, "_MAX_USAGE_DATABASE_BYTES", 100)
    assert model_limits.read_model_usage(DAY)["status"] == "unavailable"


def test_linked_database_is_rejected_before_reading_target(usage, monkeypatch):
    _create(usage, [(DAY, 2)])
    monkeypatch.setattr(type(usage.database), "lstat", lambda _: SimpleNamespace(st_mode=stat.S_IFLNK, st_size=200))
    monkeypatch.setattr(model_limits.sqlite3, "connect", lambda *args, **kwargs: pytest.fail("unexpected linked read"))
    assert model_limits.read_model_usage(DAY) == {"status": "unavailable", "day": DAY, "calls": None}


def test_sqlite_error_details_never_enter_snapshot_or_startup_log(usage, monkeypatch, capsys):
    _create(usage, [(DAY, 2)])

    def denied(*args, **kwargs):
        raise sqlite3.OperationalError("SECRET path /data/private/report.json key=do-not-print")

    monkeypatch.setattr(model_limits.sqlite3, "connect", denied)
    model_limits.emit_model_usage_snapshot()
    line = capsys.readouterr().out
    assert "SECRET" not in line and "/data" not in line and "key=" not in line
    assert json.loads(line) == {
        "event": "model_usage",
        "schema_version": 1,
        "phase": "startup",
        "status": "unavailable",
        "day": DAY,
        "calls": None,
    }


def test_startup_snapshot_then_committed_event_then_restart_snapshot_match_real_database(usage, capsys):
    model_limits.emit_model_usage_snapshot()
    model_limits._consume_daily_call(usage)
    # A new read of the configured persistent database, not an in-memory cache.
    model_limits.emit_model_usage_snapshot()
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(record["phase"], record["status"], record["calls"]) for record in records] == [
        ("startup", "not_initialized", None),
        ("call_committed", "ready", 1),
        ("startup", "ready", 1),
    ]
    assert all(set(record) == {"event", "schema_version", "phase", "status", "day", "calls"} for record in records)
    assert all(record["day"] == DAY for record in records)


def test_call_event_is_emitted_only_after_commit_is_readable_from_another_connection(usage, monkeypatch):
    snapshots = []

    def inspect(phase, snapshot):
        assert phase == "call_committed"
        assert model_limits.read_model_usage(DAY, limits=usage) == snapshot
        snapshots.append(snapshot)

    monkeypatch.setattr(model_limits, "_emit_usage_event", inspect)
    model_limits._consume_daily_call(usage)
    assert snapshots == [{"status": "ready", "day": DAY, "calls": 1}]


def test_exhausted_allowance_or_storage_failure_does_not_log_a_successful_commit(usage, monkeypatch, capsys):
    _create(usage, [(DAY, 100)])
    with pytest.raises(model_limits.ModelAllowanceError, match="allowance"):
        model_limits._consume_daily_call(usage)
    assert capsys.readouterr().out == ""

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("secret")

    monkeypatch.setattr(model_limits.sqlite3, "connect", fail)
    with pytest.raises(model_limits.ModelAllowanceError, match="counter is unavailable"):
        model_limits._consume_daily_call(usage)
    assert capsys.readouterr().out == ""


def test_failed_sqlite_commit_does_not_publish_a_false_counter_event(usage, monkeypatch, capsys):
    _create(usage)
    actual_connect = sqlite3.connect

    class FailedCommit(sqlite3.Connection):
        def __exit__(self, *args):
            self.rollback()
            raise sqlite3.OperationalError("synthetic commit failure")

    monkeypatch.setattr(
        model_limits.sqlite3, "connect", lambda *args, **kwargs: actual_connect(*args, **kwargs, factory=FailedCommit)
    )
    with pytest.raises(model_limits.ModelAllowanceError, match="counter is unavailable"):
        model_limits._consume_daily_call(usage)
    assert capsys.readouterr().out == ""
    assert model_limits.read_model_usage(DAY)["calls"] == 0


def test_counter_cannot_overflow_sqlite_integer_and_log_a_nonpersisted_python_integer(usage, monkeypatch, capsys):
    _create(usage, [(DAY, 2**63 - 1)])
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", str(2**64))
    before = _files(usage.database.parent)
    with pytest.raises(model_limits.ModelAllowanceError, match="counter is invalid"):
        model_limits._consume_daily_call(model_limits.load_model_limits())
    assert capsys.readouterr().out == ""
    assert _files(usage.database.parent) == before


def test_logging_failure_does_not_turn_committed_request_into_admission_error(usage, monkeypatch):
    def fail(*args, **kwargs):
        raise BrokenPipeError("closed output")

    monkeypatch.setattr("builtins.print", fail)
    model_limits._consume_daily_call(usage)
    assert model_limits.read_model_usage(DAY)["calls"] == 1


def test_local_usage_remains_unlogged_and_invalid_cloud_config_leaks_nothing(usage, monkeypatch, capsys):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "local")
    model_limits.emit_model_usage_snapshot()
    model_limits._consume_daily_call(model_limits.load_model_limits())
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "SECRET-BAD-CONFIG")
    model_limits.emit_model_usage_snapshot()
    assert model_limits.read_model_usage(DAY) == {"status": "unavailable", "day": DAY, "calls": None}
    assert capsys.readouterr().out == ""


def test_utc_day_rollover_does_not_disguise_old_day_counter_as_reset(usage, monkeypatch, capsys):
    model_limits._consume_daily_call(usage)
    monkeypatch.setattr(
        model_limits, "datetime", SimpleNamespace(now=lambda zone: datetime(2026, 9, 13, 0, 0, tzinfo=zone))
    )
    model_limits.emit_model_usage_snapshot()
    assert model_limits.read_model_usage(DAY)["calls"] == 1
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(record["day"], record["calls"]) for record in records] == [(DAY, 1), ("2026-09-13", 0)]


def test_container_entrypoint_emits_quota_snapshot_after_ready_before_exec(usage, monkeypatch, capsys):
    _create(usage, [(DAY, 7)])
    before = _files(usage.database.parent)
    monkeypatch.setattr(sys, "argv", ["start_container.py", "--check-only"])
    monkeypatch.setattr(start_container, "initialize_volume_permissions", lambda: None)
    monkeypatch.setattr(start_container, "prepare_runtime", lambda: {"port": 8501})
    assert start_container.main() == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[0] == {"container_ready": True, "port": 8501}
    assert records[1]["phase"] == "startup" and records[1]["calls"] == 7
    assert _files(usage.database.parent) == before


def test_failed_container_validation_does_not_read_or_emit_quota(usage, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["start_container.py", "--check-only"])
    monkeypatch.setattr(start_container, "initialize_volume_permissions", lambda: None)

    def fail():
        raise RuntimeError("controlled startup validation failure")

    monkeypatch.setattr(start_container, "prepare_runtime", fail)
    monkeypatch.setattr(start_container, "emit_model_usage_snapshot", lambda: pytest.fail("unexpected quota read"))
    assert start_container.main() == 1
    assert capsys.readouterr().out == ""
    assert not usage.database.parent.exists()


def test_explicit_historical_startup_observation_preserves_both_day_counters(usage, monkeypatch, capsys):
    _create(usage, [("2026-09-11", 7), (DAY, 2)])
    before = _files(usage.database.parent)
    monkeypatch.setattr(sys, "argv", ["start_container.py", "--check-only", "--observe-usage-day", "2026-09-11"])
    monkeypatch.setattr(start_container, "initialize_volume_permissions", lambda: None)
    monkeypatch.setattr(start_container, "prepare_runtime", lambda: {"port": 8501})
    assert start_container.main() == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()][1:]
    assert [(row["phase"], row["day"], row["calls"]) for row in records] == [
        ("startup", DAY, 2),
        ("startup", "2026-09-11", 7),
    ]
    assert _files(usage.database.parent) == before


@pytest.mark.parametrize("value", ["20260911", "2026-02-30", "2026-09-11T00:00:00", "2026-09-11;delete", "all"])
def test_invalid_observation_date_fails_before_any_container_work(value, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["start_container.py", "--observe-usage-day", value])
    monkeypatch.setattr(
        start_container, "initialize_volume_permissions", lambda: pytest.fail("unexpected storage operation")
    )
    with pytest.raises(SystemExit) as failure:
        start_container.main()
    assert failure.value.code == 2
