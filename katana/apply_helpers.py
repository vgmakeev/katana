from __future__ import annotations

import ast
import re
from pathlib import Path

from .models import SourceSplitMove, SourceSymbol
from .outline import _decorated_start_line, _symbol_name


def _placeholder_target_warnings(moves: tuple[SourceSplitMove, ...]) -> list[str]:
    placeholders = [
        match.group(1) for move in moves if (match := re.search(r"(_part\d+)$", move.target.stem))
    ]
    if not placeholders:
        return []
    shown = ", ".join(placeholders[:5])
    return [
        (
            f"{len(placeholders)} targets keep placeholder names ({shown}); "
            "rename them in the plan for meaningful modules"
        )
    ]


def _react_refresh_warnings(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    symbols: dict[str, SourceSymbol],
) -> list[str]:
    if source.suffix != ".tsx":
        return []
    warnings: list[str] = []
    for move in moves:
        moved = [symbols[name] for name in move.symbols if name in symbols]
        if any("react_component" in symbol.tags for symbol in moved) and any(
            "react_component" not in symbol.tags for symbol in moved
        ):
            warnings.append(
                f"{move.target} mixes React components and non-component exports; "
                "verify react-refresh/only-export-components"
            )
    return warnings


def _symbol_spans(tree: ast.Module) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        name = _symbol_name(node)
        if name is not None and node.end_lineno is not None:
            spans[name] = (_decorated_start_line(node), node.end_lineno)
    return spans


def _slice_with_trailing_blank(lines: list[str], span: tuple[int, int]) -> list[str]:
    start, end = span
    zero_start = start - 1
    zero_end = end
    while zero_end < len(lines) and not lines[zero_end].strip():
        zero_end += 1
        break
    return lines[zero_start:zero_end]


def _remove_ranges(lines: list[str], ranges: list[tuple[int, int]]) -> list[str]:
    removed: set[int] = set()
    for start, end in ranges:
        zero_start = start - 1
        zero_end = end
        while zero_end < len(lines) and not lines[zero_end].strip():
            zero_end += 1
            break
        removed.update(range(zero_start, zero_end))
    return [line for index, line in enumerate(lines) if index not in removed]


def _collapse_blank_lines(text: str) -> str:
    output: list[str] = []
    blank_count = 0
    for line in text.splitlines(keepends=True):
        if line.strip():
            blank_count = 0
            output.append(line)
            continue
        blank_count += 1
        if blank_count <= 2:
            output.append(line)
    return "".join(output)
