from unittest.mock import MagicMock

from src.runtime_trace import RuntimeTrace
from src.ui import diagnostic_views


def _mock_streamlit(monkeypatch):
    streamlit = MagicMock()
    streamlit.columns.return_value = [MagicMock() for _ in range(4)]
    monkeypatch.setattr(diagnostic_views, "st", streamlit)
    return streamlit


def test_runtime_diagnostics_is_empty_in_an_isolated_test_environment(monkeypatch):
    streamlit = _mock_streamlit(monkeypatch)

    diagnostic_views.render_runtime_diagnostics()

    streamlit.info.assert_called_once_with(
        "No local runtime Trace has been recorded yet. Generate or revise a report to create one."
    )
    streamlit.warning.assert_not_called()
    streamlit.columns.assert_not_called()


def test_runtime_diagnostics_renders_valid_trace_summary(tmp_path, monkeypatch):
    trace_dir = tmp_path / "runtime-traces"
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(trace_dir))
    monkeypatch.setenv("BUSHFIRE_TRACE_ENABLED", "true")
    with RuntimeTrace("report.generate") as trace:
        with trace.stage("model_generation", attempt=1):
            pass
        trace.add_metrics(repair_required=False, grounding_status="review_required")
        trace.set_outcome("success")
    streamlit = _mock_streamlit(monkeypatch)

    diagnostic_views.render_runtime_diagnostics()

    columns = streamlit.columns.return_value
    streamlit.columns.assert_called_once_with(4)
    columns[0].metric.assert_called_once_with("Traces", 1)
    columns[1].metric.assert_called_once_with("Success rate", "100.0%")
    assert columns[2].metric.call_args.args[0] == "P50 duration"
    assert columns[3].metric.call_args.args[0] == "P95 duration"
    assert any("**Grounding review rate:** 100.0%" in call.args[0] for call in streamlit.markdown.call_args_list)
    streamlit.dataframe.assert_called_once()


def test_runtime_diagnostics_reports_malformed_trace_file(tmp_path, monkeypatch):
    trace_dir = tmp_path / "runtime-traces"
    trace_dir.mkdir()
    (trace_dir / "trace_broken.json").write_text('{"schema": "wrong"}', encoding="utf-8")
    monkeypatch.setenv("BUSHFIRE_TRACE_DIR", str(trace_dir))
    streamlit = _mock_streamlit(monkeypatch)

    diagnostic_views.render_runtime_diagnostics()

    streamlit.info.assert_called_once()
    streamlit.warning.assert_called_once_with("Ignored malformed Trace files: 1")
    streamlit.columns.assert_not_called()
