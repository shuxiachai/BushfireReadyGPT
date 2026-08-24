"""Shared parsing helpers for pipe-delimited Markdown tables."""

import re

_ALIGNMENT_CELL = re.compile(r":?-{3,}:?")


def _is_escaped(text: str, index: int) -> bool:
    """Return whether the character at ``index`` has an odd slash prefix."""
    slash_count = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        slash_count += 1
        index -= 1
    return slash_count % 2 == 1


def parse_markdown_table_row(line: str) -> list[str] | None:
    """Parse one outer-pipe Markdown table row, preserving empty cells.

    Pipes escaped with an odd number of backslashes are treated as cell content;
    the escaping backslash is removed while any preceding pairs are preserved.
    ``None`` identifies text that is not a complete table row.
    """
    line = line.strip()
    if len(line) < 2 or line[0] != "|" or line[-1] != "|":
        return None
    if _is_escaped(line, len(line) - 1):
        return None

    cells: list[str] = []
    current: list[str] = []
    for index in range(1, len(line) - 1):
        character = line[index]
        if character != "|":
            current.append(character)
            continue
        if _is_escaped(line, index):
            current.pop()
            current.append("|")
            continue
        cells.append("".join(current).strip())
        current = []
    cells.append("".join(current).strip())
    return cells


def is_markdown_table_row(line: str) -> bool:
    """Return whether ``line`` is a complete outer-pipe table row."""
    return parse_markdown_table_row(line) is not None


def is_markdown_table_separator(line: str) -> bool:
    """Return whether ``line`` is a Markdown alignment separator row."""
    cells = parse_markdown_table_row(line)
    if not cells:
        return False
    return all(_ALIGNMENT_CELL.fullmatch("".join(cell.split())) for cell in cells)
