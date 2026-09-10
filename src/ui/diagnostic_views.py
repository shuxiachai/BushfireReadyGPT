import streamlit as st

from src.runtime_trace import load_trace_summary


def render_runtime_diagnostics():
    st.markdown("### Privacy-minimised Runtime Diagnostics")
    st.caption(
        "Local Trace files record stage names, status, duration, counts and safe error codes only. "
        "They do not store prompts, report text, retrieved passages, locations, audiences or reviewer identity."
    )
    summary = load_trace_summary()
    if summary.get("scan_truncated") or summary.get("scan_errors"):
        st.warning(
            "Runtime diagnostics cover only the files that could be scanned within the safety limit. "
            "These rates and recent records are a partial sample, not the complete history."
        )
    if summary.get("unread_candidate_files"):
        st.caption(
            f"Additional Trace candidates outside this summary: {summary['unread_candidate_files']}. "
            "Metrics describe the bounded loaded sample only."
        )
    if not summary["traces"]:
        st.info("No valid runtime Trace was loaded in this scan. Generate or revise a report to create one.")
        if summary["invalid_files"]:
            st.warning(f"Ignored malformed Trace files: {summary['invalid_files']}")
        return

    columns = st.columns(4)
    columns[0].metric("Traces", summary["traces"])
    columns[1].metric("Success rate", _rate(summary["success_rate"]))
    columns[2].metric("P50 duration", _duration(summary["duration_ms"]["p50"]))
    columns[3].metric("P95 duration", _duration(summary["duration_ms"]["p95"]))
    st.markdown(
        f"**Repair rate:** {_rate(summary['repair_rate'])}  "
        f"**Grounding review rate:** {_rate(summary['grounding_review_rate'])}  "
        f"**Malformed files ignored:** {summary['invalid_files']}"
    )

    with st.expander("Stage latency and safe failure codes", expanded=False):
        st.markdown("**Stage duration (milliseconds)**")
        st.json(summary["stage_duration_ms"])
        st.markdown("**Operation failures**")
        st.json(summary["failure_codes"] or {"status": "none"})
        st.markdown("**Stage failures**")
        st.json(summary["stage_errors"] or {"status": "none"})

    with st.expander("Recent Trace records", expanded=False):
        st.dataframe(summary["recent"], hide_index=True, width="stretch")


def _rate(value):
    return "N/A" if value is None else f"{float(value) * 100:.1f}%"


def _duration(value):
    return "N/A" if value is None else f"{float(value):,.0f} ms"
