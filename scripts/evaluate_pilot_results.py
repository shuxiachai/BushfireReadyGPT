"""Validate anonymous controlled-pilot records and calculate reproducible aggregate metrics."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pilot_evaluation import PilotEvaluationError, summarise_pilot_payload  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "docs" / "pilot_evaluation_template.json",
        help="Anonymous pilot JSON. Raw notes and personal data must remain outside Git.",
    )
    parser.add_argument("--output", type=Path, help="Optional destination for the aggregate JSON summary.")
    args = parser.parse_args()

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        summary = summarise_pilot_payload(payload)
    except (OSError, json.JSONDecodeError, PilotEvaluationError) as error:
        code = getattr(error, "code", error.__class__.__name__)
        raise SystemExit(f"Pilot evaluation failed ({code}): {error}") from error

    rendered = json.dumps(summary, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
