import pytest
from streamlit.testing.v1 import AppTest

from src.rag.service import _status
from src.ui import components, data_views, report_views, review_views, sidebar


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/data/private-account/index/manifest.json", "manifest.json"),
        (r"C:\Users\private-account\reports\draft.json", "draft.json"),
        (r"\\private-server\reports\draft.json", "draft.json"),
        ("filename.json", "filename.json"),
        (None, "N/A"),
        ("", "N/A"),
        ("/", "N/A"),
        ("C:\\", "N/A"),
    ],
)
def test_cloud_path_display_omits_parent_directories(path, expected, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    assert components.safe_display_path(path) == expected


def test_invalid_deployment_mode_does_not_reveal_private_path(monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "invalid")
    assert components.safe_display_path("/data/private-account/file.json") == "file.json"
    assert "private-account" not in components.safe_diagnostic_detail("Could not load /data/private-account/file.json")


def test_local_path_and_exception_details_remain_available(monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "local")
    monkeypatch.delenv("RAILWAY_PROJECT_ID", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    path = r"C:\Users\private-account\reports\draft.json"
    detail = f"Cannot read {path}: file missing"
    assert components.safe_display_path(path) == path
    assert components.safe_diagnostic_detail(detail) == detail


def _data_status():
    status = {
        key: "Not available"
        for key in (
            "core_status",
            "optional_map_status",
            "integrity_status",
            "active_type",
            "freshness",
            "source_period",
            "updated_at",
            "raw_updated_at",
            "downloaded_at_utc",
            "asgs_updated_at",
            "asgs_generated_at_utc",
        )
    }
    status.update(
        {
            "manifest_path": "/data/private-account/manifest.json",
            "active_path": "/data/private-account/profiles.csv",
            "raw_path": "/data/private-account/raw.json",
            "asgs_metadata_path": "/data/private-account/metadata.json",
            "integrity_error": "Could not read /data/private-account/integrity-private-file",
            "optional_map_error": "Could not read /data/private-account/map-private-file",
            "verified_artifact_count": 0,
            "row_count": 0,
            "latest_source_year": None,
            "freshness_assessed_for_year": 2026,
            "asgs_exists": False,
            "locations": [],
            "source_query_url": "",
            "limitations": [],
        }
    )
    return status


@pytest.mark.parametrize("mode", ["local", "cloud"])
def test_rendered_data_rag_and_network_errors_follow_deployment_privacy(mode, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", mode)
    monkeypatch.delenv("RAILWAY_PROJECT_ID", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    monkeypatch.setattr(data_views, "get_community_data_status", _data_status)
    monkeypatch.setattr(
        data_views,
        "inspect_rag_index",
        lambda: _status("invalid", "RAG index invalid", error="Unable to open /data/private-account/rag-private-file"),
    )
    app = AppTest.from_string(
        """
import streamlit as st
from src.ui.data_views import render_data_status, render_rag_status, render_official_status_panel
st.session_state.official_status_result = {
    'rows': [{'name': 'Official source', 'status': 'Check failed',
              'message': 'SSL error reading /data/private-account/private-ca.pem'}]
}
render_data_status()
render_rag_status()
render_official_status_panel()
"""
    ).run()
    assert not app.exception
    markdown = "\n".join(item.value for item in app.markdown)
    warnings = "\n".join(item.value for item in app.warning)
    table = str(app.dataframe[0].value.to_dict())
    assert "metadata.json" in markdown
    if mode == "cloud":
        assert "private-account" not in markdown + warnings + table
        assert "integrity-private-file" not in markdown
        assert "map-private-file" not in markdown
        assert "rag-private-file" not in warnings
        assert "private-ca.pem" not in table
        assert "Bundled data verification failed" in markdown
        assert "project owner" in warnings
        assert "Open the official page directly" in table
    else:
        assert "/data/private-account/metadata.json" in markdown
        assert "integrity-private-file" in markdown
        assert "map-private-file" in markdown
        assert "rag-private-file" in warnings
        assert "private-ca.pem" in table


def test_cloud_file_labels_still_escape_html(monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    app = AppTest.from_string(
        """
from src.ui.components import render_path_line
render_path_line('<script>label</script>', '/data/private-account/<file>.json')
"""
    ).run()
    assert not app.exception
    html = app.markdown[0].value
    assert "&lt;file&gt;.json" in html
    assert "&lt;script&gt;label&lt;/script&gt;" in html
    assert "<script>" not in html
    assert "private-account" not in html


@pytest.mark.parametrize("mode", ["local", "cloud"])
@pytest.mark.parametrize("view", ["preview", "sidebar", "package"])
def test_export_and_save_errors_do_not_disclose_host_details(mode, view, monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", mode)
    monkeypatch.delenv("RAILWAY_PROJECT_ID", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)

    def unavailable(*_args, **_kwargs):
        raise OSError("Could not access /data/private-account/internal-secret-artifact")

    for module in (report_views, sidebar):
        monkeypatch.setattr(module, "get_report_artifact", unavailable)
        monkeypatch.setattr(module, "download_button", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sidebar, "evaluate_governed_report", lambda *_args: {"approval_gate": {"passed": True}})
    monkeypatch.setattr(review_views, "create_pilot_export_package", unavailable)
    app = AppTest.from_string(
        """
import streamlit as st
from src.ui.report_views import render_latest_report_preview
from src.ui.sidebar import render_sidebar
from src.ui.review_views import render_pilot_export_package
st.session_state.latest_report = {'quality': {'approval_gate': {'passed': True}}}
def save():
    raise OSError('Could not access /data/private-account/internal-secret-artifact')
"""
        + {
            "preview": "render_latest_report_preview(lambda: 'Synthetic report', save, lambda _: True)",
            "sidebar": "render_sidebar(lambda: None, lambda: 'Synthetic report', save, lambda _: True)",
            "package": "render_pilot_export_package(lambda: 'Synthetic report', lambda: {}, lambda: {})",
        }[view]
    ).run()
    if view != "package":
        next(button for button in app.button if button.label.startswith("Save ")).click().run()
    assert not app.exception
    warnings = "\n".join(item.value for item in app.warning)
    assert "failed" in warnings
    if mode == "cloud":
        assert "private-account" not in warnings
        assert "internal-secret-artifact" not in warnings
    else:
        assert "private-account" in warnings
