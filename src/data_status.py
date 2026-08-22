import csv
import json
from datetime import datetime

from src.data_artifacts import get_data_artifact_status
from src.data_paths import get_data_paths
from src.data_quality import assess_source_period


def _format_timestamp(path):
    if not path.exists():
        return "Not available"
    timestamp = datetime.fromtimestamp(path.stat().st_mtime)
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _read_csv_rows(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _active_source_period(paths, active_path):
    if not paths.manifest.is_file():
        return "Not recorded"
    try:
        payload = json.loads(paths.manifest.read_text(encoding="utf-8"))
        relative_path = active_path.resolve().relative_to(paths.data_dir.resolve()).as_posix()
    except (json.JSONDecodeError, OSError, ValueError):
        return "Not recorded"
    for artifact in payload.get("bundled_core", {}).get("artifacts", []):
        if isinstance(artifact, dict) and artifact.get("path") == relative_path:
            return artifact.get("source_period") or "Not recorded"
    return "Not recorded"


def get_community_data_status(data_paths=None):
    paths = data_paths or get_data_paths()
    artifact_status = get_data_artifact_status(paths)
    active_path = paths.community_profile if paths.community_profile.exists() else paths.community_sample
    rows = _read_csv_rows(active_path)
    source_assessment = assess_source_period(_active_source_period(paths, active_path))
    raw_metadata = {}
    asgs_metadata = {}

    if paths.abs_raw.exists():
        try:
            raw_payload = json.loads(paths.abs_raw.read_text(encoding="utf-8"))
            raw_metadata = {
                "downloaded_at_utc": raw_payload.get("_downloaded_at_utc", "Not recorded"),
                "source_query_url": raw_payload.get("_source_query_url", ""),
            }
        except json.JSONDecodeError:
            raw_metadata = {"downloaded_at_utc": "Raw file could not be parsed", "source_query_url": ""}

    if paths.asgs_metadata.exists():
        try:
            asgs_metadata = json.loads(paths.asgs_metadata.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            asgs_metadata = {"generated_at_utc": "Metadata file could not be parsed", "sources": {}}

    asgs_sources = asgs_metadata.get("sources", {})

    return {
        **artifact_status,
        "active_path": str(active_path),
        "active_type": ("ABS processed data" if active_path == paths.community_profile else "Sample fallback data"),
        "active_exists": active_path.exists(),
        "source_period": source_assessment["source_period"],
        "latest_source_year": source_assessment["latest_source_year"],
        "source_age_years": source_assessment["source_age_years"],
        "freshness": source_assessment["freshness"],
        "freshness_assessed_for_year": source_assessment["assessed_for_year"],
        "row_count": len(rows),
        "locations": [row.get("location", "") for row in rows if row.get("location")],
        "mapping_summary": [
            {
                "location": row.get("location", ""),
                "population": row.get("population", ""),
                "matched_sa2_count": row.get("matched_sa2_count", ""),
                "geography_type": row.get("geography_type", ""),
            }
            for row in rows
        ],
        "updated_at": _format_timestamp(active_path),
        "raw_path": str(paths.abs_raw),
        "raw_exists": paths.abs_raw.exists(),
        "raw_updated_at": _format_timestamp(paths.abs_raw),
        "downloaded_at_utc": raw_metadata.get("downloaded_at_utc", "Not available"),
        "source_query_url": raw_metadata.get("source_query_url", ""),
        "asgs_metadata_path": str(paths.asgs_metadata),
        "asgs_exists": paths.asgs_metadata.exists(),
        "asgs_updated_at": _format_timestamp(paths.asgs_metadata),
        "asgs_generated_at_utc": asgs_metadata.get("generated_at_utc", "Not available"),
        "asgs_row_counts": {key: value.get("row_count", 0) for key, value in asgs_sources.items()},
        "limitations": [
            "The all-Australia SA2/SA3/SA4 map is an optional local capability and is not required for the bundled core demo.",
            "Current processed rows are keyword-matched SA2 subsets, not complete Local Government Area profiles.",
            "The current ABS population-and-people layer does not include no-car household percentage, so transport vulnerability must be verified separately.",
            "ASGS allocation and correspondence files improve official geography traceability, but they are not live emergency data.",
            "This data supports planning context only and does not replace live warnings, evacuation orders, or official emergency instructions.",
        ],
    }
