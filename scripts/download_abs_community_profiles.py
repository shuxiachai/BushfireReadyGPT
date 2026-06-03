"""Download a small ABS Data by Region subset for local vulnerability analysis.

The script queries an official ABS ArcGIS REST layer used by the Digital Atlas of
Australia. It stores the raw JSON response and writes a compact CSV that matches
the app's CommunityVulnerabilityAgent schema.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data_australia" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data_australia" / "processed"

ABS_LAYER_URL = (
    "https://geo.abs.gov.au/arcgis/rest/services/Hosted/"
    "ABS_Population_and_people_by_2021_SA2_Nov_2023/FeatureServer/1/query"
)
ABS_SA2_BOUNDARY_URL = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SA2/MapServer/0/query"

RAW_OUTPUT = RAW_DIR / "abs_population_people_sa2_qld_subset.json"
RAW_BOUNDARY_OUTPUT = RAW_DIR / "abs_sa2_boundaries_subset.geojson"
PROCESSED_OUTPUT = PROCESSED_DIR / "community_profiles.csv"
PROCESSED_GEOJSON_OUTPUT = PROCESSED_DIR / "sa2_coverage.geojson"
REGION_MAPPING_PATH = PROJECT_ROOT / "data_australia" / "region_mappings.yml"

POPULATION_FIELD = "erp_p_202022"
OLDER_COUNT_FIELDS = [
    "erp_p_152022",
    "erp_p_162022",
    "erp_p_172022",
    "erp_p_182022",
    "erp_p_192022",
]
LANGUAGE_COUNT_FIELD = "census_392021"


def number(value):
    if value in {None, ""}:
        return 0.0
    return float(value)


def load_region_mappings():
    with open(REGION_MAPPING_PATH, "r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    return payload.get("regions", [])


def all_configured_sa2_names(regions):
    return sorted({name for region in regions for name in region.get("sa2_names", [])})


def quote_sql_names(names):
    return ", ".join("'" + name.replace("'", "''") + "'" for name in names)


def build_query_url():
    regions = load_region_mappings()
    names = all_configured_sa2_names(regions)
    quoted_names = quote_sql_names(names)
    where = f"sa2_name_2021 IN ({quoted_names})"
    fields = [
        "sa2_code_2021",
        "sa2_name_2021",
        POPULATION_FIELD,
        LANGUAGE_COUNT_FIELD,
        *OLDER_COUNT_FIELDS,
    ]
    params = {
        "f": "json",
        "where": where,
        "outFields": ",".join(fields),
        "returnGeometry": "false",
        "resultRecordCount": "2000",
    }
    return f"{ABS_LAYER_URL}?{urlencode(params)}"


def build_boundary_query_url():
    regions = load_region_mappings()
    names = all_configured_sa2_names(regions)
    quoted_names = quote_sql_names(names)
    params = {
        "f": "geojson",
        "where": f"sa2_name_2021 IN ({quoted_names})",
        "outFields": "sa2_code_2021,sa2_name_2021,sa3_name_2021,sa4_name_2021",
        "returnGeometry": "true",
        "outSR": "4326",
        "resultRecordCount": "2000",
    }
    return f"{ABS_SA2_BOUNDARY_URL}?{urlencode(params)}"


def download_json(url):
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def support_level(language_pct):
    if language_pct >= 20:
        return "high"
    if language_pct >= 8:
        return "medium"
    return "low"


def risk_note(location, older_pct, language_pct):
    notes = [
        "ABS Data by Region SA2 population data has been aggregated for this prototype row.",
        "This row uses a configured SA2 mapping rather than a simple keyword search.",
    ]
    if older_pct >= 16:
        notes.append("Older residents should be considered in smoke, heat, transport, and welfare checks.")
    if language_pct >= 8:
        notes.append("Plain-language and multilingual communication should be considered.")
    if location == "Remote Queensland Community":
        notes.append("Remote communities may need earlier planning for long travel distances and service disruption.")
    return " ".join(notes)


def aggregate(features):
    regions = load_region_mappings()
    rows = []
    for region in regions:
        location = region["location"]
        configured_sa2_names = set(region.get("sa2_names", []))
        matched = []
        for feature in features:
            attrs = feature.get("attributes", {})
            name = str(attrs.get("sa2_name_2021", ""))
            if name in configured_sa2_names:
                matched.append(attrs)

        population = sum(number(row.get(POPULATION_FIELD)) for row in matched)
        older_count = sum(sum(number(row.get(field)) for field in OLDER_COUNT_FIELDS) for row in matched)
        language_count = sum(number(row.get(LANGUAGE_COUNT_FIELD)) for row in matched)
        older_pct = round((older_count / population * 100), 1) if population else ""
        language_pct = round((language_count / population * 100), 1) if population else ""
        matched_names = sorted(str(row.get("sa2_name_2021", "")) for row in matched)

        rows.append(
            {
                "location": location,
                "state": "Queensland",
                "population": int(population) if population else "",
                "older_people_pct": older_pct,
                "no_car_households_pct": "",
                "language_support_needed": support_level(language_pct) if population else "unknown",
                "language_other_than_english_pct": language_pct,
                "matched_sa2_count": len(matched),
                "matched_sa2_names": "; ".join(matched_names),
                "geography_type": region.get("geography_type", ""),
                "match_method": region.get("match_method", "configured_sa2_names"),
                "mapping_notes": region.get("notes", ""),
                "source": "ABS Data by Region / Digital Atlas of Australia SA2 population and people layer",
                "source_years": "2021 Census and 2022 ERP fields",
                "risk_notes": risk_note(location, older_pct if older_pct != "" else 0, language_pct if language_pct != "" else 0),
            }
        )
    return rows


def write_csv(rows):
    fieldnames = [
        "location",
        "state",
        "population",
        "older_people_pct",
        "no_car_households_pct",
        "language_support_needed",
        "language_other_than_english_pct",
        "matched_sa2_count",
        "matched_sa2_names",
        "geography_type",
        "match_method",
        "mapping_notes",
        "source",
        "source_years",
        "risk_notes",
    ]
    with open(PROCESSED_OUTPUT, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_geojson(payload):
    regions = load_region_mappings()
    sa2_to_region = {}
    for index, region in enumerate(regions):
        for sa2_name in region.get("sa2_names", []):
            sa2_to_region[sa2_name] = {
                "location": region["location"],
                "region_index": index,
                "geography_type": region.get("geography_type", ""),
            }

    colors = [
        [180, 61, 31, 90],
        [35, 117, 150, 90],
        [46, 125, 50, 90],
        [121, 85, 72, 90],
    ]
    line_colors = [
        [127, 42, 25, 220],
        [15, 76, 100, 220],
        [27, 94, 32, 220],
        [78, 52, 46, 220],
    ]

    for feature in payload.get("features", []):
        properties = feature.setdefault("properties", {})
        sa2_name = properties.get("sa2_name_2021", "")
        region = sa2_to_region.get(sa2_name, {})
        region_index = region.get("region_index", 0)
        properties["mapped_location"] = region.get("location", "Unmapped")
        properties["geography_type"] = region.get("geography_type", "")
        properties["fill_color"] = colors[region_index % len(colors)]
        properties["line_color"] = line_colors[region_index % len(line_colors)]

    payload["_downloaded_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["_source_query_url"] = build_boundary_query_url()
    RAW_BOUNDARY_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    PROCESSED_GEOJSON_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    query_url = build_query_url()
    payload = download_json(query_url)
    payload["_downloaded_at_utc"] = datetime.now(timezone.utc).isoformat()
    payload["_source_query_url"] = query_url

    RAW_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = aggregate(payload.get("features", []))
    write_csv(rows)

    boundary_payload = download_json(build_boundary_query_url())
    write_geojson(boundary_payload)

    print(f"Raw ABS subset saved: {RAW_OUTPUT}")
    print(f"Raw SA2 boundary subset saved: {RAW_BOUNDARY_OUTPUT}")
    print(f"Processed community profiles saved: {PROCESSED_OUTPUT}")
    print(f"Processed SA2 coverage GeoJSON saved: {PROCESSED_GEOJSON_OUTPUT}")
    print(f"Rows: {len(rows)}")


if __name__ == "__main__":
    main()
