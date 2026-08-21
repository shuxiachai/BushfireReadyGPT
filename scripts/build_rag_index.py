"""Download the declared static preparedness corpus and build the local RAG index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.corpus import download_catalog_sources, load_source_catalog  # noqa: E402
from src.rag.embeddings import OllamaEmbeddingClient  # noqa: E402
from src.rag.errors import RagError  # noqa: E402
from src.rag.index import build_rag_index  # noqa: E402
from src.rag.settings import RagSettings  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download missing declared sources before indexing.")
    parser.add_argument("--refresh", action="store_true", help="Re-download every declared source before indexing.")
    parser.add_argument("--max-words", type=int, default=420)
    parser.add_argument("--overlap-words", type=int, default=60)
    args = parser.parse_args()

    try:
        settings = RagSettings.from_env()
        catalog = load_source_catalog(settings.sources_path, rag_dir=settings.rag_dir)
        if args.download or args.refresh:
            download_catalog_sources(catalog, force=args.refresh)
        embedder = OllamaEmbeddingClient(
            settings.embedding_base_url,
            settings.embedding_model,
            timeout_seconds=settings.embedding_timeout_seconds,
            batch_size=settings.embedding_batch_size,
        )
        manifest = build_rag_index(
            settings,
            embedder,
            max_words=args.max_words,
            overlap_words=args.overlap_words,
        )
    except RagError as error:
        print(f"RAG index build failed [{error.code}]: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "ready",
                "schema": manifest["schema"],
                "sources": manifest["source_count"],
                "chunks": manifest["chunk_count"],
                "embedding_model": manifest["embedding_model"],
                "embedding_dimension": manifest["embedding_dimension"],
                "manifest_sha256": manifest["manifest_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
