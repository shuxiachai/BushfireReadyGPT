from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from src.data_artifacts import atomic_write_bytes, download_url_bytes, sha256_file
from src.rag.errors import RagError

_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,79}$")
_CONTENT_SELECTOR = re.compile(r"^#[A-Za-z][A-Za-z0-9_-]{0,79}$")
_FORMATS = {"html", "markdown", "pdf", "text"}


def _safe_child(root, relative_path):
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise RagError("rag_catalog_invalid", "Every RAG source must define local_path.")
    candidate = (Path(root) / relative_path).resolve()
    try:
        candidate.relative_to(Path(root).resolve())
    except ValueError as error:
        raise RagError("rag_catalog_invalid", "RAG source paths must stay inside the RAG data directory.") from error
    return candidate


def load_source_catalog(path, *, rag_dir=None):
    source_path = Path(path)
    root = Path(rag_dir or source_path.parent).resolve()
    try:
        raw = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as error:
        raise RagError("rag_not_installed", "The RAG source catalog is not installed.") from error
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise RagError("rag_catalog_invalid", "The RAG source catalog is unreadable or invalid.") from error
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise RagError("rag_catalog_invalid", "The RAG source catalog schema_version must be 1.")
    sources = raw.get("sources") if isinstance(raw, dict) else None
    if not isinstance(sources, list) or not sources:
        raise RagError("rag_catalog_invalid", "The RAG source catalog must contain at least one source.")
    result = []
    seen = set()
    for item in sources:
        if not isinstance(item, dict):
            raise RagError("rag_catalog_invalid", "RAG source entries must be mappings.")
        source_id = str(item.get("source_id") or "").strip()
        if not _SOURCE_ID.fullmatch(source_id) or source_id in seen:
            raise RagError("rag_catalog_invalid", f"Invalid or duplicate RAG source_id: {source_id or '<blank>'}.")
        seen.add(source_id)
        url = str(item.get("url") or "").strip()
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RagError("rag_catalog_invalid", f"RAG source {source_id} must use an absolute HTTPS URL.")
        source_format = str(item.get("format") or "").strip().lower()
        if source_format not in _FORMATS:
            raise RagError("rag_catalog_invalid", f"RAG source {source_id} has an unsupported format.")
        jurisdictions = item.get("jurisdictions")
        audiences = item.get("audiences")
        scenarios = item.get("scenarios")
        for label, values in (
            ("jurisdictions", jurisdictions),
            ("audiences", audiences),
            ("scenarios", scenarios),
        ):
            if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
                raise RagError("rag_catalog_invalid", f"RAG source {source_id} has invalid {label} metadata.")
        required_text = (
            "title",
            "agency",
            "document_date",
            "licence",
            "licence_url",
            "reuse_status",
            "last_verified_date",
        )
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in required_text):
            raise RagError("rag_catalog_invalid", f"RAG source {source_id} is missing required metadata.")
        content_selector = item.get("content_selector")
        content_selectors = item.get("content_selectors")
        if content_selector is not None and content_selectors is not None:
            raise RagError(
                "rag_catalog_invalid",
                f"RAG source {source_id} cannot define both content selector fields.",
            )
        if content_selector is not None:
            content_selectors = [content_selector]
        if content_selectors is not None and (
            not isinstance(content_selectors, list)
            or not content_selectors
            or len(content_selectors) != len(set(content_selectors))
            or not all(
                isinstance(selector, str) and _CONTENT_SELECTOR.fullmatch(selector) for selector in content_selectors
            )
        ):
            raise RagError(
                "rag_catalog_invalid",
                f"RAG source {source_id} has invalid content selectors.",
            )
        resolved = dict(item)
        resolved["source_id"] = source_id
        resolved["format"] = source_format
        resolved["jurisdictions"] = [value.strip() for value in jurisdictions]
        resolved["audiences"] = [value.strip() for value in audiences]
        resolved["scenarios"] = [value.strip() for value in scenarios]
        resolved["content_selectors"] = list(content_selectors or [])
        resolved["resolved_path"] = _safe_child(root, item.get("local_path"))
        result.append(resolved)
    return result


def _validate_download(payload, source_format):
    if source_format == "pdf" and not payload.startswith(b"%PDF-"):
        raise RagError("rag_download_invalid", "Downloaded PDF source has an invalid file signature.")
    if source_format == "html":
        sample = payload[: 1024 * 1024].lower()
        if b"<html" not in sample and b"<!doctype html" not in sample:
            raise RagError("rag_download_invalid", "Downloaded HTML source does not contain an HTML document.")
        if b"incapsula" in sample or b"_incapsula_resource" in sample:
            raise RagError("rag_download_invalid", "Downloaded HTML source is a web application firewall page.")
    try:
        if source_format in {"html", "markdown", "text"}:
            payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RagError("rag_download_invalid", "Downloaded text source is not valid UTF-8.") from error


def download_catalog_sources(catalog, *, force=False, timeout=30, max_bytes=25 * 1024 * 1024):
    downloaded = []
    for source in catalog:
        target = source["resolved_path"]
        if target.is_file() and not force:
            downloaded.append({"source_id": source["source_id"], "status": "existing", "path": target})
            continue
        try:
            payload = download_url_bytes(
                source["url"],
                timeout=timeout,
                attempts=3,
                max_bytes=max_bytes,
            )
            _validate_download(payload, source["format"])
            atomic_write_bytes(target, payload)
        except (OSError, ValueError) as error:
            raise RagError(
                "rag_download_failed", f"Could not download RAG source {source['source_id']}: {error}"
            ) from error
        downloaded.append({"source_id": source["source_id"], "status": "downloaded", "path": target})
    return downloaded


def _normalise_text(text):
    value = str(text or "").replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[\t ]+", " ", line).strip() for line in value.split("\n")]
    output = []
    previous_blank = False
    for line in lines:
        blank = not line
        if blank and previous_blank:
            continue
        output.append(line)
        previous_blank = blank
    return "\n".join(output).strip()


def _load_units(source):
    path = source["resolved_path"]
    if not path.is_file():
        raise RagError("rag_source_missing", f"RAG source {source['source_id']} has not been downloaded.")
    source_format = source["format"]
    try:
        if source_format == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise RagError("rag_source_invalid", f"RAG source {source['source_id']} is encrypted.")
            units = []
            for page_number, page in enumerate(reader.pages, start=1):
                text = _normalise_text(page.extract_text() or "")
                if text:
                    units.append({"text": text, "page": page_number})
            if not units:
                raise RagError("rag_source_invalid", f"RAG source {source['source_id']} contains no extractable text.")
            return units
        text = path.read_text(encoding="utf-8")
        if source_format == "html":
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(text, "html.parser")
            for element in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
                element.decompose()
            selectors = source.get("content_selectors") or []
            selected_elements = [soup.select_one(selector) for selector in selectors]
            if any(element is None for element in selected_elements):
                raise RagError(
                    "rag_source_invalid",
                    f"RAG source {source['source_id']} no longer contains every declared content selector.",
                )
            text = (
                "\n\n".join(element.get_text("\n") for element in selected_elements)
                if selected_elements
                else soup.get_text("\n")
            )
        text = _normalise_text(text)
        if not text:
            raise RagError("rag_source_invalid", f"RAG source {source['source_id']} contains no usable text.")
        return [{"text": text, "page": None}]
    except RagError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise RagError("rag_source_invalid", f"RAG source {source['source_id']} could not be parsed.") from error


def _paragraph_word_groups(text, max_words):
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    groups = []
    for paragraph in paragraphs:
        words = paragraph.split()
        if len(words) <= max_words:
            groups.append(words)
        else:
            groups.extend(words[index : index + max_words] for index in range(0, len(words), max_words))
    return groups


def chunk_catalog_sources(catalog, *, max_words=420, overlap_words=60):
    if max_words < 50 or overlap_words < 0 or overlap_words >= max_words:
        raise RagError("rag_chunk_config_invalid", "RAG chunk sizes are invalid.")
    chunks = []
    for source in catalog:
        chunk_number = 0
        for unit in _load_units(source):
            current = []
            for group in _paragraph_word_groups(unit["text"], max_words):
                if current and len(current) + len(group) > max_words:
                    chunk_number += 1
                    chunks.append(_build_chunk(source, current, chunk_number, unit.get("page")))
                    current = current[-overlap_words:] if overlap_words else []
                current.extend(group)
            if current:
                chunk_number += 1
                chunks.append(_build_chunk(source, current, chunk_number, unit.get("page")))
    if not chunks:
        raise RagError("rag_source_invalid", "The RAG corpus produced no chunks.")
    return chunks


def _build_chunk(source, words, chunk_number, page):
    text = " ".join(words).strip()
    content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    identity = f"{source['source_id']}:{page or 0}:{chunk_number}:{content_sha256}"
    chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return {
        "chunk_id": chunk_id,
        "source_id": source["source_id"],
        "title": source["title"],
        "agency": source["agency"],
        "url": source["url"],
        "document_date": source["document_date"],
        "licence": source["licence"],
        "licence_url": source["licence_url"],
        "reuse_status": source["reuse_status"],
        "last_verified_date": source["last_verified_date"],
        "jurisdictions": source["jurisdictions"],
        "audiences": source["audiences"],
        "scenarios": source["scenarios"],
        "page": page,
        "chunk_number": chunk_number,
        "text": text,
        "chunk_sha256": content_sha256,
    }


def source_artifact_records(catalog, *, rag_dir):
    result = []
    root = Path(rag_dir).resolve()
    for source in catalog:
        path = source["resolved_path"]
        if not path.is_file():
            raise RagError("rag_source_missing", f"RAG source {source['source_id']} is missing.")
        result.append(
            {
                "source_id": source["source_id"],
                "path": path.resolve().relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "retrieved_at_utc": datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat(timespec="seconds"),
            }
        )
    return result
