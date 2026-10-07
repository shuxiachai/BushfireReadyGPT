"""Maintenance observations must never initialize state or disclose raw config."""

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from scripts import check_runtime_maintenance as maintenance

DAY = "2026-10-07"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _environment(root):
    return {
        "BUSHFIRE_DEPLOYMENT_MODE": "cloud",
        "BUSHFIRE_RUNTIME_DIR": str(root),
        "BUSHFIRE_MODEL_MAX_CONCURRENT": "1",
        "BUSHFIRE_MODEL_DAILY_CALL_LIMIT": "100",
        "OPENAI_API_KEY": "PRIVATE-CREDENTIAL-MUST-NOT-APPEAR",
        "BUSHFIRE_ACCESS_PASSWORD": "PRIVATE-PASSWORD-MUST-NOT-APPEAR",
    }


def _create_database(root, rows=((DAY, 7),)):
    root.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(root / "model-usage.sqlite3")) as connection, connection:
        connection.execute("CREATE TABLE daily_calls (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
        connection.executemany("INSERT INTO daily_calls VALUES (?, ?)", rows)


def _tree(root):
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_mode,
            path.stat().st_mtime_ns,
            path.read_bytes() if path.is_file() else None,
        )
        for path in root.rglob("*")
    }


def _snapshot(root, **kwargs):
    return maintenance.maintenance_snapshot(day=DAY, persistent_root=root, environ=_environment(root), **kwargs)


def test_ready_snapshot_is_private_selected_day_and_read_only(tmp_path):
    root = tmp_path / "PRIVATE-RUNTIME-PATH"
    _create_database(root, [("2026-10-06", 99), (DAY, 7), ("2026-10-08", 12)])
    before = _tree(tmp_path)
    result, code = _snapshot(root, minimum_calls=7)
    assert code == 0
    assert result == {
        "cloud": True,
        "concurrency": 1,
        "daily_call_limit": 100,
        "model_max_tokens": 2300,
        "sdk_max_retries": 0,
        "audit_within_persistent_root": True,
        "trace_within_persistent_root": True,
        "quota_within_persistent_root": True,
        "status": "ready",
        "day": DAY,
        "calls": 7,
        "minimum_calls_met": True,
    }
    assert "PRIVATE" not in json.dumps(result)
    assert _tree(tmp_path) == before


def test_absent_database_is_unknown_even_at_zero_high_water_and_creates_nothing(tmp_path):
    root = tmp_path / "absent"
    result, code = _snapshot(root, minimum_calls=0)
    assert code == 1
    assert result["status"] == "not_initialized"
    assert result["calls"] is None and result["minimum_calls_met"] is False
    assert not root.exists()


def test_lower_counter_rejected_without_automatic_reconciliation(tmp_path):
    _create_database(tmp_path)
    before = _tree(tmp_path)
    result, code = _snapshot(tmp_path, minimum_calls=8)
    assert code == 1 and result["minimum_calls_met"] is False and result["calls"] == 7
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("kind", ["malformed", "wal", "oversized", "directory"])
def test_unavailable_database_never_creates_sidecars_or_changes_files(tmp_path, kind):
    root = tmp_path / "runtime"
    _create_database(root)
    database = root / "model-usage.sqlite3"
    if kind == "malformed":
        database.write_bytes(b"PRIVATE-MALFORMED-DATABASE" * 20)
    elif kind == "wal":
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
    elif kind == "oversized":
        database.write_bytes(b"X" * (1024 * 1024 + 1))
    else:
        database.unlink()
        database.mkdir()
    before = _tree(tmp_path)
    result, code = _snapshot(root, minimum_calls=0)
    assert code == 1 and result["status"] == "unavailable"
    assert result["calls"] is None and result["minimum_calls_met"] is False
    assert "PRIVATE" not in json.dumps(result)
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    "name, field",
    [
        ("BUSHFIRE_AUDIT_DIR", "audit_within_persistent_root"),
        ("BUSHFIRE_TRACE_DIR", "trace_within_persistent_root"),
        ("BUSHFIRE_RUNTIME_DIR", "quota_within_persistent_root"),
    ],
)
def test_path_outside_expected_mount_is_rejected_without_disclosing_path(tmp_path, name, field):
    root = tmp_path / "runtime"
    outside = tmp_path / "PRIVATE-OUTSIDE-PATH"
    _create_database(root)
    _create_database(outside)
    env = {**_environment(root), name: str(outside)}
    before = _tree(tmp_path)
    result, code = maintenance.maintenance_snapshot(day=DAY, persistent_root=root, environ=env)
    assert code == 1 and result[field] is False
    assert "PRIVATE" not in json.dumps(result)
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    "name",
    [
        "BUSHFIRE_DEPLOYMENT_MODE",
        "BUSHFIRE_MODEL_MAX_CONCURRENT",
        "BUSHFIRE_MODEL_DAILY_CALL_LIMIT",
        "BUSHFIRE_MODEL_MAX_TOKENS",
        "BUSHFIRE_MODEL_MAX_RETRIES",
    ],
)
def test_malformed_settings_have_fixed_safe_errors(tmp_path, name):
    env = {**_environment(tmp_path), name: "PRIVATE-MALFORMED-CONFIG"}
    before = _tree(tmp_path)
    assert maintenance.maintenance_snapshot(day=DAY, persistent_root=tmp_path, environ=env) == (
        {"status": "invalid_configuration"},
        2,
    )
    assert _tree(tmp_path) == before


def test_numeric_overrides_and_effective_retry_override(tmp_path):
    _create_database(tmp_path)
    env = {**_environment(tmp_path), "BUSHFIRE_MODEL_MAX_TOKENS": "1400", "BUSHFIRE_MODEL_MAX_RETRIES": "5"}
    result, code = maintenance.maintenance_snapshot(day=DAY, persistent_root=tmp_path, environ=env)
    assert code == 0 and result["model_max_tokens"] == 1400 and result["sdk_max_retries"] == 0
    env.update(BUSHFIRE_DEPLOYMENT_MODE="local", BUSHFIRE_MODEL_MAX_CONCURRENT="0", BUSHFIRE_MODEL_DAILY_CALL_LIMIT="0")
    result, code = maintenance.maintenance_snapshot(day=DAY, persistent_root=tmp_path, environ=env)
    assert code == 0 and result["cloud"] is False and result["sdk_max_retries"] == 5


@pytest.mark.parametrize(
    "arguments",
    [
        ["--day", "PRIVATE-INVALID-DAY"],
        ["--day", "20261007"],
        ["--day", "2026-02-30"],
        ["--minimum-calls", "PRIVATE-INVALID-COUNT"],
        ["--minimum-calls", "-1"],
        ["--PRIVATE-UNKNOWN"],
    ],
)
def test_invalid_cli_arguments_are_never_echoed(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        maintenance.main(arguments)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err == '{"status": "invalid_arguments"}\n'


def test_real_python_b_entrypoint_never_imports_dotenv_provider_or_bootstrap(tmp_path):
    root = tmp_path / "absent-runtime"
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("BUSHFIRE_", "RAILWAY_"))}
    environment.update(_environment(root))
    environment.update(LLM_PROVIDER="INVALID-PROVIDER-MUST-NOT-BE-INITIALIZED")
    script = PROJECT_ROOT / "scripts" / "check_runtime_maintenance.py"
    runner = """
import runpy, sys
class BlockImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'dotenv', 'openai', 'httpx'} or fullname in {
            'src.config', 'src.model_runtime', 'src.container_runtime', 'src.audit', 'src.runtime_trace'
        }:
            raise AssertionError('Forbidden maintenance import')
sys.meta_path.insert(0, BlockImports())
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    before = _tree(tmp_path)
    # A separately selected, supported Python can exercise this stdlib-only CLI
    # when a developer's test venv emits interpreter startup diagnostics.
    interpreter = os.environ.get("BUSHFIRE_TEST_CLI_PYTHON", sys.executable)
    result = subprocess.run(
        [interpreter, "-B", "-c", runner, str(script), "--day", DAY, "--persistent-root", str(root)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 1 and result.stderr == ""
    assert json.loads(result.stdout)["status"] == "not_initialized"
    assert "PRIVATE" not in result.stdout
    assert _tree(tmp_path) == before
