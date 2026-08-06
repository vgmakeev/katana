from __future__ import annotations

from pathlib import Path

from .models import SourceSplitMove, SourceSymbol

_TS_TYPE_KINDS = {"InterfaceDeclaration", "TypeAliasDeclaration", "interface", "type"}


def _text_leading_block(source: Path, lines: list[str]) -> list[str]:
    if source.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        return _typescript_leading_block(lines)
    if source.suffix == ".dart":
        return _dart_leading_block(lines)
    if source.suffix == ".css":
        return _css_leading_block(lines)
    return []


def _typescript_leading_block(lines: list[str]) -> list[str]:
    end = 0
    open_braces = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if open_braces > 0:
            # Continuation of a multiline import statement.
            open_braces += line.count("{") - line.count("}")
            end = index + 1
            continue
        if not stripped:
            if end == index:
                end = index + 1
            continue
        if stripped in {'"use client"', '"use client";', "'use client'", "'use client';"}:
            end = index + 1
            continue
        if stripped.startswith(("import ", "import type ")):
            open_braces = line.count("{") - line.count("}")
            end = index + 1
            continue
        if end and (stripped.startswith(("}", "from "))):
            end = index + 1
            continue
        if stripped.startswith(("//", "/*", "*")):
            if end == index:
                end = index + 1
            continue
        break
    return lines[:end]


def _css_leading_block(lines: list[str]) -> list[str]:
    end = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("@import", "@charset")):
            end = index + 1
            continue
        break
    return lines[:end]


def _dart_leading_block(lines: list[str]) -> list[str]:
    end = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if end == index:
                end = index + 1
            continue
        if stripped.startswith(("//", "/*", "*")) and end == index:
            end = index + 1
            continue
        if stripped.startswith(("library ", "import ", "export ", "part ")):
            end = index + 1
            continue
        break
    return lines[:end]


def _append_compat_imports(lines: list[str], insert: list[str]) -> list[str]:
    if not insert:
        return lines
    prefix = [] if not lines or not lines[-1].strip() else ["\n"]
    return [*lines, *prefix, *insert]


def _apply_text_compat_exports(
    source: Path,
    lines: list[str],
    moves: tuple[SourceSplitMove, ...],
    symbols: list[SourceSymbol],
) -> list[str]:
    if source.suffix == ".dart":
        return _insert_after_text_leading_block(source, lines, _dart_compat_lines(source, moves))
    if source.suffix == ".css":
        return _insert_after_text_leading_block(source, lines, _css_compat_lines(source, moves))
    if source.suffix not in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        return lines
    moved = {name for move in moves for name in move.symbols}
    staying_refs = {
        reference
        for symbol in symbols
        if symbol.name not in moved
        for reference in symbol.references
        if reference in moved
    }
    imports: list[str] = []
    exports: list[str] = []
    by_name = {symbol.name: symbol for symbol in symbols}
    for move in moves:
        module = _js_relative_module_name(source, move.target)
        # Re-exports do not bind names locally; staying code needs an import.
        needed = [name for name in move.symbols if name in staying_refs]
        if needed:
            imports.extend(_ts_named_lines("import", module, needed, by_name))
        exports.extend(_ts_named_lines("export", module, list(move.symbols), by_name))
    lines = _insert_after_text_leading_block(source, lines, imports)
    return _append_compat_imports(lines, exports)


def _apply_text_usage_imports(
    source: Path,
    lines: list[str],
    moves: tuple[SourceSplitMove, ...],
    symbols: list[SourceSymbol],
) -> list[str]:
    if source.suffix not in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".dart"):
        return lines
    moved = {name for move in moves for name in move.symbols}
    staying_refs = {
        reference
        for symbol in symbols
        if symbol.name not in moved
        for reference in symbol.references
        if reference in moved
    }
    imports: list[str] = []
    by_name = {symbol.name: symbol for symbol in symbols}
    for move in moves:
        needed = sorted(set(move.symbols) & staying_refs)
        if not needed:
            continue
        if source.suffix == ".dart":
            imports.append(
                f"import '{_relative_uri(source, move.target)}' show {', '.join(needed)};\n"
            )
        else:
            imports.extend(
                _ts_named_lines(
                    "import", _js_relative_module_name(source, move.target), needed, by_name
                )
            )
    if not imports:
        return lines
    return _insert_after_text_leading_block(source, lines, imports)


def _ts_exported_block(block: list[str]) -> list[str]:
    if not block:
        return block
    first = block[0]
    stripped = first.lstrip()
    if stripped.startswith("export "):
        return block
    from .models import _TS_SYMBOL_RE

    if _TS_SYMBOL_RE.match(stripped) is None:
        return block
    indent = first[: len(first) - len(stripped)]
    return [f"{indent}export {stripped}", *block[1:]]


def _ts_named_lines(
    verb: str,
    module: str,
    names: list[str],
    symbols: dict[str, SourceSymbol],
) -> list[str]:
    values, types = _ts_split_type_names(names, symbols)
    lines: list[str] = []
    if values:
        lines.append(f'{verb} {{ {", ".join(values)} }} from "{module}"\n')
    if types:
        lines.append(f'{verb} type {{ {", ".join(types)} }} from "{module}"\n')
    return lines


def _ts_split_type_names(
    names: list[str],
    symbols: dict[str, SourceSymbol],
) -> tuple[list[str], list[str]]:
    values: list[str] = []
    types: list[str] = []
    for name in names:
        symbol = symbols.get(name)
        if symbol is not None and _ts_type_only_symbol(symbol):
            types.append(name)
        else:
            values.append(name)
    return values, types


def _ts_type_only_symbol(symbol: SourceSymbol) -> bool:
    meta = symbol.meta or {}
    return bool(meta.get("type_only")) or symbol.kind in _TS_TYPE_KINDS


def _dart_compat_lines(source: Path, moves: tuple[SourceSplitMove, ...]) -> list[str]:
    lines: list[str] = []
    for move in moves:
        # Library-private symbols cannot be shown across files; they only move
        # together with all their consumers.
        public = [name for name in move.symbols if not name.startswith("_")]
        if not public:
            continue
        module = _relative_uri(source, move.target)
        symbols = ", ".join(public)
        lines.append(f"import '{module}' show {symbols};\n")
        lines.append(f"export '{module}' show {symbols};\n")
    if lines:
        lines.append("\n")
    return lines


def _css_compat_lines(source: Path, moves: tuple[SourceSplitMove, ...]) -> list[str]:
    lines = [f'@import "{_relative_uri(source, move.target)}";\n' for move in moves]
    if lines:
        lines.append("\n")
    return lines


def _insert_after_text_leading_block(
    source: Path,
    lines: list[str],
    insert: list[str],
) -> list[str]:
    if not insert:
        return lines
    end = len(_text_leading_block(source, lines))
    suffix = ["\n"] if end < len(lines) and lines[end].strip() else []
    return [*lines[:end], *insert, *suffix, *lines[end:]]


def _js_relative_module_name(source: Path, target: Path) -> str:
    try:
        relative = target.with_suffix("").relative_to(source.parent)
    except ValueError as error:
        raise ValueError("Split targets must be inside the source module directory") from error
    path = "/".join(relative.parts)
    return f"./{path}" if not path.startswith(".") else path


def _relative_uri(source: Path, target: Path) -> str:
    try:
        relative = target.relative_to(source.parent)
    except ValueError as error:
        raise ValueError("Split targets must be inside the source module directory") from error
    return "/".join(relative.parts)
