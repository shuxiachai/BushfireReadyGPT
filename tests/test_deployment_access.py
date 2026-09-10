from types import SimpleNamespace

import pytest

from src import deployment_access as access

PASSWORD = "Controlled-demo-2026-password"
ADMIN_PASSWORD = "Independent-admin-2026-password"


@pytest.fixture(autouse=True)
def _isolated_deployment_environment(monkeypatch):
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
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(access, "_LOGIN_ATTEMPTS", access.deque())


def _cloud_environment(tmp_path):
    return {
        "BUSHFIRE_DEPLOYMENT_MODE": "cloud",
        "BUSHFIRE_RUNTIME_DIR": str(tmp_path),
        "BUSHFIRE_ACCESS_PASSWORD": PASSWORD,
    }


def test_local_access_defaults_to_open_without_writing_runtime_files(tmp_path):
    access.validate_deployment_settings({})
    assert access.is_access_authorized({})
    assert access.is_admin_session({})
    assert list(tmp_path.iterdir()) == []


def test_railway_is_cloud_and_cannot_downgrade_to_local():
    assert access.deployment_mode({"RAILWAY_ENVIRONMENT_ID": "test"}) == "cloud"
    with pytest.raises(access.DeploymentConfigurationError, match="Railway deployments"):
        access.deployment_mode({"RAILWAY_PROJECT_ID": "test", "BUSHFIRE_DEPLOYMENT_MODE": "local"})
    with pytest.raises(access.DeploymentConfigurationError, match="local or cloud"):
        access.deployment_mode({"BUSHFIRE_DEPLOYMENT_MODE": "clod"})


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("BUSHFIRE_ACCESS_PASSWORD", "", "Cloud access requires"),
        ("BUSHFIRE_ACCESS_PASSWORD", "password", "16–1024"),
        ("BUSHFIRE_ACCESS_PASSWORD", "a" * 30, "distinct"),
        ("BUSHFIRE_RUNTIME_DIR", "", "persistent volume"),
        ("BUSHFIRE_SESSION_STATE_PATH", "/data/session.json", "isolate browser sessions"),
        ("BUSHFIRE_INTERACTION_LOG_PATH", "/data/history.json", "isolate browser sessions"),
        ("BUSHFIRE_MODEL_MAX_CONCURRENT", "0", "positive"),
        ("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "0", "positive"),
        ("BUSHFIRE_MODEL_DAILY_CALL_LIMIT", "bad", "integer"),
        ("BUSHFIRE_ADMIN_PASSWORD", "weak", "16–1024"),
    ],
)
def test_cloud_bad_configuration_fails_closed(tmp_path, name, value, message):
    values = _cloud_environment(tmp_path)
    values[name] = value
    with pytest.raises(access.DeploymentConfigurationError, match=message):
        access.validate_deployment_settings(values)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "encoded",
    [
        "not-a-password-hash",
        "pbkdf2_sha256$1$" + "ab" * 16 + "$" + "ab" * 32,
        "pbkdf2_sha256$9000000$" + "ab" * 16 + "$" + "ab" * 32,
        "md5$600000$" + "ab" * 16 + "$" + "ab" * 32,
        "pbkdf2_sha256$600000$zz$" + "ab" * 32,
    ],
)
def test_bad_hash_never_falls_back_to_open_access(tmp_path, encoded):
    values = _cloud_environment(tmp_path)
    values.pop("BUSHFIRE_ACCESS_PASSWORD")
    values["BUSHFIRE_ACCESS_PASSWORD_HASH"] = encoded
    with pytest.raises(access.DeploymentConfigurationError, match="valid PBKDF2"):
        access.validate_deployment_settings(values)


def test_valid_password_hash_authenticates_without_storing_a_password(tmp_path, monkeypatch):
    hashed = access.hash_access_password(PASSWORD)
    values = _cloud_environment(tmp_path)
    values.pop("BUSHFIRE_ACCESS_PASSWORD")
    values["BUSHFIRE_ACCESS_PASSWORD_HASH"] = hashed
    access.validate_deployment_settings(values)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    state = {}
    assert not access.is_access_authorized(state)
    with pytest.raises(access.AccessDeniedError, match="not accepted"):
        access.authenticate("wrong-password", state)
    assert access.authenticate(PASSWORD, state)
    assert access.is_access_authorized(state)
    assert PASSWORD not in repr(state)
    assert hashed not in repr(state)
    assert not access.is_admin_session(state)
    # Expiry and credential rotation both invalidate previously issued tokens.
    state[access._AUTH_KEY]["expires_at"] = 0
    assert not access.is_access_authorized(state)
    access.authenticate(PASSWORD, state)
    monkeypatch.delenv("BUSHFIRE_ACCESS_PASSWORD_HASH")
    monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", "A-different-strong-password")
    assert not access.is_access_authorized(state)


def test_ambiguous_password_configuration_is_rejected(tmp_path):
    values = _cloud_environment(tmp_path)
    values["BUSHFIRE_ACCESS_PASSWORD_HASH"] = "an-ignored-hash-would-be-unsafe"
    with pytest.raises(access.DeploymentConfigurationError, match="Set only one"):
        access.validate_deployment_settings(values)


def test_reconnecting_sessions_cannot_bypass_login_throttle(monkeypatch):
    monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", PASSWORD)
    current = [100.0]
    monkeypatch.setattr(access.time, "monotonic", lambda: current[0])
    for _ in range(access._LOGIN_ATTEMPT_LIMIT):
        with pytest.raises(access.AccessDeniedError, match="not accepted"):
            access.authenticate("wrong", {})
    with pytest.raises(access.AccessDeniedError, match="Too many"):
        access.authenticate(PASSWORD, {})
    current[0] += 61
    assert access.authenticate(PASSWORD, {})


def test_admin_requires_separate_authentication_and_cannot_use_demo_password(tmp_path, monkeypatch):
    for name, value in _cloud_environment(tmp_path).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("BUSHFIRE_ADMIN_PASSWORD", ADMIN_PASSWORD)
    state = {}
    with pytest.raises(access.AccessDeniedError, match="application first"):
        access.authenticate(ADMIN_PASSWORD, state, admin=True)
    access.authenticate(PASSWORD, state)
    with pytest.raises(access.AccessDeniedError, match="not accepted"):
        access.authenticate(PASSWORD, state, admin=True)
    assert access.authenticate(ADMIN_PASSWORD, state, admin=True)
    assert access.is_admin_session(state)
    state[access._ADMIN_KEY]["token"] = "forged"
    assert not access.is_admin_session(state)


def test_login_callback_erases_password_on_both_success_and_failure(monkeypatch):
    import streamlit as st

    monkeypatch.setenv("BUSHFIRE_ACCESS_PASSWORD", PASSWORD)
    state = {"_access_login_password": PASSWORD}
    monkeypatch.setattr(st, "session_state", state)
    access._submit_password(admin=False)
    assert access.is_access_authorized(state)
    assert "_access_login_password" not in state
    state["_access_login_password"] = "wrong"
    access._submit_password(admin=False)
    assert "_access_login_password" not in state
    assert not access.is_access_authorized(state)
    assert state["_access_login_error"] == "The password was not accepted."


def test_workflow_denies_an_expired_session_before_calling_provider(tmp_path, monkeypatch):
    from src import report_workflow
    from src.model_runtime import ModelServiceError

    for name, value in _cloud_environment(tmp_path).items():
        monkeypatch.setenv(name, value)
    called = []
    state = SimpleNamespace(model_client=SimpleNamespace(generate=lambda prompt: called.append(prompt)))
    monkeypatch.setattr(report_workflow, "st", SimpleNamespace(session_state={"model_client": state.model_client}))
    with pytest.raises(ModelServiceError, match="Sign in again"):
        report_workflow._call_governed_model("private prompt")
    assert called == []


def test_streamlit_gate_clears_plaintext_and_isolates_new_browser(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    for name, value in _cloud_environment(tmp_path).items():
        monkeypatch.setenv(name, value)
    script = """
import streamlit as st
from src.deployment_access import render_access_gate
if render_access_gate():
    st.success('Protected report workflow')
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert not app.success
    app.text_input[0].input("wrong").run()
    app.button[0].click().run()
    assert not app.exception
    assert "not accepted" in app.error[0].value
    assert not app.session_state.filtered_state.get("_access_login_password")
    app.text_input[0].input(PASSWORD).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.success[0].value == "Protected report workflow"
    assert PASSWORD not in repr(app.session_state.filtered_state)
    other_browser = AppTest.from_string(script).run()
    assert not other_browser.success
    assert other_browser.text_input[0].label == "Access password"


def test_admin_and_user_cannot_share_identical_credentials(tmp_path):
    values = _cloud_environment(tmp_path)
    values["BUSHFIRE_ADMIN_PASSWORD"] = PASSWORD
    with pytest.raises(access.DeploymentConfigurationError, match="must be different"):
        access.validate_deployment_settings(values)


@pytest.mark.parametrize("hashed_role", ["access", "admin"])
def test_same_password_in_different_storage_formats_is_rejected_at_preflight(tmp_path, hashed_role):
    values = _cloud_environment(tmp_path)
    values["BUSHFIRE_ADMIN_PASSWORD"] = PASSWORD
    prefix = f"BUSHFIRE_{hashed_role.upper()}_PASSWORD"
    values[f"{prefix}_HASH"] = access.hash_access_password(values.pop(prefix))

    with pytest.raises(access.DeploymentConfigurationError, match="must be different"):
        access.validate_deployment_settings(values)


def test_separately_salted_hashes_cannot_promote_the_access_password_to_admin(tmp_path, monkeypatch):
    values = _cloud_environment(tmp_path)
    values.pop("BUSHFIRE_ACCESS_PASSWORD")
    values["BUSHFIRE_ACCESS_PASSWORD_HASH"] = access.hash_access_password(PASSWORD)
    values["BUSHFIRE_ADMIN_PASSWORD_HASH"] = access.hash_access_password(PASSWORD)
    assert values["BUSHFIRE_ACCESS_PASSWORD_HASH"] != values["BUSHFIRE_ADMIN_PASSWORD_HASH"]
    # The password cannot be recovered from two independent salted hashes at startup.
    # The actual candidate must therefore also be checked at the privilege boundary.
    access.validate_deployment_settings(values)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    state = {}
    assert access.authenticate(PASSWORD, state)

    with pytest.raises(access.DeploymentConfigurationError, match="must be different"):
        access.authenticate(PASSWORD, state, admin=True)

    assert access.is_access_authorized(state)
    assert not access.is_admin_session(state)
    assert access._ADMIN_KEY not in state
    assert PASSWORD not in repr(state)
