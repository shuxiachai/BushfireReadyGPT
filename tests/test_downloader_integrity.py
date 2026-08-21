import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from src import data_artifacts
from src.coverage_map import has_all_australia_data
from src.data_artifacts import (
    atomic_publish_files,
    download_url_bytes,
    inspect_optional_sa2_map,
    recover_atomic_publish,
    render_updated_manifest,
)
from src.ui.map_views import _selectbox_with_default

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script(name):
    path = PROJECT_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _valid_optional_map(tmp_path, *, boundary_code="101"):
    profile = tmp_path / "profiles.csv"
    profile.write_text(
        "state_name,sa4_name,sa3_name,sa2_name,sa2_code\nQueensland,Cairns,Cairns,Cairns City,101\n",
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
                        "properties": {"sa2_code_2021": boundary_code},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return profile, boundary


def test_optional_map_status_distinguishes_all_four_states(tmp_path):
    profile = tmp_path / "profiles.csv"
    boundary = tmp_path / "boundaries.geojson"
    assert inspect_optional_sa2_map(profile, boundary)["state"] == "not_installed"

    profile.write_text("sa2_code\n101\n", encoding="utf-8")
    assert inspect_optional_sa2_map(profile, boundary)["state"] == "incomplete"

    boundary.write_text("not-json", encoding="utf-8")
    assert inspect_optional_sa2_map(profile, boundary)["state"] == "invalid"

    profile, boundary = _valid_optional_map(tmp_path)
    status = inspect_optional_sa2_map(profile, boundary)
    assert status["state"] == "present_unverified"
    assert status["installed"] is False
    assert status["shared_sa2_codes"] == 1
    paths = SimpleNamespace(
        all_sa2_profile=profile,
        all_sa2_boundary=boundary,
    )
    assert has_all_australia_data(data_paths=paths) is False


def test_optional_map_rejects_files_without_an_sa2_id_join(tmp_path):
    profile, boundary = _valid_optional_map(tmp_path, boundary_code="999")

    status = inspect_optional_sa2_map(profile, boundary)

    assert status["state"] == "invalid"
    assert "SA2 code sets differ" in status["error"]


def test_optional_map_requires_exact_code_sets_even_when_they_overlap(tmp_path):
    profile, boundary = _valid_optional_map(tmp_path)
    payload = json.loads(boundary.read_text(encoding="utf-8"))
    extra = json.loads(json.dumps(payload["features"][0]))
    extra["properties"]["sa2_code_2021"] = "102"
    payload["features"].append(extra)
    boundary.write_text(json.dumps(payload), encoding="utf-8")

    status = inspect_optional_sa2_map(profile, boundary)

    assert status["state"] == "invalid"
    assert "1 boundary-only" in status["error"]


def test_optional_map_allows_non_spatial_statistical_sa2_features(tmp_path):
    profile = tmp_path / "profiles.csv"
    profile.write_text(
        "state_name,sa4_name,sa3_name,sa2_name,sa2_code\n"
        "Queensland,Cairns,Cairns,Cairns City,101\n"
        "Other,Other,Other,Non-spatial,199999499\n",
        encoding="utf-8",
    )
    boundary = tmp_path / "boundaries.geojson"
    boundary.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": {"sa2_code_2021": "101"},
                        "geometry": {"type": "Point", "coordinates": [0, 0]},
                    },
                    {
                        "properties": {"sa2_code_2021": "199999499"},
                        "geometry": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    status = inspect_optional_sa2_map(profile, boundary)

    assert status["state"] == "present_unverified"
    assert status["boundary_features"] == 2


def test_national_selector_gate_rejects_empty_or_corrupt_files(tmp_path):
    profile = tmp_path / "profiles.csv"
    boundary = tmp_path / "boundaries.geojson"
    profile.write_text("", encoding="utf-8")
    boundary.write_text("{}", encoding="utf-8")
    paths = SimpleNamespace(
        all_sa2_profile=profile,
        all_sa2_boundary=boundary,
    )

    assert has_all_australia_data(data_paths=paths) is False
    assert _selectbox_with_default("Empty", [], "empty_options") is None


def test_optional_map_bundle_hashes_and_counts_are_verified(tmp_path):
    profile, boundary = _valid_optional_map(tmp_path)
    metadata = tmp_path / "sa2_map_bundle.json"
    metadata.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_rows": 1,
                "boundary_features": 1,
                "shared_sa2_codes": 1,
                "artifacts": {
                    "profile": {
                        "size_bytes": profile.stat().st_size,
                        "sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
                    },
                    "boundary": {
                        "size_bytes": boundary.stat().st_size,
                        "sha256": hashlib.sha256(boundary.read_bytes()).hexdigest(),
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    status = inspect_optional_sa2_map(profile, boundary, metadata)

    assert status["state"] == "bundle_verified"
    assert status["installed"] is True
    paths = SimpleNamespace(
        all_sa2_profile=profile,
        all_sa2_boundary=boundary,
    )
    assert has_all_australia_data(data_paths=paths) is True


def test_manifest_writing_downloaders_share_one_transaction_domain():
    community = _load_script("download_abs_community_profiles")
    asgs = _load_script("download_abs_asgs_allocations")

    assert community.BUNDLED_CORE_TRANSACTION_NAME == data_artifacts.BUNDLED_CORE_TRANSACTION_NAME
    assert asgs.BUNDLED_CORE_TRANSACTION_NAME == data_artifacts.BUNDLED_CORE_TRANSACTION_NAME


def test_optional_map_large_file_inspection_is_cached_by_signature(tmp_path):
    data_artifacts._inspect_optional_sa2_map_cached.cache_clear()
    profile, boundary = _valid_optional_map(tmp_path)

    inspect_optional_sa2_map(profile, boundary)
    before = data_artifacts._inspect_optional_sa2_map_cached.cache_info()
    inspect_optional_sa2_map(profile, boundary)
    after = data_artifacts._inspect_optional_sa2_map_cached.cache_info()

    assert after.hits == before.hits + 1


def test_atomic_group_failure_restores_every_old_file(monkeypatch, tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"old-first")
    second.write_bytes(b"old-second")
    real_replace = data_artifacts.os.replace
    failed = False

    def fail_second_publish(source, destination):
        nonlocal failed
        if not failed and Path(destination) == second and Path(source).name.endswith(".stage"):
            failed = True
            raise OSError("simulated second-file failure")
        return real_replace(source, destination)

    monkeypatch.setattr(data_artifacts.os, "replace", fail_second_publish)
    with pytest.raises(OSError, match="second-file failure"):
        atomic_publish_files(
            {first: b"new-first", second: b"new-second"},
            transaction_root=tmp_path,
            transaction_name="failure-test",
        )

    assert first.read_bytes() == b"old-first"
    assert second.read_bytes() == b"old-second"
    assert not list(tmp_path.glob(".*.stage"))
    assert not list(tmp_path.glob(".*.backup"))
    assert not (tmp_path / ".failure-test.transaction.json").exists()


def test_recovery_rolls_back_a_prepared_interrupted_transaction(tmp_path):
    target = tmp_path / "profiles.csv"
    target.write_bytes(b"old")
    stage = tmp_path / ".profiles.csv.tx.stage"
    backup = tmp_path / ".profiles.csv.tx.backup"
    stage.write_bytes(b"new")
    os.replace(target, backup)
    os.replace(stage, target)
    journal = {
        "schema_version": 1,
        "phase": "prepared",
        "transaction_id": "tx",
        "entries": [
            {
                "mode": "write",
                "target": "profiles.csv",
                "stage": ".profiles.csv.tx.stage",
                "backup": ".profiles.csv.tx.backup",
                "existed": True,
            }
        ],
    }
    (tmp_path / ".restart-test.transaction.json").write_text(json.dumps(journal), encoding="utf-8")

    assert recover_atomic_publish(tmp_path, transaction_name="restart-test") is True
    assert target.read_bytes() == b"old"
    assert not backup.exists()
    assert not (tmp_path / ".restart-test.transaction.json").exists()


def test_atomic_group_can_remove_stale_files_in_the_same_commit(tmp_path):
    current = tmp_path / "current.geojson"
    stale = tmp_path / "stale.geojson"
    current.write_bytes(b"old")
    stale.write_bytes(b"stale")

    atomic_publish_files(
        {current: b"new"},
        transaction_root=tmp_path,
        transaction_name="remove-test",
        remove_paths=[stale],
    )

    assert current.read_bytes() == b"new"
    assert not stale.exists()


def test_atomic_group_rejects_a_second_owner_lock(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"old")
    lock = tmp_path / ".lock-test.transaction.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="already running"):
        atomic_publish_files(
            {target: b"new"},
            transaction_root=tmp_path,
            transaction_name="lock-test",
        )

    assert target.read_bytes() == b"old"
    assert lock.exists()


def test_atomic_group_recovers_an_abandoned_stale_lock(monkeypatch, tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"old")
    lock = tmp_path / ".stale-test.transaction.lock"
    lock.write_text(json.dumps({"pid": 999_999_999}), encoding="utf-8")
    stale_time = 1
    os.utime(lock, (stale_time, stale_time))
    monkeypatch.setattr(data_artifacts, "_pid_is_running", lambda _pid: False)

    atomic_publish_files(
        {target: b"new"},
        transaction_root=tmp_path,
        transaction_name="stale-test",
    )

    assert target.read_bytes() == b"new"
    assert not lock.exists()


def test_windows_pid_probe_never_calls_os_kill(monkeypatch):
    calls = []
    monkeypatch.setattr(data_artifacts.os, "name", "nt")
    monkeypatch.setattr(
        data_artifacts,
        "_windows_pid_is_running",
        lambda pid: calls.append(pid) or True,
    )
    monkeypatch.setattr(
        data_artifacts.os,
        "kill",
        lambda *_args: pytest.fail("os.kill must not be called on Windows"),
    )

    assert data_artifacts._pid_is_running(987_654_321) is True
    assert calls == [987_654_321]


def test_atomic_group_rejects_a_changed_manifest_base(tmp_path):
    manifest = tmp_path / "manifest.json"
    data_file = tmp_path / "data.csv"
    manifest.write_bytes(b"old-manifest")
    data_file.write_bytes(b"old-data")
    expected = hashlib.sha256(manifest.read_bytes()).hexdigest()
    manifest.write_bytes(b"concurrent-manifest")

    with pytest.raises(RuntimeError, match="base changed"):
        atomic_publish_files(
            {data_file: b"new-data", manifest: b"new-manifest"},
            transaction_root=tmp_path,
            transaction_name="cas-test",
            expected_current_hashes={manifest: expected},
        )

    assert data_file.read_bytes() == b"old-data"
    assert manifest.read_bytes() == b"concurrent-manifest"


class _FakeResponse:
    status = 200
    headers = {}

    def __init__(self, payload=b"ok"):
        self.payload = payload

    def getcode(self):
        return self.status

    def read(self, size=None):
        return self.payload if size is None else self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_network_download_retries_5xx_then_succeeds(monkeypatch):
    attempts = iter(
        [
            HTTPError("https://example.test", 503, "down", None, None),
            HTTPError("https://example.test", 500, "down", None, None),
            _FakeResponse(b"complete"),
        ]
    )
    calls = 0

    def fake_urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(data_artifacts, "urlopen", fake_urlopen)
    monkeypatch.setattr(data_artifacts.time, "sleep", lambda _seconds: None)

    assert download_url_bytes("https://example.test", timeout=1) == b"complete"
    assert calls == 3


def test_network_download_does_not_retry_4xx(monkeypatch):
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise HTTPError("https://example.test", 404, "missing", None, None)

    monkeypatch.setattr(data_artifacts, "urlopen", fail)

    with pytest.raises(ValueError, match="HTTP 404"):
        download_url_bytes("https://example.test", timeout=1)
    assert calls == 1


def test_network_download_rejects_non_https_and_oversized_payloads(monkeypatch):
    with pytest.raises(ValueError, match="HTTPS"):
        download_url_bytes("file:///tmp/data.json", timeout=1)
    monkeypatch.setattr(
        data_artifacts,
        "urlopen",
        lambda *_args, **_kwargs: _FakeResponse(b"too-large"),
    )

    with pytest.raises(ValueError, match="size limit"):
        download_url_bytes("https://example.test", timeout=1, max_bytes=3)


def test_manifest_refresh_updates_only_declared_artifact_integrity(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bundled_core": {
                    "artifacts": [
                        {
                            "path": "processed/example.csv",
                            "size_bytes": 1,
                            "sha256": "0" * 64,
                            "row_count": 0,
                            "scope": "preserved scope",
                            "source_period": "preserved period",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    content = b"id\n1\n"

    refreshed = json.loads(
        render_updated_manifest(
            manifest,
            {"processed/example.csv": {"data": content, "row_count": 1}},
            generated_at_utc="2026-08-21T01:02:03+00:00",
        )
    )

    entry = refreshed["bundled_core"]["artifacts"][0]
    assert entry["size_bytes"] == len(content)
    assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    assert entry["row_count"] == 1
    assert entry["scope"] == "preserved scope"
    assert entry["source_period"] == "preserved period"
    assert refreshed["last_refreshed_artifacts"] == ["processed/example.csv"]


def test_community_download_requires_every_configured_sa2_name():
    module = _load_script("download_abs_community_profiles")
    profile = {
        "features": [
            {
                "attributes": {
                    "sa2_code_2021": "1",
                    "sa2_name_2021": "Alpha",
                    module.POPULATION_FIELD: 100,
                    module.LANGUAGE_COUNT_FIELD: 1,
                    **{field: 1 for field in module.OLDER_COUNT_FIELDS},
                }
            }
        ]
    }
    boundary = {
        "features": [
            {
                "properties": {"sa2_code_2021": "1", "sa2_name_2021": "Alpha"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }
        ]
    }
    regions = [{"location": "Test", "sa2_names": ["Alpha", "Beta"]}]

    with pytest.raises(ValueError, match="coverage is incomplete"):
        module.validate_configured_coverage(profile, boundary, regions)


def test_national_download_rejects_incomplete_profile_boundary_id_join():
    module = _load_script("download_abs_sa2_all")
    profile_values = {
        "sa2_code_2021": "1",
        "sa2_name_2021": "Alpha",
        module.POPULATION_FIELD: 100,
        module.LANGUAGE_COUNT_FIELD: 1,
        **{field: 1 for field in module.OLDER_COUNT_FIELDS},
    }
    boundary_values = {
        "sa2_code_2021": "2",
        "sa2_name_2021": "Beta",
        "sa3_code_2021": "20",
        "sa3_name_2021": "Beta SA3",
        "sa4_code_2021": "200",
        "sa4_name_2021": "Beta SA4",
        "state_code_2021": "2",
        "state_name_2021": "Victoria",
    }

    with pytest.raises(ValueError, match="join is incomplete"):
        module.validate_layers(
            {"features": [{"attributes": profile_values}]},
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "properties": boundary_values,
                        "geometry": {"type": "Point", "coordinates": [0, 0]},
                    }
                ],
            },
        )


def test_national_download_validator_allows_some_null_geometry():
    module = _load_script("download_abs_sa2_all")

    def profile_feature(code):
        return {
            "attributes": {
                "sa2_code_2021": code,
                "sa2_name_2021": f"Area {code}",
                module.POPULATION_FIELD: 100,
                module.LANGUAGE_COUNT_FIELD: 1,
                **{field: 1 for field in module.OLDER_COUNT_FIELDS},
            }
        }

    def boundary_feature(code, geometry):
        return {
            "properties": {
                "sa2_code_2021": code,
                "sa2_name_2021": f"Area {code}",
                "sa3_code_2021": "10",
                "sa3_name_2021": "SA3",
                "sa4_code_2021": "100",
                "sa4_name_2021": "SA4",
                "state_code_2021": "1",
                "state_name_2021": "State",
            },
            "geometry": geometry,
        }

    module.validate_layers(
        {"features": [profile_feature("101"), profile_feature("199999499")]},
        {
            "type": "FeatureCollection",
            "features": [
                boundary_feature("101", {"type": "Point", "coordinates": [0, 0]}),
                boundary_feature("199999499", None),
            ],
        },
    )


@pytest.mark.parametrize(
    "script_name",
    [
        "download_abs_community_profiles",
        "download_abs_asgs_allocations",
        "download_abs_sa2_all",
    ],
)
def test_downloaders_resolve_explicit_data_directory(script_name, tmp_path):
    module = _load_script(script_name)

    resolved = module.resolve_paths(tmp_path / "custom-data")

    assert resolved[0] == (tmp_path / "custom-data").resolve()
