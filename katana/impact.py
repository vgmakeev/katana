from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

from .external import _project_root_for
from .models import SourceSplitMove

_SCAN_EXCLUDED_DIRS = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build", "reference"}
)
_SCAN_FILE_CAP = 5000
_SCAN_SIZE_CAP = 1_000_000


def _project_source_files(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    suffixes: tuple[str, ...] = (".py",),
) -> Iterator[tuple[Path, str, bool]]:
    """Yield (path, text, capped) for project files worth scanning.

    Shared discipline for impact scans: skip excluded dirs, the split files
    themselves and oversized files; stop after the file cap, yielding a final
    capped marker so reports can say the scan was partial.
    """
    skip = {source.resolve(), *(move.target.resolve() for move in moves)}
    root = _project_root_for(source)
    scanned = 0
    for path in sorted(p for s in suffixes for p in root.rglob(f"*{s}")):
        if any(part in _SCAN_EXCLUDED_DIRS for part in path.parts):
            continue
        if path.resolve() in skip:
            continue
        scanned += 1
        if scanned > _SCAN_FILE_CAP:
            yield path, "", True
            return
        try:
            if path.stat().st_size > _SCAN_SIZE_CAP:
                continue
            text = path.read_text()
        except UnicodeDecodeError, OSError:
            continue
        if source.stem not in text:
            continue
        yield path, text, False


def dynamic_reference_warnings(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    limit: int = 20,
) -> list[str]:
    """Report textual dotted references to moved symbols across the project.

    AST-based moves cannot rewrite strings: importlib paths, test fixtures or
    configs referencing "<module>.<symbol>" keep resolving through public
    re-exports but observe the old module home; private names break outright.
    """
    moved = [name for move in moves for name in move.symbols]
    if not moved:
        return []
    pattern = re.compile(
        "|".join(rf"\b{re.escape(source.stem)}\.{re.escape(name)}\b" for name in moved)
    )
    partial_hint = f"search the project for '{source.stem}.' before relying on dotted paths"
    name_prefilter = re.compile("|".join(re.escape(name) for name in moved))
    warnings: list[str] = []
    for path, text, capped in _project_source_files(source, moves):
        if capped:
            warnings.append(
                f"textual reference scan stopped after {_SCAN_FILE_CAP} files; {partial_hint}"
            )
            return warnings
        if name_prefilter.search(text) is None:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = pattern.search(line)
            if match is None:
                continue
            warnings.append(
                f"{path}:{lineno} references {match.group(0)} textually; dotted/string "
                "references are not rewritten (public names keep resolving via the "
                "re-export, private names break)"
            )
            if len(warnings) >= limit:
                warnings.append(f"more textual references exist; {partial_hint}")
                return warnings
    return warnings


def import_impact_report(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Files that import moved symbols from the source module.

    Those imports keep working through the source re-exports; the report
    lets agents migrate consumers to the new module homes deliberately
    instead of discovering them by hand.
    """
    moved = {name for move in moves for name in move.symbols}
    if not moved:
        return []
    if source.suffix in (".ts", ".tsx", ".js", ".jsx"):
        return _text_import_impact(source, moves, moved, limit=limit)
    if source.suffix != ".py":
        return []
    targets_by_symbol = {name: move.target for move in moves for name in move.symbols}
    report: list[dict[str, object]] = []
    for path, text, capped in _project_source_files(source, moves):
        if capped:
            break
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if node.module.split(".")[-1] != source.stem:
                continue
            hits = sorted({alias.name for alias in node.names} & moved)
            if not hits:
                continue
            report.append(
                {
                    "file": str(path),
                    "line": node.lineno,
                    "module": "." * node.level + node.module,
                    "symbols": hits,
                    "new_homes": sorted({str(targets_by_symbol[name]) for name in hits}),
                }
            )
            if len(report) >= limit:
                return report
    return report


_TS_IMPORT_RE = re.compile(
    r"import\s+(?:type\s+)?\{(?P<names>[^}]*)\}\s+from\s+['\"](?P<module>[^'\"]+)['\"]",
    re.DOTALL,
)


def _text_import_impact(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    moved: set[str],
    *,
    limit: int,
) -> list[dict[str, object]]:
    targets_by_symbol = {name: move.target for move in moves for name in move.symbols}
    report: list[dict[str, object]] = []
    for path, text, capped in _project_source_files(
        source, moves, suffixes=(".ts", ".tsx", ".js", ".jsx")
    ):
        if capped:
            break
        for match in _TS_IMPORT_RE.finditer(text):
            module = match.group("module")
            if module.rsplit("/", 1)[-1] != source.stem:
                continue
            names = {
                item.split(" as ")[0].strip()
                for item in match.group("names").split(",")
                if item.strip()
            }
            hits = sorted(names & moved)
            if not hits:
                continue
            line = text.count("\n", 0, match.start()) + 1
            report.append(
                {
                    "file": str(path),
                    "line": line,
                    "module": module,
                    "symbols": hits,
                    "new_homes": sorted({str(targets_by_symbol[name]) for name in hits}),
                }
            )
            if len(report) >= limit:
                return report
    return report
