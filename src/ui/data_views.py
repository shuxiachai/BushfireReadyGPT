from html import escape

import streamlit as st

from src.app_catalog import OFFICIAL_SOURCES
from src.data_register import get_data_register
from src.data_status import get_community_data_status
from src.licence_register import get_licence_register, licence_register_csv, licence_register_markdown
from src.official_status import check_official_sources
from src.ui.components import render_path_line, safe_display_text


def render_official_sources():
    st.markdown("### Official Information Sources")
    st.markdown(
        """
        <div class="source-note">
            These are recommended official sources for verification. This module does not read
            live warnings and does not replace emergency directions. In a real emergency, follow
            official emergency services and call 000 if life is at risk.
        </div>
        """,
        unsafe_allow_html=True,
    )
    for index in range(0, len(OFFICIAL_SOURCES), 2):
        cols = st.columns(2)
        for col, source in zip(cols, OFFICIAL_SOURCES[index : index + 2]):
            col.markdown(
                '<article class="official-card">'
                f'<div class="official-name">{escape(source["name"])}</div>'
                f'<div class="official-purpose"><strong>Purpose: </strong>{escape(source["purpose"])}</div>'
                f'<div class="official-when"><strong>When to check: </strong>{escape(source["when"])}</div>'
                f'<a class="official-link" href="{escape(source["url"])}" target="_blank" rel="noopener noreferrer">Open official page</a>'
                "</article>",
                unsafe_allow_html=True,
            )


def render_official_status_panel():
    st.markdown("### Live Official Status Panel")
    st.markdown(
        """
        <div class="source-note">
            This panel checks whether official information entry points are reachable from this
            computer. It does not read or interpret current warnings, fire bans, incidents,
            evacuation orders or emergency directions.
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Check official source status", use_container_width=True):
        with st.spinner("Checking official source entry points..."):
            st.session_state.official_status_result = check_official_sources(OFFICIAL_SOURCES)

    result = st.session_state.get("official_status_result")
    if not result:
        st.info("Click the button above to check official source entry-point reachability.")
        return

    summary = result.get("summary", {})
    cols = st.columns(4)
    metrics = [
        ("Checked at", result.get("checked_at", "Not available")),
        ("Reachable", str(summary.get("reachable", 0))),
        ("Warnings", str(summary.get("warnings", 0))),
        ("Failed", str(summary.get("failed", 0))),
    ]
    for col, (label, value) in zip(cols, metrics):
        col.markdown(
            f"""
            <div class="status-card">
                <div class="status-label">{escape(safe_display_text(label))}</div>
                <div class="status-value">{escape(safe_display_text(value))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    rows = result.get("rows", [])
    st.dataframe(
        [
            {
                "source": row.get("name", ""),
                "status": row.get("status", ""),
                "http": row.get("http_status", ""),
                "response_ms": row.get("response_ms", ""),
                "message": row.get("message", ""),
                "url": row.get("url", ""),
            }
            for row in rows
        ],
        use_container_width=True,
        hide_index=True,
    )
    with st.expander("Status panel limitations", expanded=False):
        for limitation in result.get("limitations", []):
            st.markdown(f"- {limitation}")
        st.markdown("- In a life-threatening emergency, call 000.")


def render_data_status():
    status = get_community_data_status()
    st.markdown("### Data Status / Data Sources")
    st.markdown(
        """
        <div class="source-note">
            This shows the data files used by the Community Vulnerability Agent for background
            community context. It does not read live incidents and does not replace official
            warnings, evacuation orders or organisational emergency decisions.
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    metrics = [
        ("Active data", status["active_type"]),
        ("Rows", str(status["row_count"])),
        ("Processed file updated", status["updated_at"]),
        ("Raw ABS data", "Downloaded" if status["raw_exists"] else "Not downloaded"),
    ]
    for col, (label, value) in zip(cols, metrics):
        col.markdown(
            f"""
            <div class="status-card">
                <div class="status-label">{escape(safe_display_text(label))}</div>
                <div class="status-value">{escape(safe_display_text(value))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with st.expander("View data files and limitations", expanded=False):
        render_path_line("Agent active file", status["active_path"])
        render_path_line("ABS raw response", status["raw_path"])
        st.markdown(f"- **Raw file updated:** {status['raw_updated_at']}")
        st.markdown(f"- **ABS download record UTC:** {status['downloaded_at_utc']}")
        st.markdown(f"- **ASGS allocation metadata:** {status['asgs_metadata_path']}")
        st.markdown(f"- **ASGS allocation status:** {'Downloaded' if status['asgs_exists'] else 'Not downloaded'}")
        st.markdown(f"- **ASGS processed file updated:** {status['asgs_updated_at']}")
        st.markdown(f"- **ASGS generation record UTC:** {status['asgs_generated_at_utc']}")
        if status.get("asgs_row_counts"):
            st.markdown("**ASGS allocation / correspondence row counts**")
            st.table(
                [
                    {"dataset": key, "rows": value}
                    for key, value in status["asgs_row_counts"].items()
                ]
            )
        if status["locations"]:
            st.markdown(f"- **Current covered locations:** {', '.join(status['locations'])}")
        if status.get("mapping_summary"):
            st.markdown("**Region mapping summary**")
            st.table(status["mapping_summary"])
        if status["source_query_url"]:
            st.markdown(f"- **ABS query entry:** {status['source_query_url']}")
        st.markdown("**Limitations**")
        for limitation in status["limitations"]:
            st.markdown(f"- {limitation}")


def render_data_register():
    st.markdown("### Data Register")
    st.markdown(
        """
        <div class="source-note">
            For government pilot use, each data source needs an explainable origin, purpose,
            licence position and limitation statement. Licence and terms of use must be reviewed
            before commercial use or government procurement.
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("View data register", expanded=False):
        rows = get_data_register()
        st.dataframe(
            [
                {
                    "name": row["name"],
                    "provider": row["provider"],
                    "licence": row["licence"],
                    "used_for": row["used_for"],
                    "limitations": row["limitations"],
                    "local_file_status": row["local_file_status"],
                }
                for row in rows
            ],
            use_container_width=True,
            hide_index=True,
        )
        for row in rows:
            st.markdown(f"- **{row['name']}**: {row['url']}")


def render_licence_register():
    st.markdown("### Licence Register")
    st.markdown(
        """
        <div class="source-note">
            This register records the current licence assumptions for official data and website
            sources used by the prototype. It is not legal advice; commercial deployment needs
            source-by-source review.
        </div>
        """,
        unsafe_allow_html=True,
    )
    payload = get_licence_register()
    rows = payload.get("licence_register", [])
    action_cols = st.columns(2)
    with action_cols[0]:
        st.download_button(
            "Download licence CSV",
            data=licence_register_csv(),
            file_name="licence_register.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with action_cols[1]:
        st.download_button(
            "Download licence Markdown",
            data=licence_register_markdown(),
            file_name="licence_register.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with st.expander("View licence register", expanded=False):
        st.dataframe(
            [
                {
                    "source": row.get("source_name", ""),
                    "provider": row.get("provider", ""),
                    "licence_position": row.get("licence_position", ""),
                    "commercial_position": row.get("commercial_position", ""),
                    "review_status": row.get("review_status", ""),
                    "url": row.get("source_url", ""),
                }
                for row in rows
            ],
            use_container_width=True,
            hide_index=True,
        )
        for note in payload.get("notes", []):
            st.markdown(f"- {note}")
