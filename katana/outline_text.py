from __future__ import annotations

import re
from pathlib import Path

from .models import SourceSymbol, SourceSymbolChild


def _with_typescript_metadata(
    symbols: list[SourceSymbol],
    lines: list[str],
    *,
    file_meta: dict[str, object],
) -> list[SourceSymbol]:
    return [_typescript_symbol_metadata(symbol, lines, file_meta=file_meta) for symbol in symbols]


def _typescript_file_meta(path: Path, lines: list[str]) -> dict[str, object]:
    imports = "\n".join(line for line in lines if line.strip().startswith("import"))
    shadcn_imports = sorted(set(re.findall(r"[\"'](?:@/)?components/ui/([^\"']+)[\"']", imports)))
    ui_primitive_imports = sorted(set(re.findall(r"[\"']@radix-ui/([^\"']+)[\"']", imports)))
    filename = path.name
    path_parts = set(path.parts)
    next_convention = filename in {
        "page.tsx",
        "page.jsx",
        "layout.tsx",
        "layout.jsx",
        "loading.tsx",
        "loading.jsx",
        "error.tsx",
        "error.jsx",
        "not-found.tsx",
        "not-found.jsx",
        "route.ts",
        "route.js",
    } and bool({"app", "pages"} & path_parts)
    return {
        "imports_react": bool(re.search(r"[\"']react[\"']", imports)),
        "imports_next": bool(re.search(r"[\"']next(?:/[^\"']+)?[\"']", imports)),
        "next_convention": next_convention,
        "use_client": any(
            line.strip().rstrip(";") in {"'use client'", '"use client"'} for line in lines[:5]
        ),
        "shadcn_imports": shadcn_imports,
        "ui_primitive_imports": ui_primitive_imports,
    }


def _typescript_symbol_metadata(
    symbol: SourceSymbol,
    lines: list[str],
    *,
    file_meta: dict[str, object],
) -> SourceSymbol:
    body = "\n".join(lines[symbol.start_line - 1 : symbol.end_line])
    tags: list[str] = []
    meta: dict[str, object] = {}
    is_pascal = bool(re.match(r"^[A-Z][A-Za-z0-9]*$", symbol.name))
    uses_jsx = bool(re.search(r"return\s+(?:\(|<)|<[A-Z_a-z][\w.:-]*(?:\\s|>|/)", body))
    if is_pascal and uses_jsx:
        tags.append("react_component")
    if re.match(r"^use[A-Z0-9]", symbol.name):
        tags.append("react_hook")
    if file_meta.get("use_client"):
        tags.append("client_component")
        meta["use_client"] = True
    if file_meta.get("imports_next") or file_meta.get("next_convention"):
        tags.append("next")
        if file_meta.get("next_convention"):
            meta["next_convention"] = True
    class_count = len(re.findall(r"\bclassName\s*=", body))
    cn_count = len(re.findall(r"\bcn\s*\(", body))
    cva_count = len(re.findall(r"\bcva\s*\(", body))
    if class_count or cn_count or cva_count:
        tags.append("tailwind")
        meta["tailwind"] = {
            "className": class_count,
            "cn": cn_count,
            "cva": cva_count,
        }
    shadcn_imports = file_meta.get("shadcn_imports") or []
    ui_primitive_imports = file_meta.get("ui_primitive_imports") or []
    if shadcn_imports:
        tags.append("shadcn")
        meta["shadcn_imports"] = shadcn_imports
    if ui_primitive_imports:
        tags.append("ui_primitive")
        meta["ui_primitive_imports"] = ui_primitive_imports
    if file_meta.get("imports_react"):
        meta["imports_react"] = True
    return SourceSymbol(
        name=symbol.name,
        kind=symbol.kind,
        signature=symbol.signature,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        code_lines=symbol.code_lines,
        references=symbol.references,
        tags=tuple(dict.fromkeys(tags)),
        meta=meta,
        children=_text_children(
            lines,
            symbol.start_line,
            symbol.end_line,
            language="typescript",
        ),
    )


def _with_dart_metadata(symbols: list[SourceSymbol], lines: list[str]) -> list[SourceSymbol]:
    imports = "\n".join(line for line in lines if line.strip().startswith("import"))
    file_imports_flutter = bool(re.search(r"[\"']package:flutter/", imports))
    return [
        _dart_symbol_metadata(symbol, lines, imports_flutter=file_imports_flutter)
        for symbol in symbols
    ]


def _dart_symbol_metadata(
    symbol: SourceSymbol,
    lines: list[str],
    *,
    imports_flutter: bool,
) -> SourceSymbol:
    body = "\n".join(lines[symbol.start_line - 1 : symbol.end_line])
    tags: list[str] = []
    meta: dict[str, object] = {}
    if imports_flutter:
        meta["imports_flutter"] = True
    if re.search(r"\b(?:StatelessWidget|StatefulWidget|InheritedWidget)\b", body) or re.search(
        r"\bWidget\s+build\s*\(",
        body,
    ):
        tags.append("flutter_widget")
    if re.search(r"\bState<\s*[A-Za-z_]\w*\s*>", body):
        tags.append("flutter_state")
    return SourceSymbol(
        name=symbol.name,
        kind=symbol.kind,
        signature=symbol.signature,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        code_lines=symbol.code_lines,
        references=symbol.references,
        tags=tuple(dict.fromkeys(tags)),
        meta=meta,
        children=_text_children(
            lines,
            symbol.start_line,
            symbol.end_line,
            language="dart",
        ),
    )


def _text_children(
    lines: list[str],
    start_line: int,
    end_line: int,
    *,
    language: str,
) -> tuple[SourceSymbolChild, ...]:
    starts: list[tuple[int, str, str, str, tuple[str, ...]]] = []
    depth = 0
    for index in range(start_line, end_line + 1):
        line = lines[index - 1]
        stripped = line.strip()
        if index > start_line and depth == 1:
            child = _text_child_start(stripped, language=language)
            if child is not None:
                starts.append((index, *child))
        depth += _brace_delta(line)
        depth = max(depth, 0)
    children: list[SourceSymbolChild] = []
    for position, (child_start, name, kind, signature, tags) in enumerate(starts):
        child_end = starts[position + 1][0] - 1 if position + 1 < len(starts) else end_line
        children.append(
            SourceSymbolChild(
                name=name,
                kind=kind,
                signature=signature,
                start_line=child_start,
                end_line=child_end,
                code_lines=_text_code_lines(lines[child_start - 1 : child_end]),
                tags=tags,
            )
        )
    return tuple(children)


def _text_child_start(
    stripped: str,
    *,
    language: str,
) -> tuple[str, str, str, tuple[str, ...]] | None:
    if language == "typescript":
        match = re.match(
            r"^(?:(?:const|let|var)\s+)?"
            r"(?:(?:public|private|protected|static|async|readonly)\s+)*"
            r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:=|\()",
            stripped,
        )
        if match is None:
            return None
        name = match.group("name")
        tags: list[str] = ["method"] if "(" in stripped else []
        if re.match(r"^(handle|on)[A-Z0-9]", name):
            tags.append("handler")
        if re.match(r"^render[A-Z0-9]", name):
            tags.append("render_helper")
        return name, "TextChild", stripped, tuple(tags)
    match = re.match(r"^(?:[A-Za-z_][\w<>,.? ]+\s+)?(?P<name>[A-Za-z_]\w*)\s*\(", stripped)
    if match is None:
        return None
    name = match.group("name")
    tags = ["method"]
    if name == "build":
        tags.append("flutter_build")
    return name, "TextChild", stripped, tuple(tags)


def _text_code_lines(lines: list[str]) -> int:
    return sum(1 for line in lines if line.strip())


def _brace_delta(line: str) -> int:
    in_single = False
    in_double = False
    in_template = False
    escaped = False
    delta = 0
    for char in line:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double and not in_template:
            in_single = not in_single
            continue
        if char == '"' and not in_single and not in_template:
            in_double = not in_double
            continue
        if char == "`" and not in_single and not in_double:
            in_template = not in_template
            continue
        if in_single or in_double or in_template:
            continue
        if char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
    return delta
