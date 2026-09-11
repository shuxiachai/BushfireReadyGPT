"""Private exports never register bytes in Streamlit's unauthenticated media store."""

import ast
import base64
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from streamlit.runtime.media_file_manager import MediaFileManager
from streamlit.testing.v1 import AppTest

from src import deployment_access as access
from src.ui import downloads

PASSWORD = "Controlled-download-demo-2026-password"
ROTATED_PASSWORD = "Rotated-private-download-2026-password"
PRIVATE_TEXT = "PRIVATE-EXPORT-SENTINEL-4269: 私人报告"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in (
        "BUSHFIRE_DEPLOYMENT_MODE",
        "RAILWAY_ENVIRONMENT_ID",
        "RAILWAY_PROJECT_ID",
        "BUSHFIRE_ACCESS_PASSWORD",
        "BUSHFIRE_ACCESS_PASSWORD_HASH",
        "BUSHFIRE_ADMIN_PASSWORD",
        "BUSHFIRE_ADMIN_PASSWORD_HASH",
        "BUSHFIRE_SESSION_STATE_PATH",
        "BUSHFIRE_INTERACTION_LOG_PATH",
        "BUSHFIRE_MODEL_MAX_CONCURRENT",
        "BUSHFIRE_MODEL_DAILY_CALL_LIMIT",
        "BUSHFIRE_RUNTIME_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(access, "_LOGIN_ATTEMPTS", access.deque())


@pytest.fixture
def forbid_media_registration(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail("A protected download attempted to register public HTTP media.")

    monkeypatch.setattr(MediaFileManager, "add", forbidden)
    monkeypatch.setattr(MediaFileManager, "add_deferred", forbidden)
    return calls


def _protect(monkeypatch, tmp_path, mode="cloud"):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud" if mode.startswith("cloud") else "local")
    monkeypatch.setenv("BUSHFIRE_RUNTIME_DIR", str(tmp_path))
    if mode.endswith("hash"):
        monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD_HASH", access.hash_access_password(PASSWORD))
    else:
        monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", PASSWORD)


def _renderer(monkeypatch, state):
    renderer = SimpleNamespace(session_state=state, iframe=Mock(), download_button=Mock())
    monkeypatch.setattr(downloads, "st", renderer)
    return renderer


def _download(**kwargs):
    values = {
        "label": "Download private report",
        "data": PRIVATE_TEXT,
        "file_name": "private-report.md",
        "mime": "text/markdown",
    }
    values.update(kwargs)
    return downloads.download_button(**values)


class _Document(HTMLParser):
    def __init__(self, document):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.scripts = []
        self.current_script = None
        self.feed(document)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if tag == "script":
            self.current_script = {"attrs": attributes, "body": ""}
            self.scripts.append(self.current_script)

    def handle_endtag(self, tag):
        if tag == "script":
            self.current_script = None

    def handle_data(self, data):
        if self.current_script is not None:
            self.current_script["body"] += data

    @property
    def payload(self):
        encoded = next(row["body"] for row in self.scripts if row["attrs"].get("id") == "payload")
        return base64.b64decode(encoded, validate=True)


@pytest.mark.parametrize("mode", ["cloud", "cloud-hash", "local-password", "local-hash"])
def test_authenticated_delivery_is_inline_and_never_public_media(
    tmp_path,
    monkeypatch,
    mode,
    forbid_media_registration,
):
    _protect(monkeypatch, tmp_path, mode)
    state = {}
    access.authenticate(PASSWORD, state)
    renderer = _renderer(monkeypatch, state)
    result = _download(key="private-report")
    assert result is renderer.iframe.return_value
    renderer.download_button.assert_not_called()
    document = renderer.iframe.call_args.args[0]
    assert isinstance(document, str)
    assert _Document(document).payload == PRIVATE_TEXT.encode("utf-8")
    assert "/media/" not in document
    assert PRIVATE_TEXT not in document
    assert renderer.iframe.call_args.kwargs == {"height": "content", "width": "stretch", "tab_index": 0}
    assert forbid_media_registration == []


@pytest.mark.parametrize("mode", ["cloud", "cloud-hash", "local-password", "local-hash"])
def test_unauthenticated_calls_do_not_serialize_or_deliver_any_bytes(tmp_path, monkeypatch, mode):
    _protect(monkeypatch, tmp_path, mode)
    renderer = _renderer(monkeypatch, {})
    serializer = Mock(side_effect=AssertionError("Unauthorized data must never be serialized."))
    monkeypatch.setattr(downloads, "_private_download_html", serializer)
    with pytest.raises(access.AccessDeniedError, match="Sign in again"):
        _download(data=object())
    renderer.iframe.assert_not_called()
    renderer.download_button.assert_not_called()
    serializer.assert_not_called()


@pytest.mark.parametrize("change", ["expiry", "rotation", "token", "expiry_forgery", "other_session"])
def test_expired_rotated_or_forged_sessions_fail_closed(tmp_path, monkeypatch, change):
    _protect(monkeypatch, tmp_path)
    state = {}
    access.authenticate(PASSWORD, state)
    if change == "expiry":
        now = access.time.time()
        monkeypatch.setattr(access.time, "time", lambda: now + access._SESSION_SECONDS + 1)
    elif change == "rotation":
        monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", ROTATED_PASSWORD)
    elif change == "token":
        state[access._AUTH_KEY]["token"] = "forged"
    elif change == "expiry_forgery":
        state[access._AUTH_KEY]["expires_at"] += access._SESSION_SECONDS
    else:
        state = {}
    renderer = _renderer(monkeypatch, state)
    with pytest.raises(access.AccessDeniedError):
        _download()
    renderer.iframe.assert_not_called()
    renderer.download_button.assert_not_called()


@pytest.mark.parametrize(
    "settings",
    [
        {"BUSHFIRE_DEPLOYMENT_MODE": "unknown"},
        {"BUSHFIRE_ACCESS_PASSWORD": "weak"},
        {"BUSHFIRE_ACCESS_PASSWORD_HASH": "invalid hash"},
        {"BUSHFIRE_ACCESS_PASSWORD": PASSWORD, "BUSHFIRE_ACCESS_PASSWORD_HASH": "ambiguous"},
        {"RAILWAY_PROJECT_ID": "test-project", "BUSHFIRE_DEPLOYMENT_MODE": "local"},
    ],
)
def test_bad_authentication_configuration_never_selects_open_downloads(monkeypatch, settings):
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    renderer = _renderer(monkeypatch, {})
    with pytest.raises(access.DeploymentConfigurationError):
        _download()
    renderer.iframe.assert_not_called()
    renderer.download_button.assert_not_called()


def test_cloud_without_any_credential_still_cannot_fall_back_to_open_download(monkeypatch):
    monkeypatch.setenv("BUSHFIRE_DEPLOYMENT_MODE", "cloud")
    renderer = _renderer(monkeypatch, {})
    with pytest.raises(access.AccessDeniedError):
        _download()
    renderer.iframe.assert_not_called()
    renderer.download_button.assert_not_called()


def test_local_without_password_preserves_original_download_button(monkeypatch):
    renderer = _renderer(monkeypatch, {})
    callback = Mock()
    result = _download(key="legacy", width=320, on_click=callback)
    assert result is renderer.download_button.return_value
    renderer.download_button.assert_called_once_with(
        "Download private report",
        data=PRIVATE_TEXT,
        file_name="private-report.md",
        mime="text/markdown",
        width=320,
        key="legacy",
        on_click=callback,
    )
    renderer.iframe.assert_not_called()
    callback.assert_not_called()


@pytest.mark.parametrize("protected", [True, False])
def test_explicit_sidebar_target_preserves_location(tmp_path, monkeypatch, protected):
    state = {}
    if protected:
        _protect(monkeypatch, tmp_path)
        access.authenticate(PASSWORD, state)
    renderer = _renderer(monkeypatch, state)
    sidebar = SimpleNamespace(iframe=Mock(), download_button=Mock())
    _download(target=sidebar)
    renderer.iframe.assert_not_called()
    renderer.download_button.assert_not_called()
    if protected:
        sidebar.iframe.assert_called_once()
        sidebar.download_button.assert_not_called()
    else:
        sidebar.download_button.assert_called_once()
        sidebar.iframe.assert_not_called()


@pytest.mark.parametrize("mime", sorted(downloads._ALLOWED_MIME_TYPES))
def test_all_supported_binary_and_text_exports_round_trip(mime):
    payload = b"\x00\xff\xfePK\x03\x04</script><script>attack()</script>\n"
    document = downloads._private_download_html("下载", payload, "私人报告.bin", mime)
    parsed = _Document(document)
    assert parsed.payload == payload
    assert len(parsed.scripts) == 2
    assert not any("attack()" in row["body"] for row in parsed.scripts)
    button = next(attrs for tag, attrs in parsed.elements if tag == "button")
    assert button["data-mime"] == mime
    assert button["data-filename"] == "私人报告.bin"


def test_hostile_label_and_filename_cannot_escape_markup_or_executable_script():
    label = '</script><img src=x onerror="attack()"> & <script>attack()</script>'
    filename = 'report" autofocus onfocus="attack()\'.txt'
    document = downloads._private_download_html(label, "safe", filename, "text/plain")
    parsed = _Document(document)
    assert [tag for tag, _ in parsed.elements].count("script") == 2
    assert not any(tag == "img" for tag, _ in parsed.elements)
    button = next(attrs for tag, attrs in parsed.elements if tag == "button")
    assert button["data-filename"] == filename
    assert set(button) == {"id", "type", "data-filename", "data-mime", "aria-describedby"}
    assert not any("attack()" in row["body"] for row in parsed.scripts)
    assert parsed.payload == b"safe"
    assert "default-src 'none'" in document
    assert "base-uri 'none'" in document
    assert "form-action 'none'" in document


@pytest.mark.parametrize(
    "mime",
    [
        "text/html",
        "image/svg+xml",
        "application/javascript",
        "text/plain;charset=utf-8",
        'text/plain" onmouseover="attack()',
        "data:text/html",
        "",
        None,
    ],
)
def test_untrusted_or_executable_mime_is_rejected(mime):
    with pytest.raises(ValueError, match="format"):
        downloads._private_download_html("Download", b"data", "report.txt", mime)


@pytest.mark.parametrize(
    "filename",
    [
        "",
        " ",
        ".",
        "..",
        "../report.md",
        "..\\report.md",
        "/tmp/report.md",
        "C:\\report.md",
        "report.txt:stream",
        "report\nname.txt",
        "report\x00.txt",
        "report\x7f.txt",
        "x" * 241,
        None,
    ],
)
def test_unsafe_filename_is_rejected(filename):
    with pytest.raises(ValueError, match="filename"):
        downloads._private_download_html("Download", b"data", filename, "text/plain")


@pytest.mark.parametrize("label", ["", " ", "x" * 241, None, 123])
def test_invalid_label_is_rejected(label):
    with pytest.raises(ValueError, match="label"):
        downloads._private_download_html(label, b"data", "report.txt", "text/plain")


@pytest.mark.parametrize("data", [Path("private.pdf"), BytesIO(b"private"), lambda: b"private", memoryview(b"private")])
def test_paths_callbacks_and_unexpected_input_types_are_not_interpreted(data):
    with pytest.raises(ValueError, match="text or bytes"):
        downloads._private_download_html("Download", data, "report.txt", "text/plain")


def test_size_limit_counts_utf8_bytes_and_allows_exact_boundary(monkeypatch):
    assert downloads.MAX_PRIVATE_DOWNLOAD_BYTES == 8 * 1024 * 1024
    monkeypatch.setattr(downloads, "MAX_PRIVATE_DOWNLOAD_BYTES", 8)
    for payload in ("学学ab", b"12345678", b""):
        document = downloads._private_download_html("Download", payload, "report.txt", "text/plain")
        expected = payload.encode("utf-8") if isinstance(payload, str) else payload
        assert _Document(document).payload == expected
    for payload in ("学学学", "123456789", b"123456789"):
        with pytest.raises(ValueError, match="limit"):
            downloads._private_download_html("Download", payload, "report.txt", "text/plain")


def test_feedback_is_accessible_and_keeps_the_existing_private_delivery_boundary():
    document = _Document(downloads._private_download_html("Download", PRIVATE_TEXT, "report.md", "text/markdown"))
    elements = {attrs.get("id"): attrs for _tag, attrs in document.elements if attrs.get("id")}
    assert elements["download"]["aria-describedby"] == "download-status"
    assert elements["download-status"]["role"] == "status"
    assert elements["download-status"]["aria-live"] == "polite"
    assert elements["download-status"]["aria-atomic"] == "true"
    assert document.payload == PRIVATE_TEXT.encode("utf-8")
    csp = next(attrs["content"] for tag, attrs in document.elements if tag == "meta" and "http-equiv" in attrs)
    assert "default-src 'none'" in csp
    assert "script-src 'unsafe-inline'" in csp
    assert "connect-src" not in csp


def test_authenticated_oversized_or_callback_exports_deliver_nothing(tmp_path, monkeypatch):
    _protect(monkeypatch, tmp_path)
    state = {}
    access.authenticate(PASSWORD, state)
    renderer = _renderer(monkeypatch, state)
    callback = Mock()
    with pytest.raises(ValueError, match="callbacks"):
        _download(on_click=callback)
    monkeypatch.setattr(downloads, "MAX_PRIVATE_DOWNLOAD_BYTES", 1)
    with pytest.raises(ValueError, match="limit"):
        _download()
    callback.assert_not_called()
    renderer.iframe.assert_not_called()
    renderer.download_button.assert_not_called()


APP = f"""
import streamlit as st
from src.deployment_access import render_access_gate
from src.ui.downloads import download_button
if render_access_gate():
    download_button('Private report', {PRIVATE_TEXT!r}, '私人报告.md', 'text/markdown')
    download_button('Private sidebar', {PRIVATE_TEXT!r}, '私人报告.json', 'application/json', target=st.sidebar)
"""


@pytest.mark.parametrize("mode", ["cloud", "local-password", "local-hash"])
def test_apptest_real_login_delivers_srcdoc_and_isolates_anonymous_session(
    tmp_path,
    monkeypatch,
    mode,
    forbid_media_registration,
):
    _protect(monkeypatch, tmp_path, mode)
    app = AppTest.from_string(APP).run()
    assert not app.exception
    assert not app.get("iframe")
    assert not app.get("download_button")
    app.text_input[0].input(PASSWORD).run()
    app.button[0].click().run()
    assert not app.exception
    assert len(app.get("iframe")) == 2
    assert len(app.sidebar.get("iframe")) == 1
    for iframe in app.get("iframe"):
        assert not iframe.proto.src
        assert _Document(iframe.proto.srcdoc).payload == PRIVATE_TEXT.encode("utf-8")
    assert not app.get("download_button")
    assert PASSWORD not in repr(app.session_state.filtered_state)
    other = AppTest.from_string(APP).run()
    assert not other.exception
    assert not other.get("iframe")
    assert not other.get("download_button")
    assert other.text_input[0].label == "Access password"
    assert forbid_media_registration == []


@pytest.mark.parametrize("change", ["expiry", "rotation"])
def test_apptest_rerun_after_expiry_or_rotation_does_not_redeliver(
    tmp_path,
    monkeypatch,
    change,
    forbid_media_registration,
):
    _protect(monkeypatch, tmp_path)
    app = AppTest.from_string(APP).run()
    app.text_input[0].input(PASSWORD).run()
    app.button[0].click().run()
    assert len(app.get("iframe")) == 2
    if change == "rotation":
        monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", ROTATED_PASSWORD)
    else:
        now = access.time.time()
        monkeypatch.setattr(access.time, "time", lambda: now + access._SESSION_SECONDS + 1)
    app.run()
    assert not app.exception
    assert not app.get("iframe")
    assert not app.get("download_button")
    assert app.text_input[0].label == "Access password"
    assert forbid_media_registration == []


def test_apptest_invalid_credentials_do_not_render_private_downloads(monkeypatch, forbid_media_registration):
    monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD_HASH", "malformed")
    app = AppTest.from_string(APP).run()
    assert not app.exception
    assert app.error
    assert not app.get("iframe")
    assert not app.get("download_button")
    assert forbid_media_registration == []


def test_ui_cannot_bypass_the_shared_download_helper():
    violations = []
    for path in (ROOT / "src").rglob("*.py"):
        if path == ROOT / "src" / "ui" / "downloads.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"download_button", "_download_button"}:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("streamlit"):
                if any(alias.name in {"download_button", "_download_button"} for alias in node.names):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, "Direct Streamlit downloads bypass private-session delivery: " + ", ".join(violations)
