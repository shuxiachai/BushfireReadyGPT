"""Download all Australian SA2 profiles and boundaries for local map selection.

This script creates a full offline SA2/SA3/SA4 selection dataset from official
ABS services. It is larger than the small Cairns-focused prototype dataset, but
it lets the Streamlit app filter maps across Australia without live queries.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data_australia" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data_australia" / "processed"

ABS_PROFILE_URL = (
    "https://geo.abs.gov.au/arcgis/rest/services/Hosted/"
    "ABS_Population_and_people_by_2021_SA2_Nov_2023/FeatureServer/1/query"
)
ABS_SA2_BOUNDARY_URL = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SA2/MapServer/0/query"

RAW_PROFILE_OUTPUT = RAW_DIR / "abs_population_people_sa2_all.json"
RAW_BOUNDARY_OUTPUT = RAW_DIR / "abs_sa2_boundaries_all.geojson"
PROCESSED_PROFILE_OUTPUT = PROCESSED_DIR / "sa2_profiles_all.csv"
PROCESSED_GEOJSON_OUTPUT = PROCESSED_DIR / "sa2_boundaries_all.geojson"
STATE_GEOJSON_DIR = PROCESSED_DIR / "sa2_boundaries_by_state"

POPULATION_FIELD = "erp_p_202022"
OLDER_COUNT_FIELDS = ["erp_p_152022", "erp_p_162022", "erp_p_172022", "erp_p_182022", "erp_p_192022"]
LANGUAGE_COUNT_FIELD = "census_392021"
PAGE_SIZE = 2000


def number(value):
    if value in {None, ""}:
        return 0.0
    return float(value)


def download_paged_json(base_url, params, feature_collection=False):
    features = []
    offset = 0
    template = None

    while True:
        page_params = {
            **params,
            "resultRecordCount": str(PAGE_SIZE),
            "resultOffset": str(offset),
        }
        url = f"{base_url}?{urlencode(page_params)}"
        with urlopen(url, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if template is None:
            template = {key: value for key, value in payload.items() if key != "features"}
        page_features = payload.get("features", [])
        features.extend(page_features)
        if len(page_features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    result = template or {}
    result["features"] = features
    result["_downloaded_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["_source_url"] = base_url
    result["_feature_count"] = len(features)
    if feature_collection:
        result.setdefault("type", "FeatureCollection")
    return result


def support_level(language_pct):
    if language_pct >= 20:
        return "high"
    if language_pct >= 8:
        return "medium"
    return "low"


def load_official_layers():
    profile_fields = [
        "sa2_code_2021",
        "sa2_name_2021",
        POPULATION_FIELD,
        LANGUAGE_COUNT_FIELD,
        *OLDER_COUNT_FIELDS,
    ]
    profile_payload = download_paged_json(
        ABS_PROFILE_URL,
        {
            "f": "json",
            "where": "1=1",
            "outFields": ",".join(profile_fields),
            "returnGeometry": "false",
        },
    )

    boundary_payload = download_paged_json(
        ABS_SA2_BOUNDARY_URL,
        {
            "f": "geojson",
            "where": "1=1",
            "outFields": (
                "sa2_code_2021,sa2_name_2021,sa3_code_2021,sa3_name_2021,"
                "sa4_code_2021,sa4_name_2021,state_code_2021,state_name_2021"
            ),
            "returnGeometry": "true",
            "outSR": "4326",
        },
        feature_collection=True,
    )
    return profile_payload, boundary_payload


def build_profiles(profile_payload, boundary_payload):
    profile_by_code = {
        str(feature.get("attributes", {}).get("sa2_code_2021")): feature.get("attributes", {})
        for feature in profile_payload.get("features", [])
    }
    rows = []
    for feature in boundary_payload.get("features", []):
        props = feature.get("properties", {})
        sa2_code = str(props.get("sa2_code_2021"))
        attrs = profile_by_code.get(sa2_code, {})
        population = number(attrs.get(POPULATION_FIELD))
        older_count = sum(number(attrs.get(field)) for field in OLDER_COUNT_FIELDS)
        language_count = number(attrs.get(LANGUAGE_COUNT_FIELD))
        older_pct = round(older_count / population * 100, 1) if population else ""
        language_pct = round(language_count / population * 100, 1) if population else ""
        rows.append(
            {
                "state_name": props.get("state_name_2021", ""),
                "state_code": props.get("state_code_2021", ""),
                "sa4_name": props.get("sa4_name_2021", ""),
                "sa4_code": props.get("sa4_code_2021", ""),
                "sa3_name": props.get("sa3_name_2021", ""),
                "sa3_code": props.get("sa3_code_2021", ""),
                "sa2_name": props.get("sa2_name_2021", ""),
                "sa2_code": sa2_code,
                "population": int(population) if population else "",
                "older_people_count": int(older_count) if older_count else "",
                "older_people_pct": older_pct,
                "language_other_than_english_count": int(language_count) if language_count else "",
                "language_other_than_english_pct": language_pct,
                "language_support_needed": support_level(language_pct) if population else "unknown",
                "source": "ABS Data by Region / Digital Atlas SA2 population and ASGS 2021 SA2 boundary layers",
                "source_years": "2021 Census and 2022 ERP fields",
            }
        )
    return rows


def enrich_geojson(boundary_payload, rows):
    row_by_code = {row["sa2_code"]: row for row in rows}
    for feature in boundary_payload.get("features", []):
        props = feature.setdefault("properties", {})
        row = row_by_code.get(str(props.get("sa2_code_2021")), {})
        props["population"] = row.get("population", "")
        props["older_people_pct"] = row.get("older_people_pct", "")
        props["language_other_than_english_pct"] = row.get("language_other_than_english_pct", "")
        props["language_support_needed"] = row.get("language_support_needed", "")
        props["mapped_location"] = props.get("sa4_name_2021", "")
        level = row.get("language_support_needed", "unknown")
        if level == "high":
            props["fill_color"] = [180, 61, 31, 85]
        elif level == "medium":
            props["fill_color"] = [35, 117, 150, 85]
        else:
            props["fill_color"] = [46, 125, 50, 75]
        props["line_color"] = [24, 33, 47, 180]
    return boundary_payload


def write_state_geojson_files(geojson):
    STATE_GEOJSON_DIR.mkdir(parents=True, exist_ok=True)
    features_by_state = {}
    for feature in geojson.get("features", []):
        state_name = feature.get("properties", {}).get("state_name_2021", "Unknown")
        features_by_state.setdefault(state_name, []).append(feature)

    for state_name, features in features_by_state.items():
        payload = {**geojson, "features": features}
        output_path = STATE_GEOJSON_DIR / f"{slugify(state_name)}.geojson"
        output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def slugify(value):
    return "".join(char if char.isalnum() else "_" for char in value).strip("_")


def write_profiles(rows):
    fieldnames = [
        "state_name",
        "state_code",
        "sa4_name",
        "sa4_code",
        "sa3_name",
        "sa3_code",
        "sa2_name",
        "sa2_code",
        "population",
        "older_people_count",
        "older_people_pct",
        "language_other_than_english_count",
        "language_other_than_english_pct",
        "language_support_needed",
        "source",
        "source_years",
    ]
    with open(PROCESSED_PROFILE_OUTPUT, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    profile_payload, boundary_payload = load_official_layers()
    rows = build_profiles(profile_payload, boundary_payload)
    enriched_geojson = enrich_geojson(boundary_payload, rows)

    RAW_PROFILE_OUTPUT.write_text(json.dumps(profile_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    RAW_BOUNDARY_OUTPUT.write_text(json.dumps(boundary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_profiles(rows)
    PROCESSED_GEOJSON_OUTPUT.write_text(json.dumps(enriched_geojson, ensure_ascii=False), encoding="utf-8")
    write_state_geojson_files(enriched_geojson)

    print(f"Raw all-Australia SA2 profile data saved: {RAW_PROFILE_OUTPUT}")
    print(f"Raw all-Australia SA2 boundaries saved: {RAW_BOUNDARY_OUTPUT}")
    print(f"Processed all-Australia SA2 profiles saved: {PROCESSED_PROFILE_OUTPUT}")
    print(f"Processed all-Australia SA2 boundaries saved: {PROCESSED_GEOJSON_OUTPUT}")
    print(f"State SA2 boundary files saved: {STATE_GEOJSON_DIR}")
    print(f"SA2 rows: {len(rows)}")


if __name__ == "__main__":
    main()
