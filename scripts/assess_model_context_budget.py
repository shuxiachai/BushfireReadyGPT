"""Read an explicitly named local JSON request and print an offline assessment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.model_context_budget import assess_model_context_budget  # noqa: E402

_REQUEST_FIELDS = {
    "messages",
    "model_digest",
    "template_sha256",
    "context_tokens",
    "requested_output_tokens",
    "margin_tokens",
    "exact_count",
}


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # Parser diagnostics can otherwise echo private paths or pasted data.
        self.exit(2, "assessment error: invalid_arguments\n")


def main(argv=None):
    parser = _SafeParser(
        prog="assess_model_context_budget.py",
        description="Assess a supplied offline prompt token measurement.",
        allow_abbrev=False,
    )
    parser.add_argument("input_json", help="Path to a local JSON object containing assessor keyword arguments.")
    args = parser.parse_args(argv)
    try:
        with Path(args.input_json).open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if type(payload) is not dict or set(payload) - _REQUEST_FIELDS:
            raise ValueError("Invalid request fields.")
        result = assess_model_context_budget(**payload)
    except (OSError, TypeError, ValueError, RecursionError):
        print("assessment error: invalid_input", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
