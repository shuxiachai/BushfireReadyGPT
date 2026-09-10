"""Process-wide concurrency and persistent daily model-request allowances.

Counters measure HTTP completion attempts, including structural repairs. They
are not token or currency budgets. A timed-out worker keeps its slot until it
actually finishes, so reconnecting a browser cannot bypass concurrency limits.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.deployment_access import DeploymentConfigurationError, deployment_mode

_ACTIVE_LOCK = threading.Lock()
_ACTIVE_REQUESTS = 0


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
            if not isinstance(count, int) or count < 0:
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
