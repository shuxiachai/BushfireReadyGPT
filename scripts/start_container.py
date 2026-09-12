"""Validate the deployment, initialize its volume, and execute Streamlit."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.container_runtime import initialize_volume_permissions, prepare_runtime, streamlit_command  # noqa: E402
from src.model_limits import emit_model_usage_snapshot  # noqa: E402


def _observation_day(value):
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Use one UTC date in YYYY-MM-DD format.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--observe-usage-day",
        type=_observation_day,
        help="Additionally read one historical UTC day's aggregate quota into private startup logs; never modifies it.",
    )
    args = parser.parse_args()
    try:
        initialize_volume_permissions()
        result = prepare_runtime()
    except Exception as error:
        # Provider SDK exceptions can include URLs and request details. Keep startup
        # output limited to known-safe configuration errors or the exception type.
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        print(f"Container startup failed: {message}", file=sys.stderr)
        return 1
    print(json.dumps({"container_ready": True, **result}), flush=True)
    emit_model_usage_snapshot()
    if args.observe_usage_day:
        emit_model_usage_snapshot(args.observe_usage_day)
    if not args.check_only:
        os.chdir(PROJECT_ROOT)
        # Fixed interpreter/argument list, with a validated numeric port; no shell.
        os.execv(sys.executable, streamlit_command(result["port"]))  # nosec B606
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
