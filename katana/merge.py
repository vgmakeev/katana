from __future__ import annotations

import ast
from pathlib import Path

from .apply_compat import _ts_named_lines
from .imports import (
    _dependency_import_lines,
    _format_from_import,
    _insert_after_import_block,
    _module_name_between,
    _prune_unused_imports,
)
from .models import SourceSplitMove, SourceSymbol
from .outline import _symbol_name, outline_source_file
from .source_io import read_source_text


def merge_into_existing_target(
    source: Path,
    move: SourceSplitMove,
    *,
    blocks: list[list[str]],
    import_block: list[str],
    symbols: dict[str, SourceSymbol],
    moved_to: dict[str, Path],
    keep_compat_imports: bool,
    staying_refs: set[str],
    package_relative: bool = True,
) -> str:
    """Append moved symbols to an existing sibling module.

    Guarantees before any write: no name collisions, no import binding
    conflicts and no source<->target import cycle.
    """
    target = move.target
    text = read_source_text(target)
    try:
        target_tree = ast.parse(text, filename=str(target))
    except SyntaxError as error:
        raise ValueError(
            f"{target} is not parseable ({error.msg} at line {error.lineno}); "
            "fix it before merging moved symbols into it"
        ) from error

    existing = {name for node in target_tree.body if (name := _symbol_name(node)) is not None}
    collisions = existing & set(move.symbols)
    if collisions:
        raise ValueError(f"Merge target {target} already defines: {', '.join(sorted(collisions))}")

    target_lines = text.splitlines(keepends=True)
    source_module = _module_name_between(target, source, package_relative=package_relative)
    target_lines, imports_source = _drop_moved_imports_from_source(
        target_lines, target_tree, source_module, source, set(move.symbols)
    )
    source_imports_target = bool(staying_refs & set(move.symbols)) or (
        keep_compat_imports and any(not name.startswith("_") for name in move.symbols)
    )
    if imports_source and source_imports_target:
        raise ValueError(
            f"Merging into {target} would create an import cycle: the target still "
            f"imports {source.name} and the source will import the target back; "
            "move the shared dependencies too or pick another target"
        )

    new_imports = _missing_import_lines(
        source,
        target,
        blocks,
        import_block,
        target_tree,
        existing,
    )
    new_imports.extend(
        line
        for line in _dependency_import_lines(
            source,
            target,
            move.symbols,
            symbols,
            moved_to,
            package_relative=package_relative,
        )
        if line.split()[1] != source_module or not source_imports_target
    )
    if new_imports:
        target_lines = _insert_after_import_block(target_lines, new_imports)

    while target_lines and not target_lines[-1].strip():
        target_lines.pop()
    content = [*target_lines, "\n", "\n"]
    for index, block in enumerate(blocks):
        if index and content[-1].strip():
            content.append("\n")
        content.extend(block)
        if content[-1].strip():
            content.append("\n")
    return _prune_unused_imports("".join(content), target)


def merge_text_into_existing_target(
    source: Path,
    move: SourceSplitMove,
    *,
    blocks: list[list[str]],
    leading_block: list[str],
    symbols: dict[str, SourceSymbol],
    moved_to: dict[str, Path],
    keep_compat_imports: bool,
    staying_refs: set[str],
) -> str:
    target = move.target
    existing_symbols = {symbol.name for symbol in _outline_text_target(target)}
    collisions = existing_symbols & set(move.symbols)
    if collisions:
        raise ValueError(f"Merge target {target} already defines: {', '.join(sorted(collisions))}")

    target_text = read_source_text(target)
    source_module = _text_module_reference(source, target)
    target_lines, imports_source = _drop_text_imports_from_source(
        target_text.splitlines(keepends=True),
        source_module,
        set(move.symbols),
        source.suffix,
    )
    source_imports_target = keep_compat_imports and (
        source.suffix in (".ts", ".tsx", ".js", ".jsx")
        or any(not name.startswith("_") for name in move.symbols)
        or bool(staying_refs & set(move.symbols))
    )
    if imports_source and source_imports_target:
        raise ValueError(
            f"Merging into {target} would create an import cycle: the target still "
            f"imports {source.name} and the source will import the target back; "
            "move the shared dependencies too or pick another target"
        )

    imports = _missing_text_imports(target_text, leading_block)
    imports.extend(_text_dependency_imports(source, move.target, move.symbols, symbols, moved_to))
    if imports:
        target_lines = _insert_text_imports(target_lines, imports, source.suffix)

    while target_lines and not target_lines[-1].strip():
        target_lines.pop()
    content = [*target_lines, "\n", "\n"]
    for index, block in enumerate(blocks):
        if index and content[-1].strip():
            content.append("\n")
        content.extend(block)
        if content[-1].strip():
            content.append("\n")
    return _collapse_text_blank_lines("".join(content))


def _drop_moved_imports_from_source(
    target_lines: list[str],
    target_tree: ast.Module,
    source_module: str,
    source: Path,
    moved: set[str],
) -> tuple[list[str], bool]:
    """Remove target imports of symbols that now live in the target itself.

    Returns the rewritten lines and whether the target still imports the
    source module afterwards.
    """
    replacements: dict[int, tuple[int, list[str]]] = {}
    imports_source = False
    for node in target_tree.body:
        if not isinstance(node, ast.ImportFrom) or node.end_lineno is None:
            continue
        module = "." * node.level + (node.module or "")
        absolute_source = node.level == 0 and module.endswith(f".{source.stem}")
        if module != source_module and not absolute_source:
            continue
        kept = [alias for alias in node.names if alias.name not in moved]
        if len(kept) == len(node.names):
            imports_source = True
            continue
        if kept:
            imports_source = True
            rendered = [
                alias.name if alias.asname is None else f"{alias.name} as {alias.asname}"
                for alias in kept
            ]
            replacements[node.lineno - 1] = (
                node.end_lineno,
                [_format_from_import(module, rendered)],
            )
        else:
            replacements[node.lineno - 1] = (node.end_lineno, [])
    if not replacements:
        return target_lines, imports_source
    rewritten: list[str] = []
    index = 0
    while index < len(target_lines):
        if index in replacements:
            end, new_lines = replacements[index]
            rewritten.extend(new_lines)
            index = end
            continue
        rewritten.append(target_lines[index])
        index += 1
    return rewritten, imports_source


def _missing_import_lines(
    source: Path,
    target: Path,
    blocks: list[list[str]],
    import_block: list[str],
    target_tree: ast.Module,
    existing_symbols: set[str],
) -> list[str]:
    pseudo_text = _prune_unused_imports(
        "".join([*import_block, "\n", *(line for block in blocks for line in block)]),
        target,
        keep_reexports=False,
    )
    target_bindings = _import_bindings(target_tree)
    lines: list[str] = []
    for node in ast.parse(pseudo_text).body:
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for alias in node.names:
            if isinstance(node, ast.Import):
                bound = alias.asname or alias.name.split(".")[0]
                origin = (alias.name, "")
                rendered_line = (
                    f"import {alias.name}\n"
                    if alias.asname is None
                    else f"import {alias.name} as {alias.asname}\n"
                )
            else:
                bound = alias.asname or alias.name
                module = "." * node.level + (node.module or "")
                origin = (module, alias.name)
                rendered = alias.name if alias.asname is None else f"{alias.name} as {alias.asname}"
                rendered_line = _format_from_import(module, [rendered])
            if bound in existing_symbols:
                if origin[0].split(".")[-1] == target.stem and origin[1] in ("", bound):
                    # The moved code imported this name from the merge target
                    # itself; after the merge it resolves locally.
                    continue
                raise ValueError(
                    f"Moved code needs import {bound!r}, which collides with a "
                    f"symbol defined in {target}"
                )
            if bound in target_bindings:
                if target_bindings[bound] != origin:
                    raise ValueError(
                        f"Moved code imports {bound!r} from {origin[0]!r} but {target} "
                        f"already binds it from {target_bindings[bound][0]!r}"
                    )
                continue
            lines.append(rendered_line)
    return lines


def _import_bindings(tree: ast.Module) -> dict[str, tuple[str, str]]:
    bindings: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings[alias.asname or alias.name.split(".")[0]] = (alias.name, "")
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                bindings[alias.asname or alias.name] = (module, alias.name)
    return bindings


def _outline_text_target(target: Path) -> list[SourceSymbol]:
    try:
        return outline_source_file(target)
    except ValueError as error:
        raise ValueError(f"Unsupported merge target for source-split: {target}") from error


def _text_module_reference(source: Path, target: Path) -> str:
    relative = source.with_suffix("").relative_to(target.parent)
    path = "/".join(relative.parts)
    if source.suffix == ".dart":
        return f"{path}{source.suffix}"
    return f"./{path}" if not path.startswith(".") else path


def _drop_text_imports_from_source(
    lines: list[str],
    source_module: str,
    moved: set[str],
    suffix: str,
) -> tuple[list[str], bool]:
    rewritten: list[str] = []
    imports_source = False
    for line in lines:
        stripped = line.strip()
        if source_module not in stripped:
            rewritten.append(line)
            continue
        if suffix == ".dart":
            if not stripped.startswith(("import ", "export ")):
                rewritten.append(line)
                continue
            kept = _kept_show_names(stripped, moved)
            if kept is None:
                imports_source = True
                rewritten.append(line)
            elif kept:
                imports_source = True
                prefix = stripped.split(" show ", 1)[0]
                rewritten.append(f"{prefix} show {', '.join(kept)};\n")
            continue
        if not stripped.startswith(("import ", "export ")):
            rewritten.append(line)
            continue
        kept = _kept_braced_names(stripped, moved)
        if kept is None:
            imports_source = True
            rewritten.append(line)
        elif kept:
            imports_source = True
            prefix, suffix_text = stripped.split("{", 1)
            _, rest = suffix_text.split("}", 1)
            rewritten.append(f"{prefix}{{ {', '.join(kept)} }}{rest}\n")
    return rewritten, imports_source


def _kept_show_names(line: str, moved: set[str]) -> list[str] | None:
    if " show " not in line:
        return None
    names = line.rsplit(" show ", 1)[1].rstrip(";").split(",")
    return [name.strip() for name in names if name.strip() and name.strip() not in moved]


def _kept_braced_names(line: str, moved: set[str]) -> list[str] | None:
    if "{" not in line or "}" not in line:
        return None
    inside = line.split("{", 1)[1].split("}", 1)[0]
    return [name.strip() for name in inside.split(",") if name.strip() not in moved]


def _missing_text_imports(target_text: str, leading_block: list[str]) -> list[str]:
    # Join multiline statements first; copying single lines of a braced
    # import would inject syntax fragments into the target.
    statements: list[str] = []
    current = ""
    open_braces = 0
    for line in leading_block:
        if current:
            current += line
            open_braces += line.count("{") - line.count("}")
            if open_braces <= 0:
                statements.append(current)
                current = ""
            continue
        stripped = line.strip()
        if not stripped.startswith(("import ", "import type ")):
            continue
        open_braces = line.count("{") - line.count("}")
        if open_braces > 0:
            current = line
        else:
            statements.append(line)
    if current:
        statements.append(current)
    return [
        statement if statement.endswith("\n") else statement + "\n"
        for statement in statements
        if statement.strip() not in target_text
    ]


def _text_dependency_imports(
    source: Path,
    target: Path,
    move_symbols: tuple[str, ...],
    symbols: dict[str, SourceSymbol],
    moved_to: dict[str, Path],
) -> list[str]:
    refs_by_target: dict[Path, list[str]] = {}
    own_target = target.resolve()
    moved_names = set(move_symbols)
    for name in move_symbols:
        for reference in symbols[name].references:
            if reference in moved_names:
                continue
            # References to staying source symbols import back from the
            # source module: a legal ESM cycle for render-time calls.
            ref_target = moved_to.get(reference, source)
            if ref_target.resolve() == own_target:
                continue
            refs_by_target.setdefault(ref_target, []).append(reference)
    lines: list[str] = []
    for ref_target, names in sorted(refs_by_target.items(), key=lambda item: str(item[0])):
        unique = sorted(dict.fromkeys(names))
        if source.suffix == ".dart":
            module = _relative_uri(target, ref_target)
            lines.append(f"import '{module}' show {', '.join(unique)};\n")
        elif source.suffix in (".ts", ".tsx", ".js", ".jsx"):
            module = _js_relative_module_name(target, ref_target)
            lines.extend(_ts_named_lines("import", module, unique, symbols))
    if lines:
        lines.append("\n")
    return lines


def _insert_text_imports(lines: list[str], imports: list[str], suffix: str) -> list[str]:
    end = 0
    open_braces = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if open_braces > 0:
            # Continuation of a multiline import/export statement.
            open_braces += line.count("{") - line.count("}")
            end = index + 1
            continue
        if not stripped:
            if end == index:
                end = index + 1
            continue
        if suffix == ".dart" and stripped.startswith(("library ", "import ", "export ", "part ")):
            end = index + 1
            continue
        if suffix in (".ts", ".tsx", ".js", ".jsx") and stripped.startswith(
            ("import ", "import type ", "export {", "export type {", "export *")
        ):
            open_braces = line.count("{") - line.count("}")
            end = index + 1
            continue
        break
    suffix_lines = ["\n"] if end < len(lines) and lines[end].strip() else []
    return [*lines[:end], *imports, *suffix_lines, *lines[end:]]


def _js_relative_module_name(source: Path, target: Path) -> str:
    relative = target.with_suffix("").relative_to(source.parent)
    path = "/".join(relative.parts)
    return f"./{path}" if not path.startswith(".") else path


def _relative_uri(source: Path, target: Path) -> str:
    return "/".join(target.relative_to(source.parent).parts)


def _collapse_text_blank_lines(text: str) -> str:
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
