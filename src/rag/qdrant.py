"""Compatibility helpers for Qdrant's embedded SQLite backend."""

from __future__ import annotations

import sqlite3

from src.rag.errors import RagError


def load_qdrant():
    try:
        from qdrant_client import QdrantClient, models
    except ImportError as error:
        raise RagError("rag_dependency_missing", "qdrant-client is not installed.") from error

    try:
        from qdrant_client.local.persistence import CollectionPersistence
    except ImportError:
        pass
    else:
        if CollectionPersistence.CHECK_SAME_THREAD is None:
            # qdrant-client probes SQLite with a temporary connection that its
            # current Python 3.13 path does not close. Python already exposes
            # the same compile-time thread-safety result without opening it.
            CollectionPersistence.CHECK_SAME_THREAD = sqlite3.threadsafety != 3
    return QdrantClient, models
