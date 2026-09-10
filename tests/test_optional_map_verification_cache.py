"""Report generation must not treat a UI metadata cache as an integrity check."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from src import data_artifacts
from src.agents import pipeline
from src.coverage_map import load_all_sa2_geojson, load_all_sa2_profiles
from src.data_artifacts import (
    DataArtifactError,
    build_data_provenance,
    get_data_artifact_status,
    inspect_optional_sa2_map,
)
from src.data_paths import get_data_paths


@pytest.fixture(autouse=True)
def _isolated_content_cache():
    with data_artifacts._OPTIONAL_MAP_CONTENT_LOCK:
        data_artifacts._OPTIONAL_MAP_CONTENT_CACHE.clear()
    yield
    with data_artifacts._OPTIONAL_MAP_CONTENT_LOCK:
        data_artifacts._OPTIONAL_MAP_CONTENT_CACHE.clear()


def _bundle(tmp_path):
    profile = tmp_path / "profiles.csv"
    profile.write_text(
        "state_name,sa4_name,sa3_name,sa2_name,sa2_code\nQueensland,Test,Test,Test Town,101\n",
        encoding="utf-8",
    )
    boundary = tmp_path / "boundaries.geojson"
    boundary.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"sa2_code": "101"},
                        "geometry": {"type": "Point", "coordinates": [1, 2]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "sa2_map_bundle.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_rows": 1,
                "boundary_features": 1,
                "shared_sa2_codes": 1,
                "artifacts": {
                    key: {"size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    for key, path in (("profile", profile), ("boundary", boundary))
                },
            }
        ),
        encoding="utf-8",
    )
    return profile, boundary, manifest


def test_report_map_validation_is_not_satisfied_by_a_metadata_cache(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    assert inspect_optional_sa2_map(profile, boundary, manifest)["state"] == "bundle_verified"
    original_stat = profile.stat()
    profile.write_bytes(profile.read_bytes().replace(b"Test Town", b"Fake Town"))
    os.utime(profile, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    monkeypatch.setenv("BUSHFIRE_ALL_SA2_PROFILE_PATH", str(profile))
    monkeypatch.setenv("BUSHFIRE_ALL_SA2_BOUNDARY_PATH", str(boundary))

    # Force a realistic stale UI result, independent of platform inode/ctime behaviour.
    monkeypatch.setattr(
        data_artifacts,
        "_inspect_optional_sa2_map_cached",
        lambda *args: {"state": "bundle_verified", "status": "Cached", "installed": True, "error": ""},
    )

    with pytest.raises(DataArtifactError) as caught:
        pipeline.run_analysis_pipeline(
            "Test Town, Queensland",
            "Community",
            "Council community preparedness",
            [],
            "7-day action plan",
            "",
            area_selection={"level": "SA2", "area_name": "Test Town", "state": "Queensland"},
        )
    assert caught.value.code == "optional_map_unverified"


def test_forced_map_verification_rechecks_same_size_preserved_mtime_bytes(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    assert inspect_optional_sa2_map(profile, boundary, manifest)["state"] == "bundle_verified"
    original_stat = boundary.stat()
    boundary.write_bytes(boundary.read_bytes().replace(b"[1, 2]", b"[8, 9]"))
    os.utime(boundary, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    monkeypatch.setenv("BUSHFIRE_ALL_SA2_PROFILE_PATH", str(profile))
    monkeypatch.setenv("BUSHFIRE_ALL_SA2_BOUNDARY_PATH", str(boundary))

    status = get_data_artifact_status(get_data_paths(), verify_optional_map=True)

    assert status["optional_map_state"] == "invalid"
    assert "boundary hash" in status["optional_map_error"]


def _replace_preserving_mtime(path, old, new):
    previous = path.stat()
    staged = path.with_suffix(path.suffix + ".staged")
    staged.write_bytes(path.read_bytes().replace(old, new))
    os.utime(staged, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    os.replace(staged, path)
    assert path.stat().st_size == previous.st_size
    assert path.stat().st_mtime_ns == previous.st_mtime_ns


def test_same_size_preserved_mtime_replacement_invalidates_profile_and_geometry_caches(tmp_path):
    profile, boundary, manifest = _bundle(tmp_path)
    paths = SimpleNamespace(all_sa2_profile=profile, all_sa2_boundary=boundary)
    assert load_all_sa2_profiles(paths)[0]["sa2_name"] == "Test Town"
    assert load_all_sa2_geojson(data_paths=paths)["features"][0]["geometry"]["coordinates"] == [1, 2]
    assert inspect_optional_sa2_map(profile, boundary, manifest)["state"] == "bundle_verified"

    _replace_preserving_mtime(profile, b"Test Town", b"Next Town")
    _replace_preserving_mtime(boundary, b"[1, 2]", b"[8, 9]")

    assert load_all_sa2_profiles(paths)[0]["sa2_name"] == "Next Town"
    assert load_all_sa2_geojson(data_paths=paths)["features"][0]["geometry"]["coordinates"] == [8, 9]
    assert inspect_optional_sa2_map(profile, boundary, manifest)["state"] == "invalid"


def test_map_caches_do_not_cross_data_roots_with_identical_file_metadata(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_profile, first_boundary, _ = _bundle(first_root)
    second_profile, second_boundary, _ = _bundle(second_root)
    second_profile.write_bytes(second_profile.read_bytes().replace(b"Test Town", b"Next Town"))
    os.utime(second_profile, ns=(first_profile.stat().st_atime_ns, first_profile.stat().st_mtime_ns))
    first_paths = SimpleNamespace(all_sa2_profile=first_profile, all_sa2_boundary=first_boundary)
    second_paths = SimpleNamespace(all_sa2_profile=second_profile, all_sa2_boundary=second_boundary)

    assert load_all_sa2_profiles(first_paths)[0]["sa2_name"] == "Test Town"
    assert load_all_sa2_profiles(second_paths)[0]["sa2_name"] == "Next Town"
    assert load_all_sa2_profiles(first_paths)[0]["sa2_name"] == "Test Town"


@pytest.mark.parametrize("member", ["boundary", "manifest"])
def test_analysis_snapshot_pins_map_boundary_and_sidecar_not_only_profile(tmp_path, monkeypatch, member):
    profile, boundary, manifest = _bundle(tmp_path)
    monkeypatch.setenv("BUSHFIRE_ALL_SA2_PROFILE_PATH", str(profile))
    monkeypatch.setenv("BUSHFIRE_ALL_SA2_BOUNDARY_PATH", str(boundary))
    paths = get_data_paths()
    before = build_data_provenance(paths, include_all_sa2_profile=True)

    changed = boundary if member == "boundary" else manifest
    changed.write_bytes(changed.read_bytes() + b" ")
    after = build_data_provenance(paths, include_all_sa2_profile=True)

    assert before["all_sa2_profile"] == after["all_sa2_profile"]
    assert before != after
    assert "all_sa2_map_bundle" in after
    assert "all_sa2_boundary" in after
    assert "all_sa2_boundary" not in build_data_provenance(paths)


def _update_manifest_hashes(profile, boundary, manifest):
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    for key, path in (("profile", profile), ("boundary", boundary)):
        payload["artifacts"][key] = {
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    manifest.write_text(json.dumps(payload), encoding="utf-8")


def _observe_boundary_parsing(monkeypatch):
    observed = []
    original = data_artifacts._read_optional_boundary_codes

    def record(path, **kwargs):
        observed.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(data_artifacts, "_read_optional_boundary_codes", record)
    return observed


def test_identical_fresh_content_rehashes_every_file_without_parsing_json(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    first = inspect_optional_sa2_map(profile, boundary, manifest)
    assert first["state"] == "bundle_verified"
    original_hash = data_artifacts.sha256_file
    hashed = []

    def record_hash(path, **kwargs):
        hashed.append(path)
        return original_hash(path, **kwargs)

    def no_json_parse(*args, **kwargs):
        pytest.fail("Unchanged, successfully verified content must not parse the large GeoJSON again.")

    with monkeypatch.context() as patched:
        patched.setattr(data_artifacts, "sha256_file", record_hash)
        patched.setattr(data_artifacts.json, "loads", no_json_parse)
        second = inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)
    assert second == first
    assert all(hashed.count(path) == 2 for path in (profile, boundary, manifest))
    second["profile_rows"] = 999
    assert inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)["profile_rows"] == 1


def test_content_cache_rejects_in_place_same_size_same_mtime_tampering(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    assert inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)["state"] == "bundle_verified"
    parsed = _observe_boundary_parsing(monkeypatch)
    original = boundary.stat()
    boundary.write_bytes(boundary.read_bytes().replace(b"[1, 2]", b"[8, 9]"))
    os.utime(boundary, ns=(original.st_atime_ns, original.st_mtime_ns))

    result = inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)

    assert result["state"] == "invalid"
    assert "boundary hash" in result["error"]
    assert parsed == [boundary]
    assert len(data_artifacts._OPTIONAL_MAP_CONTENT_CACHE) == 1  # Only the earlier valid generation.


def test_changed_valid_content_gets_its_own_structure_validation(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    assert inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)["state"] == "bundle_verified"
    parsed = _observe_boundary_parsing(monkeypatch)
    boundary.write_bytes(boundary.read_bytes().replace(b"[1, 2]", b"[8, 9]"))
    _update_manifest_hashes(profile, boundary, manifest)

    assert inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)["state"] == "bundle_verified"
    assert inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)["state"] == "bundle_verified"
    assert parsed == [boundary]
    assert len(data_artifacts._OPTIONAL_MAP_CONTENT_CACHE) == 2


def test_changed_sidecar_cannot_reuse_a_successful_structure_result(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    assert inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)["state"] == "bundle_verified"
    parsed = _observe_boundary_parsing(monkeypatch)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["profile_rows"] = 2
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)

    assert result["state"] == "invalid"
    assert "profile_rows" in result["error"]
    assert parsed == [boundary]


def test_concurrent_fresh_checks_share_only_one_structure_parse(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    parsed = _observe_boundary_parsing(monkeypatch)
    ready = Barrier(4)

    def check(_number):
        ready.wait(timeout=5)
        return inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(check, range(4)))

    assert all(result["state"] == "bundle_verified" for result in results)
    assert parsed == [boundary]


def test_positive_content_cache_is_bounded_and_scoped_to_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(data_artifacts, "_OPTIONAL_MAP_CONTENT_CACHE_SIZE", 3)
    parsed = _observe_boundary_parsing(monkeypatch)
    bundles = []
    for number in range(4):
        directory = tmp_path / str(number)
        directory.mkdir()
        bundles.append(_bundle(directory))
        assert inspect_optional_sa2_map(*bundles[-1], verify_content=True)["state"] == "bundle_verified"
        assert len(data_artifacts._OPTIONAL_MAP_CONTENT_CACHE) <= 3
    assert len(parsed) == 4  # Equal content at different paths is independently verified.
    assert len(data_artifacts._OPTIONAL_MAP_CONTENT_CACHE) == 3
    assert inspect_optional_sa2_map(*bundles[0], verify_content=True)["state"] == "bundle_verified"
    assert len(parsed) == 5  # The evicted oldest bundle requires structural validation again.


def test_invalid_content_is_never_saved_in_positive_cache(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    boundary.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    _update_manifest_hashes(profile, boundary, manifest)
    parsed = _observe_boundary_parsing(monkeypatch)

    for _attempt in range(2):
        assert inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)["state"] == "invalid"
    assert parsed == [boundary, boundary]
    assert not data_artifacts._OPTIONAL_MAP_CONTENT_CACHE


def test_parsed_bytes_must_match_cache_identity_even_if_original_is_restored(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    original_bytes = boundary.read_bytes()
    parse = data_artifacts._read_optional_boundary_codes

    def replace_before_parse(path, **kwargs):
        path.write_bytes(original_bytes.replace(b"[1, 2]", b"[8, 9]"))
        try:
            return parse(path, **kwargs)
        finally:
            path.write_bytes(original_bytes)

    monkeypatch.setattr(data_artifacts, "_read_optional_boundary_codes", replace_before_parse)
    result = inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)

    assert result["state"] == "invalid"
    assert "changed before parsing" in result["error"]
    assert not data_artifacts._OPTIONAL_MAP_CONTENT_CACHE


def test_content_cache_hit_rechecks_identity_before_returning(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    assert inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)["state"] == "bundle_verified"
    original_signature = data_artifacts._optional_map_content_signature
    calls = 0

    def change_after_first_fingerprint(paths):
        nonlocal calls
        calls += 1
        signature = original_signature(paths)
        if calls == 1:
            boundary.write_bytes(boundary.read_bytes().replace(b"[1, 2]", b"[8, 9]"))
        return signature

    monkeypatch.setattr(data_artifacts, "_optional_map_content_signature", change_after_first_fingerprint)
    result = inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)

    assert result["state"] == "invalid"
    assert "changed during content verification" in result["error"]
    assert calls == 2


def test_sidecar_appearing_mid_check_cannot_upgrade_unbound_structure_to_verified(tmp_path, monkeypatch):
    profile, boundary, manifest = _bundle(tmp_path)
    manifest.unlink()
    parse = data_artifacts._read_optional_boundary_codes

    def publish_different_generation_after_parsing(path, **kwargs):
        codes = parse(path, **kwargs)
        path.write_bytes(b"not valid JSON")
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile_rows": 1,
                    "boundary_features": 1,
                    "shared_sa2_codes": 1,
                    "artifacts": {},
                }
            ),
            encoding="utf-8",
        )
        _update_manifest_hashes(profile, path, manifest)
        return codes

    with monkeypatch.context() as patched:
        patched.setattr(data_artifacts, "_read_optional_boundary_codes", publish_different_generation_after_parsing)
        result = inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)

    assert result["state"] == "invalid"
    assert "appeared during verification" in result["error"]
    assert not data_artifacts._OPTIONAL_MAP_CONTENT_CACHE
    assert inspect_optional_sa2_map(profile, boundary, manifest, verify_content=True)["state"] == "invalid"
