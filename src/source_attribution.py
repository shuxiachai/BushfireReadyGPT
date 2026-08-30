from __future__ import annotations

import hashlib
import html
import re
import unicodedata

RAG_ATTRIBUTION_EXAMPLE = "[O1-RAG][source_id=<source_id>] <source title>"
RAG_CITATION_TOKEN_EXAMPLE = "[O1-RAG][ref=<opaque_ref>]"  # nosec B105
OFFICIAL_CITATION_TOKEN_EXAMPLE = "[O1][ref=<opaque_ref>]"  # nosec B105
MODEL_SOURCE_ATTRIBUTION_RULES = f"""- For every factual claim derived from an O1-RAG passage, append the supplied opaque citation token in this exact form: `{RAG_CITATION_TOKEN_EXAMPLE}`. Copy only a token supplied by the application; never copy or invent a title.
- Source titles are deliberately withheld from the model citation contract. The application expands recognised tokens to verified display labels after generation.
- Do not write, infer, copy or retype a URL in the model-authored narrative. The application binds verified URLs deterministically in Evidence Table 4 and Evidence Table 5."""

_URL = re.compile(
    r"(?i)(?:https?://|ftps?://|wss?://|www\.|mailto:|data:|javascript:|file:|tel:|(?<![:/])//)"
    r"[^\s<>]+"
)
_MARKDOWN_INLINE_LINK = re.compile(r"(?P<prefix>!?\[[^\]\r\n]*\]\(\s*<?)(?P<destination>[^)\s>]+)(?P<suffix>>?\s*\))")
_MARKDOWN_LINK_START = re.compile(r"!?\[[^\]\r\n]*\]\(\s*<?[^)\s>]+")
_MARKDOWN_REFERENCE_LINK = re.compile(
    r"(?m)^(?P<prefix> {0,3}\[[^\]\r\n]+\]:\s*<?)(?P<destination>\S+?)(?P<suffix>>?\s*)$"
)
_SOURCE_ID_INVALID = re.compile(r"[^A-Za-z0-9_.-]+")
_ATTRIBUTION_TOKEN = re.compile(
    r"\[O1(?:-RAG)?\]\[(?:source_id|ref)=[^\]\r\n]+\]",
    re.IGNORECASE,
)
_UNBOUND_ATTRIBUTION_MARKER = re.compile(
    r"\]\s*\[\s*[^\]\r\n=]{1,32}\s*=",
    re.IGNORECASE,
)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_UNCLOSED_HTML_COMMENT = re.compile(r"<!--.*\Z", re.DOTALL)
_NON_VISIBLE_HTML_BLOCK = re.compile(
    r"<(?P<tag>script|style|template)\b[^>]*>.*?</(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_HIDDEN_HTML_BLOCK = re.compile(
    r"<(?P<tag>[A-Za-z][\w:-]*)\b(?P<attrs>[^>]*(?:\bhidden\b|display\s*:\s*none|visibility\s*:\s*hidden)[^>]*)>"
    r".*?</(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_UNCLOSED_NON_VISIBLE_HTML_BLOCK = re.compile(
    r"<(?:script|style|template)\b[^>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)
_UNCLOSED_HIDDEN_HTML_BLOCK = re.compile(
    r"<[A-Za-z][\w:-]*\b[^>]*(?:\bhidden\b|display\s*:\s*none|visibility\s*:\s*hidden)[^>]*>.*\Z",
    re.IGNORECASE | re.DOTALL,
)
_REFERENCE_DEFINITION = re.compile(r"^ {0,3}\[[^\]\r\n]+\]:")
_LIST_MARKER = re.compile(r"^\s*(?:[-+*]\s+|\d+[.)]\s+)")
_CANONICAL_RAG_RETRIEVAL_CLAIM = (
    "The application retrieved this static official passage as preparedness-planning evidence for human review."
)
_SOURCE_ANNOTATION_WORD = (
    r"(?:unregistered|registered|retrieved|verified|official|canonical|source|citation|verification|knowledge|"
    r"evidence|entry|record|reference)"
)
_SOURCE_ANNOTATION_ONLY = re.compile(
    rf"^\(?\s*{_SOURCE_ANNOTATION_WORD}(?:[\s/,:;-]+{_SOURCE_ANNOTATION_WORD})*\s*\)?[.!]?$",
    re.IGNORECASE,
)
_PROMPT_DATA_MARKER_NAME = (
    r"(?:DETERMINISTIC\s*_\s*ANALYSIS\s*_\s*DATA|"
    r"CANONICAL\s*_\s*SOURCE\s*_\s*TOKEN\s*_\s*DATA|"
    r"REQUIRED\s*_\s*SOURCE\s*_\s*TOKENS|"
    r"U0\s*_\s*REVISION\s*_\s*REQUEST\s*_\s*DATA|"
    r"PRIOR\s*_\s*MODEL\s*_\s*NARRATIVE\s*_\s*DATA)"
)
_PROMPT_CONTROL_MARKER = re.compile(
    rf"<\s*(?:/?\s*(?:BEGIN|END)\s*_\s*{_PROMPT_DATA_MARKER_NAME}|"
    r"(?P<retrieved>/?\s*retrieved\s*-\s*official\s*-\s*evidence\b[^>]*))\s*>",
    re.IGNORECASE,
)
_RAW_HTML = re.compile(
    r"<!--|<\s*(?:!\s*\[CDATA\[|/?\s*[A-Za-z][\w:-]*(?=\s|/?>|$)|![A-Za-z]|\?)",
    re.IGNORECASE | re.MULTILINE,
)
_VOID_HTML_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


def format_rag_attribution(source):
    """Return the deterministic human-readable label for one retrieved source."""

    item = source if isinstance(source, dict) else {}
    source_id = _normalise_source_id(item.get("source_id"))
    title = _normalise_metadata(item.get("title"), fallback="Untitled official source")
    return f"[O1-RAG][source_id={source_id}] {title}"


def format_official_attribution(source):
    """Return the deterministic human-readable label for an official source."""

    item = source if isinstance(source, dict) else {}
    source_id = _normalise_source_id(item.get("id"))
    title = _normalise_metadata(item.get("name"), fallback="Untitled official source")
    return f"[O1][source_id={source_id}] {title}"


def format_rag_citation_token(source):
    """Return the opaque token a model may copy for one retrieved source."""

    item = source if isinstance(source, dict) else {}
    source_id = _normalise_source_id(item.get("source_id"))
    return f"[O1-RAG][ref={_opaque_source_ref('rag', source_id)}]"


def format_official_citation_token(source):
    """Return the opaque token a model may copy for one official register entry."""

    item = source if isinstance(source, dict) else {}
    source_id = _normalise_source_id(item.get("id"))
    return f"[O1][ref={_opaque_source_ref('official', source_id)}]"


def canonical_rag_labels(sources):
    """Return unique, copy-ready labels for complete retrieved-source metadata."""

    labels = []
    seen = set()
    for source in sources or []:
        item = source if isinstance(source, dict) else {}
        if not str(item.get("source_id") or "").strip() or not str(item.get("title") or "").strip():
            continue
        label = format_rag_attribution(item)
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def canonical_official_labels(sources):
    """Return unique, copy-ready labels for complete registered-source metadata."""

    labels = []
    seen = set()
    for source in sources or []:
        item = source if isinstance(source, dict) else {}
        if not str(item.get("id") or "").strip() or not str(item.get("name") or "").strip():
            continue
        label = format_official_attribution(item)
        if label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def canonical_source_token_data(*, official_sources=(), rag_sources=()):
    """Return detached opaque citation tokens without model-visible source titles."""

    official_tokens = []
    rag_tokens = []
    seen_official = set()
    seen_rag = set()
    for source in official_sources or []:
        item = source if isinstance(source, dict) else {}
        if not str(item.get("id") or "").strip() or not str(item.get("name") or "").strip():
            continue
        token = format_official_citation_token(item)
        if token not in seen_official:
            official_tokens.append(token)
            seen_official.add(token)
    for source in rag_sources or []:
        item = source if isinstance(source, dict) else {}
        if not str(item.get("source_id") or "").strip() or not str(item.get("title") or "").strip():
            continue
        token = format_rag_citation_token(item)
        if token not in seen_rag:
            rag_tokens.append(token)
            seen_rag.add(token)
    return {
        "official_source_tokens": official_tokens,
        "rag_source_tokens": rag_tokens,
    }


def expand_known_attribution_tokens(text, *, official_sources=(), rag_sources=()):
    """Expand only registered model tokens to deterministic, human-readable labels."""

    bindings = canonical_attribution_bindings(
        official_sources=official_sources,
        rag_sources=rag_sources,
    )
    if not bindings:
        return str(text or "")
    patterns = [re.escape(token) for token in sorted(bindings, key=len, reverse=True)]
    matcher = re.compile("|".join(f"(?:{pattern})" for pattern in patterns))

    def replace(match):
        matched = match.group(0)
        token = matched[: matched.find("]", matched.find("]") + 1) + 1]
        return bindings[token]

    return matcher.sub(replace, str(text or ""))


def canonicalise_model_source_section(text, *, official_sources=(), rag_sources=()):
    """Install the application-owned citation block in one real source section.

    Local models are useful for drafting prose but are not reliable custodians of
    exact citation-line syntax.  The application therefore owns the small set of
    source lines that the deterministic quality gate evaluates.  Existing
    model-authored attribution lines are removed only from the real Markdown
    ``Data Sources and Limitations`` section; all other prose is preserved.

    Missing or duplicate target headings, raw HTML and incomplete source
    bindings are deliberately left unchanged for the governed quality checks
    rather than being rewritten invisibly by this step.
    """

    content = str(text or "")
    if has_model_authored_raw_html(content):
        return content

    token_data = canonical_source_token_data(
        official_sources=official_sources,
        rag_sources=rag_sources,
    )
    official_tokens = token_data["official_source_tokens"][:2]
    if len(official_tokens) < 2:
        return content

    lines = content.splitlines()
    target_headings = _markdown_heading_positions(lines, "Data Sources and Limitations")
    if len(target_headings) != 1:
        return content

    heading_index, heading_level = target_headings[0]
    section_end = _markdown_section_end(lines, heading_index, heading_level)
    known_labels = {
        *canonical_official_labels(official_sources),
        *canonical_rag_labels(rag_sources),
    }
    cleaned_section = _remove_model_attribution_lines(
        lines[heading_index + 1 : section_end],
        known_labels=known_labels,
    )
    while cleaned_section and not cleaned_section[0].strip():
        cleaned_section.pop(0)

    canonical_lines = [*(f"- {token}" for token in official_tokens)]
    canonical_lines.append("")
    rag_tokens = token_data["rag_source_tokens"]
    if rag_tokens:
        canonical_lines.append(f"{_CANONICAL_RAG_RETRIEVAL_CLAIM} {rag_tokens[0]}")
        canonical_lines.append("")

    return "\n".join(
        [
            *lines[: heading_index + 1],
            *canonical_lines,
            *cleaned_section,
            *lines[section_end:],
        ]
    )


def canonical_attribution_bindings(*, official_sources=(), rag_sources=()):
    """Build a unique token-to-label map and reject canonical identifier collisions."""

    bindings = {}
    for source in official_sources or []:
        item = source if isinstance(source, dict) else {}
        if str(item.get("id") or "").strip() and str(item.get("name") or "").strip():
            _add_attribution_binding(
                bindings,
                format_official_citation_token(item),
                format_official_attribution(item),
            )
    for source in rag_sources or []:
        item = source if isinstance(source, dict) else {}
        if str(item.get("source_id") or "").strip() and str(item.get("title") or "").strip():
            _add_attribution_binding(
                bindings,
                format_rag_citation_token(item),
                format_rag_attribution(item),
            )
    return bindings


def fold_known_attribution_labels(text, *, official_sources=(), rag_sources=()):
    """Replace deterministic display labels with opaque tokens before model access."""

    bindings = canonical_attribution_bindings(
        official_sources=official_sources,
        rag_sources=rag_sources,
    )
    labels_to_tokens = {label: token for token, label in bindings.items()}
    if not labels_to_tokens:
        return str(text or "")
    matcher = re.compile("|".join(re.escape(label) for label in sorted(labels_to_tokens, key=len, reverse=True)))
    return matcher.sub(lambda match: labels_to_tokens[match.group(0)], str(text or ""))


def _add_attribution_binding(bindings, token, label):
    existing = bindings.get(token)
    if existing is not None and existing != label:
        raise ValueError(f"Canonical source identifier collision for {token}.")
    bindings[token] = label


def canonical_rag_source_ids(text, sources):
    """Return source IDs whose complete canonical RAG labels occur in ``text``."""

    content = visible_markdown_text(text)
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

    content = visible_markdown_text(text)
    attributed = set()
    for source in sources or []:
        item = source if isinstance(source, dict) else {}
        if not str(item.get("id") or "").strip() or not str(item.get("name") or "").strip():
            continue
        label = format_official_attribution(item)
        if label in content:
            attributed.add(_normalise_source_id(item["id"]))
    return attributed


def canonical_official_source_ids_on_plain_lines(text, sources):
    """Return official IDs whose display label is a complete visible list/text line."""

    lines = _plain_visible_lines(text)
    attributed = set()
    for source in sources or []:
        item = source if isinstance(source, dict) else {}
        if not str(item.get("id") or "").strip() or not str(item.get("name") or "").strip():
            continue
        label = format_official_attribution(item)
        if any(_LIST_MARKER.sub("", line).strip() == label for line in lines):
            attributed.add(_normalise_source_id(item["id"]))
    return attributed


def canonical_rag_claim_source_ids(text, sources):
    """Return RAG IDs cited at the end of a visible, substantive sentence."""

    lines = _plain_visible_lines(text)
    attributed = set()
    for source in sources or []:
        item = source if isinstance(source, dict) else {}
        if not str(item.get("source_id") or "").strip() or not str(item.get("title") or "").strip():
            continue
        label = format_rag_attribution(item)
        for line in lines:
            visible = _LIST_MARKER.sub("", line).strip()
            if not visible.endswith(label):
                continue
            claim = visible[: -len(label)].strip()
            if len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", claim)) >= 5 and re.search(r"[.!?]\s*$", claim):
                attributed.add(_normalise_source_id(item["source_id"]))
                break
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
    return result


def strip_application_source_bindings(text, *, official_sources=(), rag_sources=()):
    """Remove exact application-owned source lines before scoring model prose."""

    token_data = canonical_source_token_data(
        official_sources=official_sources,
        rag_sources=rag_sources,
    )
    official_bindings = {
        *canonical_official_labels(official_sources),
        *token_data["official_source_tokens"],
    }
    rag_bindings = {
        *canonical_rag_labels(rag_sources),
        *token_data["rag_source_tokens"],
    }
    result = []
    for line in str(text or "").splitlines():
        visible = normalise_render_equivalent_text(line)
        candidate = _LIST_MARKER.sub("", visible).strip()
        if candidate in official_bindings:
            continue
        if any(candidate == f"{_CANONICAL_RAG_RETRIEVAL_CLAIM} {binding}" for binding in rag_bindings):
            continue
        result.append(line)
    return "\n".join(result)


def extract_markdown_section(text, heading):
    """Extract one exact Markdown section, including only its nested subsections."""

    target = normalise_markdown_heading(heading)
    selected = []
    active_level = None
    fence_character = None
    fence_length = 0
    html_block_tag = None
    for line in visible_markdown_text(text).splitlines():
        if html_block_tag is not None:
            if re.search(rf"</{re.escape(html_block_tag)}\s*>", line, flags=re.IGNORECASE):
                html_block_tag = None
            continue
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
        html_open = re.match(r"^\s*<([A-Za-z][\w:-]*)\b", line)
        if html_open:
            tag = html_open.group(1)
            if (
                tag.casefold() not in _VOID_HTML_TAGS
                and not re.search(rf"</{re.escape(tag)}\s*>", line, flags=re.IGNORECASE)
                and not re.search(r"/\s*>\s*$", line)
            ):
                html_block_tag = tag
            continue
        match = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*$", line)
        if match:
            level = len(match.group(1))
            current = normalise_markdown_heading(match.group(2))
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


def visible_markdown_text(text):
    """Remove non-rendered HTML containers before accepting model-authored citations."""

    content = _HTML_COMMENT.sub("", str(text or ""))
    content = _UNCLOSED_HTML_COMMENT.sub("", content)
    previous = None
    while previous != content:
        previous = content
        content = _NON_VISIBLE_HTML_BLOCK.sub("", content)
        content = _HIDDEN_HTML_BLOCK.sub("", content)
        content = _UNCLOSED_NON_VISIBLE_HTML_BLOCK.sub("", content)
        content = _UNCLOSED_HIDDEN_HTML_BLOCK.sub("", content)
    return content


def plain_markdown_claim_text(text):
    """Remove inline Markdown/HTML syntax for safety lint while preserving line boundaries."""

    content = normalise_policy_lint_text(text)
    content = content.replace("<!--", "").replace("-->", "")
    content = re.sub(r"<[^>\r\n]+>", "", content)
    content = re.sub(r"!\[([^\]]*)\]\([^\r\n)]*\)", r"\1", content)
    content = re.sub(r"\[([^\]]+)\]\([^\r\n)]*\)", r"\1", content)
    content = re.sub(r"(?m)^ {0,3}(?:#{1,6}\s+|>\s*)", "", content)
    content = re.sub(r"\\([\\`*{}\[\]()#+.!_>~-])", r"\1", content)
    content = content.replace("`", "").replace("*", "").replace("_", "").replace("~", "")
    return content


def normalise_render_equivalent_text(text):
    """Canonicalise entity and compatibility variants in model-visible text."""

    content = html.unescape(str(text or ""))
    content = unicodedata.normalize("NFKC", content)
    return "".join(
        character
        for character in content
        if unicodedata.category(character) != "Cf" and not _is_variation_selector(character)
    )


def normalise_policy_lint_text(text):
    """Build an accent-insensitive shadow used only by deterministic policy lint."""

    content = unicodedata.normalize("NFKD", normalise_render_equivalent_text(text))
    return "".join(character for character in content if unicodedata.category(character) not in {"Cf", "Mn", "Me"})


def has_model_authored_url(text):
    """Return whether rendered model-authored text contains a web URL."""

    content = normalise_policy_lint_text(text)
    return any(
        pattern.search(content) is not None for pattern in (_URL, _MARKDOWN_LINK_START, _MARKDOWN_REFERENCE_LINK)
    )


def has_model_authored_raw_html(text):
    """Return whether a narrative contains a raw HTML tag or comment opener."""

    return _RAW_HTML.search(normalise_render_equivalent_text(text)) is not None


def has_unbound_attribution_marker(text):
    """Return whether model prose retains an attribution-like unverified marker."""

    content = normalise_render_equivalent_text(text)
    dash_normalised = "".join("-" if unicodedata.category(character) == "Pd" else character for character in content)
    return _UNBOUND_ATTRIBUTION_MARKER.search(dash_normalised) is not None


def neutralise_prompt_control_markers(value, *, preserve_retrieved_evidence=False):
    """Remove untrusted text that could close or forge an application prompt block."""

    content = normalise_render_equivalent_text(value)

    def replace(match):
        if preserve_retrieved_evidence and match.group("retrieved") is not None:
            return match.group(0)
        return "[prompt control marker removed]"

    return _PROMPT_CONTROL_MARKER.sub(replace, content)


def _plain_visible_lines(text):
    """Yield rendered prose/list candidates while excluding code, raw HTML and references."""

    content = visible_markdown_text(text)
    result = []
    fence_character = None
    fence_length = 0
    html_block_tag = None
    previous_line_added = False
    for raw_line in content.splitlines():
        if html_block_tag is not None:
            if re.search(rf"</{re.escape(html_block_tag)}\s*>", raw_line, flags=re.IGNORECASE):
                html_block_tag = None
            previous_line_added = False
            continue
        html_open = re.match(r"^\s*<([A-Za-z][\w:-]*)\b", raw_line)
        if html_open:
            tag = html_open.group(1)
            if not re.search(rf"</{re.escape(tag)}\s*>", raw_line, flags=re.IGNORECASE) and not re.search(
                r"/\s*>\s*$", raw_line
            ):
                html_block_tag = tag
            previous_line_added = False
            continue
        if re.match(r"^ {0,3}(?:=+|-+)\s*$", raw_line):
            if previous_line_added and result:
                result.pop()
            previous_line_added = False
            continue
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", raw_line)
        if fence_character is not None:
            marker = fence.group(1) if fence else ""
            suffix = fence.group(2) if fence else ""
            if marker.startswith(fence_character * fence_length) and not suffix.strip():
                fence_character = None
                fence_length = 0
            previous_line_added = False
            continue
        if fence:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            previous_line_added = False
            continue
        if (
            raw_line.startswith(("    ", "\t"))
            or re.match(r"^ {0,3}(?:#|>)", raw_line)
            or _REFERENCE_DEFINITION.match(raw_line)
            or re.search(r"</?[A-Za-z][^>]*>", raw_line)
            or "`" in raw_line
        ):
            previous_line_added = False
            continue
        if raw_line.strip():
            result.append(raw_line)
            previous_line_added = True
        else:
            previous_line_added = False
    return result


def normalise_source_metadata(value, *, fallback="To be confirmed"):
    """Bound source metadata before placing it beside untrusted retrieved text."""

    return _normalise_metadata(value, fallback=fallback)


def redact_urls(value):
    """Keep model-visible evidence free of links bound by deterministic appendices."""

    placeholder = "[URL omitted; see deterministic Evidence Tables]"
    content = normalise_render_equivalent_text(value)
    content = _MARKDOWN_INLINE_LINK.sub(
        lambda match: f"{match.group('prefix')}{placeholder}{match.group('suffix')}",
        content,
    )
    content = _MARKDOWN_REFERENCE_LINK.sub(
        lambda match: f"{match.group('prefix')}{placeholder}{match.group('suffix')}",
        content,
    )
    return _URL.sub(placeholder, content)


def _normalise_source_id(value):
    source_id = _SOURCE_ID_INVALID.sub("-", " ".join(str(value or "").split())).strip("-.")
    return source_id[:120] or "unknown-source"


def _opaque_source_ref(kind, source_id):
    return hashlib.sha256(f"{kind}:{source_id}".encode("utf-8")).hexdigest()[:12]


def _markdown_heading_positions(lines, heading):
    target = normalise_markdown_heading(heading)
    positions = []
    fence_character = None
    fence_length = 0
    for index, line in enumerate(lines):
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
        if match and normalise_markdown_heading(match.group(2)) == target:
            positions.append((index, len(match.group(1))))
    return positions


def _markdown_section_end(lines, heading_index, heading_level):
    fence_character = None
    fence_length = 0
    for index in range(heading_index + 1, len(lines)):
        line = lines[index]
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
        match = re.match(r"^ {0,3}(#{1,6})\s+", line)
        if match and len(match.group(1)) <= heading_level:
            return index
    return len(lines)


def _remove_model_attribution_lines(lines, *, known_labels):
    result = []
    fence_character = None
    fence_length = 0
    normalised_labels = sorted(
        (normalise_render_equivalent_text(label) for label in known_labels),
        key=len,
        reverse=True,
    )
    for line in lines:
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence_character is not None:
            result.append(line)
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
            result.append(line)
            continue
        visible = normalise_render_equivalent_text(line)
        if _ATTRIBUTION_TOKEN.search(visible) is None and not any(label in visible for label in normalised_labels):
            result.append(line)
            continue
        visible = _ATTRIBUTION_TOKEN.sub("", visible)
        for label in normalised_labels:
            visible = visible.replace(label, "")
        visible = visible.rstrip()
        if re.fullmatch(r"\s*(?:[-+*]|\d+[.)])\s*", visible):
            continue
        prose = _LIST_MARKER.sub("", visible).strip()
        if not prose or prose == _CANONICAL_RAG_RETRIEVAL_CLAIM or _SOURCE_ANNOTATION_ONLY.fullmatch(prose) is not None:
            continue
        result.append(visible)
    return result


def _is_variation_selector(character):
    codepoint = ord(character)
    return 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF


def _normalise_metadata(value, *, fallback):
    text = visible_markdown_text(redact_urls(value))
    text = _ATTRIBUTION_TOKEN.sub("[citation token removed]", text)
    text = text.replace("`", "'").replace("<", "(").replace(">", ")")
    text = " ".join(text.split()).strip()
    return text[:300] or fallback


def normalise_markdown_heading(value):
    """Canonicalise a rendered ATX heading title for governed comparisons."""

    content = normalise_render_equivalent_text(value)
    content = re.sub(r"\s+#+\s*$", "", content)
    content = " ".join(content.split())
    return re.sub(r"^\d+[.)]\s*", "", content).casefold()
