from __future__ import annotations

import re

from .apply_compat import _typescript_leading_block

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
    if suffix not in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
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
