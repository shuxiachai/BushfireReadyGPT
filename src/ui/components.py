from html import escape

import streamlit as st


def safe_display_text(value, fallback="N/A"):
    if value is None:
        return fallback
    text = str(value)
    return text if text.strip() else fallback


def render_path_line(label, path):
    st.markdown(
        f"""
        <div class="path-line">
            <strong>{escape(safe_display_text(label))}:</strong>
            <span class="path-chip">{escape(safe_display_text(path))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
