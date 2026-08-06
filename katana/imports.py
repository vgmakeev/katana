from __future__ import annotations

import ast
import symtable
from pathlib import Path

from .models import SourceSymbol
from .outline import _symbol_name


def _format_from_import(module: str, names: list[str]) -> str:
    joined = ", ".join(names)
    line = f"from {module} import {joined}\n"
    if len(line) <= 101:
        return line
    body = "".join(f"    {name},\n" for name in names)
    return f"from {module} import (\n{body})\n"


def _isort_name_key(rendered: str) -> tuple[int, str]:
    # isort order-by-type: constants, then classes, then the rest;
    # case-insensitive within each group.
    base = rendered.split(" as ")[0]
    if base.isupper():
        rank = 0
    elif base[:1].isupper():
        rank = 1
    else:
        rank = 2
    return (rank, base.lower())


def _module_import_block(lines: list[str], tree: ast.Module) -> list[str]:
    end_line = 0
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and end_line == 0
        ):
            end_line = node.end_lineno or node.lineno
            continue
        if isinstance(node, ast.Import | ast.ImportFrom):
            end_line = node.end_lineno or node.lineno
            continue
        if not isinstance(node, ast.Expr):
            break
    return lines[:end_line]


def _module_parts(target: Path, relative: Path) -> tuple[str, ...]:
    parts = relative.parts
    if not parts or not all(part.isidentifier() for part in parts):
        raise ValueError(f"Split target {target} does not map to an importable Python module name")
    return parts


def _relative_module_name(
    source: Path,
    target: Path,
    *,
    package_relative: bool = True,
) -> str:
    try:
        relative = target.with_suffix("").relative_to(source.parent)
    except ValueError as error:
        raise ValueError("Split targets must be inside the source module directory") from error
    module = ".".join(_module_parts(target, relative))
    return f".{module}" if package_relative else module


def _module_name_between(
    importer: Path,
    imported: Path,
    *,
    package_relative: bool = True,
) -> str:
    try:
        relative = imported.with_suffix("").relative_to(importer.parent)
    except ValueError as error:
        raise ValueError("Split dependency targets must share the importer package") from error
    module = ".".join(_module_parts(imported, relative))
    return f".{module}" if package_relative else module


def _dependency_import_lines(
    source: Path,
    target: Path,
    moved_symbols: tuple[str, ...],
    symbols: dict[str, SourceSymbol],
    moved_to: dict[str, Path],
    *,
    package_relative: bool = True,
) -> list[str]:
    imports_by_module: dict[str, list[str]] = {}
    same_target = set(moved_symbols)
    for symbol_name in moved_symbols:
        symbol = symbols[symbol_name]
        for reference in symbol.references:
            if reference in same_target:
                continue
            reference_file = moved_to.get(reference, source)
            module = _module_name_between(
                target,
                reference_file,
                package_relative=package_relative,
            )
            imports_by_module.setdefault(module, [])
            if reference not in imports_by_module[module]:
                imports_by_module[module].append(reference)
    return [
        _format_from_import(module, sorted(names, key=_isort_name_key))
        for module, names in sorted(imports_by_module.items())
    ]


def _source_dependency_import_lines(
    source: Path,
    tree: ast.Module,
    symbols: dict[str, SourceSymbol],
    moved_to: dict[str, Path],
    moved_symbols: set[str],
    *,
    include_compat: bool = True,
    package_relative: bool = True,
) -> list[str]:
    remaining_names = [
        name
        for node in tree.body
        if (name := _symbol_name(node)) is not None and name not in moved_symbols
    ]
    referenced: dict[str, set[str]] = {}
    for name in remaining_names:
        for reference in symbols[name].references:
            target = moved_to.get(reference)
            if target is None:
                continue
            referenced.setdefault(
                _relative_module_name(source, target, package_relative=package_relative),
                set(),
            ).add(reference)

    plain_by_module: dict[str, list[str]] = {}
    aliased_by_module: dict[str, list[str]] = {}
    for name, target in moved_to.items():
        module = _relative_module_name(source, target, package_relative=package_relative)
        if name in referenced.get(module, set()):
            plain_by_module.setdefault(module, []).append(name)
        elif include_compat and not name.startswith("_"):
            # Redundant aliases mark intentional re-exports for external
            # consumers of the source module. isort keeps every aliased
            # import in its own statement (combine-as-imports default).
            aliased_by_module.setdefault(module, []).append(f"{name} as {name}")
    lines: list[str] = []
    for module in sorted(plain_by_module | aliased_by_module):
        statements = (
            [sorted(plain_by_module[module], key=_isort_name_key)]
            if module in plain_by_module
            else []
        )
        statements.extend([alias] for alias in aliased_by_module.get(module, []))
        statements.sort(key=lambda names: _isort_name_key(names[0]))
        lines.extend(_format_from_import(module, names) for names in statements)
    return lines


def _insert_after_import_block(lines: list[str], insert: list[str]) -> list[str]:
    if not insert:
        return lines
    tree = ast.parse("".join(lines))
    end_line = len(_module_import_block(lines, tree))
    imports = [
        node
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom) and (node.end_lineno or 0) <= end_line
    ]
    # Generated dependency imports are relative; isort keeps them in their own
    # group, alphabetically sorted.
    relative = [node for node in imports if isinstance(node, ast.ImportFrom) and node.level > 0]
    inserted_module = insert[0].split()[1] if len(insert[0].split()) > 1 else ""
    for node in relative:
        module = "." * node.level + (node.module or "")
        if module > inserted_module:
            position = node.lineno - 1
            return [*lines[:position], *insert, *lines[position:]]
    if relative:
        position = relative[-1].end_lineno or end_line
        return [*lines[:position], *insert, *lines[position:]]
    prefix = ["\n"] if imports else []
    suffix = ["\n"] if end_line >= len(lines) or lines[end_line].strip() else []
    return [*lines[:end_line], *prefix, *insert, *suffix, *lines[end_line:]]


def _prune_unused_imports(text: str, path: Path, *, keep_reexports: bool = True) -> str:
    """Drop import aliases in the leading import block that the module no
    longer uses.

    Usage analysis is scope-aware: locals and parameters do not count as
    uses of a same-named import, while annotations, decorators, defaults and
    `__all__` entries do. Redundant aliases are explicit re-exports and are
    kept only where the module intentionally re-exports (the split source).
    """
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text, filename=str(path))
    block_length = len(_module_import_block(lines, tree))
    used = _module_used_names(text, path, tree)

    replacements: dict[int, tuple[int, list[str]]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        if node.end_lineno is None or node.end_lineno > block_length:
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        kept = [
            alias
            for alias in node.names
            if alias.name == "*"
            or (keep_reexports and alias.asname == alias.name)
            or (
                alias.asname
                or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
            )
            in used
        ]
        if len(kept) == len(node.names):
            continue
        rendered = [
            alias.name if alias.asname is None else f"{alias.name} as {alias.asname}"
            for alias in kept
        ]
        if not rendered:
            new_lines: list[str] = []
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            new_lines = [_format_from_import(module, rendered)]
        else:
            new_lines = [f"import {', '.join(rendered)}\n"]
        replacements[node.lineno - 1] = (node.end_lineno, new_lines)

    if not replacements:
        return text
    pruned: list[str] = []
    index = 0
    while index < len(lines):
        if index in replacements:
            end, new_lines = replacements[index]
            pruned.extend(new_lines)
            index = end
            if (
                not new_lines
                and pruned
                and not pruned[-1].strip()
                and index < len(lines)
                and not lines[index].strip()
            ):
                # A fully dropped statement would leave doubled blank lines.
                index += 1
            continue
        pruned.append(lines[index])
        index += 1
    return "".join(pruned)


def _module_used_names(text: str, path: Path, tree: ast.Module) -> set[str]:
    used: set[str] = set()
    scope_names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.Import | ast.ImportFrom):
            continue
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            scope_names.add(statement.name)
            used.update(_statement_header_names(statement))
            used.update(_annotation_names(statement))
        else:
            used.update(node.id for node in ast.walk(statement) if isinstance(node, ast.Name))
            used.update(_dunder_all_names(statement))

    module_table = symtable.symtable(text, str(path), "exec")

    def collect(table: symtable.SymbolTable) -> None:
        for symbol in table.get_symbols():
            if symbol.is_global() or symbol.is_free():
                used.add(symbol.get_name())
        for child in table.get_children():
            collect(child)

    for child in module_table.get_children():
        if child.get_name() in scope_names:
            collect(child)
    return used


def _statement_header_names(statement: ast.stmt) -> set[str]:
    header_nodes: list[ast.AST] = []
    if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
        arguments = statement.args
        header_nodes.extend(statement.decorator_list)
        header_nodes.extend(arguments.defaults)
        header_nodes.extend(default for default in arguments.kw_defaults if default is not None)
        if statement.returns is not None:
            header_nodes.append(statement.returns)
    elif isinstance(statement, ast.ClassDef):
        header_nodes.extend(statement.decorator_list)
        header_nodes.extend(statement.bases)
        header_nodes.extend(keyword.value for keyword in statement.keywords)
    names: set[str] = set()
    for header in header_nodes:
        names.update(node.id for node in ast.walk(header) if isinstance(node, ast.Name))
    return names


def _annotation_names(statement: ast.stmt) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(statement):
        annotation = getattr(node, "annotation", None)
        if annotation is None and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            annotation = node.returns
        if annotation is None:
            continue
        names.update(sub.id for sub in ast.walk(annotation) if isinstance(sub, ast.Name))
    return names


def _dunder_all_names(statement: ast.stmt) -> set[str]:
    targets: list[ast.expr] = []
    if isinstance(statement, ast.Assign):
        targets = statement.targets
    elif isinstance(statement, ast.AugAssign):
        targets = [statement.target]
    if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
        return set()
    return {
        node.value
        for node in ast.walk(statement)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
