import csv
import json
from functools import lru_cache

import pydeck as pdk

from src.data_artifacts import inspect_optional_sa2_map
from src.data_paths import get_data_paths


def _path_signature(path):
    try:
        stat = path.stat()
    except OSError:
        return path, None, None
    return path, stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=1)
def _read_geojson(path, _modified_ns, _size):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


@lru_cache(maxsize=16)
def _read_csv(path, _modified_ns, _size):
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))
    except (OSError, UnicodeError, csv.Error):
        return []


def load_coverage_geojson(data_paths=None):
    paths = data_paths or get_data_paths()
    return _read_geojson(*_path_signature(paths.sa2_coverage))


def load_all_sa2_geojson(state=None, data_paths=None):
    paths = data_paths or get_data_paths()
    path = _state_geojson_path(state, paths)
    if not path.exists():
        path = paths.all_sa2_boundary
    return _read_geojson(*_path_signature(path))


def load_all_sa2_profiles(data_paths=None):
    paths = data_paths or get_data_paths()
    return _read_csv(*_path_signature(paths.all_sa2_profile))


def has_all_australia_data(data_paths=None):
    paths = data_paths or get_data_paths()
    status = inspect_optional_sa2_map(
        paths.all_sa2_profile,
        paths.all_sa2_boundary,
    )
    return status["state"] == "bundle_verified" and status["installed"] is True


def is_area_selection_available(selection, data_paths=None):
    """Return whether an explicit SA2/SA3/SA4 selection exists in active data."""

    if not isinstance(selection, dict) or not has_all_australia_data(data_paths=data_paths):
        return False
    level = selection.get("level")
    area_name = selection.get("area_name")
    state = selection.get("state")
    if level not in {"SA2", "SA3", "SA4"} or not area_name:
        return False
    field = _level_name_field(level)
    return any(
        row.get(field) == area_name and (not state or row.get("state_name") == state)
        for row in load_all_sa2_profiles(data_paths=data_paths)
    )


def get_coverage_table(location_filter=None, data_paths=None):
    paths = data_paths or get_data_paths()
    if not paths.community_profile.exists():
        return []
    with open(paths.community_profile, "r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    rows = _filter_rows(rows, location_filter)
    return [
        {
            "location": row.get("location", ""),
            "population": row.get("population", ""),
            "older_people_pct": row.get("older_people_pct", ""),
            "language_support_needed": row.get("language_support_needed", ""),
            "language_other_than_english_pct": row.get("language_other_than_english_pct", ""),
            "matched_sa2_count": row.get("matched_sa2_count", ""),
            "geography_type": row.get("geography_type", ""),
        }
        for row in rows
    ]


def get_states(data_paths=None):
    states = sorted(
        {row.get("state_name", "") for row in load_all_sa2_profiles(data_paths=data_paths) if row.get("state_name")}
    )
    return states


def get_area_options(level, state=None, search="", data_paths=None):
    rows = load_all_sa2_profiles(data_paths=data_paths)
    field = _level_name_field(level)
    if state:
        rows = [row for row in rows if row.get("state_name") == state]
    if search:
        needle = search.lower()
        rows = [row for row in rows if needle in row.get(field, "").lower()]
    return sorted({row.get(field, "") for row in rows if row.get(field)})


def get_all_australia_table(level, area_name, state=None, data_paths=None):
    rows = _filter_all_rows(
        load_all_sa2_profiles(data_paths=data_paths),
        level,
        area_name,
        state,
    )
    return _summarize_rows(rows, level, area_name)


def build_all_australia_deck(level, area_name, state=None, data_paths=None):
    geojson = load_all_sa2_geojson(state, data_paths=data_paths)
    if not geojson or not geojson.get("features"):
        return None
    filtered = _filter_all_geojson(geojson, level, area_name, state)
    if not filtered.get("features"):
        return None

    longitude, latitude = _calculate_center(filtered)
    zoom = {"SA2": 9, "SA3": 8, "SA4": 6}.get(level, 5)
    layer = pdk.Layer(
        "GeoJsonLayer",
        filtered,
        pickable=True,
        stroked=True,
        filled=True,
        get_fill_color="properties.fill_color",
        get_line_color="properties.line_color",
        get_line_width=100,
        line_width_min_pixels=1,
    )
    tooltip = {
        "html": (
            "<b>{sa2_name_2021}</b><br/>"
            "SA3: {sa3_name_2021}<br/>"
            "SA4: {sa4_name_2021}<br/>"
            "State: {state_name_2021}<br/>"
            "Population: {population}<br/>"
            "Language support: {language_support_needed}"
        ),
        "style": {"backgroundColor": "#18212f", "color": "white"},
    }
    return pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(
            latitude=latitude,
            longitude=longitude,
            zoom=zoom,
            pitch=0,
        ),
        layers=[layer],
        tooltip=tooltip,
    )


def build_coverage_deck(location_filter=None, data_paths=None):
    geojson = load_coverage_geojson(data_paths=data_paths)
    if not geojson or not geojson.get("features"):
        return None
    geojson = _filter_geojson(geojson, location_filter)
    if not geojson.get("features"):
        return None

    longitude, latitude = _calculate_center(geojson)
    zoom = 8 if location_filter else 7
    layer = pdk.Layer(
        "GeoJsonLayer",
        geojson,
        pickable=True,
        stroked=True,
        filled=True,
        get_fill_color="properties.fill_color",
        get_line_color="properties.line_color",
        get_line_width=120,
        line_width_min_pixels=1,
    )

    tooltip = {
        "html": (
            "<b>{sa2_name_2021}</b><br/>"
            "Mapped location: {mapped_location}<br/>"
            "SA3: {sa3_name_2021}<br/>"
            "SA4: {sa4_name_2021}"
        ),
        "style": {"backgroundColor": "#18212f", "color": "white"},
    }

    return pdk.Deck(
        map_style=None,
        initial_view_state=pdk.ViewState(
            latitude=latitude,
            longitude=longitude,
            zoom=zoom,
            pitch=0,
        ),
        layers=[layer],
        tooltip=tooltip,
    )


def resolve_all_australia_selection(raw_location, data_paths=None):
    if not raw_location or not has_all_australia_data(data_paths=data_paths):
        return None
    normalized = raw_location.lower()
    rows = load_all_sa2_profiles(data_paths=data_paths)
    for level in ("SA4", "SA3", "SA2"):
        field = _level_name_field(level)
        for row in rows:
            value = row.get(field, "")
            if value and (value.lower() in normalized or normalized in value.lower()):
                return {
                    "level": level,
                    "area_name": value,
                    "state": row.get("state_name", ""),
                }
    return None


def resolve_location_filter(raw_location, data_paths=None):
    if not raw_location:
        return None
    normalized = raw_location.lower()
    locations = [row["location"] for row in get_coverage_table(data_paths=data_paths)]
    for location in locations:
        if location.lower() in normalized or normalized in location.lower():
            return location
    return None


def _level_name_field(level):
    return {"SA2": "sa2_name", "SA3": "sa3_name", "SA4": "sa4_name"}.get(level, "sa4_name")


def _level_geojson_field(level):
    return {"SA2": "sa2_name_2021", "SA3": "sa3_name_2021", "SA4": "sa4_name_2021"}.get(level, "sa4_name_2021")


def _state_geojson_path(state, data_paths):
    if not state:
        return data_paths.all_sa2_boundary
    return data_paths.all_sa2_boundary_by_state_dir / f"{_slugify(state)}.geojson"


def _slugify(value):
    return "".join(char if char.isalnum() else "_" for char in value).strip("_")


def _filter_all_rows(rows, level, area_name, state=None):
    field = _level_name_field(level)
    result = [row for row in rows if row.get(field) == area_name]
    if state:
        result = [row for row in result if row.get("state_name") == state]
    return result


def _filter_all_geojson(geojson, level, area_name, state=None):
    field = _level_geojson_field(level)
    features = []
    for feature in geojson.get("features", []):
        properties = feature.get("properties", {})
        if properties.get(field) != area_name:
            continue
        if state and properties.get("state_name_2021") != state:
            continue
        features.append(feature)
    return {**geojson, "features": features}


def _summarize_rows(rows, level, area_name):
    population = sum(_int_value(row.get("population")) for row in rows)
    older_count = sum(_int_value(row.get("older_people_count")) for row in rows)
    language_count = sum(_int_value(row.get("language_other_than_english_count")) for row in rows)
    older_pct = round(older_count / population * 100, 1) if population else ""
    language_pct = round(language_count / population * 100, 1) if population else ""
    support = (
        "high"
        if language_pct != "" and language_pct >= 20
        else "medium"
        if language_pct != "" and language_pct >= 8
        else "low"
    )
    return [
        {
            "selected_level": level,
            "selected_area": area_name,
            "sa2_count": len(rows),
            "population": population,
            "older_people_pct": older_pct,
            "language_other_than_english_pct": language_pct,
            "language_support_needed": support if population else "unknown",
        }
    ]


def _int_value(value):
    if value in {None, ""}:
        return 0
    return int(float(value))


def _filter_rows(rows, location_filter):
    if not location_filter:
        return rows
    normalized = location_filter.lower()
    return [row for row in rows if row.get("location", "").lower() == normalized]


def _filter_geojson(geojson, location_filter):
    if not location_filter:
        return geojson
    normalized = location_filter.lower()
    return {
        **geojson,
        "features": [
            feature
            for feature in geojson.get("features", [])
            if feature.get("properties", {}).get("mapped_location", "").lower() == normalized
        ],
    }


def _calculate_center(geojson):
    points = []
    for feature in geojson.get("features", []):
        points.extend(_extract_points(feature.get("geometry", {})))
    if not points:
        return 134.0, -25.7
    longitude = sum(point[0] for point in points) / len(points)
    latitude = sum(point[1] for point in points) / len(points)
    return longitude, latitude


def _extract_points(geometry):
    if not isinstance(geometry, dict):
        return []
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    points = []

    if geometry_type == "Polygon":
        for ring in coordinates:
            points.extend(_valid_points(ring))
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                points.extend(_valid_points(ring))
    return points


def _valid_points(items):
    return [(float(item[0]), float(item[1])) for item in items if isinstance(item, list) and len(item) >= 2]
