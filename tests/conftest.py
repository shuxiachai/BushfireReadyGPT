import pytest


@pytest.fixture(autouse=True)
def _disable_workstation_rag_index(monkeypatch):
    """Keep tests independent of a developer's optional local RAG index."""

    monkeypatch.setenv("BUSHFIRE_RAG_ENABLED", "false")
