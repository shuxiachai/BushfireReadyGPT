"""Process-wide concurrency and persistent daily model-request allowances.

Counters measure HTTP completion attempts, including structural repairs. They
are not token or currency budgets. A timed-out worker keeps its slot until it
actually finishes, so reconnecting a browser cannot bypass concurrency limits.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import threading
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from src.deployment_access import DeploymentConfigurationError, deployment_mode

_ACTIVE_LOCK = threading.Lock()
_ACTIVE_REQUESTS = 0
_MAX_USAGE_DATABASE_BYTES = 1024 * 1024


class ModelAllowanceError(RuntimeError):
    """A non-secret, displayable request-admission failure."""


@dataclass(frozen=True)
class ModelLimits:
    concurrency: int
    daily_calls: int
    database: Path
    cloud: bool

    @property
    def enabled(self) -> bool:
        return bool(self.concurrency or self.daily_calls or self.cloud)


def _limit(values: Mapping[str, str], name: str, default: int, *, cloud: bool) -> int:
    raw = values.get(name, str(default)).strip()
    try:
        result = int(raw)
    except ValueError as error:
        raise DeploymentConfigurationError(f"{name} must be an integer.") from error
    if result < 0 or (cloud and result == 0):
        raise DeploymentConfigurationError(f"{name} must be positive in cloud mode and non-negative locally.")
    return result


def load_model_limits(environ: Mapping[str, str] | None = None) -> ModelLimits:
    values = os.environ if environ is None else environ
    cloud = deployment_mode(values) == "cloud"
    root = values.get("BUSHFIRE_RUNTIME_DIR", "").strip()
    if cloud and not root:
        raise DeploymentConfigurationError("Cloud model quotas require BUSHFIRE_RUNTIME_DIR on a persistent volume.")
    project_root = Path(__file__).resolve().parents[1]
    directory = Path(root).expanduser() if root else project_root / "chat_history"
    if not directory.is_absolute():
        directory = project_root / directory
    return ModelLimits(
        concurrency=_limit(values, "BUSHFIRE_MODEL_MAX_CONCURRENT", 1 if cloud else 0, cloud=cloud),
        daily_calls=_limit(values, "BUSHFIRE_MODEL_DAILY_CALL_LIMIT", 100 if cloud else 0, cloud=cloud),
        database=directory.resolve() / "model-usage.sqlite3",
        cloud=cloud,
    )


def _usage_day(day: str | None) -> str:
    if day is None:
        return datetime.now(timezone.utc).date().isoformat()
    try:
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError:
        raise ValueError("Model usage requires a canonical UTC date (YYYY-MM-DD).") from None
    return day


def read_model_usage(day: str | None = None, *, limits: ModelLimits | None = None) -> dict:
    """Read one UTC day's aggregate without creating, repairing or incrementing state.

    An absent database is not evidence of zero usage. An existing valid table with
    no row for the requested day does mean zero. Only the configured rollback-mode
    counter is supported: WAL reads may create shared-memory sidecars, so reject
    that format rather than opening it or ignoring its possibly uncheckpointed data.
    Results contain no paths, configuration values, records or raw error details.
    """
    selected_day = _usage_day(day)
    unavailable = {"status": "unavailable", "day": selected_day, "calls": None}
    try:
        database = (limits or load_model_limits()).database
        try:
            metadata = database.lstat()
        except FileNotFoundError:
            return {"status": "not_initialized", "day": selected_day, "calls": None}
        if not stat.S_ISREG(metadata.st_mode) or not 100 <= metadata.st_size <= _MAX_USAGE_DATABASE_BYTES:
            return unavailable
        with database.open("rb") as source:
            header = source.read(20)
        if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
            return unavailable
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1.0)) as connection:
            connection.execute("PRAGMA query_only=ON")
            # Bound work even if the persisted schema has been replaced by a view
            # or lost its index; never inspect unrelated rows as an alternative.
            connection.set_progress_handler(lambda: 1, 10_000)
            if connection.execute("SELECT type FROM sqlite_schema WHERE name = 'daily_calls'").fetchone() != ("table",):
                return unavailable
            columns = connection.execute("PRAGMA table_info(daily_calls)").fetchall()
            if [(item[1], item[2].upper(), item[3], item[5]) for item in columns] != [
                ("day", "TEXT", 0, 1),
                ("calls", "INTEGER", 1, 0),
            ]:
                return unavailable
            row = connection.execute("SELECT calls FROM daily_calls WHERE day = ?", (selected_day,)).fetchone()
        if row is None:
            return {"status": "ready", "day": selected_day, "calls": 0}
        if type(row[0]) is int and row[0] >= 0:
            return {"status": "ready", "day": selected_day, "calls": row[0]}
    except (OSError, sqlite3.Error, DeploymentConfigurationError, ValueError):
        pass
    return unavailable


def _emit_usage_event(phase: str, snapshot: dict) -> None:
    # Fixed fields only. Observability must not fail a request after its allowance
    # has already been committed (for example when stdout is closing on shutdown).
    event = {"event": "model_usage", "schema_version": 1, "phase": phase, **snapshot}
    try:
        print(json.dumps(event, sort_keys=True), flush=True)
    except (OSError, ValueError):
        pass


def emit_model_usage_snapshot(day: str | None = None) -> None:
    """Emit a cloud startup's selected UTC-day aggregate to private runtime logs.

    Explicit dates support a same-day comparison across a midnight deployment;
    they do not change the day charged by real model calls.
    """
    try:
        limits = load_model_limits()
    except DeploymentConfigurationError:
        return
    if limits.cloud:
        _emit_usage_event("startup", read_model_usage(day, limits=limits))


def _consume_daily_call(limits: ModelLimits) -> None:
    if not limits.daily_calls:
        return
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        limits.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(limits.database, timeout=5.0)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS daily_calls (day TEXT PRIMARY KEY, calls INTEGER NOT NULL)")
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT calls FROM daily_calls WHERE day = ?", (today,)).fetchone()
            count = row[0] if row else 0
            if not isinstance(count, int) or not 0 <= count < 2**63 - 1:
                raise ModelAllowanceError("The model usage counter is invalid. Contact the project owner.")
            if count >= limits.daily_calls:
                raise ModelAllowanceError(
                    "The shared daily model-call allowance has been reached. Retry after 00:00 UTC."
                )
            connection.execute(
                "INSERT INTO daily_calls(day, calls) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET calls = calls + 1",
                (today,),
            )
    except (OSError, sqlite3.Error) as error:
        raise ModelAllowanceError(
            "Model requests are paused because the persistent usage counter is unavailable."
        ) from error
    if limits.cloud:
        # The connection context committed before this event. It records the
        # admitted HTTP attempt, not a successful provider response or token cost.
        _emit_usage_event("call_committed", {"status": "ready", "day": today, "calls": count + 1})


class ModelRequestSlot:
    def __init__(self, limits: ModelLimits, *, counted: bool):
        self.limits = limits
        self._counted = counted
        self._released = False

    def consume_call(self) -> None:
        _consume_daily_call(self.limits)

    def release(self) -> None:
        global _ACTIVE_REQUESTS
        with _ACTIVE_LOCK:
            if not self._released:
                if self._counted:
                    _ACTIVE_REQUESTS -= 1
                self._released = True


def acquire_model_slot() -> ModelRequestSlot:
    global _ACTIVE_REQUESTS
    limits = load_model_limits()
    with _ACTIVE_LOCK:
        if limits.concurrency and _ACTIVE_REQUESTS >= limits.concurrency:
            raise ModelAllowanceError(
                "The shared model service is busy. Wait for the active request to finish and retry."
            )
        # Count all requests in the process, including ones admitted before a configuration change.
        _ACTIVE_REQUESTS += 1
    return ModelRequestSlot(limits, counted=True)
