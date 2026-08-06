from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import SourceSplitMove, SourceSplitPlan, SourceSymbol
from .text_planning import (
    _ordered_text_moves,
    _pinned_text_symbol,
    _reference_text_moves,
    _safe_move_group,
    _text_move_closures,
    _text_safe_move_groups,
)

_PYTHON_MOVABLE_KINDS = frozenset({"FunctionDef", "AsyncFunctionDef", "ClassDef"})

_PYTHON_STATE_KINDS = frozenset({"Assign", "AnnAssign"})


def _build_python_split_plan(
    source: Path,
    symbols: list[SourceSymbol],
    *,
    code_lines: int,
    max_lines: int = 750,
    headroom_lines: int = 0,
    target_prefix: str | None = None,
) -> SourceSplitPlan:
    movable = [symbol for symbol in symbols if symbol.kind in _PYTHON_MOVABLE_KINDS]
    if code_lines <= max_lines or not movable:
        return SourceSplitPlan(source=source, moves=(), moved_symbols=(), warnings=())

    by_name = {symbol.name: symbol for symbol in symbols}
    safe = _safe_python_moves(symbols)
    closures = {
        symbol.name: _safe_closure(symbol.name, by_name, safe)
        for symbol in movable
        if symbol.name in safe
    }

    def closure_lines(name: str) -> int:
        return sum(by_name[member].code_lines for member in closures[name])

    # Private helpers first, largest dependency closure first; public symbols
    # only when private helpers cannot get the source under budget.
    seeds = sorted(
        closures,
        key=lambda name: (
            not name.startswith("_"),
            -closure_lines(name),
            by_name[name].start_line,
        ),
    )
    selected: set[str] = set()
    remaining_lines = code_lines
    target_lines = max(max_lines - headroom_lines, 0)
    for seed in seeds:
        if remaining_lines <= target_lines:
            break
        added = closures[seed] - selected
        added_lines = sum(by_name[name].code_lines for name in added)
        if not added_lines:
            continue
        selected |= added
        remaining_lines -= added_lines

    prefix = target_prefix or source.stem
    moves = _python_part_moves(source, prefix, selected, by_name, target_lines or max_lines)
    plan = _plan_from_symbols(source, tuple(moves), symbols)
    warnings = list(plan.warnings)
    if remaining_lines > max_lines:
        warnings.append(
            f"suggested moves leave source near {remaining_lines} code lines; "
            "the remaining symbols are pinned by module-level state or public API "
            "kept in place, so split them manually with explicit moves or "
            "increase --max-lines"
        )
    return SourceSplitPlan(
        source=plan.source,
        moves=plan.moves,
        moved_symbols=plan.moved_symbols,
        warnings=tuple(warnings),
    )


def _safe_python_moves(symbols: list[SourceSymbol]) -> set[str]:
    """Greatest set of symbols whose in-file references all stay inside the set.

    Moving any subset closed under references only ever creates source -> target
    imports, so suggested plans cannot introduce import cycles. Module-level
    state pins itself and every symbol that reaches it; private constants may
    move together with their consumers.
    """
    by_name = {symbol.name: symbol for symbol in symbols}
    safe = {
        symbol.name
        for symbol in symbols
        if symbol.kind in _PYTHON_MOVABLE_KINDS
        or (symbol.kind in _PYTHON_STATE_KINDS and symbol.name.startswith("_"))
    }
    changed = True
    while changed:
        changed = False
        for name in tuple(safe):
            references = by_name[name].references
            if any(ref in by_name and ref not in safe for ref in references):
                safe.discard(name)
                changed = True
    return safe


def _safe_closure(seed: str, by_name: dict[str, SourceSymbol], safe: set[str]) -> frozenset[str]:
    closure: set[str] = set()
    stack = [seed]
    while stack:
        name = stack.pop()
        if name in closure:
            continue
        closure.add(name)
        stack.extend(ref for ref in by_name[name].references if ref in safe)
    return frozenset(closure)


def _python_part_moves(
    source: Path,
    prefix: str,
    selected: set[str],
    by_name: dict[str, SourceSymbol],
    max_lines: int,
) -> tuple[SourceSplitMove, ...]:
    # Chunk in dependency order so later parts only import earlier parts.
    parts: list[list[str]] = []
    part: list[str] = []
    part_lines = 0
    for name in _dependency_order(selected, by_name):
        lines = by_name[name].code_lines
        if part and part_lines + lines > max_lines:
            parts.append(part)
            part = []
            part_lines = 0
        part.append(name)
        part_lines += lines
    if part:
        parts.append(part)

    moves: list[SourceSplitMove] = []
    for index, names in enumerate(parts, start=1):
        names.sort(key=lambda name: by_name[name].start_line)
        moves.append(
            SourceSplitMove(
                target=source.with_name(f"{prefix}_part{index}.py"),
                symbols=tuple(names),
            )
        )
    return tuple(moves)


def _dependency_order(selected: set[str], by_name: dict[str, SourceSymbol]) -> list[str]:
    order: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        for ref in sorted(by_name[name].references):
            if ref in selected:
                visit(ref)
        order.append(name)

    for name in sorted(selected, key=lambda name: by_name[name].start_line):
        visit(name)
    return order


def _build_source_split_plan(
    source: Path,
    symbols: list[SourceSymbol],
    *,
    code_lines: int,
    max_lines: int = 750,
    headroom_lines: int = 0,
    target_prefix: str | None = None,
) -> SourceSplitPlan:
    from .adapters import language_adapter_for

    return language_adapter_for(source).build_plan(
        source,
        symbols,
        code_lines=code_lines,
        max_lines=max_lines,
        headroom_lines=headroom_lines,
        target_prefix=target_prefix,
    )


def _build_text_split_plan(
    source: Path,
    symbols: list[SourceSymbol],
    *,
    code_lines: int,
    max_lines: int = 750,
    headroom_lines: int = 0,
    target_prefix: str | None = None,
    reference_aware: bool,
) -> SourceSplitPlan:
    if code_lines <= max_lines or not symbols:
        return SourceSplitPlan(source=source, moves=(), moved_symbols=(), warnings=())

    prefix = target_prefix or source.stem
    target_lines = max(max_lines - headroom_lines, 0)
    if reference_aware:
        moves, remaining_lines = _reference_text_moves(
            source, prefix, symbols, code_lines, target_lines
        )
    else:
        moves, remaining_lines = _ordered_text_moves(
            source, prefix, symbols, code_lines, target_lines
        )
    plan = _plan_from_symbols(source, moves, symbols)
    warnings = list(plan.warnings)
    if remaining_lines > max_lines:
        warnings.append(
            f"suggested moves leave source near {remaining_lines} code lines; "
            "the remaining symbols are pinned by entrypoints, default exports or "
            "shared references kept in place, so split them manually with "
            "explicit moves or increase --max-lines"
        )
    return SourceSplitPlan(source, plan.moves, plan.moved_symbols, tuple(warnings))


def source_safe_move_groups(source: Path, symbols: list[SourceSymbol]) -> dict[str, Any]:
    """Decision space for agents: every safe move group with its co-movers.

    The suggested plan is just one valid composition of these groups; agents
    compose their own plan file from the menu without reading the source.
    """
    from .adapters import language_adapter_for

    return language_adapter_for(source).safe_move_groups(source, symbols)


def _python_safe_move_payload(symbols: list[SourceSymbol]) -> dict[str, Any]:
    return {
        "composition": (
            "compose a plan from whole groups; python parts may import the "
            "source and each other, so any union of groups is valid. Pinned "
            "entries list module-state blockers: moving a blocker together "
            "with its dependents in an explicit plan unlocks those lines"
        ),
        "groups": _python_safe_move_groups(symbols),
        "pinned": _python_pin_hints(symbols),
    }


def _text_safe_move_groups_payload(
    source: Path,
    symbols: list[SourceSymbol],
    *,
    reference_aware: bool,
) -> dict[str, Any]:
    if reference_aware:
        composition = (
            "compose a plan from whole groups and keep each group inside one "
            "target: text parts cannot import the source or other parts"
        )
        if source.suffix == ".dart":
            composition += "; dart private symbols only move with all their consumers"
        return {
            "composition": composition,
            "groups": _text_safe_move_groups(source, symbols),
            "pinned": _text_pin_hints(source, symbols),
        }
    if source.suffix == ".css":
        return {
            "composition": (
                "moved rules are @import-ed above the remaining rules; move a "
                "leading run of rules in source order to preserve the cascade"
            ),
            "groups": [],
        }
    return {
        "composition": (
            "sections have no reference constraints; any sections can move, "
            "keep document order inside each part"
        ),
        "groups": [],
    }


def _python_pin_hints(symbols: list[SourceSymbol]) -> list[dict[str, Any]]:
    """Group pinned symbols by the module-state names that pin them.

    Shows the unlock order for oversized files in one assess: which blockers
    hold the most lines in place, without the agent tracing reference chains.
    """
    by_name = {symbol.name: symbol for symbol in symbols}
    pool = {
        symbol.name
        for symbol in symbols
        if symbol.kind in _PYTHON_MOVABLE_KINDS
        or (symbol.kind in _PYTHON_STATE_KINDS and symbol.name.startswith("_"))
    }
    safe = _safe_python_moves(symbols)
    hints: dict[frozenset[str], dict[str, Any]] = {}
    for symbol in symbols:
        if symbol.kind not in _PYTHON_MOVABLE_KINDS or symbol.name in safe:
            continue
        blockers: set[str] = set()
        seen: set[str] = set()
        stack = [symbol.name]
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            for reference in by_name[name].references:
                if reference not in by_name:
                    continue
                if reference in pool:
                    stack.append(reference)
                else:
                    blockers.add(reference)
        entry = hints.setdefault(
            frozenset(blockers),
            {"blockers": sorted(blockers), "symbols": [], "code_lines": 0},
        )
        entry["symbols"].append(symbol.name)
        entry["code_lines"] += symbol.code_lines
    ranked = sorted(hints.values(), key=lambda hint: -int(hint["code_lines"]))
    for hint in ranked:
        names = hint["symbols"]
        hint["symbol_count"] = len(names)
        hint["symbols"] = names[:8]
    return ranked[:5]


def _text_pin_hints(source: Path, symbols: list[SourceSymbol]) -> list[dict[str, Any]]:
    by_name = {symbol.name: symbol for symbol in symbols}
    closures = _text_move_closures(source, symbols)
    movable = set(closures)
    pinned = {symbol.name for symbol in symbols if symbol.name not in movable}
    if not pinned:
        return []
    hints: dict[frozenset[str], dict[str, Any]] = {}
    for symbol in symbols:
        if symbol.name in movable:
            continue
        blockers = _text_blockers(source, symbol, by_name, movable)
        entry = hints.setdefault(
            frozenset(blockers),
            {"blockers": sorted(blockers), "symbols": [], "code_lines": 0},
        )
        entry["symbols"].append(symbol.name)
        entry["code_lines"] += symbol.code_lines
    ranked = sorted(hints.values(), key=lambda hint: -int(hint["code_lines"]))
    for hint in ranked:
        names = hint["symbols"]
        hint["symbol_count"] = len(names)
        hint["symbols"] = names[:8]
    return ranked[:5]


def _text_blockers(
    source: Path,
    symbol: SourceSymbol,
    by_name: dict[str, SourceSymbol],
    movable: set[str],
) -> set[str]:
    if _pinned_text_symbol(source, symbol):
        return {symbol.name}
    blockers: set[str] = set()
    seen: set[str] = set()
    stack = [symbol.name]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        current = by_name.get(name)
        if current is None:
            continue
        for reference in current.references:
            if reference not in by_name:
                continue
            if reference in movable:
                stack.append(reference)
            else:
                blockers.add(reference)
    return blockers or {symbol.name}


def _python_safe_move_groups(symbols: list[SourceSymbol]) -> list[dict[str, Any]]:
    by_name = {symbol.name: symbol for symbol in symbols}
    safe = _safe_python_moves(symbols)
    entries: list[tuple[SourceSymbol, frozenset[str]]] = []
    seen: set[frozenset[str]] = set()
    for symbol in symbols:
        if symbol.kind not in _PYTHON_MOVABLE_KINDS or symbol.name not in safe:
            continue
        closure = _safe_closure(symbol.name, by_name, safe)
        if closure in seen:
            continue
        seen.add(closure)
        entries.append((symbol, closure))
    groups = [
        _safe_move_group(
            seed,
            closure,
            by_name,
            visibility="private" if seed.name.startswith("_") else "public",
        )
        for seed, closure in entries
    ]
    groups.sort(key=lambda group: (group["visibility"] != "private", -group["code_lines"]))
    return groups


def _plan_from_symbols(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    symbols: list[SourceSymbol],
) -> SourceSplitPlan:
    by_name = {symbol.name: symbol for symbol in symbols}
    moved: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for move in moves:
        for name in move.symbols:
            if name in seen:
                raise ValueError(f"Symbol is moved more than once: {name}")
            if name not in by_name:
                raise ValueError(f"Symbol not found in {source}: {name}")
            seen.add(name)
            moved.append(name)
    moved_set = set(moved)
    for name in moved:
        refs = [ref for ref in by_name[name].references if ref not in moved_set]
        if refs:
            warnings.append(
                f"{name} references source-local symbols not moved with it: " + ", ".join(refs)
            )
    if source.suffix == ".css" and moves:
        ordered_names = [symbol.name for symbol in symbols]
        if moved != ordered_names[: len(moved)]:
            warnings.append(
                "moved CSS rules are re-imported at the top of the source; cascade "
                "order changes for equal-specificity selectors, verify styles after applying"
            )
    return SourceSplitPlan(source, moves, tuple(moved), tuple(warnings))


def _suggested_plan_payload(
    plan: SourceSplitPlan,
    symbols: list[SourceSymbol],
    code_lines: int,
    *,
    max_lines: int,
    headroom_lines: int,
) -> dict[str, Any]:
    payload = plan.to_payload()
    by_name = {symbol.name: symbol for symbol in symbols}
    remaining = code_lines
    moves: list[dict[str, Any]] = []
    for move in plan.moves:
        move_payload = move.to_payload()
        move_symbols = [by_name[name] for name in move.symbols if name in by_name]
        moved_lines = sum(symbol.code_lines for symbol in move_symbols)
        remaining = max(remaining - moved_lines, 0)
        move_payload.update(
            {
                "symbol_payloads": [
                    symbol.to_payload(total_code_lines=code_lines) for symbol in move_symbols
                ],
                "moved_code_lines": moved_lines,
                "moved_code_lines_pct": round(moved_lines * 100 / code_lines, 1)
                if code_lines
                else 0,
                "estimated_source_code_lines_after_move": remaining,
                "produced_files": [
                    {
                        "path": str(plan.source),
                        "projected_lines": remaining,
                        "headroom": max_lines - remaining,
                    },
                    {
                        "path": str(move.target),
                        "projected_lines": moved_lines,
                        "headroom": max_lines - moved_lines,
                    },
                ],
                "reason": _move_reason(move_symbols),
            }
        )
        moves.append(move_payload)
    payload["moves"] = moves
    return payload


def _move_reason(symbols: list[SourceSymbol]) -> str:
    if not symbols:
        return "No matching symbols found for this move."
    tags = sorted({tag for symbol in symbols for tag in symbol.tags})
    refs = sorted({ref for symbol in symbols for ref in symbol.references})
    total_lines = sum(symbol.code_lines for symbol in symbols)
    parts = [f"Moves {len(symbols)} connected symbol(s) totaling {total_lines} code lines"]
    if tags:
        parts.append(f"tags={','.join(tags)}")
    if refs:
        parts.append(f"refs={','.join(refs)}")
    return "; ".join(parts)
