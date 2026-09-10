"""Prepare a bounded, ignored local corpus bundle; never download or upload sources."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.corpus_bundle import (  # noqa: E402
    CorpusBundleError,
    create_test_corpus_bundle,
    install_corpus_bundle,
    package_private_corpus,
    validate_corpus_bundle,
)
from src.rag.errors import RagError  # noqa: E402
from src.rag.settings import RagSettings  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "output" / "private-corpus")
    parser.add_argument(
        "--acknowledge-source-terms",
        action="store_true",
        help="Acknowledge original source terms for this local private-research snapshot; this grants no rights.",
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--test-fixture", action="store_true", help="Create synthetic, non-official public-CI test data."
    )
    actions.add_argument("--validate", type=Path, metavar="BUNDLE", help="Validate an existing bundle without changes.")
    actions.add_argument(
        "--install", type=Path, metavar="BUNDLE", help="Install a verified bundle at a new --output path."
    )
    args = parser.parse_args(argv)
    try:
        if args.validate:
            manifest = validate_corpus_bundle(args.validate)
        elif args.install:
            installed = install_corpus_bundle(args.install, args.output)
            manifest = validate_corpus_bundle(installed)
        elif args.test_fixture:
            manifest = create_test_corpus_bundle(args.output)
        else:
            load_dotenv(PROJECT_ROOT / ".env")
            manifest = package_private_corpus(
                RagSettings.from_env(),
                args.output,
                acknowledge_source_terms=args.acknowledge_source_terms,
            )
    except (CorpusBundleError, RagError, OSError) as error:
        print(f"Private corpus preparation failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "validated" if args.validate else "ready",
                "source_count": manifest["source_count"],
                "fixture_only": manifest["fixture_only"],
                "manifest_sha256": manifest["manifest_sha256"],
                "payload_size_bytes": manifest["payload_size_bytes"],
                "uploaded": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
