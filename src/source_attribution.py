from __future__ import annotations

import re

RAG_ATTRIBUTION_EXAMPLE = "[O1-RAG][source_id=<source_id>] <source title>"
MODEL_SOURCE_ATTRIBUTION_RULES = f"""- For every factual claim derived from an O1-RAG passage, cite the supplied source in this exact form: `{RAG_ATTRIBUTION_EXAMPLE}`. Copy only the stable source identifier and title supplied in its Citation label.
- Do not write, infer, copy or retype a URL in the model-authored narrative. The application binds verified URLs deterministically in Evidence Table 4 and Evidence Table 5."""

_URL = re.compile(r"(?i)(?:https?://|www\.)[^\s<>\[\]{}|\\^`\"]+")
_SOURCE_ID_INVALID = re.compile(r"[^A-Za-z0-9_.-]+")


def format_rag_attribution(source):
    """Return the canonical model-visible label for one retrieved source."""

    item = source if isinstance(source, dict) else {}
    source_id = _normalise_source_id(item.get("source_id"))
    title = _normalise_metadata(item.get("title"), fallback="Untitled official source")
    return f"[O1-RAG][source_id={source_id}] {title}"


def format_official_attribution(source):
    """Return the canonical model-visible label for a registered official source."""

    item = source if isinstance(source, dict) else {}
    source_id = _normalise_source_id(item.get("id"))
    title = _normalise_metadata(item.get("name"), fallback="Untitled official source")
    return f"[O1][source_id={source_id}] {title}"


def canonical_rag_source_ids(text, sources):
    """Return source IDs whose complete canonical RAG labels occur in ``text``."""

    content = str(text or "")
    attributed = set()
    for source in sources or []:
        item = source if isinstance(source, dict) else {}
        if not str(item.get("source_id") or "").strip() or not str(item.get("title") or "").strip():
            continue
        label = format_rag_attribution(item)
        if label in content:
            attributed.add(_normalise_source_id(item["source_id"]))
    return attributed


def canonical_official_source_ids(text, sources):
    """Return source IDs whose complete canonical O1 labels occur in ``text``."""

    content = str(text or "")
    attributed = set()
    for source in sources or []:
        item = source if isinstance(source, dict) else {}
        if not str(item.get("id") or "").strip() or not str(item.get("name") or "").strip():
            continue
        label = format_official_attribution(item)
        if label in content:
            attributed.add(_normalise_source_id(item["id"]))
    return attributed


def strip_known_attribution_labels(text, *, rag_sources=(), official_sources=()):
    """Remove verified canonical labels before scoring the surrounding claim text."""

    result = str(text or "")
    labels = []
    for source in rag_sources or []:
        item = source if isinstance(source, dict) else {}
        if str(item.get("source_id") or "").strip() and str(item.get("title") or "").strip():
            labels.append(format_rag_attribution(item))
    for source in official_sources or []:
        item = source if isinstance(source, dict) else {}
        if str(item.get("id") or "").strip() and str(item.get("name") or "").strip():
            labels.append(format_official_attribution(item))
    for label in sorted(set(labels), key=len, reverse=True):
        result = result.replace(label, " ")
    return " ".join(result.split())


def extract_markdown_section(text, heading):
    """Extract one exact Markdown section, including only its nested subsections."""

    target = _normalise_heading(heading)
    selected = []
    active_level = None
    fence_character = None
    fence_length = 0
    for line in str(text or "").splitlines():
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_character is not None:
            marker = fence.group(1) if fence else ""
            suffix = fence.group(2) if fence else ""
            if marker.startswith(fence_character * fence_length) and not suffix.strip():
                fence_character = None
                fence_length = 0
            continue
        if fence:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            continue
        match = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*$", line)
        if match:
            level = len(match.group(1))
            current = _normalise_heading(match.group(2))
            if current == target:
                active_level = level
                continue
            if active_level is not None and level <= active_level:
                active_level = None
            elif active_level is not None:
                selected.append(line)
                continue
        elif active_level is not None:
            selected.append(line)
    return "\n".join(selected).strip()


def normalise_source_metadata(value, *, fallback="To be confirmed"):
    """Bound source metadata before placing it beside untrusted retrieved text."""

    return _normalise_metadata(value, fallback=fallback)


def redact_urls(value):
    """Keep model-visible evidence free of links bound by deterministic appendices."""

    return _URL.sub("[URL omitted; see deterministic Evidence Tables]", str(value or ""))


def _normalise_source_id(value):
    source_id = _SOURCE_ID_INVALID.sub("-", " ".join(str(value or "").split())).strip("-.")
    return source_id[:120] or "unknown-source"


def _normalise_metadata(value, *, fallback):
    text = " ".join(redact_urls(value).split()).strip()
    return text[:300] or fallback


def _normalise_heading(value):
    return re.sub(r"^\d+[.)]\s*", "", " ".join(str(value or "").split())).casefold()
