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


def render_all_australia_map_selector(active_location):
    inferred = resolve_all_australia_selection(active_location)
    states = get_states()
    default_state = inferred.get("state") if inferred else "Queensland"
    state_index = states.index(default_state) if default_state in states else 0
    control_cols = st.columns([1, 1, 1.4, 1.6])
    with control_cols[0]:
        state = st.selectbox("State / territory", states, index=state_index, key="map_state")
    with control_cols[1]:
        default_level = inferred.get("level") if inferred else "SA4"
        level_options = ["SA4", "SA3", "SA2"]
        level = st.selectbox("Geography level", level_options, index=level_options.index(default_level), key="map_level")
    with control_cols[2]:
        search = st.text_input("Search area", value="", placeholder="e.g. Cairns / Brisbane / Darwin", key="map_search")
    options = get_area_options(level, state=state, search=search)
    inferred_area = inferred.get("area_name") if inferred and inferred.get("level") == level and inferred.get("state") == state else None
    selected_index = options.index(inferred_area) if inferred_area in options else 0
    with control_cols[3]:
        area_name = st.selectbox("Select area", options or ["No matches"], index=selected_index, key="map_area")
    if not options:
        st.info("No matching area was found. Try another keyword or switch between SA4, SA3 and SA2.")
        st.session_state.selected_map_area = None
        return
    st.session_state.selected_map_area = {"state": state, "level": level, "area_name": area_name}
    st.caption(f"Current map selection: {state} / {level} / {area_name}")
    deck = build_all_australia_deck(level, area_name, state=state)
    table_rows = get_all_australia_table(level, area_name, state=state)
    if deck:
        st.pydeck_chart(deck, use_container_width=True)
    else:
        st.info("No SA2 boundary was found for this area. Re-run scripts/download_abs_sa2_all.py to generate all-Australia map data.")
    if table_rows:
        with st.expander("View aggregated profile for the selected area", expanded=True):
            st.dataframe(table_rows, use_container_width=True, hide_index=True)
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
        st.pydeck_chart(deck, use_container_width=True)
    else:
        st.info("No SA2 coverage GeoJSON was found. Run scripts/download_abs_community_profiles.py to generate map data.")
    if table_rows:
        with st.expander("View community profile data table", expanded=False):
            st.dataframe(table_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No processed/community_profiles.csv file was found.")
