import json
import os
import shutil

import pytest

from src import data_artifacts
from src.agents.pipeline import run_analysis_pipeline
from src.data_artifacts import (
    DataArtifactError,
    atomic_publish_files,
    atomic_write_text,
    get_data_artifact_status,
    render_updated_manifest,
    sha256_file,
    validate_data_manifest,
)
from src.data_paths import PROJECT_ROOT, DataPaths, get_data_paths


def _copy_bundled_core(destination):
    source = PROJECT_ROOT / "data_australia"
    payload = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "manifest.json", destination / "manifest.json")
    for artifact in payload["bundled_core"]["artifacts"]:
        source_path = source / artifact["path"]
        destination_path = destination / artifact["path"]
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
    return payload


def _clear_data_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("BUSHFIRE_"):
            monkeypatch.delenv(name, raising=False)


def test_repository_manifest_matches_every_bundled_core_artifact():
    paths = get_data_paths()

    result = validate_data_manifest(paths.manifest, data_dir=paths.data_dir)

    assert result["core_ready"] is True
    assert len(result["verified_artifacts"]) == 11
    assert "all_australia_map" in result["optional_capabilities"]
    assert all(item["sha256"] for item in result["verified_artifacts"])


def test_manifest_rejects_a_missing_required_artifact(tmp_path):
    data_dir = tmp_path / "data_australia"
    payload = _copy_bundled_core(data_dir)
    missing_relative_path = payload["bundled_core"]["artifacts"][0]["path"]
    (data_dir / missing_relative_path).unlink()

    with pytest.raises(DataArtifactError) as caught:
        validate_data_manifest(data_dir / "manifest.json", data_dir=data_dir)

    assert caught.value.code == "artifact_missing"
    assert caught.value.relative_path == missing_relative_path


def test_manifest_rejects_same_size_content_tampering(monkeypatch, tmp_path):
    _clear_data_environment(monkeypatch)
    data_dir = tmp_path / "data_australia"
    payload = _copy_bundled_core(data_dir)
    relative_path = payload["bundled_core"]["artifacts"][0]["path"]
    artifact_path = data_dir / relative_path
    original = artifact_path.read_bytes()
    replacement = b"X" if original[:1] != b"X" else b"Y"
    artifact_path.write_bytes(replacement + original[1:])

    with pytest.raises(DataArtifactError) as caught:
        validate_data_manifest(data_dir / "manifest.json", data_dir=data_dir)

    assert caught.value.code == "hash_mismatch"
    assert caught.value.relative_path == relative_path

    status = get_data_artifact_status(DataPaths.from_env(project_root=tmp_path))
    assert status["core_status"] == "Bundled core invalid"
    assert status["integrity_status"] == "Bundled data mismatch"


def test_manifest_rejects_path_traversal_before_opening_artifact(tmp_path):
    data_dir = tmp_path / "data_australia"
    data_dir.mkdir()
    manifest = {
        "schema_version": 1,
        "bundled_core": {
            "artifacts": [
                {
                    "path": "../outside.csv",
                    "size_bytes": 0,
                    "row_count": 0,
                    "sha256": "0" * 64,
                    "scope": "test",
                    "source_period": "test",
                }
            ]
        },
        "optional_capabilities": [],
    }
    (data_dir / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(DataArtifactError) as caught:
        validate_data_manifest(data_dir / "manifest.json", data_dir=data_dir)

    assert caught.value.code == "unsafe_path"


def test_optional_national_map_can_be_absent_while_core_is_ready(
    monkeypatch,
    tmp_path,
):
    _clear_data_environment(monkeypatch)
    project_root = tmp_path / "clean-clone"
    _copy_bundled_core(project_root / "data_australia")
    paths = DataPaths.from_env(project_root=project_root)

    status = get_data_artifact_status(paths)

    assert status["core_status"] == "Bundled core ready"
    assert status["core_ready"] is True
    assert status["optional_map_status"] == "Optional map not installed"
    assert status["optional_map_installed"] is False
    assert status["integrity_status"] == "Matches bundled manifest"


def test_custom_runtime_path_is_labelled_unverified(monkeypatch, tmp_path):
    _clear_data_environment(monkeypatch)
    project_root = tmp_path / "project"
    data_dir = project_root / "data_australia"
    _copy_bundled_core(data_dir)
    override = tmp_path / "custom-community.csv"
    shutil.copy2(data_dir / "processed/community_profiles.csv", override)
    monkeypatch.setenv("BUSHFIRE_COMMUNITY_PROFILE_PATH", str(override))
    paths = DataPaths.from_env(project_root=project_root)

    status = get_data_artifact_status(paths)

    assert status["core_ready"] is True
    assert status["custom_data"] is True
    assert status["integrity_status"] == "Unverified custom data"


def test_optional_map_path_override_is_labelled_unverified(monkeypatch, tmp_path):
    _clear_data_environment(monkeypatch)
    project_root = tmp_path / "project"
    _copy_bundled_core(project_root / "data_australia")
    monkeypatch.setenv(
        "BUSHFIRE_ALL_SA2_PROFILE_PATH",
        str(tmp_path / "operator-map" / "profiles.csv"),
    )

    status = get_data_artifact_status(DataPaths.from_env(project_root=project_root))

    assert status["core_ready"] is True
    assert status["custom_data"] is True
    assert status["integrity_status"] == "Unverified custom data"


def test_unverified_optional_map_cannot_enter_analysis(monkeypatch, tmp_path):
    _clear_data_environment(monkeypatch)
    project_root = tmp_path / "project"
    data_dir = project_root / "data_australia"
    _copy_bundled_core(data_dir)
    profile = data_dir / "processed" / "sa2_profiles_all.csv"
    profile.write_text(
        "state_name,sa4_name,sa3_name,sa2_name,sa2_code\nQueensland,Cairns,Cairns,Cairns City,101\n",
        encoding="utf-8",
    )
    boundary = data_dir / "processed" / "sa2_boundaries_all.geojson"
    boundary.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {"sa2_code_2021": "101"},
                        "geometry": {"type": "Point", "coordinates": [145.8, -16.9]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    paths = DataPaths.from_env(project_root=project_root)

    with pytest.raises(DataArtifactError) as caught:
        run_analysis_pipeline(
            location="Cairns, Queensland",
            audience="community residents",
            scenario="Community preparedness",
            concerns=["Evacuation"],
            timeframe="7-day action plan",
            extra_context="",
            area_selection={
                "state": "Queensland",
                "level": "SA2",
                "area_name": "Cairns City",
            },
            data_paths=paths,
        )

    assert caught.value.code == "optional_map_unverified"


def test_atomic_write_failure_preserves_old_file_and_removes_staging_file(
    monkeypatch,
    tmp_path,
):
    target = tmp_path / "profiles.csv"
    target.write_text("trusted-old-data\n", encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(data_artifacts.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write_text(target, "partial-new-data\n")

    assert target.read_text(encoding="utf-8") == "trusted-old-data\n"
    assert list(tmp_path.glob(".profiles.csv.*.tmp")) == []


def test_core_refresh_publishes_matching_data_and_manifest_together(tmp_path):
    data_dir = tmp_path / "data_australia"
    _copy_bundled_core(data_dir)
    manifest = data_dir / "manifest.json"
    profile = data_dir / "processed" / "community_profiles.csv"
    base_manifest_sha = sha256_file(manifest)
    refreshed_profile = profile.read_bytes().replace(b"Cairns", b"Cairns refreshed", 1)
    refreshed_manifest = render_updated_manifest(
        manifest,
        {
            "processed/community_profiles.csv": {
                "data": refreshed_profile,
                "row_count": 4,
            }
        },
        generated_at_utc="2026-08-21T02:03:04+00:00",
    )

    atomic_publish_files(
        {profile: refreshed_profile, manifest: refreshed_manifest},
        transaction_root=data_dir,
        transaction_name="manifest-refresh-test",
        expected_current_hashes={manifest: base_manifest_sha},
    )

    result = validate_data_manifest(manifest, data_dir=data_dir)
    assert result["core_ready"] is True
    assert sha256_file(profile) in {artifact["sha256"] for artifact in result["verified_artifacts"]}
