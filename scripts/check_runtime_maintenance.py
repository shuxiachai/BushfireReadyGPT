"""Read-only runtime checks; no dotenv loading, provider calls, repair or writes.

Run with ``python -B scripts/check_runtime_maintenance.py --day YYYY-MM-DD``
inside the service. The default persistent-root contract is the image's /data
mount; isolated candidates must supply their own --persistent-root. Containment
does not prove a directory is mounted, durable, backed up or large enough.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.deployment_access import DeploymentConfigurationError  # noqa: E402
from src.model_limits import load_model_limits, read_model_usage  # noqa: E402


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes bad values, which may contain a private path
        # or an accidentally pasted credential. Never render user input.
        self.exit(2, '{"status": "invalid_arguments"}\n')


def _day(value):
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except (TypeError, ValueError):
        pass
    raise argparse.ArgumentTypeError("Use a canonical UTC date.")


def _nonnegative(value):
    try:
        number = int(value)
        if number >= 0:
            return number
    except (TypeError, ValueError):
        pass
    raise argparse.ArgumentTypeError("Use a non-negative integer.")


def _model_integer(values, name, default, *, minimum):
    # Match config._positive_number's integer/blank semantics without importing
    # config: importing it loads dotenv and constructs a provider client.
    raw = values.get(name, "").strip()
    value = int(raw) if raw else default
    if value < minimum:
        raise ValueError("Invalid numeric setting.")
    return value


def maintenance_snapshot(*, day=None, persistent_root="/data", minimum_calls=None, environ=None):
    """Return (safe aggregate, exit code), observing only the selected UTC day.

    minimum_calls is an operator-supplied, independently retained high-water
    mark for that same day. It detects rollback; it never reconciles counters.
    This does not establish atomicity with concurrent service writes.
    """
    values = os.environ if environ is None else environ
    selected_day = _day(day) if day is not None else datetime.now(timezone.utc).date().isoformat()
    if minimum_calls is not None and (type(minimum_calls) is not int or minimum_calls < 0):
        raise ValueError("Invalid minimum call count.")
    try:
        limits = load_model_limits(values)
        root = Path(persistent_root).expanduser().resolve()
        runtime = limits.database.parent
        audit_override = values.get("BUSHFIRE_AUDIT_DIR", "").strip()
        trace_override = values.get("BUSHFIRE_TRACE_DIR", "").strip()
        audit = Path(audit_override).expanduser().resolve() if audit_override else (runtime / "audit").resolve()
        traces = Path(trace_override).expanduser().resolve() if trace_override else (runtime / "traces").resolve()
        model_max_tokens = _model_integer(values, "BUSHFIRE_MODEL_MAX_TOKENS", 2300, minimum=1)
        retries = _model_integer(values, "BUSHFIRE_MODEL_MAX_RETRIES", 1, minimum=0)
        snapshot = {
            "cloud": limits.cloud,
            "concurrency": limits.concurrency,
            "daily_call_limit": limits.daily_calls,
            "model_max_tokens": model_max_tokens,
            # GovernedModelClient overrides the configured retry count when
            # admission limits are enabled: one reservation = one HTTP attempt.
            "sdk_max_retries": 0 if limits.enabled else retries,
            "audit_within_persistent_root": audit.is_relative_to(root),
            "trace_within_persistent_root": traces.is_relative_to(root),
            "quota_within_persistent_root": limits.database.resolve().is_relative_to(root),
            **read_model_usage(selected_day, limits=limits),
        }
    except (DeploymentConfigurationError, OSError, RuntimeError, TypeError, ValueError):
        return {"status": "invalid_configuration"}, 2
    valid = snapshot["status"] == "ready" and all(
        snapshot[name]
        for name in ("audit_within_persistent_root", "trace_within_persistent_root", "quota_within_persistent_root")
    )
    if minimum_calls is not None:
        snapshot["minimum_calls_met"] = snapshot["calls"] is not None and snapshot["calls"] >= minimum_calls
        valid = valid and snapshot["minimum_calls_met"]
    return snapshot, 0 if valid else 1


def main(argv=None):
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--day", type=_day, help="Selected UTC day (YYYY-MM-DD); default: today in UTC.")
    parser.add_argument("--persistent-root", default="/data", help="Expected persistent mount root (default: /data).")
    parser.add_argument(
        "--minimum-calls", type=_nonnegative, help="Reject a count below this same-day high-water mark."
    )
    args = parser.parse_args(argv)
    snapshot, code = maintenance_snapshot(
        day=args.day, persistent_root=args.persistent_root, minimum_calls=args.minimum_calls
    )
    print(json.dumps(snapshot, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
