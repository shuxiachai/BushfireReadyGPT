import streamlit as st

from src.coverage_map import (
    build_all_australia_deck,
    build_coverage_deck,
    get_all_australia_table,
    get_area_options,
    get_coverage_table,
    get_states,
    has_all_australia_data,
    resolve_all_australia_selection,
    resolve_location_filter,
)


def render_coverage_analysis_tools(active_location):
    st.markdown("### Map and Data Table Analysis")
    st.markdown(
        """
        <div class="source-note">
            This shows local ABS SA2 mapping coverage and community profile data. The map is
            evidence context for the agents; it is not a live fire map, evacuation route map
            or official safety boundary.
        </div>
        """,
        unsafe_allow_html=True,
    )
    if has_all_australia_data():
        render_all_australia_map_selector(active_location)
    else:
        render_configured_map_selector(active_location)


def _selectbox_with_default(label, options, key, preferred=None):
    resolved_options = list(options)
    if not resolved_options:
        return None
    default = preferred if preferred in resolved_options else resolved_options[0]
    if st.session_state.get(key) not in resolved_options:
        st.session_state[key] = default
    return st.selectbox(label, resolved_options, key=key)


def render_all_australia_map_selector(active_location):
    inferred = resolve_all_australia_selection(active_location)
    states = get_states()
    if not states:
        st.info(
            "National-map files contain no selectable states. Refresh the optional "
            "map bundle before using the national selector."
        )
        return
    default_state = inferred.get("state") if inferred else None
    control_cols = st.columns([1, 1, 1.4, 1.6])
    with control_cols[0]:
        state = _selectbox_with_default("State / territory", states, "map_state", default_state)
    with control_cols[1]:
        default_level = inferred.get("level") if inferred else "SA4"
        level_options = ["SA4", "SA3", "SA2"]
        level = _selectbox_with_default("Geography level", level_options, "map_level", default_level)
    with control_cols[2]:
        if "map_search" not in st.session_state:
            st.session_state.map_search = ""
        search = st.text_input("Search area", placeholder="e.g. Cairns / Brisbane / Darwin", key="map_search")
    options = get_area_options(level, state=state, search=search)
    inferred_area = (
        inferred.get("area_name")
        if inferred and inferred.get("level") == level and inferred.get("state") == state
        else None
    )
    display_options = options or ["No matches"]
    with control_cols[3]:
        area_name = _selectbox_with_default("Select area", display_options, "map_area", inferred_area)
    if not options:
        st.info("No matching area was found. Try another keyword or switch between SA4, SA3 and SA2.")
        return
    preview_selection = {"state": state, "level": level, "area_name": area_name}
    st.caption(f"Map preview: {state} / {level} / {area_name}")
    apply_col, clear_col = st.columns(2)
    with apply_col:
        if st.button("Use previewed area for report", width="stretch"):
            st.session_state.selected_map_area = preview_selection
            st.session_state.official_status_result = None
            st.success("The previewed area is now the active report geography.")
    with clear_col:
        if st.button("Clear active report geography", width="stretch"):
            st.session_state.selected_map_area = None
            st.session_state.official_status_result = None
            st.success("The report will use the form location and best available data match.")
    active_selection = st.session_state.get("selected_map_area")
    if active_selection:
        st.caption(
            "Active report geography: "
            f"{active_selection.get('state')} / {active_selection.get('level')} / "
            f"{active_selection.get('area_name')}"
        )
    else:
        st.caption("Active report geography: none")
    deck = build_all_australia_deck(level, area_name, state=state)
    table_rows = get_all_australia_table(level, area_name, state=state)
    if deck:
        st.pydeck_chart(deck, width="stretch")
    else:
        st.info(
            "No SA2 boundary was found for this area. Re-run scripts/download_abs_sa2_all.py to generate all-Australia map data."
        )
    if table_rows:
        with st.expander("View aggregated profile for the selected area", expanded=True):
            st.dataframe(table_rows, width="stretch", hide_index=True)
    else:
        st.info("No processed SA2 profile data was found for this area.")


def render_configured_map_selector(active_location):
    location_filter = resolve_location_filter(active_location)
    if location_filter:
        st.caption(f"Current location filter: {location_filter}")
    else:
        st.caption("No specific location has been matched; the map shows all configured demonstration areas.")
    deck = build_coverage_deck(location_filter)
    table_rows = get_coverage_table(location_filter)
    if deck:
        st.pydeck_chart(deck, width="stretch")
    else:
        st.info(
            "No SA2 coverage GeoJSON was found. Run scripts/download_abs_community_profiles.py to generate map data."
        )
    if table_rows:
        with st.expander("View community profile data table", expanded=False):
            st.dataframe(table_rows, width="stretch", hide_index=True)
    else:
        st.info("No processed/community_profiles.csv file was found.")
