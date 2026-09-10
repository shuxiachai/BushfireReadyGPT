from html import escape
from pathlib import PureWindowsPath

import streamlit as st

from src.deployment_access import DeploymentConfigurationError, is_cloud_deployment


def safe_display_text(value, fallback="N/A"):
    if value is None:
        return fallback
    text = str(value)
    return text if text.strip() else fallback


def _hide_server_details():
    try:
        return is_cloud_deployment()
    except DeploymentConfigurationError:
        return True


def safe_display_path(path, fallback="N/A"):
    """Show a file label in cloud mode, without revealing either Windows or POSIX directories."""
    text = safe_display_text(path, fallback)
    if text == fallback or not _hide_server_details():
        return text
    # PureWindowsPath recognises both separators, including Windows paths stored in older local records.
    return PureWindowsPath(text).name or fallback


def safe_diagnostic_detail(value, cloud_message="Technical details are available to the project owner."):
    """Keep full local diagnostics while avoiding server paths and transport details in the hosted UI."""
    return cloud_message if _hide_server_details() else safe_display_text(value)


def render_path_line(label, path):
    st.markdown(
        f"""
        <div class="path-line">
            <strong>{escape(safe_display_text(label))}:</strong>
            <span class="path-chip">{escape(safe_display_path(path))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
