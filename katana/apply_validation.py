from __future__ import annotations

from pathlib import Path

from .models import SourceSplitMove
from .outline import outline_python_module


def _check_code_line_count(path: Path, text: str) -> int:
    if path.suffix == ".py":
        return sum(
            1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
        )
    if path.suffix in (".md", ".mdx"):
        return sum(1 for line in text.splitlines() if line.strip())
    if path.suffix == ".css":
        return sum(
            1
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(("/*", "*"))
        )
    return sum(
        1
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("//", "/*", "*"))
    )


def _plan_cycle_warnings(source: Path, moves: tuple[SourceSplitMove, ...]) -> list[str]:
    if not moves:
        return []
    symbols = {symbol.name: symbol for symbol in outline_python_module(source)}
    symbol_file = {symbol.name: source for symbol in symbols.values()}
    for move in moves:
        for moved_symbol in move.symbols:
            symbol_file[moved_symbol] = move.target

    edges: set[tuple[Path, Path]] = set()
    for symbol in symbols.values():
        from_file = symbol_file[symbol.name]
        for reference in symbol.references:
            to_file = symbol_file.get(reference)
            if to_file is not None and to_file != from_file:
                edges.add((from_file, to_file))

    warnings: list[str] = []
    for left, right in sorted(edges):
        if (right, left) in edges and str(left) < str(right):
            warnings.append(f"potential import cycle between {left} and {right}")
    return warnings
