"""Isolated browser fixture: synthetic exports only, no model or private corpus."""

import streamlit as st

from src.deployment_access import render_access_gate
from src.ui.downloads import download_button

PAYLOAD = 'Synthetic private export: 中文 </script><script>fetch("/leak")</script>\n'.encode()

st.set_page_config(page_title="Private download regression")
if not render_access_gate():
    st.stop()

st.success("Authenticated export session")
for label, filename, mime in (
    ("Download Markdown", "测试报告.md", "text/markdown"),
    ("Download PDF", "report.pdf", "application/pdf"),
    ("Download DOCX", "report.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("Download ZIP", "report.zip", "application/zip"),
    ("Download audit", "audit.json", "application/json"),
    ("Download CSV", "register.csv", "text/csv"),
):
    download_button(label, data=PAYLOAD, file_name=filename, mime=mime)

if st.button("End test session"):
    st.session_state.clear()
    st.rerun()
