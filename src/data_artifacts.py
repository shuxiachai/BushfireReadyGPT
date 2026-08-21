"""Integrity checks and crash-safe writes for local data artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import socket
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import yaml

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TRANSACTION_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")
_TRANSACTION_LOCK_STALE_SECONDS = 6 * 60 * 60
BUNDLED_CORE_TRANSACTION_NAME = "abs-bundled-core-refresh"


class DataArtifactError(ValueError):
    """Raised when a data manifest or one of its artifacts is unsafe or invalid."""

    def __init__(self, code, message, *, relative_path=None):
        super().__init__(message)
        self.code = code
        self.relative_path = relative_path


def load_yaml_mapping(path, *, label="YAML data"):
    """Load a required YAML mapping and raise an actionable domain error."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise DataArtifactError(
            "artifact_missing",
            f"Required {label} file was not found: {source}",
            relative_path=str(source),
        ) from error
    except (OSError, UnicodeError) as error:
        raise DataArtifactError(
            "artifact_unreadable",
            f"Required {label} file could not be read: {source} ({error})",
            relative_path=str(source),
        ) from error
    try:
        payload = yaml.safe_load(text) or {}
    except yaml.YAMLError as error:
        raise DataArtifactError(
            "artifact_invalid",
            f"Required {label} file contains invalid YAML: {source}",
            relative_path=str(source),
        ) from error
    if not isinstance(payload, dict):
        raise DataArtifactError(
            "artifact_invalid",
            f"Required {label} file must contain a YAML mapping: {source}",
            relative_path=str(source),
        )
    return payload


def sha256_file(path, *, chunk_size=1024 * 1024):
    """Return the lowercase SHA-256 digest for the exact bytes in *path*."""

    digest = hashlib.sha256()
    with open(path, "rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def download_url_bytes(
    url,
    *,
    timeout,
    attempts=3,
    backoff_seconds=0.25,
    max_bytes=None,
):
    """Download non-empty bytes with bounded retries for transient failures only."""

    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if max_bytes is not None and (isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1):
        raise ValueError("max_bytes must be a positive integer")
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise ValueError("Only absolute HTTPS download URLs are allowed.")
    last_error = None
    for attempt in range(attempts):
        try:
            request = Request(  # noqa: S310 - URL was restricted to HTTPS above.
                url,
                headers={
                    "Accept": "application/json, application/pdf, text/html, */*",
                    "User-Agent": "BushfireReadyGPT/0.1 (official-data-downloader)",
                },
            )
            # The scheme and hostname are constrained immediately above.
            with urlopen(request, timeout=timeout) as response:  # nosec B310
                status = getattr(response, "status", None) or response.getcode()
                if status is not None and 400 <= status < 500:
                    raise ValueError(f"Request failed with HTTP {status}.")
                if status is not None and status >= 500:
                    raise HTTPError(url, status, "transient server error", None, None)
                if max_bytes is not None:
                    content_length = getattr(response, "headers", {}).get("Content-Length")
                    if content_length and int(content_length) > max_bytes:
                        raise ValueError("Download exceeds the configured size limit.")
                    payload = response.read(max_bytes + 1)
                else:
                    payload = response.read()
            if max_bytes is not None and len(payload) > max_bytes:
                raise ValueError("Download exceeds the configured size limit.")
            if not payload:
                raise ValueError("Download was empty; existing files were preserved.")
            return payload
        except HTTPError as error:
            if not 500 <= error.code < 600:
                raise ValueError(f"Request failed with HTTP {error.code}.") from error
            last_error = error
        except (
            URLError,
            HTTPException,
            socket.timeout,
            TimeoutError,
            ConnectionError,
        ) as error:
            last_error = error
        if attempt + 1 < attempts:
            time.sleep(backoff_seconds * (2**attempt))
    raise ValueError(f"Download failed after {attempts} attempts: {last_error}") from last_error


def _payload_size_and_sha256(data):
    if isinstance(data, (bytes, bytearray, memoryview)):
        payload = bytes(data)
        return len(payload), hashlib.sha256(payload).hexdigest()
    path = Path(data)
    if not path.is_file():
        raise ValueError(f"Manifest update source does not exist: {path}")
    return path.stat().st_size, sha256_file(path)


def render_updated_manifest(manifest_path, artifact_updates, *, generated_at_utc=None):
    """Render a core manifest updated for an already validated publication bundle."""

    payload = _load_manifest(manifest_path)
    core = payload.get("bundled_core")
    entries = core.get("artifacts") if isinstance(core, dict) else None
    if not isinstance(entries, list):
        raise DataArtifactError("manifest_invalid", "Manifest has no bundled-core artifacts.")
    if not isinstance(artifact_updates, dict) or not artifact_updates:
        raise ValueError("artifact_updates must be a non-empty mapping")
    by_path = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise DataArtifactError("manifest_invalid", "Manifest artifact entry is invalid.")
        if entry["path"] in by_path:
            raise DataArtifactError("manifest_invalid", f"Duplicate core artifact path: {entry['path']}")
        by_path[entry["path"]] = entry

    for relative_path, update in artifact_updates.items():
        if relative_path not in by_path:
            raise DataArtifactError(
                "manifest_invalid",
                f"Cannot refresh undeclared bundled-core artifact: {relative_path}",
                relative_path=relative_path,
            )
        if not isinstance(update, dict) or "data" not in update:
            raise ValueError(f"Manifest update for {relative_path} requires data")
        entry = by_path[relative_path]
        size, digest = _payload_size_and_sha256(update["data"])
        entry["size_bytes"] = size
        entry["sha256"] = digest
        if "row_count" in entry:
            row_count = update.get("row_count")
            if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
                raise ValueError(f"Manifest update for {relative_path} requires row_count")
            entry["row_count"] = row_count

    refreshed_at = generated_at_utc or datetime.now(timezone.utc).isoformat()
    payload["generated_for_repository_date"] = refreshed_at[:10]
    payload["last_refreshed_at_utc"] = refreshed_at
    payload["last_refreshed_artifacts"] = sorted(artifact_updates)
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_data_provenance(data_paths, *, include_all_sa2_profile=False):
    """Fingerprint the data files used by one deterministic analysis run."""

    from src.data_paths import safe_data_path_label

    attributes = [
        "manifest",
        "community_profile",
        "community_sample",
        "sa2_coverage",
        "asgs_metadata",
        "asgs_sa2_allocation",
        "asgs_lga_summary",
        "official_sources",
        "risk_context_rules",
        "region_mappings",
        "licence_register",
    ]
    if include_all_sa2_profile:
        attributes.append("all_sa2_profile")

    provenance = {}
    for attribute in attributes:
        path = Path(getattr(data_paths, attribute))
        entry = {
            "path": safe_data_path_label(path, data_paths),
            "exists": path.is_file(),
        }
        if path.is_file():
            entry.update(
                {
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        provenance[attribute] = entry
    return provenance


def _load_manifest(manifest_path):
    try:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise DataArtifactError(
            "manifest_missing",
            f"Data manifest was not found: {manifest_path}",
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DataArtifactError(
            "manifest_invalid",
            f"Data manifest could not be read: {error}",
        ) from error
    if not isinstance(payload, dict):
        raise DataArtifactError("manifest_invalid", "Data manifest must be a JSON object.")
    if payload.get("schema_version") != 1:
        raise DataArtifactError(
            "manifest_invalid",
            "Unsupported data manifest schema_version; expected 1.",
        )
    return payload


def _safe_artifact_path(data_dir, relative_path):
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise DataArtifactError(
            "unsafe_path",
            "Manifest artifact paths must be non-empty strings.",
            relative_path=relative_path,
        )
    if "\\" in relative_path:
        raise DataArtifactError(
            "unsafe_path",
            f"Manifest artifact path must use forward slashes: {relative_path}",
            relative_path=relative_path,
        )

    portable_path = PurePosixPath(relative_path)
    native_path = Path(relative_path)
    if (
        portable_path.is_absolute()
        or native_path.is_absolute()
        or native_path.drive
        or any(part in {"", ".", ".."} for part in portable_path.parts)
    ):
        raise DataArtifactError(
            "unsafe_path",
            f"Manifest artifact path is not a safe relative path: {relative_path}",
            relative_path=relative_path,
        )

    root = Path(data_dir).resolve()
    candidate = (root / Path(*portable_path.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise DataArtifactError(
            "unsafe_path",
            f"Manifest artifact escapes the data directory: {relative_path}",
            relative_path=relative_path,
        ) from error
    return candidate


def _csv_row_count(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file)
            next(reader, None)
            return sum(1 for _row in reader)
    except (csv.Error, UnicodeError) as error:
        raise DataArtifactError(
            "row_count_invalid",
            f"CSV row count could not be verified for {path}: {error}",
        ) from error


def _validate_core_artifact(entry, data_dir, seen_paths):
    if not isinstance(entry, dict):
        raise DataArtifactError("manifest_invalid", "Core artifact entries must be objects.")
    relative_path = entry.get("path")
    path = _safe_artifact_path(data_dir, relative_path)
    if relative_path in seen_paths:
        raise DataArtifactError(
            "manifest_invalid",
            f"Duplicate core artifact path: {relative_path}",
            relative_path=relative_path,
        )
    seen_paths.add(relative_path)

    for field in ("scope", "source_period"):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            raise DataArtifactError(
                "manifest_invalid",
                f"Core artifact {relative_path} is missing {field} metadata.",
                relative_path=relative_path,
            )

    expected_size = entry.get("size_bytes")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
        raise DataArtifactError(
            "manifest_invalid",
            f"Core artifact {relative_path} has an invalid size_bytes value.",
            relative_path=relative_path,
        )
    expected_digest = entry.get("sha256")
    if not isinstance(expected_digest, str) or not _SHA256_PATTERN.fullmatch(expected_digest):
        raise DataArtifactError(
            "manifest_invalid",
            f"Core artifact {relative_path} has an invalid SHA-256 digest.",
            relative_path=relative_path,
        )
    if not path.is_file():
        raise DataArtifactError(
            "artifact_missing",
            f"Required data artifact was not found: {relative_path}",
            relative_path=relative_path,
        )

    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise DataArtifactError(
            "size_mismatch",
            f"Size mismatch for {relative_path}: expected {expected_size}, found {actual_size}.",
            relative_path=relative_path,
        )
    actual_digest = sha256_file(path)
    if actual_digest != expected_digest:
        raise DataArtifactError(
            "hash_mismatch",
            f"SHA-256 mismatch for {relative_path}.",
            relative_path=relative_path,
        )

    if "row_count" in entry:
        expected_rows = entry["row_count"]
        if isinstance(expected_rows, bool) or not isinstance(expected_rows, int) or expected_rows < 0:
            raise DataArtifactError(
                "manifest_invalid",
                f"Core artifact {relative_path} has an invalid row_count value.",
                relative_path=relative_path,
            )
        actual_rows = _csv_row_count(path)
        if actual_rows != expected_rows:
            raise DataArtifactError(
                "row_count_mismatch",
                f"Row-count mismatch for {relative_path}: expected {expected_rows}, found {actual_rows}.",
                relative_path=relative_path,
            )
    return {
        "path": relative_path,
        "size_bytes": actual_size,
        "sha256": actual_digest,
        "row_count": entry.get("row_count"),
    }


def _inspect_optional_capabilities(payload, data_dir):
    raw_capabilities = payload.get("optional_capabilities", [])
    if not isinstance(raw_capabilities, list):
        raise DataArtifactError(
            "manifest_invalid",
            "optional_capabilities must be a list.",
        )

    capabilities = {}
    for capability in raw_capabilities:
        if not isinstance(capability, dict):
            raise DataArtifactError(
                "manifest_invalid",
                "Optional capability entries must be objects.",
            )
        capability_id = capability.get("id")
        artifact_entries = capability.get("artifacts")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise DataArtifactError(
                "manifest_invalid",
                "Optional capabilities require a non-empty id.",
            )
        if capability_id in capabilities:
            raise DataArtifactError(
                "manifest_invalid",
                f"Duplicate optional capability id: {capability_id}",
            )
        if not isinstance(artifact_entries, list) or not artifact_entries:
            raise DataArtifactError(
                "manifest_invalid",
                f"Optional capability {capability_id} must list its artifacts.",
            )

        missing = []
        installed = []
        for artifact_entry in artifact_entries:
            relative_path = artifact_entry.get("path") if isinstance(artifact_entry, dict) else artifact_entry
            artifact_path = _safe_artifact_path(data_dir, relative_path)
            if artifact_path.is_file():
                installed.append(relative_path)
            else:
                missing.append(relative_path)
        capabilities[capability_id] = {
            "installed": not missing,
            "installed_artifacts": installed,
            "missing_artifacts": missing,
            "scope": capability.get("scope", ""),
            "source_period": capability.get("source_period", ""),
        }
    return capabilities


def validate_data_manifest(manifest_path, *, data_dir=None):
    """Validate every bundled-core artifact declared by *manifest_path*.

    Paths are constrained to *data_dir*. Missing files, metadata mismatches,
    malformed manifests, path traversal, and symlink escapes fail closed.
    Optional capabilities are reported but never block bundled-core readiness.
    """

    manifest_path = Path(manifest_path)
    root = Path(data_dir) if data_dir is not None else manifest_path.parent
    payload = _load_manifest(manifest_path)
    core = payload.get("bundled_core")
    if not isinstance(core, dict) or not isinstance(core.get("artifacts"), list):
        raise DataArtifactError(
            "manifest_invalid",
            "Data manifest must define bundled_core.artifacts.",
        )
    if not core["artifacts"]:
        raise DataArtifactError(
            "manifest_invalid",
            "Data manifest bundled_core.artifacts must not be empty.",
        )

    seen_paths = set()
    verified = [_validate_core_artifact(entry, root, seen_paths) for entry in core["artifacts"]]
    capabilities = _inspect_optional_capabilities(payload, root)
    return {
        "core_ready": True,
        "manifest_path": str(manifest_path.resolve()),
        "data_dir": str(root.resolve()),
        "verified_artifacts": verified,
        "optional_capabilities": capabilities,
    }


def _uses_custom_data(data_paths):
    expected_data_dir = (data_paths.project_root / "data_australia").resolve()
    if data_paths.data_dir.resolve() != expected_data_dir:
        return True
    expected_paths = {
        "manifest": "manifest.json",
        "community_profile": "processed/community_profiles.csv",
        "community_sample": "community_profile_sample.csv",
        "sa2_coverage": "processed/sa2_coverage.geojson",
        "all_sa2_profile": "processed/sa2_profiles_all.csv",
        "all_sa2_boundary": "processed/sa2_boundaries_all.geojson",
        "all_sa2_boundary_by_state_dir": "processed/sa2_boundaries_by_state",
        "official_sources": "official_sources.yml",
        "risk_context_rules": "risk_context_rules.yml",
        "region_mappings": "region_mappings.yml",
        "licence_register": "licence_register.yml",
        "asgs_metadata": "processed/asgs_allocations/metadata.json",
        "asgs_sa2_allocation": "processed/asgs_allocations/sa2_to_sa3_sa4_state_2021.csv",
        "asgs_lga_summary": "processed/asgs_allocations/lga_2025_summary.csv",
    }
    return any(
        getattr(data_paths, attribute).resolve() != (data_paths.data_dir / relative_path).resolve()
        for attribute, relative_path in expected_paths.items()
    )


def _path_cache_signature(path):
    resolved = Path(path).expanduser().resolve()
    try:
        stat = resolved.stat()
    except OSError:
        return resolved, None, None
    return resolved, stat.st_mtime_ns, stat.st_size


def inspect_optional_sa2_map(profile_path, boundary_path, bundle_manifest_path=None):
    """Classify the national map, caching large-file checks by stable file metadata."""

    profile = Path(profile_path).expanduser().resolve()
    boundary = Path(boundary_path).expanduser().resolve()
    metadata = Path(bundle_manifest_path or boundary.parent / "sa2_map_bundle.json").expanduser().resolve()
    return dict(
        _inspect_optional_sa2_map_cached(
            *_path_cache_signature(profile),
            *_path_cache_signature(boundary),
            *_path_cache_signature(metadata),
        )
    )


@lru_cache(maxsize=8)
def _inspect_optional_sa2_map_cached(
    profile,
    _profile_modified_ns,
    _profile_size,
    boundary,
    _boundary_modified_ns,
    _boundary_size,
    metadata,
    _metadata_modified_ns,
    _metadata_size,
):
    existing = (profile.is_file(), boundary.is_file())
    if not any(existing):
        return {
            "state": "not_installed",
            "status": "Optional map not installed",
            "installed": False,
            "error": "",
        }
    if not all(existing):
        missing = boundary.name if existing[0] else profile.name
        return {
            "state": "incomplete",
            "status": "Optional map incomplete",
            "installed": False,
            "error": f"Missing required national-map artifact: {missing}",
        }

    try:
        profile_codes = _read_optional_profile_codes(profile)
        boundary_codes = _read_optional_boundary_codes(boundary)
        profile_code_set = set(profile_codes)
        boundary_code_set = set(boundary_codes)
        if profile_code_set != boundary_code_set:
            raise ValueError(
                "National profile and boundary SA2 code sets differ "
                f"({len(boundary_code_set - profile_code_set)} boundary-only; "
                f"{len(profile_code_set - boundary_code_set)} profile-only)."
            )
        bundle_verified = _verify_optional_map_bundle(
            metadata,
            profile,
            boundary,
            profile_rows=len(profile_codes),
            boundary_features=len(boundary_codes),
            shared_sa2_codes=len(profile_code_set),
        )
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ValueError) as error:
        return {
            "state": "invalid",
            "status": "Optional map invalid",
            "installed": False,
            "error": str(error),
        }
    return {
        "state": "bundle_verified" if bundle_verified else "present_unverified",
        "status": ("Optional map bundle verified" if bundle_verified else "Optional map present (unverified)"),
        "installed": bundle_verified,
        "error": "",
        "profile_rows": len(profile_codes),
        "boundary_features": len(boundary_codes),
        "shared_sa2_codes": len(profile_code_set),
    }


def _read_optional_profile_codes(profile):
    with open(profile, "r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required_columns = {"state_name", "sa4_name", "sa3_name", "sa2_name", "sa2_code"}
        missing_columns = sorted(required_columns - set(reader.fieldnames or []))
        if missing_columns:
            raise ValueError("National profile CSV is missing columns: " + ", ".join(missing_columns))
        codes = []
        for row in reader:
            code = str(row.get("sa2_code", "")).strip()
            if not code:
                raise ValueError("National profile CSV contains an empty SA2 code.")
            codes.append(code)
    if not codes:
        raise ValueError("National profile CSV contains no data rows.")
    if len(set(codes)) != len(codes):
        raise ValueError("National profile CSV contains duplicate SA2 codes.")
    return codes


def _read_optional_boundary_codes(boundary):
    payload = json.loads(boundary.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("National boundary file is not a GeoJSON FeatureCollection.")
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("National boundary GeoJSON contains no features.")

    codes = []
    spatial_feature_count = 0
    for feature in features:
        code, has_geometry = _validate_optional_boundary_feature(feature)
        codes.append(code)
        spatial_feature_count += int(has_geometry)
    if not spatial_feature_count:
        raise ValueError("National boundary GeoJSON contains no spatial features.")
    if len(set(codes)) != len(codes):
        raise ValueError("National boundary GeoJSON contains duplicate SA2 codes.")
    return codes


def _validate_optional_boundary_feature(feature):
    if not isinstance(feature, dict):
        raise ValueError("National boundary GeoJSON contains an invalid feature.")
    geometry = feature.get("geometry")
    if geometry is not None and (
        not isinstance(geometry, dict)
        or not str(geometry.get("type", "")).strip()
        or not isinstance(geometry.get("coordinates"), list)
        or not geometry["coordinates"]
    ):
        raise ValueError("National boundary GeoJSON contains invalid geometry.")
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("National boundary GeoJSON feature properties are invalid.")
    code = str(properties.get("sa2_code_2021") or properties.get("sa2_code") or "").strip()
    if not code:
        raise ValueError("National boundary GeoJSON contains an empty SA2 code.")
    return code, geometry is not None


def _verify_optional_map_bundle(
    metadata,
    profile,
    boundary,
    *,
    profile_rows,
    boundary_features,
    shared_sa2_codes,
):
    if not metadata.is_file():
        return False
    bundle = json.loads(metadata.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or bundle.get("schema_version") != 1:
        raise ValueError("National map bundle manifest is invalid.")
    expected_counts = {
        "profile_rows": profile_rows,
        "boundary_features": boundary_features,
        "shared_sa2_codes": shared_sa2_codes,
    }
    for field, actual in expected_counts.items():
        if bundle.get(field) != actual:
            raise ValueError(f"National map bundle {field} does not match its files.")
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("National map bundle artifact metadata is missing.")
    for key, path in (("profile", profile), ("boundary", boundary)):
        _verify_optional_map_artifact(artifacts, key, path)
    return True


def _verify_optional_map_artifact(artifacts, key, path):
    item = artifacts.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"National map bundle {key} metadata is missing.")
    if item.get("size_bytes") != path.stat().st_size:
        raise ValueError(f"National map bundle {key} size does not match.")
    if item.get("sha256") != sha256_file(path):
        raise ValueError(f"National map bundle {key} hash does not match.")


def _integrity_status(error, *, custom_data):
    if custom_data:
        return "Unverified custom data"
    if error is None:
        return "Matches bundled manifest"
    if error.code in {"hash_mismatch", "size_mismatch", "row_count_mismatch"}:
        return "Bundled data mismatch"
    if error.code in {"manifest_missing", "manifest_invalid", "unsafe_path"}:
        return "Invalid data manifest"
    if error.code == "artifact_missing":
        return "Missing bundled artifact"
    return "Bundled data invalid"


def get_data_artifact_status(data_paths):
    """Return concise integrity and optional-capability labels for Data Status."""

    custom_data = _uses_custom_data(data_paths)
    error = None
    validation = None
    try:
        validation = validate_data_manifest(
            data_paths.manifest,
            data_dir=data_paths.data_dir,
        )
    except DataArtifactError as caught:
        error = caught

    optional_map = inspect_optional_sa2_map(
        data_paths.all_sa2_profile,
        data_paths.all_sa2_boundary,
    )
    integrity_status = _integrity_status(error, custom_data=custom_data)

    return {
        "core_status": ("Bundled core ready" if error is None else "Bundled core invalid"),
        "core_ready": error is None,
        "optional_map_status": optional_map["status"],
        "optional_map_state": optional_map["state"],
        "optional_map_installed": optional_map["installed"],
        "optional_map_error": optional_map["error"],
        "optional_map_profile_rows": optional_map.get("profile_rows", 0),
        "optional_map_boundary_features": optional_map.get("boundary_features", 0),
        "optional_map_shared_sa2_codes": optional_map.get("shared_sa2_codes", 0),
        "integrity_status": integrity_status,
        "custom_data": custom_data,
        "manifest_path": str(data_paths.manifest),
        "verified_artifact_count": (len(validation["verified_artifacts"]) if validation else 0),
        "integrity_error_code": error.code if error else "",
        "integrity_error": str(error) if error else "",
    }


def _fsync_directory(path):
    """Best-effort directory sync for durable rename metadata."""

    try:
        descriptor = os.open(Path(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _replace_durable(source, destination):
    source = Path(source)
    destination = Path(destination)
    os.replace(source, destination)
    _fsync_directory(destination.parent)
    if source.parent != destination.parent:
        _fsync_directory(source.parent)


def _unlink_durable(path, *, missing_ok=True):
    target = Path(path)
    try:
        target.unlink(missing_ok=missing_ok)
    except FileNotFoundError:
        if not missing_ok:
            raise
    else:
        _fsync_directory(target.parent)


def atomic_write_bytes(path, data):
    """Write bytes through a same-directory staging file and ``os.replace``."""

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("atomic_write_bytes data must be bytes-like")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        _replace_durable(temporary_path, target)
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def atomic_write_text(path, text, *, encoding="utf-8"):
    """Atomically replace a text file after the complete payload is encoded."""

    if not isinstance(text, str):
        raise TypeError("atomic_write_text text must be a string")
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path, payload, *, indent=2):
    """Serialize JSON fully before atomically replacing the destination."""

    text = json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"
    return atomic_write_text(path, text)


def _transaction_journal_path(transaction_root, transaction_name):
    if not isinstance(transaction_name, str) or not _TRANSACTION_NAME_PATTERN.fullmatch(transaction_name):
        raise ValueError("transaction_name may contain only letters, numbers, '.', '_' and '-'")
    return Path(transaction_root).resolve() / f".{transaction_name}.transaction.json"


def _transaction_lock_path(transaction_root, transaction_name):
    _transaction_journal_path(transaction_root, transaction_name)
    return Path(transaction_root).resolve() / f".{transaction_name}.transaction.lock"


def _windows_pid_is_running(pid):
    """Query a Windows PID without using ``os.kill``, which is destructive there."""

    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        error_code = ctypes.get_last_error()
        if error_code == 87:  # ERROR_INVALID_PARAMETER: PID does not exist.
            return False
        return True  # Access denied and unknown failures are conservatively active.
    except (AttributeError, OSError):
        return True


def _pid_is_running(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_pid_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _lock_is_stale(lock_path):
    try:
        stat = lock_path.stat()
    except OSError:
        return False
    if time.time() - stat.st_mtime <= _TRANSACTION_LOCK_STALE_SECONDS:
        return False
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True
    return not _pid_is_running(payload.get("pid"))


@contextmanager
def _transaction_lock(transaction_root, transaction_name):
    root = Path(transaction_root).resolve()
    lock_path = _transaction_lock_path(root, transaction_name)
    descriptor = None
    for _attempt in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            if _lock_is_stale(lock_path):
                try:
                    _unlink_durable(lock_path)
                except OSError:
                    pass
                continue
            raise RuntimeError(f"Another publication is already running: {lock_path.name}") from error
        else:
            break
    if descriptor is None:
        raise RuntimeError(f"Could not acquire publication lock: {lock_path.name}")
    try:
        payload = json.dumps({"schema_version": 1, "pid": os.getpid(), "created_at": time.time()}).encode("utf-8")
        lock_descriptor = descriptor
        descriptor = None
        with os.fdopen(lock_descriptor, "wb") as lock_file:
            lock_file.write(payload)
            lock_file.flush()
            os.fsync(lock_file.fileno())
        _fsync_directory(root)
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            _unlink_durable(lock_path)
        except OSError:
            pass


def _transaction_relative_path(root, path):
    resolved_root = Path(root).resolve()
    resolved_path = Path(path).resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as error:
        raise ValueError(f"Transaction target escapes its data directory: {path}") from error


def _transaction_member(root, relative_path):
    try:
        return _safe_artifact_path(root, relative_path)
    except DataArtifactError as error:
        raise ValueError(f"Unsafe transaction journal path: {relative_path}") from error


def _recover_atomic_publish_unlocked(transaction_root, *, transaction_name):
    """Recover or finish cleanup for an interrupted multi-file publication.

    A ``prepared`` transaction is rolled back to the complete previous bundle.
    A ``committed`` transaction keeps the complete new bundle and only removes
    transaction debris. The deterministic journal name lets download scripts run
    this recovery on every invocation before preparing new network data.
    """

    root = Path(transaction_root).resolve()
    journal_path = _transaction_journal_path(root, transaction_name)
    if not journal_path.is_file():
        return False
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot recover publication because its journal is unreadable: {journal_path}") from error
    if (
        not isinstance(journal, dict)
        or journal.get("schema_version") != 1
        or journal.get("phase") not in {"prepared", "committed"}
        or not isinstance(journal.get("entries"), list)
    ):
        raise RuntimeError(f"Cannot recover invalid publication journal: {journal_path}")

    entries = []
    for raw_entry in journal["entries"]:
        if not isinstance(raw_entry, dict) or raw_entry.get("mode") not in {
            "write",
            "delete",
        }:
            raise RuntimeError(f"Cannot recover invalid publication journal: {journal_path}")
        entries.append(
            {
                **raw_entry,
                "target_path": _transaction_member(root, raw_entry.get("target", "")),
                "backup_path": _transaction_member(root, raw_entry.get("backup", "")),
                "stage_path": (_transaction_member(root, raw_entry["stage"]) if raw_entry.get("stage") else None),
            }
        )

    if journal["phase"] == "prepared":
        for entry in reversed(entries):
            target = entry["target_path"]
            backup = entry["backup_path"]
            stage = entry["stage_path"]
            if backup.is_file():
                _unlink_durable(target)
                _replace_durable(backup, target)
            elif (
                not entry.get("existed", False)
                and entry["mode"] == "write"
                and stage is not None
                and not stage.exists()
            ):
                # A missing stage means it was already renamed into a target that
                # did not exist before this transaction.
                _unlink_durable(target)

    for entry in entries:
        stage = entry["stage_path"]
        if stage is not None:
            _unlink_durable(stage)
        _unlink_durable(entry["backup_path"])
    _unlink_durable(journal_path, missing_ok=False)
    return True


def recover_atomic_publish(transaction_root, *, transaction_name):
    root = Path(transaction_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _transaction_lock(root, transaction_name):
        return _recover_atomic_publish_unlocked(root, transaction_name=transaction_name)


def _atomic_publish_files_unlocked(
    files,
    *,
    transaction_root,
    transaction_name,
    remove_paths=(),
    expected_current_hashes=None,
):
    """Publish a validated file bundle with rollback and restart recovery.

    ``files`` maps destination paths to either complete bytes or a complete
    staged file under ``transaction_root``. Staged paths are moved into the
    transaction and are useful for very large GeoJSON bundles. All destinations
    and optional removals must stay inside ``transaction_root``. Existing files
    are first moved to unique same-directory backups. If any replace fails, the
    journal-driven recovery restores the entire prior bundle instead of leaving
    a mixture of old and new artifacts.
    """

    if not isinstance(files, dict) or not files:
        raise ValueError("files must be a non-empty path-to-bytes mapping")
    root = Path(transaction_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    _recover_atomic_publish_unlocked(root, transaction_name=transaction_name)
    journal_path = _transaction_journal_path(root, transaction_name)
    transaction_id = uuid.uuid4().hex
    _validate_expected_current_hashes(root, expected_current_hashes)
    normalised_files = _normalise_publish_files(root, files)
    removals = _normalise_publish_removals(root, remove_paths, normalised_files)

    entries = []
    try:
        _prepare_publish_entries(root, normalised_files, removals, transaction_id, entries)
        _commit_publish_entries(root, journal_path, transaction_id, entries)
        _recover_atomic_publish_unlocked(root, transaction_name=transaction_name)
    except BaseException as error:
        try:
            _recover_failed_publish(root, journal_path, transaction_name, entries)
        except BaseException as recovery_error:
            error.add_note(f"Transaction recovery also failed: {recovery_error}")
        raise
    return tuple(normalised_files)


def _validate_expected_current_hashes(root, expected_current_hashes):
    for raw_target, expected_digest in (expected_current_hashes or {}).items():
        target = Path(raw_target).resolve()
        _transaction_relative_path(root, target)
        if not isinstance(expected_digest, str) or not _SHA256_PATTERN.fullmatch(expected_digest):
            raise ValueError(f"Invalid expected SHA-256 for transaction target: {target}")
        if not target.is_file() or sha256_file(target) != expected_digest:
            raise RuntimeError(f"Publication base changed while data was being prepared: {target.name}")


def _normalise_publish_files(root, files):
    normalised = {}
    for raw_target, data in files.items():
        target = Path(raw_target).resolve()
        _transaction_relative_path(root, target)
        if isinstance(data, (bytes, bytearray, memoryview)):
            normalised[target] = bytes(data)
            continue
        if not isinstance(data, (str, os.PathLike)):
            raise TypeError("Every publication payload must be bytes-like or a staged path")
        staged_source = Path(data).resolve()
        _transaction_relative_path(root, staged_source)
        if not staged_source.is_file():
            raise ValueError(f"Staged publication file does not exist: {staged_source}")
        if staged_source == target:
            raise ValueError("A staged publication source cannot already be its target")
        normalised[target] = staged_source
    return normalised


def _normalise_publish_removals(root, remove_paths, normalised_files):
    removals = {Path(path).resolve() for path in remove_paths}
    for target in removals:
        _transaction_relative_path(root, target)
    overlap = set(normalised_files) & removals
    if overlap:
        raise ValueError(f"A transaction cannot write and remove the same path: {overlap}")
    return removals


def _prepare_publish_entries(root, normalised_files, removals, transaction_id, entries):
    for target, data in normalised_files.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.with_name(f".{target.name}.{transaction_id}.stage")
        backup = target.with_name(f".{target.name}.{transaction_id}.backup")
        if isinstance(data, Path):
            _replace_durable(data, stage)
        else:
            atomic_write_bytes(stage, data)
        entries.append(
            {
                "mode": "write",
                "target": _transaction_relative_path(root, target),
                "stage": _transaction_relative_path(root, stage),
                "backup": _transaction_relative_path(root, backup),
                "existed": target.is_file(),
            }
        )
    for target in sorted(removals):
        if target.is_file():
            entries.append(_publish_delete_entry(root, target, transaction_id))


def _publish_delete_entry(root, target, transaction_id):
    backup = target.with_name(f".{target.name}.{transaction_id}.backup")
    return {
        "mode": "delete",
        "target": _transaction_relative_path(root, target),
        "stage": "",
        "backup": _transaction_relative_path(root, backup),
        "existed": True,
    }


def _commit_publish_entries(root, journal_path, transaction_id, entries):
    journal = {
        "schema_version": 1,
        "phase": "prepared",
        "transaction_id": transaction_id,
        "entries": entries,
    }
    atomic_write_json(journal_path, journal)
    for entry in entries:
        target = _transaction_member(root, entry["target"])
        backup = _transaction_member(root, entry["backup"])
        if entry["existed"]:
            _replace_durable(target, backup)
        if entry["mode"] == "write":
            _replace_durable(_transaction_member(root, entry["stage"]), target)
    journal["phase"] = "committed"
    atomic_write_json(journal_path, journal)


def _recover_failed_publish(root, journal_path, transaction_name, entries):
    if journal_path.exists():
        _recover_atomic_publish_unlocked(root, transaction_name=transaction_name)
        return
    for entry in entries:
        if entry.get("stage"):
            _unlink_durable(_transaction_member(root, entry["stage"]))
        _unlink_durable(_transaction_member(root, entry["backup"]))


def atomic_publish_files(
    files,
    *,
    transaction_root,
    transaction_name,
    remove_paths=(),
    expected_current_hashes=None,
):
    """Lock and transactionally publish a complete, previously validated bundle."""

    root = Path(transaction_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _transaction_lock(root, transaction_name):
        return _atomic_publish_files_unlocked(
            files,
            transaction_root=root,
            transaction_name=transaction_name,
            remove_paths=remove_paths,
            expected_current_hashes=expected_current_hashes,
        )
