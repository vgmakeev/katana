from __future__ import annotations

import os
from pathlib import Path

from katana.apply_io import _write_split_outputs
from katana.models import SourceSplitMove, SourceSplitPlan

from .parser import RustItem, parse_rust_items


def plan_rust_split(source: Path, moves: tuple[SourceSplitMove, ...]) -> SourceSplitPlan:
    items = parse_rust_items(source)
    by_name = _unique_items(items)
    moved: list[str] = []
    seen: set[str] = set()
    targets: set[Path] = set()
    for move in moves:
        if move.target.suffix != ".rs":
            raise ValueError(f"Rust split target must use .rs: {move.target}")
        resolved_target = move.target.resolve()
        if resolved_target in targets:
            raise ValueError(f"Multiple Rust moves target {move.target}; combine their symbols")
        targets.add(resolved_target)
        selected: list[RustItem] = []
        for name in move.symbols:
            if name in seen:
                raise ValueError(f"Symbol is moved more than once: {name}")
            item = by_name.get(name)
            if item is None:
                raise ValueError(f"Symbol not found in {source}: {name}")
            seen.add(name)
            moved.append(name)
            selected.append(item)
        _validate_move_context(items, move, selected)
    return SourceSplitPlan(source, moves, tuple(moved), ())


def apply_rust_split(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    force: bool,
) -> SourceSplitPlan:
    plan = plan_rust_split(source, moves)
    items = _unique_items(parse_rust_items(source))
    source_bytes = source.read_bytes()
    newline = b"\r\n" if b"\r\n" in source_bytes else b"\n"
    replacements: list[tuple[int, int, bytes]] = []
    insertions: dict[int, list[bytes]] = {}
    outputs: dict[Path, str] = {}
    for move in moves:
        if move.target.exists() and not force:
            raise ValueError(f"Rust split target already exists: {move.target}; use --force")
        selected = sorted((items[name] for name in move.symbols), key=lambda item: item.ordinal)
        blocks = [source_bytes[item.span.start_byte : item.span.end_byte] for item in selected]
        moved_bytes = (newline * 2).join(block.rstrip(b"\r\n") for block in blocks)
        if selected[0].wrapper_start_byte is not None:
            wrapper_start = selected[0].wrapper_start_byte
            wrapper_end = selected[0].wrapper_end_byte
            assert wrapper_end is not None
            target_bytes = (
                source_bytes[wrapper_start:wrapper_end]
                + newline
                + moved_bytes
                + newline
                + b"}"
                + newline
            )
        else:
            target_bytes = moved_bytes + newline
        outputs[move.target] = target_bytes.decode("utf-8")

        first = selected[0]
        relative = os.path.relpath(move.target, source.parent).replace(os.sep, "/")
        if first.wrapper_start_byte is None:
            indent = _line_indent(source_bytes, first.span.start_byte)
            directive = indent + f'include!("{relative}");'.encode() + newline
            replacements.append((first.span.start_byte, first.span.end_byte, directive))
            replacements.extend(
                (item.span.start_byte, item.span.end_byte, b"") for item in selected[1:]
            )
        else:
            replacements.extend(
                (item.span.start_byte, item.span.end_byte, b"") for item in selected
            )
            insertions.setdefault(first.include_byte, []).append(
                newline + f'include!("{relative}");'.encode() + newline
            )

    rewritten = source_bytes
    replacements.extend(
        (offset, offset, b"".join(directives)) for offset, directives in insertions.items()
    )
    for start, end, replacement in sorted(replacements, reverse=True):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    outputs[source] = rewritten.decode("utf-8")
    _write_split_outputs(source, moves, outputs)
    return plan


def _unique_items(items: list[RustItem]) -> dict[str, RustItem]:
    result: dict[str, RustItem] = {}
    duplicates: set[str] = set()
    for item in items:
        if item.symbol.name in result:
            duplicates.add(item.symbol.name)
        result[item.symbol.name] = item
    if duplicates:
        names = ", ".join(sorted(duplicates))
        raise ValueError(f"Rust symbols need unique qualified names; duplicates: {names}")
    return result


def _validate_move_context(
    items: list[RustItem],
    move: SourceSplitMove,
    selected: list[RustItem],
) -> None:
    if not selected:
        raise ValueError(f"Move has no Rust symbols: {move.target}")
    contexts = {item.context for item in selected}
    if len(contexts) != 1:
        raise ValueError(f"Rust move {move.target} mixes module items and/or distinct impl blocks")
    indexes = sorted(items.index(item) for item in selected)
    if indexes != list(range(indexes[0], indexes[-1] + 1)):
        raise ValueError(
            f"Rust move {move.target} must contain a contiguous item range to preserve order"
        )


def _line_indent(source: bytes, offset: int) -> bytes:
    line_start = source.rfind(b"\n", 0, offset) + 1
    prefix = source[line_start:offset]
    return prefix if not prefix.strip() else b""


__all__ = ("apply_rust_split", "plan_rust_split")
