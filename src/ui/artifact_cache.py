"""Session-local caches for derived and audit-bound report files."""

import hashlib

import streamlit as st

from src.export_artifacts import _renderer_identity, get_report_artifacts

_CACHE_STATE_KEY = "_derived_report_artifacts"
_BOUND_CACHE_STATE_KEY = "_governed_report_artifacts"


def get_governed_artifact_cache():
    """Keep private report bytes within this one browser session."""
    cache = st.session_state.setdefault(_BOUND_CACHE_STATE_KEY, {})
    if not isinstance(cache, dict):
        cache = {}
        st.session_state[_BOUND_CACHE_STATE_KEY] = cache
    return cache


def get_governed_report_artifacts(report_text, *, audit_path):
    return get_report_artifacts(report_text, audit_path=audit_path, cache=get_governed_artifact_cache())


def get_report_artifact(report_text, artifact_type, build, *, cache=None):
    """Build a derived artifact once per exact report text and session.

    The cache is deliberately kept in Streamlit session state rather than a
    process-wide decorator so private reports are not shared across users.
    """

    text = str(report_text or "")
    kind = str(artifact_type or "").strip().lower()
    if not text:
        raise ValueError("A report is required to build a derived artifact.")
    if not kind:
        raise ValueError("An artifact type is required.")
    if not callable(build):
        raise TypeError("build must be callable.")

    active_cache = cache if cache is not None else st.session_state.setdefault(_CACHE_STATE_KEY, {})
    if not isinstance(active_cache, dict):
        active_cache = {}
        if cache is None:
            st.session_state[_CACHE_STATE_KEY] = active_cache
    identity = hashlib.sha256(text.encode("utf-8")).hexdigest()
    renderer_identity = _renderer_identity(build)
    entry = active_cache.get(kind)
    if (
        isinstance(entry, dict)
        and entry.get("identity") == identity
        and entry.get("renderer_identity") == renderer_identity
        and isinstance(entry.get("content"), bytes)
    ):
        return entry["content"]

    content = build(text)
    if not isinstance(content, bytes):
        raise TypeError("Derived report builders must return bytes.")
    active_cache[kind] = {
        "identity": identity,
        "renderer_identity": renderer_identity,
        "content": content,
    }
    return content
