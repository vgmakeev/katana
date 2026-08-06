from __future__ import annotations

import ast
import re
from pathlib import Path

from .external import (
    outline_css_with_ast,
    outline_dart_with_analyzer,
    outline_typescript_with_ast,
)
from .ir import DocumentIR
from .models import _TS_SYMBOL_RE, SourceSymbol, SourceSymbolChild
from .outline_text import (
    _brace_delta,
    _text_code_lines,
    _typescript_file_meta,
    _with_dart_metadata,
    _with_typescript_metadata,
)
from .source_io import read_source_text

_DART_CLASS_RE = re.compile(
    r"^(?:(?:abstract|base|final|interface|sealed)\s+)*"
    r"(?P<class>class|mixin|enum|extension)\s+"
    r"(?P<name>[A-Za-z_]\w*)"
)
_DART_FUNCTION_RE = re.compile(
    r"^(?:[A-Za-z_][\w<>,.? ]*\s+)?"
    r"(?P<name>[A-Za-z_]\w*)\s*\([^;]*\)\s*(?:async\s*)?(?:\{|=>)"
)


def outline_python_module(path: Path) -> list[SourceSymbol]:
    text = read_source_text(path)
    lines = text.splitlines()
    tree = ast.parse(text, filename=str(path))
    names = _top_level_symbol_names(tree)
    symbols: list[SourceSymbol] = []
    for node in tree.body:
        symbol = _source_symbol(node, names, lines)
        if symbol is not None:
            symbols.append(symbol)
    return symbols


def outline_source_file(path: Path) -> list[SourceSymbol]:
    from .adapters import language_adapter_for

    adapter = language_adapter_for(path)
    outline = getattr(adapter, "outline", None)
    if callable(outline):
        symbols = outline(path)
        if isinstance(symbols, list):
            return symbols
    return list(adapter.analyze(path).source_symbols)


def analyze_source_file(path: Path) -> DocumentIR:
    from .adapters import language_adapter_for, validate_document_ir

    document = language_adapter_for(path).analyze(path)
    validate_document_ir(document)
    return document


def outline_typescript_module(path: Path) -> list[SourceSymbol]:
    ast_symbols = outline_typescript_with_ast(path)
    if ast_symbols is not None:
        return ast_symbols
    lines = read_source_text(path).splitlines()
    starts: list[tuple[int, str, str, str]] = []
    file_meta = _typescript_file_meta(path, lines)
    depth = 0
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if depth == 0:
            match = _TS_SYMBOL_RE.match(stripped)
            if match is not None:
                kind = match.group("kind") or "const"
                name = match.group("name")
                starts.append((index, name, kind, stripped))
        depth += _brace_delta(line)
        depth = max(depth, 0)
    return _with_typescript_metadata(
        _symbols_from_text_starts(lines, starts),
        lines,
        file_meta=file_meta,
    )


def outline_css_file(path: Path) -> list[SourceSymbol]:
    ast_symbols = outline_css_with_ast(path)
    if ast_symbols is not None:
        return ast_symbols
    lines = read_source_text(path).splitlines()
    starts: list[tuple[int, str, str, str]] = []
    depth = 0
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if depth == 0 and "{" in stripped and not stripped.startswith(("/*", "@import")):
            selector = stripped.split("{", 1)[0].strip()
            if selector:
                kind = "CssAtRule" if selector.startswith("@") else "CssRule"
                starts.append(
                    (index, _slug_symbol(selector, fallback=f"rule_{index}"), kind, selector)
                )
        depth += line.count("{") - line.count("}")
        depth = max(depth, 0)
    return _symbols_from_braced_starts(lines, starts)


def outline_markdown_file(path: Path) -> list[SourceSymbol]:
    lines = read_source_text(path).splitlines()
    starts: list[tuple[int, str, str, str]] = []
    for index, line in enumerate(lines, start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match is None:
            continue
        title = match.group(2).strip()
        starts.append(
            (
                index,
                _slug_symbol(title, fallback=f"section_{index}"),
                f"MarkdownHeading{len(match.group(1))}",
                line.strip(),
            )
        )
    return _symbols_from_text_starts(lines, starts, include_references=False)


def outline_dart_file(path: Path) -> list[SourceSymbol]:
    ast_symbols = outline_dart_with_analyzer(path)
    if ast_symbols is not None:
        return ast_symbols
    lines = read_source_text(path).splitlines()
    starts: list[tuple[int, str, str, str]] = []
    depth = 0
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if depth == 0:
            match = _DART_CLASS_RE.match(stripped) or _DART_FUNCTION_RE.match(stripped)
            if match is not None:
                kind = (
                    "class" if "class" in match.groupdict() and match.group("class") else "function"
                )
                starts.append((index, match.group("name"), kind, stripped))
        depth += _brace_delta(line)
        depth = max(depth, 0)
    return _with_dart_metadata(_symbols_from_text_starts(lines, starts), lines)


def source_language(path: Path) -> str:
    from .adapters import language_adapter_for_extension

    adapter = language_adapter_for_extension(path.suffix)
    return adapter.language_for(path) if adapter is not None else "text"


def source_parser_capabilities(path: Path) -> dict[str, object]:
    from .adapters import language_adapter_for_extension, legacy_capabilities_for

    adapter = language_adapter_for_extension(path.suffix)
    if adapter is None:
        return {
            "language": "text",
            "parser": "unsupported",
            "strategy": "none",
            "precision": "none",
            "safe_apply": False,
            "verifications": [],
            "limitations": ["unsupported source-split file type"],
        }
    return legacy_capabilities_for(adapter, path)


def _source_symbol(node: ast.stmt, names: set[str], lines: list[str]) -> SourceSymbol | None:
    symbol_name = _symbol_name(node)
    if symbol_name is None or node.end_lineno is None:
        return None
    start = _decorated_start_line(node)
    references = tuple(sorted(_name_references(node) & names - {symbol_name}))
    return SourceSymbol(
        name=symbol_name,
        kind=type(node).__name__,
        signature=_symbol_signature(node),
        start_line=start,
        end_line=node.end_lineno,
        code_lines=_python_span_code_lines(lines, start, node.end_lineno),
        references=references,
        children=_source_children(node, lines),
    )


def _source_children(node: ast.stmt, lines: list[str]) -> tuple[SourceSymbolChild, ...]:
    body = getattr(node, "body", ())
    children: list[SourceSymbolChild] = []
    for child in body:
        if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if child.end_lineno is None:
            continue
        start = _decorated_start_line(child)
        children.append(
            SourceSymbolChild(
                name=child.name,
                kind=type(child).__name__,
                signature=_symbol_signature(child),
                start_line=start,
                end_line=child.end_lineno,
                code_lines=_python_span_code_lines(lines, start, child.end_lineno),
                tags=_python_child_tags(node, child),
            )
        )
    return tuple(children)


def _python_span_code_lines(lines: list[str], start_line: int, end_line: int) -> int:
    return sum(
        1
        for line in lines[start_line - 1 : end_line]
        if line.strip() and not line.lstrip().startswith("#")
    )


def _python_child_tags(parent: ast.stmt, child: ast.stmt) -> tuple[str, ...]:
    tags: list[str] = []
    if isinstance(parent, ast.ClassDef) and isinstance(
        child, ast.FunctionDef | ast.AsyncFunctionDef
    ):
        tags.append("method")
        if child.name.startswith("test_"):
            tags.append("test")
    elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
        tags.append("nested_function")
    elif isinstance(child, ast.ClassDef):
        tags.append("nested_class")
    return tuple(tags)


def _top_level_symbol_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        name = _symbol_name(node)
        if name is not None:
            names.add(name)
    return names


def _symbol_name(node: ast.stmt) -> str | None:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _symbol_signature(node: ast.stmt) -> str:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        args = ", ".join(_format_arg(arg) for arg in node.args.posonlyargs)
        if node.args.posonlyargs:
            args = f"{args}, /"
        regular = ", ".join(_format_arg(arg) for arg in node.args.args)
        if args and regular:
            args = f"{args}, {regular}"
        elif regular:
            args = regular
        if node.args.vararg is not None:
            args = (
                f"{args}, *{_format_arg(node.args.vararg)}" if args else f"*{node.args.vararg.arg}"
            )
        elif node.args.kwonlyargs:
            args = f"{args}, *" if args else "*"
        for arg in node.args.kwonlyargs:
            rendered = _format_arg(arg)
            args = f"{args}, {rendered}" if args else rendered
        if node.args.kwarg is not None:
            args = (
                f"{args}, **{_format_arg(node.args.kwarg)}" if args else f"**{node.args.kwarg.arg}"
            )
        returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        return f"{prefix} {node.name}({args}){returns}"
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(base) for base in node.bases]
        bases.extend(f"{keyword.arg}={ast.unparse(keyword.value)}" for keyword in node.keywords)
        suffix = f"({', '.join(bases)})" if bases else ""
        return f"class {node.name}{suffix}"
    if isinstance(node, ast.Assign | ast.AnnAssign):
        name = _symbol_name(node) or "<assignment>"
        return name
    return type(node).__name__


def _format_arg(arg: ast.arg) -> str:
    annotation = f": {ast.unparse(arg.annotation)}" if arg.annotation is not None else ""
    return f"{arg.arg}{annotation}"


def _decorated_start_line(node: ast.stmt) -> int:
    decorators: list[ast.expr] = getattr(node, "decorator_list", [])
    if decorators:
        return min(decorator.lineno for decorator in decorators)
    return node.lineno


def _name_references(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _symbols_from_text_starts(
    lines: list[str],
    starts: list[tuple[int, str, str, str]],
    *,
    include_references: bool = True,
) -> list[SourceSymbol]:
    names = _unique_names([name for _, name, _, _ in starts])
    raw_symbols: list[SourceSymbol] = []
    for index, (start, _raw_name, kind, signature) in enumerate(starts):
        end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
        name = names[index]
        raw_symbols.append(
            SourceSymbol(
                name=name,
                kind=kind,
                signature=signature,
                start_line=start,
                end_line=end,
                code_lines=_text_code_lines(lines[start - 1 : end]),
                references=(),
            )
        )
    names_set = {symbol.name for symbol in raw_symbols}
    if not include_references:
        return raw_symbols
    return [_with_text_references(symbol, lines, names_set) for symbol in raw_symbols]


def _symbols_from_braced_starts(
    lines: list[str],
    starts: list[tuple[int, str, str, str]],
) -> list[SourceSymbol]:
    symbols: list[SourceSymbol] = []
    used: set[str] = set()
    for start, raw_name, kind, signature in starts:
        depth = 0
        end = start
        for index in range(start, len(lines) + 1):
            line = lines[index - 1]
            depth += line.count("{") - line.count("}")
            end = index
            if depth <= 0 and "{" in "".join(lines[start - 1 : index]):
                break
        name = _dedupe_name(raw_name, used)
        symbols.append(
            SourceSymbol(
                name=name,
                kind=kind,
                signature=signature,
                start_line=start,
                end_line=end,
                code_lines=_text_code_lines(lines[start - 1 : end]),
                references=(),
            )
        )
    return symbols


def _with_text_references(
    symbol: SourceSymbol,
    lines: list[str],
    names: set[str],
) -> SourceSymbol:
    body = "\n".join(lines[symbol.start_line - 1 : symbol.end_line])
    refs = tuple(
        sorted(
            name
            for name in names
            if name != symbol.name and re.search(rf"\b{re.escape(name)}\b", body)
        )
    )
    return SourceSymbol(
        name=symbol.name,
        kind=symbol.kind,
        signature=symbol.signature,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        code_lines=symbol.code_lines,
        references=refs,
        tags=symbol.tags,
        meta=symbol.meta,
        children=symbol.children,
    )


def _unique_names(names: list[str]) -> list[str]:
    used: set[str] = set()
    return [_dedupe_name(name, used) for name in names]


def _dedupe_name(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    index = 2
    while f"{name}_{index}" in used:
        index += 1
    unique = f"{name}_{index}"
    used.add(unique)
    return unique


def _slug_symbol(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
    if not slug or slug[0].isdigit():
        return fallback
    return slug
