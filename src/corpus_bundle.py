"""Bounded, local-only corpus snapshots for private container build contexts.

This module never downloads or uploads data. Source terms remain in the original
catalog; an acknowledgement records intent, not permission or a new licence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml

from src.rag.corpus import load_source_catalog
from src.rag.index import load_and_validate_index

BUNDLE_SCHEMA = "bushfire-private-corpus-v1"
BUNDLE_MANIFEST = "bundle-manifest.json"
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_BUNDLE_BYTES = 10 * 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024
MAX_SOURCE_COUNT = 64
MTIME_PROVENANCE = "Observed local filesystem modification time; not an HTTP retrieval receipt."
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_WINDOWS_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.IGNORECASE)


class CorpusBundleError(ValueError):
    """A corpus snapshot is unsafe, incomplete, or inconsistent."""


def _digest(payload):
    return hashlib.sha256(payload).hexdigest()


def _canonical(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _with_hash(payload):
    return {**payload, "manifest_sha256": _digest(_canonical(payload))}


def _is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _without_links(path):
    candidate = Path(os.path.abspath(path))
    if any(_is_link(part) for part in (candidate, *candidate.parents)):
        raise CorpusBundleError("Corpus paths cannot contain symbolic links or junctions.")
    return candidate


def _raw_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise CorpusBundleError("Source files must use a portable relative raw/ path.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or len(path.parts) < 2
        or path.parts[0] != "raw"
        or path.as_posix() != value
        or any(
            part in {".", ".."}
            or part.endswith((".", " "))
            or _WINDOWS_RESERVED.fullmatch(part)
            or any(ord(char) < 32 for char in part)
            for part in path.parts
        )
    ):
        raise CorpusBundleError("Source files must stay within raw/ without traversal or ambiguous names.")
    return path.as_posix()


def _read_file(path, limit):
    path = _without_links(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise CorpusBundleError("A corpus file is missing, not regular, or exceeds its size limit.")
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
        stat = os.fstat(stream.fileno())
    if len(payload) > limit or len(payload) != stat.st_size:
        raise CorpusBundleError("A corpus file changed while being read or exceeds its size limit.")
    return payload, stat


def _catalog(path, root):
    catalog = load_source_catalog(path, rag_dir=root)
    if len(catalog) > MAX_SOURCE_COUNT:
        raise CorpusBundleError("The corpus has too many sources.")
    paths = [_raw_path(source["local_path"]) for source in catalog]
    if len({path.casefold() for path in paths}) != len(paths):
        raise CorpusBundleError("The corpus contains duplicate source file paths.")
    for relative in paths:
        _without_links(root / relative)
    return catalog


def _new_target(target_dir):
    target = _without_links(target_dir)
    if target.exists():
        raise CorpusBundleError("The target already exists; choose a new directory. Nothing was overwritten.")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _timestamp(stat):
    return datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")


def _publish(target, payloads):
    """Stage and fully validate before publishing a new directory on one filesystem."""
    target = _new_target(target)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-", dir=target.parent) as staging_parent:
        staged = Path(staging_parent) / "corpus"
        staged.mkdir()
        for relative, payload in payloads.items():
            destination = staged / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        validate_corpus_bundle(staged)
        # Recheck after staging. rename never replaces a non-empty directory.
        if target.exists() or _is_link(target):
            raise CorpusBundleError("The target appeared during staging; nothing was overwritten.")
        staged.rename(target)
    return target


def _record(source, payload, stat):
    return {
        "source_id": source["source_id"],
        "path": _raw_path(source["local_path"]),
        "sha256": _digest(payload),
        "size_bytes": len(payload),
        "observed_file_mtime_utc": _timestamp(stat),
    }


def _manifest(catalog_bytes, records, *, index_sha, fixture_only, acknowledged):
    return _with_hash(
        {
            "schema": BUNDLE_SCHEMA,
            "catalog_path": "sources.yml",
            "catalog_sha256": _digest(catalog_bytes),
            "catalog_size_bytes": len(catalog_bytes),
            "source_index_manifest_sha256": index_sha,
            "fixture_only": fixture_only,
            "usage_intent": "synthetic_test_only" if fixture_only else "private_research_noncommercial",
            "source_terms_acknowledged": acknowledged,
            "mtime_provenance": MTIME_PROVENANCE,
            "source_count": len(records),
            "payload_size_bytes": len(catalog_bytes) + sum(row["size_bytes"] for row in records),
            "files": records,
        }
    )


def package_private_corpus(settings, target_dir, *, acknowledge_source_terms=False):
    """Copy an index-verified local catalog and its raw bytes; never upload them."""
    root = _without_links(settings.rag_dir)
    target = _without_links(target_dir)
    if target == root or target.is_relative_to(root) or root.is_relative_to(target):
        raise CorpusBundleError("The private bundle target must be separate from the original RAG directory.")
    catalog_bytes, _ = _read_file(settings.sources_path, MAX_METADATA_BYTES)
    catalog = _catalog(settings.sources_path, root)
    if any(row["reuse_status"] != "open_with_attribution" for row in catalog) and not acknowledge_source_terms:
        raise CorpusBundleError("Review the source terms and explicitly acknowledge them before local packaging.")
    declared_size = len(catalog_bytes)
    for source in catalog:
        path = _without_links(root / source["local_path"])
        if not path.is_file() or not _valid_size(path.stat().st_size, MAX_FILE_BYTES):
            raise CorpusBundleError("A corpus source is missing or exceeds its size limit.")
        declared_size += path.stat().st_size
    if declared_size > MAX_BUNDLE_BYTES:
        raise CorpusBundleError("The corpus exceeds the total size limit.")
    for name in ("manifest.json", "documents.jsonl", "qdrant"):
        _without_links(Path(settings.index_dir) / name)
    index = load_and_validate_index(settings)
    if index["catalog_sha256"] != _digest(catalog_bytes):
        raise CorpusBundleError("The catalog changed during packaging.")
    indexed = {row["source_id"]: row for row in index["source_artifacts"]}
    payloads = {"sources.yml": catalog_bytes}
    records = []
    total = len(catalog_bytes)
    for source in catalog:
        relative = _raw_path(source["local_path"])
        payload, stat = _read_file(root / relative, MAX_FILE_BYTES)
        record = _record(source, payload, stat)
        original = indexed.get(source["source_id"], {})
        if any(record[key] != original.get(key) for key in ("source_id", "path", "sha256", "size_bytes")):
            raise CorpusBundleError("A source file no longer matches the validated local index.")
        total += len(payload)
        if total > MAX_BUNDLE_BYTES:
            raise CorpusBundleError("The corpus exceeds the total size limit.")
        payloads[relative] = payload
        records.append(record)
    manifest = _manifest(
        catalog_bytes,
        records,
        index_sha=index["manifest_sha256"],
        fixture_only=False,
        acknowledged=bool(acknowledge_source_terms),
    )
    payloads[BUNDLE_MANIFEST] = _canonical(manifest)
    _publish(target, payloads)
    return manifest


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CorpusBundleError("The bundle manifest contains duplicate JSON keys.")
        result[key] = value
    return result


def _valid_size(value, maximum):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= maximum


def _validate_metadata(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema") != BUNDLE_SCHEMA:
        raise CorpusBundleError("The bundle schema is invalid.")
    original = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != _digest(_canonical(original)):
        raise CorpusBundleError("The bundle manifest hash does not match.")
    fixture = manifest.get("fixture_only")
    index_hash = manifest.get("source_index_manifest_sha256")
    if (
        type(fixture) is not bool
        or type(manifest.get("source_terms_acknowledged")) is not bool
        or manifest.get("catalog_path") != "sources.yml"
        or not _SHA256.fullmatch(str(manifest.get("catalog_sha256", "")))
        or not _valid_size(manifest.get("catalog_size_bytes"), MAX_METADATA_BYTES)
        or not _valid_size(manifest.get("source_count"), MAX_SOURCE_COUNT)
        or not _valid_size(manifest.get("payload_size_bytes"), MAX_BUNDLE_BYTES)
        or manifest.get("mtime_provenance") != MTIME_PROVENANCE
        or manifest.get("usage_intent") != ("synthetic_test_only" if fixture else "private_research_noncommercial")
        or (fixture and index_hash is not None)
        or (not fixture and not _SHA256.fullmatch(str(index_hash)))
    ):
        raise CorpusBundleError("The bundle provenance or metadata is invalid.")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != manifest["source_count"]:
        raise CorpusBundleError("The bundle source count is invalid.")
    return files


def _validate_record(record, source):
    if not isinstance(record, dict) or record.get("source_id") != source["source_id"]:
        raise CorpusBundleError("The bundle source identities do not match the catalog.")
    path = _raw_path(record.get("path"))
    if (
        path != source["local_path"]
        or not _valid_size(record.get("size_bytes"), MAX_FILE_BYTES)
        or not _SHA256.fullmatch(str(record.get("sha256", "")))
    ):
        raise CorpusBundleError("The bundle source metadata is invalid.")
    try:
        timestamp = datetime.fromisoformat(record["observed_file_mtime_utc"])
        if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
            raise ValueError("not UTC")
    except (ValueError, TypeError, KeyError) as error:
        raise CorpusBundleError("The observed filesystem timestamp must be a UTC datetime.") from error
    return path


def _validate_tree(root, expected, *, allow_index=False):
    expected_dirs = {"."}
    for path in expected:
        expected_dirs.update(str(parent) for parent in PurePosixPath(path).parents)
    remaining = [root]
    while remaining:
        directory = remaining.pop()
        for item in directory.iterdir():
            if _is_link(item):
                raise CorpusBundleError("The bundle cannot contain links or junctions.")
            relative = item.relative_to(root).as_posix()
            index_path = allow_index and (relative == "index" or relative.startswith("index/"))
            lock_path = allow_index and relative in {".index.lock", ".index.lock.guard"}
            if item.is_dir() and (relative in expected_dirs or index_path):
                remaining.append(item)
            elif lock_path and item.is_file() and item.stat().st_size <= MAX_METADATA_BYTES:
                continue
            elif index_path and relative != "index" and item.is_file():
                continue
            elif not item.is_file() or relative not in expected:
                raise CorpusBundleError("The bundle contains undeclared files or directories.")


def validate_corpus_bundle(bundle_dir, *, allow_index=False):
    """Validate declared bytes without mutation; installed roots may allow index files.

    ``allow_index`` permits only the index subtree and its two named lock files.
    It does not validate vectors: installed-root callers must also call
    ``load_and_validate_index``. Links remain forbidden throughout that subtree.
    """
    root = _without_links(bundle_dir)
    encoded, _ = _read_file(root / BUNDLE_MANIFEST, MAX_METADATA_BYTES)
    try:
        manifest = json.loads(encoded, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as error:
        raise CorpusBundleError("The bundle manifest is invalid JSON.") from error
    records = _validate_metadata(manifest)
    catalog_bytes, _ = _read_file(root / "sources.yml", MAX_METADATA_BYTES)
    if len(catalog_bytes) != manifest["catalog_size_bytes"] or _digest(catalog_bytes) != manifest["catalog_sha256"]:
        raise CorpusBundleError("The bundle catalog failed integrity validation.")
    catalog = _catalog(root / "sources.yml", root)
    if len(catalog) != len(records):
        raise CorpusBundleError("The catalog and bundle source counts differ.")
    if (
        not manifest["fixture_only"]
        and not manifest["source_terms_acknowledged"]
        and any(row["reuse_status"] != "open_with_attribution" for row in catalog)
    ):
        raise CorpusBundleError("The private source terms were not acknowledged.")
    expected = {BUNDLE_MANIFEST, "sources.yml"}
    total = len(catalog_bytes)
    for record, source in zip(records, catalog, strict=True):
        relative = _validate_record(record, source)
        payload, _ = _read_file(root / relative, MAX_FILE_BYTES)
        if len(payload) != record["size_bytes"] or _digest(payload) != record["sha256"]:
            raise CorpusBundleError("A bundled source failed integrity validation.")
        expected.add(relative)
        total += len(payload)
        if total + len(encoded) > MAX_BUNDLE_BYTES:
            raise CorpusBundleError("The corpus exceeds the total size limit.")
    if total != manifest["payload_size_bytes"]:
        raise CorpusBundleError("The bundle total size is inconsistent.")
    _validate_tree(root, expected, allow_index=allow_index)
    return manifest


def install_corpus_bundle(bundle_dir, target_dir):
    """Validate then atomically install a catalog and raw bytes into a new RAG root."""
    root = _without_links(bundle_dir)
    manifest = validate_corpus_bundle(root)
    target = _without_links(target_dir)
    if target == root or target.is_relative_to(root) or root.is_relative_to(target):
        raise CorpusBundleError("The install target must be separate from the source bundle.")
    payloads = {"sources.yml": _read_file(root / "sources.yml", MAX_METADATA_BYTES)[0]}
    payloads[BUNDLE_MANIFEST] = _canonical(manifest)
    for row in manifest["files"]:
        payloads[row["path"]] = _read_file(root / row["path"], MAX_FILE_BYTES)[0]
    return _publish(target, payloads)


def create_test_corpus_bundle(target_dir):
    """Create original synthetic text for public CI; never copy official source text."""
    source = {
        "source_id": "synthetic_qld_test",
        "title": "Synthetic Queensland preparedness test fixture — not official guidance",
        "agency": "BushfireReadyGPT test authors (not a government agency)",
        "url": "https://example.invalid/bushfire-ready-test-fixture",
        "format": "text",
        "local_path": "raw/synthetic_qld_test.txt",
        "jurisdictions": ["Queensland"],
        "audiences": ["community", "school", "council", "aged_care"],
        "scenarios": ["preparedness", "evacuation", "property_preparation", "emergency_kits"],
        "document_date": "unknown",
        "licence": "Original synthetic test text; available under the repository licence. Not official advice.",
        "licence_url": "https://github.com/shuxiachai/BushfireReadyGPT/blob/main/LICENSE",
        "reuse_status": "open_with_attribution",
        "last_verified_date": "2026-09-10",
    }
    catalog_bytes = yaml.safe_dump({"schema_version": 1, "sources": [source]}, sort_keys=False).encode("utf-8")
    payload = (
        "SYNTHETIC TEST FIXTURE — NOT OFFICIAL GUIDANCE.\n\n"
        "This invented Queensland school and community preparedness exercise asks the test participant "
        "to record a planning contact, review a fictional emergency kit inventory, and mark an evacuation "
        "discussion for human review. Council staff in this fictional exercise compare the draft with "
        "a fictional property preparation checklist. It does not describe live fires or real directions.\n"
    ).encode("utf-8")
    record = {
        "source_id": source["source_id"],
        "path": source["local_path"],
        "sha256": _digest(payload),
        "size_bytes": len(payload),
        "observed_file_mtime_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest = _manifest(catalog_bytes, [record], index_sha=None, fixture_only=True, acknowledged=False)
    _publish(
        target_dir, {"sources.yml": catalog_bytes, source["local_path"]: payload, BUNDLE_MANIFEST: _canonical(manifest)}
    )
    return manifest
