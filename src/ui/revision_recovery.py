"""Editable recovery for a failed revision without replacing the current report."""

import hashlib
import json

import streamlit as st

from src.input_validation import REVISION_REQUEST_MAX_CHARS
from src.revision_state import discard_pending_revision, get_pending_revision
from src.ui.workflow_progress import workflow_progress


def render_revision_recovery(revise_current_report):
    pending = get_pending_revision(st.session_state)
    if not pending:
        return
    with st.container(border=True):
        st.markdown("### Continue a revision")
        st.warning("Your original report is unchanged. This revision request has not been applied to it.")
        if pending.get("message"):
            st.text(pending["message"])
        if pending.get("error_code"):
            st.caption(f"Failure category: {pending['error_code']}")
        for failure in pending.get("blocking_failures") or []:
            if isinstance(failure, dict):
                st.text(f"{failure.get('name', 'Check')}: {failure.get('detail', '')}")
        st.caption(
            "This unfinished request is held in the current application session. "
            "It is not added to the optional saved session or audit record before a successful revision."
        )
        token = hashlib.sha256(
            json.dumps(
                [pending.get("binding"), pending.get("request_text")], sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()[:16]
        allowed = bool(pending.get("retry_allowed")) and pending.get("status") != "running"
        with st.form("retry_pending_revision"):
            edited_request = st.text_area(
                "Edit the revision request",
                value=pending.get("request_text", ""),
                key=f"_pending_revision_editor_{token}",
                max_chars=REVISION_REQUEST_MAX_CHARS,
                height=120,
            )
            submitted = st.form_submit_button("Retry revision", disabled=not allowed)
        if not allowed:
            st.info("Resolve the reported issue before retrying. Audit-finalization failures need recovery first.")
        st.button(
            "Discard request",
            key="discard_pending_revision",
            on_click=discard_pending_revision,
            args=(st.session_state,),
        )
        if submitted:
            if not edited_request.strip():
                st.warning("Enter a revision request before retrying.")
                return
            with workflow_progress("Revising the report") as progress:
                _response, error = revise_current_report(edited_request, progress_callback=progress)
                progress.finish(error=bool(error))
            st.rerun()
