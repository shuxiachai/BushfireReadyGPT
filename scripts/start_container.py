"""Validate the deployment, initialize its volume, and execute Streamlit."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.container_runtime import initialize_volume_permissions, prepare_runtime, streamlit_command  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
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
    if not args.check_only:
        os.chdir(PROJECT_ROOT)
        # Fixed interpreter/argument list, with a validated numeric port; no shell.
        os.execv(sys.executable, streamlit_command(result["port"]))  # nosec B606
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
