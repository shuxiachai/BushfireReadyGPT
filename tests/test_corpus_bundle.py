import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from scripts.prepare_private_corpus import main
from src import corpus_bundle as bundles
from src.rag.errors import RagError
from src.rag.index import build_rag_index
from src.rag.settings import RagSettings


class _Embedding:
    model = "synthetic-test-vector"

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
def indexed(tmp_path):
    root = tmp_path / "original-rag"
    bundles.create_test_corpus_bundle(root)
    catalog = yaml.safe_load((root / "sources.yml").read_bytes())
    catalog["sources"][0]["reuse_status"] = "permission_review_required"
    catalog["sources"][0]["licence"] = "Synthetic terms requiring review; do not replace or relabel this field."
    (root / "sources.yml").write_text(yaml.safe_dump(catalog), encoding="utf-8")
    settings = RagSettings(
        rag_dir=root,
        sources_path=root / "sources.yml",
        raw_dir=root / "raw",
        index_dir=root / "index",
        embedding_base_url="http://127.0.0.1:11434",
        embedding_model=_Embedding.model,
        embedding_timeout_seconds=1,
        embedding_batch_size=8,
        top_k=8,
        score_threshold=0.35,
    )
    index = build_rag_index(settings, _Embedding())
    return settings, index


def _rewrite_manifest(root, transform):
    path = root / bundles.BUNDLE_MANIFEST
    manifest = json.loads(path.read_bytes())
    manifest.pop("manifest_sha256")
    transform(manifest)
    path.write_bytes(bundles._canonical(bundles._with_hash(manifest)))


def _source_path(root):
    return root / "raw" / "synthetic_qld_test.txt"


def test_private_packaging_requires_explicit_terms_acknowledgement(indexed, tmp_path):
    settings, _ = indexed
    with pytest.raises(bundles.CorpusBundleError, match="acknowledge"):
        bundles.package_private_corpus(settings, tmp_path / "private")
    assert not (tmp_path / "private").exists()


def test_private_bundle_preserves_original_catalog_and_index_bound_bytes(indexed, tmp_path):
    settings, index = indexed
    original_catalog = settings.sources_path.read_bytes()
    original_text = _source_path(settings.rag_dir).read_bytes()
    output = tmp_path / "private"
    manifest = bundles.package_private_corpus(settings, output, acknowledge_source_terms=True)
    assert bundles.validate_corpus_bundle(output) == manifest
    assert (output / "sources.yml").read_bytes() == original_catalog
    assert _source_path(output).read_bytes() == original_text
    assert settings.sources_path.read_bytes() == original_catalog
    assert _source_path(settings.rag_dir).read_bytes() == original_text
    assert manifest["source_index_manifest_sha256"] == index["manifest_sha256"]
    assert manifest["catalog_sha256"] == hashlib.sha256(original_catalog).hexdigest()
    assert manifest["usage_intent"] == "private_research_noncommercial"
    assert manifest["source_terms_acknowledged"] is True
    assert manifest["fixture_only"] is False
    assert "not an HTTP retrieval receipt" in manifest["mtime_provenance"]
    assert "observed_file_mtime_utc" in manifest["files"][0]
    assert "retrieved_at_utc" not in manifest["files"][0]
    assert not (output / "index").exists()


@pytest.mark.parametrize("changed", ["catalog", "source", "index"])
def test_packaging_rejects_stale_or_tampered_index(indexed, tmp_path, changed):
    settings, _ = indexed
    if changed == "catalog":
        with settings.sources_path.open("ab") as stream:
            stream.write(b"\n# changed catalog\n")
    elif changed == "source":
        _source_path(settings.rag_dir).write_bytes(b"changed text")
    else:
        (settings.index_dir / "manifest.json").write_bytes(b"{}")
    with pytest.raises(RagError):
        bundles.package_private_corpus(settings, tmp_path / "private", acknowledge_source_terms=True)
    assert not (tmp_path / "private").exists()


def test_install_is_a_new_verified_rag_root(tmp_path):
    source = tmp_path / "bundle"
    original = bundles.create_test_corpus_bundle(source)
    output = bundles.install_corpus_bundle(source, tmp_path / "installed")
    assert output == tmp_path / "installed"
    assert bundles.validate_corpus_bundle(output) == original
    assert (output / "sources.yml").read_bytes() == (source / "sources.yml").read_bytes()
    assert _source_path(output).read_bytes() == _source_path(source).read_bytes()


@pytest.mark.parametrize("nonempty", [False, True])
def test_existing_target_is_never_modified(tmp_path, nonempty):
    source = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(source)
    target = tmp_path / "existing"
    target.mkdir()
    if nonempty:
        (target / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(bundles.CorpusBundleError, match="already exists"):
        bundles.install_corpus_bundle(source, target)
    assert target.is_dir()
    assert list(target.iterdir()) == ([target / "keep.txt"] if nonempty else [])


@pytest.mark.parametrize("relative", ["..", "nested"])
def test_bundle_and_install_target_cannot_overlap(tmp_path, relative):
    source = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(source)
    with pytest.raises(bundles.CorpusBundleError, match="separate"):
        bundles.install_corpus_bundle(source, source / relative)


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.txt",
        "/raw/absolute.txt",
        "raw/../outside.txt",
        "raw//double.txt",
        "raw/./dot.txt",
        "other/file.txt",
        "raw\\windows.txt",
        "raw/C:drive.txt",
        "raw/NUL",
        "raw/trailing.",
        "raw/control\x01.txt",
    ],
)
def test_bundle_rejects_unsafe_manifest_paths(tmp_path, relative):
    root = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(root)
    _rewrite_manifest(root, lambda value: value["files"][0].update(path=relative))
    with pytest.raises(bundles.CorpusBundleError):
        bundles.validate_corpus_bundle(root)


@pytest.mark.parametrize("changed", ["catalog", "source", "manifest", "extra_file", "extra_dir", "missing_source"])
def test_validation_rejects_tampering_and_undeclared_files_before_install(tmp_path, changed):
    root = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(root)
    if changed == "catalog":
        (root / "sources.yml").write_bytes(b"schema_version: 1\nsources: []\n")
    elif changed == "source":
        _source_path(root).write_bytes(b"tampered source")
    elif changed == "manifest":
        (root / bundles.BUNDLE_MANIFEST).write_bytes(b"{}")
    elif changed == "extra_file":
        (root / "secret.env").write_text("never included", encoding="utf-8")
    elif changed == "extra_dir":
        (root / "extra-empty").mkdir()
    else:
        _source_path(root).unlink()
    with pytest.raises(bundles.CorpusBundleError):
        bundles.install_corpus_bundle(root, tmp_path / "installed")
    assert not (tmp_path / "installed").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("fixture_only", "false"),
        ("source_terms_acknowledged", "true"),
        ("source_index_manifest_sha256", "f" * 64),
        ("catalog_size_bytes", True),
        ("source_count", 0),
        ("source_count", 65),
        ("payload_size_bytes", 1),
        ("mtime_provenance", "HTTP download receipt"),
        ("usage_intent", "commercial_redistribution_licensed"),
    ],
)
def test_bundle_rejects_invalid_metadata(tmp_path, field, value):
    root = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(root)
    _rewrite_manifest(root, lambda data: data.update({field: value}))
    with pytest.raises(bundles.CorpusBundleError):
        bundles.validate_corpus_bundle(root)


@pytest.mark.parametrize("value", ["", "today", "2026-09-10T00:00:00", "2026-09-10T00:00:00+10:00", None])
def test_bundle_requires_explicit_utc_observation_timestamp(tmp_path, value):
    root = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(root)
    _rewrite_manifest(root, lambda data: data["files"][0].update(observed_file_mtime_utc=value))
    with pytest.raises(bundles.CorpusBundleError, match="UTC"):
        bundles.validate_corpus_bundle(root)


def test_bundle_rejects_duplicate_json_keys(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    (root / bundles.BUNDLE_MANIFEST).write_text('{"schema": "first", "schema": "second"}', encoding="utf-8")
    with pytest.raises(bundles.CorpusBundleError, match="JSON"):
        bundles.validate_corpus_bundle(root)


def test_bundle_bounds_are_enforced_before_publication(indexed, tmp_path, monkeypatch):
    settings, _ = indexed
    monkeypatch.setattr(bundles, "MAX_FILE_BYTES", 32)
    with pytest.raises(bundles.CorpusBundleError, match="size limit"):
        bundles.package_private_corpus(settings, tmp_path / "private", acknowledge_source_terms=True)
    assert not (tmp_path / "private").exists()


def test_total_includes_manifest_and_catalog(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    manifest = bundles.create_test_corpus_bundle(root)
    monkeypatch.setattr(bundles, "MAX_BUNDLE_BYTES", manifest["payload_size_bytes"])
    with pytest.raises(bundles.CorpusBundleError, match="total size"):
        bundles.validate_corpus_bundle(root)


def test_installed_mode_allows_only_index_and_named_locks(tmp_path):
    root = tmp_path / "bundle"
    manifest = bundles.create_test_corpus_bundle(root)
    (root / "index" / "qdrant").mkdir(parents=True)
    (root / "index" / "qdrant" / "storage.sqlite").write_bytes(b"synthetic vector store")
    (root / ".index.lock.guard").touch()
    (root / ".index.lock").write_bytes(b"synthetic lock owner")
    with pytest.raises(bundles.CorpusBundleError, match="undeclared"):
        bundles.validate_corpus_bundle(root)
    assert bundles.validate_corpus_bundle(root, allow_index=True) == manifest
    (root / ".index.backup").mkdir()
    with pytest.raises(bundles.CorpusBundleError, match="undeclared"):
        bundles.validate_corpus_bundle(root, allow_index=True)


@pytest.mark.parametrize("extra", ["index", ".index.lock", ".index.lock.guard"])
def test_installed_mode_rejects_wrong_types_for_allowed_paths(tmp_path, extra):
    root = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(root)
    if extra == "index":
        (root / extra).write_bytes(b"not a directory")
    else:
        (root / extra).mkdir()
    with pytest.raises(bundles.CorpusBundleError, match="undeclared"):
        bundles.validate_corpus_bundle(root, allow_index=True)


def test_duplicate_catalog_paths_are_rejected_even_with_consistent_hashes(tmp_path):
    root = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(root)
    catalog_path = root / "sources.yml"
    catalog = yaml.safe_load(catalog_path.read_bytes())
    duplicate = {**catalog["sources"][0], "source_id": "duplicate_source"}
    catalog["sources"].append(duplicate)
    catalog_path.write_text(yaml.safe_dump(catalog), encoding="utf-8")

    def add_duplicate(manifest):
        manifest["catalog_sha256"] = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
        manifest["catalog_size_bytes"] = catalog_path.stat().st_size
        manifest["source_count"] = 2
        manifest["files"].append({**manifest["files"][0], "source_id": "duplicate_source"})

    _rewrite_manifest(root, add_duplicate)
    with pytest.raises(bundles.CorpusBundleError, match="duplicate source file paths"):
        bundles.validate_corpus_bundle(root)


def test_restricted_bundle_cannot_drop_terms_acknowledgement(indexed, tmp_path):
    settings, _ = indexed
    root = tmp_path / "private"
    bundles.package_private_corpus(settings, root, acknowledge_source_terms=True)
    _rewrite_manifest(root, lambda value: value.update(source_terms_acknowledged=False))
    with pytest.raises(bundles.CorpusBundleError, match="terms were not acknowledged"):
        bundles.validate_corpus_bundle(root)


def test_install_rejects_link_inside_index_even_in_installed_mode(tmp_path):
    root = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(root)
    (root / "index" / "qdrant").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("not corpus", encoding="utf-8")
    try:
        (root / "index" / "qdrant" / "link").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links is unavailable on this Windows account.")
    with pytest.raises(bundles.CorpusBundleError, match="links|junctions"):
        bundles.validate_corpus_bundle(root, allow_index=True)


@pytest.mark.parametrize("link_target", ["source", "catalog", "directory", "bundle", "index"])
def test_packaging_and_validation_reject_symbolic_links(indexed, tmp_path, link_target):
    settings, _ = indexed
    try:
        probe = tmp_path / "probe-link"
        probe.symlink_to(settings.rag_dir, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symbolic links is unavailable on this Windows account.")
    if link_target == "index":
        link = tmp_path / "index-link"
        link.symlink_to(settings.index_dir, target_is_directory=True)
        settings = replace(settings, index_dir=link)
    elif link_target == "bundle":
        settings = replace(settings, rag_dir=probe)
    elif link_target == "directory":
        settings.raw_dir.rename(settings.rag_dir / "original-raw")
        settings.raw_dir.symlink_to(settings.rag_dir / "original-raw", target_is_directory=True)
    else:
        original = _source_path(settings.rag_dir) if link_target == "source" else settings.sources_path
        moved = original.with_suffix(".saved")
        original.rename(moved)
        original.symlink_to(moved)
    with pytest.raises(bundles.CorpusBundleError, match="links|junctions"):
        bundles.package_private_corpus(settings, tmp_path / "private", acknowledge_source_terms=True)


def test_install_detects_source_changes_between_prevalidation_and_copy(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    bundles.create_test_corpus_bundle(root)
    original = bundles.validate_corpus_bundle

    def mutate_after_validation(path):
        result = original(path)
        if Path(path) == root:
            _source_path(root).write_bytes(b"changed after the first validation")
        return result

    monkeypatch.setattr(bundles, "validate_corpus_bundle", mutate_after_validation)
    with pytest.raises(bundles.CorpusBundleError, match="integrity"):
        bundles.install_corpus_bundle(root, tmp_path / "installed")
    assert not (tmp_path / "installed").exists()
    assert not list(tmp_path.glob(".installed-*"))


def test_public_ci_fixture_is_original_and_explicitly_not_official(tmp_path):
    root = tmp_path / "bundle"
    manifest = bundles.create_test_corpus_bundle(root)
    assert manifest["fixture_only"] is True
    assert manifest["source_count"] == 1
    assert manifest["source_index_manifest_sha256"] is None
    assert manifest["usage_intent"] == "synthetic_test_only"
    assert "NOT OFFICIAL GUIDANCE" in _source_path(root).read_text(encoding="utf-8")
    source = yaml.safe_load((root / "sources.yml").read_bytes())["sources"][0]
    assert source["url"].startswith("https://example.invalid/")
    assert source["jurisdictions"] == ["Queensland"]


def test_cli_fixture_validate_and_install(tmp_path, capsys):
    root = tmp_path / "bundle"
    assert main(["--test-fixture", "--output", str(root)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["uploaded"] is False
    assert result["fixture_only"] is True
    assert main(["--validate", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "validated"
    assert main(["--install", str(root), "--output", str(tmp_path / "installed")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_cli_default_output_does_not_conflict_with_tracked_docker_placeholder(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("scripts.prepare_private_corpus.PROJECT_ROOT", tmp_path)
    placeholder = tmp_path / "deployment_corpus" / ".keep"
    placeholder.parent.mkdir()
    placeholder.write_text("public image placeholder", encoding="utf-8")
    assert main(["--test-fixture"]) == 0
    assert json.loads(capsys.readouterr().out)["fixture_only"] is True
    assert (tmp_path / "output" / "private-corpus" / bundles.BUNDLE_MANIFEST).is_file()
    assert placeholder.read_text(encoding="utf-8") == "public image placeholder"


def test_cli_default_refuses_unacknowledged_restricted_sources(indexed, tmp_path, monkeypatch, capsys):
    settings, _ = indexed
    monkeypatch.setattr("scripts.prepare_private_corpus.load_dotenv", lambda *args: None)
    monkeypatch.setattr("scripts.prepare_private_corpus.RagSettings.from_env", lambda: settings)
    target = tmp_path / "private"
    assert main(["--output", str(target)]) == 1
    assert "acknowledge" in capsys.readouterr().err
    assert not target.exists()
    assert main(["--output", str(target), "--acknowledge-source-terms"]) == 0
    assert json.loads(capsys.readouterr().out)["fixture_only"] is False
