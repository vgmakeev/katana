from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import SourceSplitMove, SourceSymbol


def _symbol_groups(symbols: list[SourceSymbol]) -> list[list[SourceSymbol]]:
    by_name = {symbol.name: symbol for symbol in symbols}
    graph: dict[str, set[str]] = {symbol.name: set() for symbol in symbols}
    for symbol in symbols:
        for reference in symbol.references:
            if reference in by_name:
                graph[symbol.name].add(reference)
                graph[reference].add(symbol.name)

    groups: list[list[SourceSymbol]] = []
    visited: set[str] = set()
    for symbol in symbols:
        if symbol.name in visited:
            continue
        stack = [symbol.name]
        component: list[SourceSymbol] = []
        visited.add(symbol.name)
        while stack:
            name = stack.pop()
            component.append(by_name[name])
            for next_name in graph[name]:
                if next_name not in visited:
                    visited.add(next_name)
                    stack.append(next_name)
        component.sort(key=lambda item: item.start_line)
        groups.append(component)
    return groups


def _text_move_closures(source: Path, symbols: list[SourceSymbol]) -> dict[str, frozenset[str]]:
    by_name = {symbol.name: symbol for symbol in symbols}
    pinned = {symbol.name for symbol in symbols if _pinned_text_symbol(source, symbol)}
    dart = source.suffix == ".dart"
    consumers: dict[str, set[str]] = {name: set() for name in by_name}
    for symbol in symbols:
        for reference in symbol.references:
            if reference in consumers:
                consumers[reference].add(symbol.name)

    def closure_for(seed: str) -> frozenset[str]:
        closure: set[str] = set()
        stack = [seed]
        while stack:
            name = stack.pop()
            if name in closure:
                continue
            closure.add(name)
            stack.extend(ref for ref in by_name[name].references if ref in by_name)
            # Dart private symbols are library-private: they can only move
            # together with every consumer, in the same target file.
            if dart and name.startswith("_"):
                stack.extend(consumers[name])
        return frozenset(closure)

    closures: dict[str, frozenset[str]] = {}
    for symbol in symbols:
        if symbol.name in pinned:
            continue
        closure = closure_for(symbol.name)
        if closure & pinned:
            continue
        closures[symbol.name] = closure
    return closures


def _pinned_text_symbol(source: Path, symbol: SourceSymbol) -> bool:
    if source.suffix == ".dart":
        return symbol.name == "main"
    meta = symbol.meta or {}
    if meta.get("default_export") or symbol.name == "default_export":
        return True
    return "export default" in symbol.signature


def _text_seed_tier(source: Path, symbol: SourceSymbol) -> int:
    if source.suffix == ".dart":
        return 0 if symbol.name.startswith("_") else 1
    meta = symbol.meta or {}
    if "exported" in meta:
        return 1 if meta["exported"] else 0
    return 1 if symbol.signature.lstrip().startswith("export") else 0


def _text_part_moves(
    source: Path,
    prefix: str,
    parts: list[list[str]],
) -> tuple[SourceSplitMove, ...]:
    return tuple(
        SourceSplitMove(
            target=source.with_name(f"{prefix}_part{index}{source.suffix}"),
            symbols=tuple(names),
        )
        for index, names in enumerate(parts, start=1)
    )


def _ordered_text_moves(
    source: Path,
    prefix: str,
    symbols: list[SourceSymbol],
    source_lines: int,
    max_lines: int,
) -> tuple[tuple[SourceSplitMove, ...], int]:
    # CSS parts are @import-ed above the remaining rules, so only a leading
    # run of rules preserves cascade order. Markdown moves trailing sections
    # so the document keeps its intro in place.
    from_top = source.suffix == ".css"
    ordered = list(symbols) if from_top else list(reversed(symbols))
    remaining_lines = source_lines
    selected: list[SourceSymbol] = []
    for symbol in ordered:
        if remaining_lines <= max_lines:
            break
        selected.append(symbol)
        remaining_lines -= symbol.code_lines
    if not from_top:
        selected.reverse()

    parts: list[list[str]] = []
    part: list[str] = []
    part_lines = 0
    for symbol in selected:
        if part and part_lines + symbol.code_lines > max_lines:
            parts.append(part)
            part = []
            part_lines = 0
        part.append(symbol.name)
        part_lines += symbol.code_lines
    if part:
        parts.append(part)
    return _text_part_moves(source, prefix, parts), remaining_lines


def _reference_text_moves(
    source: Path,
    prefix: str,
    symbols: list[SourceSymbol],
    source_lines: int,
    max_lines: int,
) -> tuple[tuple[SourceSplitMove, ...], int]:
    by_name = {symbol.name: symbol for symbol in symbols}
    closures = _text_move_closures(source, symbols)

    def lines_of(names: frozenset[str] | set[str]) -> int:
        return sum(by_name[name].code_lines for name in names)

    seeds = sorted(
        closures,
        key=lambda name: (
            _text_seed_tier(source, by_name[name]),
            -lines_of(closures[name]),
            by_name[name].start_line,
        ),
    )
    selected: set[str] = set()
    remaining_lines = source_lines
    for seed in seeds:
        if remaining_lines <= max_lines:
            break
        added = closures[seed] - selected
        added_lines = lines_of(added)
        if not added_lines:
            continue
        selected |= added
        remaining_lines -= added_lines

    # Text applies cannot generate imports between parts, so each part packs
    # whole reference-connected components.
    components = _symbol_groups([by_name[name] for name in selected])
    components.sort(key=lambda component: component[0].start_line)
    parts: list[list[str]] = []
    part: list[str] = []
    part_lines = 0
    for component in components:
        component_lines = sum(symbol.code_lines for symbol in component)
        if part and part_lines + component_lines > max_lines:
            parts.append(part)
            part = []
            part_lines = 0
        part.extend(symbol.name for symbol in component)
        part_lines += component_lines
    if part:
        parts.append(part)
    for names in parts:
        names.sort(key=lambda name: by_name[name].start_line)
    return _text_part_moves(source, prefix, parts), remaining_lines


def _text_safe_move_groups(source: Path, symbols: list[SourceSymbol]) -> list[dict[str, Any]]:
    by_name = {symbol.name: symbol for symbol in symbols}
    closures = _text_move_closures(source, symbols)
    entries: list[tuple[SourceSymbol, frozenset[str]]] = []
    seen: set[frozenset[str]] = set()
    for symbol in symbols:
        closure = closures.get(symbol.name)
        if closure is None or closure in seen:
            continue
        seen.add(closure)
        entries.append((symbol, closure))
    dart = source.suffix == ".dart"
    groups = []
    for seed, closure in entries:
        if dart:
            visibility = "private" if seed.name.startswith("_") else "public"
        else:
            visibility = "exported" if _text_seed_tier(source, seed) else "local"
        groups.append(_safe_move_group(seed, closure, by_name, visibility=visibility))
    groups.sort(
        key=lambda group: (
            group["visibility"] not in ("private", "local"),
            -group["code_lines"],
        )
    )
    return groups


def _safe_move_group(
    seed: SourceSymbol,
    closure: frozenset[str],
    by_name: dict[str, SourceSymbol],
    *,
    visibility: str,
) -> dict[str, Any]:
    return {
        "seed": seed.name,
        "kind": seed.kind,
        "visibility": visibility,
        "code_lines": sum(by_name[name].code_lines for name in closure),
        "symbols": sorted(closure, key=lambda name: by_name[name].start_line),
        "tags": list(seed.tags),
    }
