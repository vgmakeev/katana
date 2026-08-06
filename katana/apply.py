from __future__ import annotations

import ast
import os
import py_compile
import re
from pathlib import Path
from typing import Any

from .apply_compat import (
    _apply_text_compat_exports,
    _apply_text_usage_imports,
    _text_leading_block,
    _ts_exported_block,
    _typescript_leading_block,
)
from .impact import dynamic_reference_warnings
from .imports import (
    _dependency_import_lines,
    _insert_after_import_block,
    _module_import_block,
    _prune_unused_imports,
    _relative_module_name,
    _source_dependency_import_lines,
)
from .merge import (
    _text_dependency_imports,
    merge_into_existing_target,
    merge_text_into_existing_target,
)
from .models import (
    KATANA_PLAN_SUFFIX,
    LEGACY_SOURCE_SPLIT_PLAN_SUFFIX,
    SPLIT_PLAN_VERSION,
    SourceSplitCheck,
    SourceSplitMove,
    SourceSplitPlan,
    SourceSymbol,
)
from .outline import (
    _decorated_start_line,
    _symbol_name,
    outline_python_module,
    outline_source_file,
)
from .source_io import encode_source_text, read_source_text, source_newline
from .toolchain import run_toolchain_after_split


def parse_move_specs(source: Path, specs: list[str]) -> tuple[SourceSplitMove, ...]:
    moves: list[SourceSplitMove] = []
    for spec in specs:
        if ":" not in spec:
            raise ValueError(f"Move spec must be TARGET:SYMBOL[,SYMBOL...], got {spec!r}")
        target_text, symbols_text = spec.split(":", 1)
        symbols = tuple(symbol.strip() for symbol in symbols_text.split(",") if symbol.strip())
        if not symbols:
            raise ValueError(f"Move spec has no symbols: {spec!r}")
        target = Path(target_text)
        if not target.is_absolute():
            target = source.parent / target
        moves.append(SourceSplitMove(target=target, symbols=symbols))
    return tuple(moves)


def parse_move_plan(
    source: Path,
    specs: list[str],
    plan_file: Path | None,
) -> tuple[SourceSplitMove, ...]:
    moves = list(parse_move_specs(source, specs))
    resolved_plan_file = plan_file
    if resolved_plan_file is None and not moves:
        resolved_plan_file = _default_plan_file(source)
    if resolved_plan_file is not None:
        payload = _load_split_plan_payload(resolved_plan_file)
        raw_moves = payload["moves"]
        plan_source = Path(str(payload["source"])) if payload.get("source") else None
        for index, raw in enumerate(raw_moves):
            if not isinstance(raw, dict):
                raise TypeError(f"Split plan moves[{index}] must be an object")
            target = Path(str(raw["target"]))
            if not target.is_absolute():
                # Older plans stored targets relative to the directory the plan
                # was generated from; rebase those onto the plan's own source
                # path so they resolve next to the real source file.
                if plan_source is not None and target.is_relative_to(plan_source.parent):
                    target = source.parent / target.relative_to(plan_source.parent)
                else:
                    target = source.parent / target
            symbols = raw["symbols"]
            if not isinstance(symbols, list):
                raise TypeError(f"Split plan moves[{index}].symbols must be an array")
            moves.append(
                SourceSplitMove(
                    target=target,
                    symbols=tuple(str(symbol) for symbol in symbols),
                )
            )
    return tuple(moves)


def _default_plan_file(source: Path) -> Path | None:
    current = source.with_suffix(KATANA_PLAN_SUFFIX)
    if current.exists():
        return current
    legacy = source.with_suffix(LEGACY_SOURCE_SPLIT_PLAN_SUFFIX)
    if legacy.exists():
        return legacy
    return None


def _load_split_plan_payload(plan_file: Path) -> dict[str, Any]:
    import json

    payload = json.loads(plan_file.read_text())
    if not isinstance(payload, dict):
        raise TypeError("Split plan must be a JSON object")

    allowed_top_level = {"version", "source", "moves", "moved_symbols", "warnings"}
    for key in payload:
        if key not in allowed_top_level:
            raise ValueError(f"Unknown split plan key: {key}")

    version = int(payload.get("version", SPLIT_PLAN_VERSION))
    if version != SPLIT_PLAN_VERSION:
        raise ValueError(f"Unsupported split plan version {version}; expected {SPLIT_PLAN_VERSION}")

    if "moves" not in payload:
        raise ValueError("Split plan must include moves")
    raw_moves = payload["moves"]
    if not isinstance(raw_moves, list):
        raise TypeError("Split plan moves must be an array")

    allowed_move_keys = {"target", "symbols"}
    for index, raw in enumerate(raw_moves):
        if not isinstance(raw, dict):
            raise TypeError(f"Split plan moves[{index}] must be an object")
        for key in raw:
            if key not in allowed_move_keys:
                raise ValueError(f"Unknown split plan moves[{index}] key: {key}")
        for key in ("target", "symbols"):
            if key not in raw:
                raise ValueError(f"Split plan moves[{index}] must include {key}")

    return payload


def plan_python_split(source: Path, moves: tuple[SourceSplitMove, ...]) -> SourceSplitPlan:
    symbols = {symbol.name: symbol for symbol in outline_python_module(source)}
    moved: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for move in moves:
        for name in move.symbols:
            if name in seen:
                raise ValueError(f"Symbol is moved more than once: {name}")
            if name not in symbols:
                raise ValueError(f"Symbol not found in {source}: {name}")
            seen.add(name)
            moved.append(name)

    moved_set = set(moved)
    for name in moved:
        symbol = symbols[name]
        external_refs = [ref for ref in symbol.references if ref not in moved_set]
        if external_refs:
            warnings.append(
                f"{name} references source-local symbols not moved with it: "
                + ", ".join(external_refs)
            )
    warnings.extend(_plan_cycle_warnings(source, moves))

    return SourceSplitPlan(
        source=source,
        moves=moves,
        moved_symbols=tuple(moved),
        warnings=tuple(warnings),
    )


def plan_source_split(source: Path, moves: tuple[SourceSplitMove, ...]) -> SourceSplitPlan:
    from .adapters import language_adapter_for

    return language_adapter_for(source).plan_split(source, moves)


def plan_text_split(source: Path, moves: tuple[SourceSplitMove, ...]) -> SourceSplitPlan:
    ordered_symbols = outline_source_file(source)
    symbols = {symbol.name: symbol for symbol in ordered_symbols}
    moved: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for move in moves:
        for name in move.symbols:
            if name in seen:
                raise ValueError(f"Symbol is moved more than once: {name}")
            if name not in symbols:
                raise ValueError(f"Symbol not found in {source}: {name}")
            seen.add(name)
            moved.append(name)
    moved_set = set(moved)
    for name in moved:
        refs = [ref for ref in symbols[name].references if ref not in moved_set]
        if refs:
            warnings.append(
                f"{name} references source-local symbols not moved with it: " + ", ".join(refs)
            )
    if source.suffix == ".css" and moves:
        # Moved rules are @import-ed above the remaining rules, so a move of
        # the leading rules in source order preserves the cascade exactly.
        ordered_names = [symbol.name for symbol in ordered_symbols]
        if moved != ordered_names[: len(moved)]:
            warnings.append(
                "moved CSS rules are re-imported at the top of the source; cascade "
                "order changes for equal-specificity selectors, verify styles after applying"
            )
    return SourceSplitPlan(source, moves, tuple(moved), tuple(warnings))


def apply_python_split(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    keep_compat_imports: bool = True,
    force: bool = False,
    package_relative: bool = True,
) -> SourceSplitPlan:
    try:
        plan = plan_python_split(source, moves)
    except SyntaxError as error:
        raise ValueError(
            f"{source} is not parseable ({error.msg} at line {error.lineno}); "
            "fix the syntax first, e.g. leftovers from a previously failed apply"
        ) from error
    blocking_warnings = [warning for warning in plan.warnings if "import cycle" in warning]
    if blocking_warnings and not force:
        details = "; ".join(blocking_warnings)
        raise ValueError(
            "Split plan has warnings; review with source-split plan, adjust the "
            f"moves, or rerun apply --force to accept them: {details}"
        )
    for move in moves:
        _relative_module_name(source, move.target)
    _validate_unique_targets(moves)
    text = read_source_text(source)
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text, filename=str(source))
    spans = _symbol_spans(tree)
    symbols = {symbol.name: symbol for symbol in outline_python_module(source)}
    moved_to = {symbol: move.target for move in moves for symbol in move.symbols}
    import_block = _module_import_block(lines, tree)

    moved_all = set(moved_to)
    staying_refs = {
        reference
        for symbol in symbols.values()
        if symbol.name not in moved_all
        for reference in symbol.references
        if reference in moved_all
    }
    outputs: dict[Path, str] = {}
    for move in moves:
        blocks = [_slice_with_trailing_blank(lines, spans[name]) for name in move.symbols]
        if move.target.exists() and not force:
            # Existing sibling modules receive the symbols instead of being
            # overwritten; overwrite stays behind --force.
            outputs[move.target] = merge_into_existing_target(
                source,
                move,
                blocks=blocks,
                import_block=import_block,
                symbols=symbols,
                moved_to=moved_to,
                keep_compat_imports=keep_compat_imports,
                staying_refs=staying_refs,
                package_relative=package_relative,
            )
            continue
        dependency_imports = _dependency_import_lines(
            source,
            move.target,
            move.symbols,
            symbols,
            moved_to,
            package_relative=package_relative,
        )
        content = [*import_block]
        if dependency_imports:
            if content and content[-1].strip():
                content.append("\n")
            content.extend(dependency_imports)
        while content and not content[-1].strip():
            content.pop()
        if content:
            content.extend(["\n", "\n"])
        for index, block in enumerate(blocks):
            if index and (not content or content[-1].strip()):
                content.append("\n")
            content.extend(block)
            if content and content[-1].strip():
                content.append("\n")
        target_text = _prune_unused_imports(
            _collapse_blank_lines("".join(content)),
            move.target,
            keep_reexports=False,
        )
        outputs[move.target] = target_text

    moved_set = set(plan.moved_symbols)
    remove_ranges = [spans[name] for name in plan.moved_symbols]
    kept_lines = _remove_ranges(lines, remove_ranges)
    source_dependency_imports = _source_dependency_import_lines(
        source,
        tree,
        symbols,
        moved_to,
        moved_set,
        include_compat=keep_compat_imports,
        package_relative=package_relative,
    )
    kept_lines = _insert_after_import_block(kept_lines, source_dependency_imports)
    kept_text = _prune_unused_imports(_collapse_blank_lines("".join(kept_lines)), source)
    warnings = [
        *plan.warnings,
        *_placeholder_target_warnings(moves),
        *dynamic_reference_warnings(source, moves),
    ]
    outputs[source] = kept_text
    _write_split_outputs(source, moves, outputs)
    return SourceSplitPlan(
        source=plan.source,
        moves=plan.moves,
        moved_symbols=plan.moved_symbols,
        warnings=tuple(warnings),
    )


def apply_source_split(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    keep_compat_imports: bool = True,
    force: bool = False,
    package_relative: bool = True,
) -> SourceSplitPlan:
    from .adapters import language_adapter_for

    _validate_targets_stay_in_source_tree(source, moves)
    return language_adapter_for(source).apply_split(
        source,
        moves,
        keep_compat_imports=keep_compat_imports,
        force=force,
        package_relative=package_relative,
    )


def _validate_targets_stay_in_source_tree(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
) -> None:
    root = source.parent.resolve()
    for move in moves:
        target = move.target.resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Split target escapes the source tree {root}: {move.target}")


def _validate_unique_targets(moves: tuple[SourceSplitMove, ...]) -> None:
    seen: set[Path] = set()
    for move in moves:
        target = move.target.resolve()
        if target in seen:
            raise ValueError(
                f"Multiple source-split moves target {move.target}; combine symbols into one move"
            )
        seen.add(target)


def _write_split_outputs(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    outputs: dict[Path, str],
) -> None:
    init_outputs = _package_init_outputs(source, moves)
    write_outputs = {**init_outputs, **outputs}
    target_paths = [path for path in (move.target for move in moves) if path in outputs]
    paths = list(dict.fromkeys([*init_outputs, *target_paths, source]))
    for path in paths:
        parent = path.parent
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"Split target parent is not a directory: {parent}")
        if path.exists() and not path.is_file():
            raise ValueError(f"Split output is not a file: {path}")
        _validate_writable_output(path)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        newline_owner = path if path.exists() and path.stat().st_size else source
        path.write_bytes(
            encode_source_text(write_outputs[path], newline=source_newline(newline_owner))
        )


def _package_init_outputs(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
) -> dict[Path, str]:
    outputs: dict[Path, str] = {}
    for move in moves:
        if move.target.suffix != ".py":
            continue
        parent = move.target.parent
        while source.parent in parent.parents:
            init = parent / "__init__.py"
            if not init.exists():
                outputs[init] = ""
            parent = parent.parent
    return outputs


def _validate_writable_output(path: Path) -> None:
    if path.exists():
        if not os.access(path, os.W_OK):
            raise ValueError(f"Split output is not writable: {path}")
        return
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    if not os.access(parent, os.W_OK):
        raise ValueError(f"Split output parent is not writable: {parent}")


def apply_text_split(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    keep_compat_imports: bool = True,
    force: bool = False,
) -> SourceSplitPlan:
    plan = plan_source_split(source, moves)
    _validate_unique_targets(moves)
    text = read_source_text(source)
    lines = text.splitlines(keepends=True)
    symbols = outline_source_file(source)
    spans = {symbol.name: (symbol.start_line, symbol.end_line) for symbol in symbols}
    leading_block = _text_leading_block(source, lines)
    typescript = source.suffix in (".ts", ".tsx", ".js", ".jsx")
    symbols_by_name = {symbol.name: symbol for symbol in symbols}
    moved_to = {symbol: move.target for move in moves for symbol in move.symbols}
    moved_all = set(moved_to)
    staying_refs = {
        reference
        for symbol in symbols
        if symbol.name not in moved_all
        for reference in symbol.references
        if reference in moved_all
    }

    outputs: dict[Path, str] = {}
    for move in moves:
        dependency_imports = _text_dependency_imports(
            source,
            move.target,
            move.symbols,
            symbols_by_name,
            moved_to,
        )
        content: list[str] = [*leading_block]
        if dependency_imports:
            content.extend(dependency_imports)
        if content and content[-1].strip():
            content.append("\n")
        blocks: list[list[str]] = []
        for symbol in move.symbols:
            block = _slice_with_trailing_blank(lines, spans[symbol])
            if typescript:
                # The source re-imports moved symbols, so they must be
                # exported from the split file.
                block = _ts_exported_block(block)
            blocks.append(block)
            content.extend(block)
            if content and content[-1].strip():
                content.append("\n")
        if move.target.exists() and not force:
            outputs[move.target] = merge_text_into_existing_target(
                source,
                move,
                blocks=blocks,
                leading_block=leading_block,
                symbols=symbols_by_name,
                moved_to=moved_to,
                keep_compat_imports=keep_compat_imports,
                staying_refs=staying_refs,
            )
        else:
            outputs[move.target] = _prune_text_imports(
                _collapse_blank_lines("".join(content)), source.suffix
            )

    kept = _remove_ranges(lines, [spans[name] for name in plan.moved_symbols])
    if keep_compat_imports:
        kept = _apply_text_compat_exports(source, kept, moves, symbols)
    else:
        # The source still needs imports for its own references to moved
        # symbols even when compatibility re-exports are disabled.
        kept = _apply_text_usage_imports(source, kept, moves, symbols)
    outputs[source] = _prune_text_imports(_collapse_blank_lines("".join(kept)), source.suffix)
    _write_split_outputs(source, moves, outputs)
    return SourceSplitPlan(
        source=plan.source,
        moves=plan.moves,
        moved_symbols=plan.moved_symbols,
        warnings=(
            *plan.warnings,
            *_placeholder_target_warnings(moves),
            *_react_refresh_warnings(source, moves, symbols_by_name),
        ),
    )


def fix_lint_after_split(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    typecheck: bool = False,
) -> dict[str, object]:
    return run_toolchain_after_split(source, moves, typecheck=typecheck)


def check_split_result(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    max_lines: int | None = None,
) -> SourceSplitCheck:
    files = (source, *(move.target for move in moves))
    for path in files:
        if path.suffix == ".py":
            py_compile.compile(str(path), doraise=True)
    oversized: list[tuple[Path, int]] = []
    if max_lines is not None:
        for path in files:
            code_lines = _check_code_line_count(path, read_source_text(path))
            if code_lines > max_lines:
                oversized.append((path, code_lines))
    return SourceSplitCheck(files=files, max_lines=max_lines, oversized=tuple(oversized))


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


_TS_IMPORT_STMT_RE = re.compile(
    r"import\s+(?P<type>type\s+)?"
    r"(?:(?P<default>[A-Za-z_$][\w$]*)\s*,?\s*)?"
    r"(?:\{(?P<named>[^}]*)\})?\s*"
    r"(?:\*\s+as\s+(?P<namespace>[A-Za-z_$][\w$]*))?\s*"
    r"from\s*(?P<module>[\"'][^\"']+[\"'])",
    re.DOTALL,
)


def _prune_text_imports(text: str, suffix: str) -> str:
    """Drop leading-block import bindings the file no longer uses.

    The text twin of the Python symtable pruner: usage is a word-boundary
    match in the code after the import block, which covers JSX and type
    positions alike.
    """
    if suffix not in (".ts", ".tsx", ".js", ".jsx"):
        return text
    lines = text.splitlines(keepends=True)
    block = _typescript_leading_block(lines)
    rest = "".join(lines[len(block) :])

    statements: list[list[str]] = []
    current: list[str] = []
    open_braces = 0
    for line in block:
        if current:
            current.append(line)
            open_braces += line.count("{") - line.count("}")
            if open_braces <= 0:
                statements.append(current)
                current = []
            continue
        stripped = line.strip()
        if stripped.startswith(("import ", "import type")):
            open_braces = line.count("{") - line.count("}")
            if open_braces > 0:
                current = [line]
            else:
                statements.append([line])
            continue
        statements.append([line])
    if current:
        statements.append(current)

    def used(name: str) -> bool:
        return re.search(rf"\b{re.escape(name)}\b", rest) is not None

    out: list[str] = []
    for statement in statements:
        joined = "".join(statement)
        stripped = joined.strip()
        if not stripped.startswith("import"):
            out.append(joined)
            continue
        match = _TS_IMPORT_STMT_RE.search(joined)
        if match is None:
            # Side-effect import or a shape we do not model: keep verbatim.
            out.append(joined)
            continue
        type_kw = "type " if match.group("type") else ""
        default = match.group("default")
        namespace = match.group("namespace")
        named = [item.strip() for item in (match.group("named") or "").split(",") if item.strip()]
        kept_named = [
            item for item in named if used(item.split(" as ")[-1].removeprefix("type ").strip())
        ]
        kept_default = default if default and used(default) else None
        kept_namespace = namespace if namespace and used(namespace) else None
        if not kept_named and not kept_default and not kept_namespace:
            continue
        pieces: list[str] = []
        if kept_default:
            pieces.append(kept_default)
        if kept_named:
            pieces.append("{ " + ", ".join(kept_named) + " }")
        if kept_namespace:
            pieces.append(f"* as {kept_namespace}")
        out.append(f"import {type_kw}{', '.join(pieces)} from {match.group('module')}\n")
    return "".join(out) + rest


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
