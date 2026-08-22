"""Run the deterministic report grounding review against a narrative and frozen analysis JSON."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.report_grounding import evaluate_report_grounding  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSON with narrative and analysis fields.")
    parser.add_argument("--output", type=Path, help="Optional destination for the evaluation JSON.")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Grounding input could not be loaded: {error}") from error
    if set(payload) - {"narrative", "analysis", "thresholds"} or not isinstance(payload.get("analysis"), dict):
        raise SystemExit("Grounding input must contain narrative and analysis, with optional thresholds.")
    result = evaluate_report_grounding(
        payload.get("narrative", ""),
        payload["analysis"],
        thresholds=payload.get("thresholds"),
    )
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not result["review_required"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
