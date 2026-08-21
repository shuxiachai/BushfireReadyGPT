"""Download the validated ABS subset used by the bundled community demo."""

from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_artifacts import (  # noqa: E402
    BUNDLED_CORE_TRANSACTION_NAME,
    atomic_publish_files,
    download_url_bytes,
    recover_atomic_publish,
    render_updated_manifest,
    sha256_file,
    validate_data_manifest,
)
from src.data_paths import get_data_paths  # noqa: E402

ABS_LAYER_URL = (
    "https://geo.abs.gov.au/arcgis/rest/services/Hosted/"
    "ABS_Population_and_people_by_2021_SA2_Nov_2023/FeatureServer/1/query"
)
ABS_SA2_BOUNDARY_URL = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SA2/MapServer/0/query"
POPULATION_FIELD = "erp_p_202022"
OLDER_COUNT_FIELDS = [
    "erp_p_152022",
    "erp_p_162022",
    "erp_p_172022",
    "erp_p_182022",
    "erp_p_192022",
]
LANGUAGE_COUNT_FIELD = "census_392021"


def resolve_paths(data_dir=None):
    root = Path(data_dir or get_data_paths().data_dir).expanduser().resolve()
    return root, {
        "raw_profile": root / "raw" / "abs_population_people_sa2_qld_subset.json",
        "raw_boundary": root / "raw" / "abs_sa2_boundaries_subset.geojson",
        "profile": root / "processed" / "community_profiles.csv",
        "boundary": root / "processed" / "sa2_coverage.geojson",
        "regions": root / "region_mappings.yml",
        "manifest": root / "manifest.json",
    }


def number(value):
    if value in {None, ""}:
        return 0.0
    return float(value)


def load_region_mappings(path=None):
    if path is None:
        path = resolve_paths()[1]["regions"]
    with open(path, "r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    regions = payload.get("regions")
    if not isinstance(regions, list) or not regions:
        raise ValueError("Region mapping must define a non-empty 'regions' list.")
    for region in regions:
        if (
            not isinstance(region, dict)
            or not str(region.get("location", "")).strip()
            or not isinstance(region.get("sa2_names"), list)
            or not region["sa2_names"]
            or any(not str(name).strip() for name in region["sa2_names"])
        ):
            raise ValueError("Every region requires a location and non-empty SA2 names.")
    return regions


def all_configured_sa2_names(regions):
    return sorted({str(name).strip() for region in regions for name in region["sa2_names"]})


def quote_sql_names(names):
    return ", ".join("'" + name.replace("'", "''") + "'" for name in names)


def build_query_url(regions=None):
    regions = regions or load_region_mappings()
    quoted_names = quote_sql_names(all_configured_sa2_names(regions))
    fields = [
        "sa2_code_2021",
        "sa2_name_2021",
        POPULATION_FIELD,
        LANGUAGE_COUNT_FIELD,
        *OLDER_COUNT_FIELDS,
    ]
    params = {
        "f": "json",
        "where": f"sa2_name_2021 IN ({quoted_names})",
        "outFields": ",".join(fields),
        "returnGeometry": "false",
        "resultRecordCount": "2000",
    }
    return f"{ABS_LAYER_URL}?{urlencode(params)}"


def build_boundary_query_url(regions=None):
    regions = regions or load_region_mappings()
    quoted_names = quote_sql_names(all_configured_sa2_names(regions))
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
    raw = download_url_bytes(url, timeout=30, attempts=3, max_bytes=32 * 1024 * 1024)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("ABS response was not valid UTF-8 JSON.") from error


def validate_feature_payload(payload, *, require_geometry=False):
    if not isinstance(payload, dict):
        raise ValueError("ABS response must be a JSON object.")
    if payload.get("error"):
        raise ValueError(f"ABS response reported an error: {payload['error']}")
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("ABS response contained no features; existing files were preserved.")
    if require_geometry and payload.get("type") != "FeatureCollection":
        raise ValueError("ABS boundary response was not a GeoJSON FeatureCollection.")
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError("ABS response contained a malformed feature.")
        container_name = "properties" if require_geometry else "attributes"
        values = feature.get(container_name)
        if not isinstance(values, dict):
            raise ValueError(f"ABS feature is missing {container_name}.")
        for field in ("sa2_code_2021", "sa2_name_2021"):
            if not str(values.get(field, "")).strip():
                raise ValueError(f"ABS feature is missing {field}.")
        if require_geometry and not feature.get("geometry"):
            raise ValueError("ABS boundary feature is missing geometry.")
    return payload


def validate_configured_coverage(profile_payload, boundary_payload, regions):
    configured = set(all_configured_sa2_names(regions))
    profile_by_name = {}
    required_profile_fields = {
        POPULATION_FIELD,
        LANGUAGE_COUNT_FIELD,
        *OLDER_COUNT_FIELDS,
    }
    for feature in profile_payload["features"]:
        values = feature["attributes"]
        missing = required_profile_fields - set(values)
        if missing:
            raise ValueError("ABS profile feature is missing fields: " + ", ".join(sorted(missing)))
        name = str(values["sa2_name_2021"]).strip()
        if name in profile_by_name:
            raise ValueError(f"ABS profile response contains duplicate SA2 name: {name}")
        profile_by_name[name] = str(values["sa2_code_2021"]).strip()
    boundary_by_name = {}
    for feature in boundary_payload["features"]:
        values = feature["properties"]
        name = str(values["sa2_name_2021"]).strip()
        if name in boundary_by_name:
            raise ValueError(f"ABS boundary response contains duplicate SA2 name: {name}")
        boundary_by_name[name] = str(values["sa2_code_2021"]).strip()

    missing_profiles = sorted(configured - set(profile_by_name))
    missing_boundaries = sorted(configured - set(boundary_by_name))
    if missing_profiles or missing_boundaries:
        details = []
        if missing_profiles:
            details.append("profile: " + ", ".join(missing_profiles))
        if missing_boundaries:
            details.append("boundary: " + ", ".join(missing_boundaries))
        raise ValueError("Configured SA2 coverage is incomplete (" + "; ".join(details) + ").")
    mismatched = sorted(name for name in configured if profile_by_name[name] != boundary_by_name[name])
    if mismatched:
        raise ValueError("Profile/boundary SA2 code mismatch: " + ", ".join(mismatched))


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


def aggregate(features, regions=None):
    regions = regions or load_region_mappings()
    rows = []
    for region in regions:
        configured_names = set(region["sa2_names"])
        matched = [
            feature["attributes"]
            for feature in features
            if str(feature["attributes"].get("sa2_name_2021", "")) in configured_names
        ]
        population = sum(number(row.get(POPULATION_FIELD)) for row in matched)
        older_count = sum(sum(number(row.get(field)) for field in OLDER_COUNT_FIELDS) for row in matched)
        language_count = sum(number(row.get(LANGUAGE_COUNT_FIELD)) for row in matched)
        older_pct = round(older_count / population * 100, 1) if population else ""
        language_pct = round(language_count / population * 100, 1) if population else ""
        location = region["location"]
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
                "matched_sa2_names": "; ".join(sorted(str(row["sa2_name_2021"]) for row in matched)),
                "geography_type": region.get("geography_type", ""),
                "match_method": region.get("match_method", "configured_sa2_names"),
                "mapping_notes": region.get("notes", ""),
                "source": "ABS Data by Region / Digital Atlas of Australia SA2 population and people layer",
                "source_years": "2021 Census and 2022 ERP fields",
                "risk_notes": risk_note(location, older_pct or 0, language_pct or 0),
            }
        )
    return rows


def render_csv(rows):
    fieldnames = list(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def enrich_geojson(payload, regions, *, source_url):
    result = copy.deepcopy(payload)
    mappings = {}
    for index, region in enumerate(regions):
        for name in region["sa2_names"]:
            mappings[name] = (region, index)
    colors = [[180, 61, 31, 90], [35, 117, 150, 90], [46, 125, 50, 90], [121, 85, 72, 90]]
    line_colors = [[127, 42, 25, 220], [15, 76, 100, 220], [27, 94, 32, 220], [78, 52, 46, 220]]
    for feature in result["features"]:
        properties = feature["properties"]
        region, index = mappings[str(properties["sa2_name_2021"])]
        properties["mapped_location"] = region["location"]
        properties["geography_type"] = region.get("geography_type", "")
        properties["fill_color"] = colors[index % len(colors)]
        properties["line_color"] = line_colors[index % len(line_colors)]
    result["_downloaded_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["_source_query_url"] = source_url
    return result


def json_bytes(payload, *, indent=2):
    return (json.dumps(payload, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Data root (defaults to BUSHFIRE_DATA_DIR).")
    args = parser.parse_args(argv)
    data_dir, paths = resolve_paths(args.data_dir)
    recover_atomic_publish(data_dir, transaction_name=BUNDLED_CORE_TRANSACTION_NAME)
    validate_data_manifest(paths["manifest"], data_dir=data_dir)
    base_manifest_sha256 = sha256_file(paths["manifest"])
    regions = load_region_mappings(paths["regions"])
    profile_url = build_query_url(regions)
    profile_payload = validate_feature_payload(download_json(profile_url))
    boundary_url = build_boundary_query_url(regions)
    boundary_payload = validate_feature_payload(download_json(boundary_url), require_geometry=True)
    validate_configured_coverage(profile_payload, boundary_payload, regions)
    rows = aggregate(profile_payload["features"], regions)
    if any(row["matched_sa2_count"] != len(region["sa2_names"]) for row, region in zip(rows, regions)):
        raise ValueError("Processed rows do not cover every configured SA2 name.")

    downloaded_at = datetime.now(timezone.utc).isoformat()
    raw_profile = copy.deepcopy(profile_payload)
    raw_profile.update(_downloaded_at_utc=downloaded_at, _source_query_url=profile_url)
    raw_boundary = copy.deepcopy(boundary_payload)
    raw_boundary.update(_downloaded_at_utc=downloaded_at, _source_query_url=boundary_url)
    processed_boundary = enrich_geojson(boundary_payload, regions, source_url=boundary_url)
    profile_bytes = render_csv(rows)
    boundary_bytes = json_bytes(processed_boundary, indent=None)
    manifest_bytes = render_updated_manifest(
        paths["manifest"],
        {
            "processed/community_profiles.csv": {
                "data": profile_bytes,
                "row_count": len(rows),
            },
            "processed/sa2_coverage.geojson": {"data": boundary_bytes},
        },
        generated_at_utc=downloaded_at,
    )
    if sha256_file(paths["manifest"]) != base_manifest_sha256:
        raise RuntimeError("Data manifest changed while the download was being prepared.")
    atomic_publish_files(
        {
            paths["raw_profile"]: json_bytes(raw_profile),
            paths["raw_boundary"]: json_bytes(raw_boundary),
            paths["profile"]: profile_bytes,
            paths["boundary"]: boundary_bytes,
            # Keep the manifest last so a non-atomic reader never sees it point
            # at files that have not yet reached their transaction destinations.
            paths["manifest"]: manifest_bytes,
        },
        transaction_root=data_dir,
        transaction_name=BUNDLED_CORE_TRANSACTION_NAME,
        expected_current_hashes={paths["manifest"]: base_manifest_sha256},
    )
    print(f"Raw ABS subset saved: {paths['raw_profile']}")
    print(f"Raw SA2 boundary subset saved: {paths['raw_boundary']}")
    print(f"Processed community profiles saved: {paths['profile']}")
    print(f"Processed SA2 coverage GeoJSON saved: {paths['boundary']}")
    print(f"Rows: {len(rows)}")
    print("Recompute and review manifest.json before using refreshed bundled-core data.")


if __name__ == "__main__":
    main()
