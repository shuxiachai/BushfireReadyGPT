"""Controlled-demo authentication, independent of model credentials and SDK setup.

This is a shared-password demonstration gate, not per-user identity or an RBAC
system. Login throttling is shared by all browser sessions in one process.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import deque
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field

_PBKDF2_ITERATIONS = 600_000
_AUTH_KEY = "_bushfire_access_auth"
_ADMIN_KEY = "_bushfire_admin_auth"
_SESSION_SIGNING_KEY = secrets.token_bytes(32)
_LOGIN_LOCK = threading.Lock()
_LOGIN_ATTEMPTS: deque[float] = deque()
_LOGIN_WINDOW_SECONDS = 60
_LOGIN_ATTEMPT_LIMIT = 20
_SESSION_SECONDS = 8 * 60 * 60


class DeploymentConfigurationError(RuntimeError):
    """Deployment configuration is unsafe or malformed; messages contain no secrets."""


class AccessDeniedError(RuntimeError):
    """A controlled-demo authentication attempt was rejected."""


def deployment_mode(environ: Mapping[str, str] | None = None) -> str:
    values = os.environ if environ is None else environ
    railway = any(values.get(name, "").strip() for name in ("RAILWAY_ENVIRONMENT_ID", "RAILWAY_PROJECT_ID"))
    mode = values.get("BUSHFIRE_DEPLOYMENT_MODE", "cloud" if railway else "local").strip().lower()
    if mode not in {"local", "cloud"}:
        raise DeploymentConfigurationError("BUSHFIRE_DEPLOYMENT_MODE must be local or cloud.")
    if railway and mode != "cloud":
        raise DeploymentConfigurationError("Railway deployments must use BUSHFIRE_DEPLOYMENT_MODE=cloud.")
    return mode


def is_cloud_deployment() -> bool:
    return deployment_mode() == "cloud"


def hash_access_password(password: str) -> str:
    """Create an environment-ready salted PBKDF2 hash without contacting any service."""
    _validate_password_strength(password, "Access password")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _validate_password_strength(password: str, name: str) -> None:
    if not isinstance(password, str) or not 16 <= len(password) <= 1024 or len(set(password)) < 8:
        raise DeploymentConfigurationError(
            f"{name} must contain 16–1024 characters and at least 8 distinct characters."
        )


@dataclass(frozen=True)
class _Credential:
    digest: bytes = field(repr=False)
    salt: bytes = field(default=b"", repr=False)
    iterations: int = 0

    @property
    def identity(self) -> str:
        payload = self.salt + str(self.iterations).encode("ascii") + self.digest
        return hmac.new(_SESSION_SIGNING_KEY, payload, "sha256").hexdigest()

    def matches(self, candidate: str) -> bool:
        if not isinstance(candidate, str) or len(candidate) > 1024:
            return False
        raw = candidate.encode("utf-8")
        digest = (
            hashlib.pbkdf2_hmac("sha256", raw, self.salt, self.iterations)
            if self.iterations
            else hashlib.sha256(raw).digest()
        )
        return hmac.compare_digest(digest, self.digest)


def _credential(values: Mapping[str, str], *, admin: bool = False) -> _Credential | None:
    prefix = "BUSHFIRE_ADMIN_PASSWORD" if admin else "BUSHFIRE_ACCESS_PASSWORD"
    password = values.get(prefix, "")
    encoded = values.get(f"{prefix}_HASH", "").strip()
    if password and encoded:
        raise DeploymentConfigurationError(f"Set only one of {prefix} and {prefix}_HASH.")
    if password:
        _validate_password_strength(password, prefix)
        return _Credential(hashlib.sha256(password.encode("utf-8")).digest())
    if not encoded:
        return None
    try:
        algorithm, count, salt_hex, digest_hex = encoded.split("$")
        iterations = int(count)
        salt, digest = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        if (
            algorithm != "pbkdf2_sha256"
            or not _PBKDF2_ITERATIONS <= iterations <= 2_000_000
            or not 16 <= len(salt) <= 64
            or len(digest) != 32
        ):
            raise ValueError("Unsupported password hash.")
    except (ValueError, TypeError) as error:
        raise DeploymentConfigurationError(f"{prefix}_HASH must be a valid PBKDF2-SHA256 password hash.") from error
    return _Credential(digest=digest, salt=salt, iterations=iterations)


def validate_deployment_settings(environ: Mapping[str, str] | None = None) -> None:
    """Pure startup preflight: validate configuration without opening files or APIs."""
    values = os.environ if environ is None else environ
    mode = deployment_mode(values)
    credential = _credential(values)
    admin_credential = _credential(values, admin=True)
    if admin_credential is not None and admin_credential == credential:
        raise DeploymentConfigurationError("Administrator and application access credentials must be different.")
    if mode == "cloud":
        if credential is None:
            raise DeploymentConfigurationError(
                "Cloud access requires BUSHFIRE_ACCESS_PASSWORD_HASH or a strong password."
            )
        if not values.get("BUSHFIRE_RUNTIME_DIR", "").strip():
            raise DeploymentConfigurationError("Cloud deployment requires BUSHFIRE_RUNTIME_DIR on a persistent volume.")
        for name in ("BUSHFIRE_SESSION_STATE_PATH", "BUSHFIRE_INTERACTION_LOG_PATH"):
            if values.get(name, "").strip():
                raise DeploymentConfigurationError(f"{name} must be unset in cloud mode to isolate browser sessions.")
    from src.model_limits import load_model_limits

    load_model_limits(values)


def _session_valid(state: Mapping, credential: _Credential | None, key: str) -> bool:
    record = state.get(key)
    if credential is None or not isinstance(record, dict):
        return False
    expires_at = record.get("expires_at")
    if not isinstance(expires_at, (int, float)) or not time.time() < expires_at:
        return False
    expected = hmac.new(
        _SESSION_SIGNING_KEY, f"{credential.identity}:{expires_at}:{key}".encode("ascii"), "sha256"
    ).hexdigest()
    token = record.get("token")
    return isinstance(token, str) and hmac.compare_digest(token, expected)


def is_access_authorized(state: Mapping | None = None) -> bool:
    credential = _credential(os.environ)
    if deployment_mode() == "local" and credential is None:
        return True
    if state is None:
        import streamlit as st

        state = st.session_state
    return _session_valid(state, credential, _AUTH_KEY)


def is_admin_session(state: Mapping | None = None) -> bool:
    if deployment_mode() == "local":
        return is_access_authorized(state)
    if state is None:
        import streamlit as st

        state = st.session_state
    return is_access_authorized(state) and _session_valid(state, _credential(os.environ, admin=True), _ADMIN_KEY)


def authenticate(password: str, state: MutableMapping, *, admin: bool = False) -> bool:
    """Authenticate server-side; only an expiring, signed token is stored in the session."""
    now = time.monotonic()
    with _LOGIN_LOCK:
        while _LOGIN_ATTEMPTS and _LOGIN_ATTEMPTS[0] <= now - _LOGIN_WINDOW_SECONDS:
            _LOGIN_ATTEMPTS.popleft()
        if len(_LOGIN_ATTEMPTS) >= _LOGIN_ATTEMPT_LIMIT:
            raise AccessDeniedError("Too many sign-in attempts. Wait one minute and retry.")
        _LOGIN_ATTEMPTS.append(now)
    key = _ADMIN_KEY if admin else _AUTH_KEY
    state.pop(key, None)
    credential = _credential(os.environ, admin=admin)
    if admin and not is_access_authorized(state):
        raise AccessDeniedError("Sign in to the application first.")
    if credential is None or not credential.matches(password):
        raise AccessDeniedError("The password was not accepted.")
    expires_at = time.time() + _SESSION_SECONDS
    token = hmac.new(
        _SESSION_SIGNING_KEY, f"{credential.identity}:{expires_at}:{key}".encode("ascii"), "sha256"
    ).hexdigest()
    state[key] = {"expires_at": expires_at, "token": token}
    return True


def _submit_password(*, admin: bool) -> None:
    import streamlit as st

    prefix = "_admin_login" if admin else "_access_login"
    candidate = st.session_state.pop(f"{prefix}_password", "")
    st.session_state.pop(f"{prefix}_error", None)
    try:
        authenticate(candidate, st.session_state, admin=admin)
    except (AccessDeniedError, DeploymentConfigurationError) as error:
        st.session_state[f"{prefix}_error"] = str(error)


def _render_password_form(*, admin: bool) -> None:
    import streamlit as st

    prefix = "_admin_login" if admin else "_access_login"
    with st.form(f"{prefix}_form", clear_on_submit=True):
        st.text_input(
            "Administrator password" if admin else "Access password", type="password", key=f"{prefix}_password"
        )
        st.form_submit_button("Sign in", on_click=_submit_password, kwargs={"admin": admin})
    error = st.session_state.pop(f"{prefix}_error", None)
    if error:
        st.error(error)


def render_access_gate() -> bool:
    """Render before session initialization; False means the caller must stop rendering."""
    import streamlit as st

    try:
        validate_deployment_settings()
        if is_access_authorized(st.session_state):
            return True
    except DeploymentConfigurationError as error:
        st.error(f"Application access is unavailable: {error}")
        return False
    st.title("BushfireReadyGPT")
    st.write("This is a controlled demonstration. Enter the access password provided by the project owner.")
    _render_password_form(admin=False)
    return False


def render_admin_access() -> bool:
    """Optional diagnostics gate: a demo password never grants administrator access."""
    import streamlit as st

    if is_admin_session(st.session_state):
        return True
    if _credential(os.environ, admin=True) is None or not is_access_authorized(st.session_state):
        return False
    with st.expander("Administrator sign-in"):
        _render_password_form(admin=True)
    return False
