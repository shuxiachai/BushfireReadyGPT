import pytest


@pytest.fixture(autouse=True)
def _isolate_optional_workstation_state(monkeypatch, tmp_path):
    """Keep tests independent of developer-local RAG and runtime Trace files."""

    monkeypatch.setenv("BUSHFIRE_RAG_ENABLED", "false")
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "false")
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(tmp_path / "runtime-traces"))
