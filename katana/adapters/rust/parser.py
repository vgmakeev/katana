from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import tree_sitter_rust
from tree_sitter import Language, Node, Parser

from katana.ir import SourceSpan
from katana.models import SourceSymbol

_TOP_LEVEL_ITEMS = {
    "const_item": "const",
    "enum_item": "enum",
    "function_item": "function",
    "macro_definition": "macro",
    "mod_item": "module",
    "static_item": "static",
    "struct_item": "struct",
    "trait_item": "trait",
    "type_item": "type",
    "union_item": "union",
}
_REFERENCE_NODES = {"field_identifier", "identifier", "type_identifier"}
_TRIVIA_NODES = {"attribute_item", "block_comment", "line_comment"}


@dataclass(frozen=True)
class RustItem:
    symbol: SourceSymbol
    span: SourceSpan
    context: str
    context_start_byte: int
    context_end_byte: int
    wrapper_start_byte: int | None
    wrapper_end_byte: int | None
    include_byte: int
    ordinal: int


def parse_rust_items(path: Path) -> list[RustItem]:
    source = path.read_bytes()
    parser = Parser(Language(tree_sitter_rust.language()))
    tree = parser.parse(source)
    if tree.root_node.has_error:
        raise ValueError(f"Rust source is not parseable: {path}")
    items: list[RustItem] = []
    ordinal = 0
    children = tree.root_node.children
    for index, node in enumerate(children):
        if node.type == "impl_item":
            impl_start = _attached_start(source, children, index, node.start_byte)
            impl_items = _impl_items(source, node, impl_start, ordinal)
            items.extend(impl_items)
            ordinal += len(impl_items)
            continue
        kind = _TOP_LEVEL_ITEMS.get(node.type)
        if kind is None:
            continue
        start = _attached_start(source, children, index, node.start_byte)
        items.append(
            _rust_item(
                source,
                node,
                start=start,
                kind=kind,
                name=_item_name(source, node),
                context="module",
                context_start=0,
                context_end=len(source),
                wrapper_start=None,
                wrapper_end=None,
                include_byte=start,
                ordinal=ordinal,
            )
        )
        ordinal += 1
    return _resolve_references(items, source)


def _impl_items(source: bytes, impl: Node, impl_start: int, ordinal: int) -> list[RustItem]:
    body = impl.child_by_field_name("body")
    owner_node = impl.child_by_field_name("type")
    if body is None or owner_node is None:
        return []
    owner = _text(source, owner_node).strip()
    trait = impl.child_by_field_name("trait")
    if trait is not None:
        owner = f"<{owner} as {_text(source, trait).strip()}>"
    result: list[RustItem] = []
    for index, node in enumerate(body.children):
        if node.type != "function_item":
            continue
        method = _item_name(source, node)
        start = _attached_start(source, body.children, index, node.start_byte)
        result.append(
            _rust_item(
                source,
                node,
                start=start,
                kind="method",
                name=f"{owner}::{method}",
                context=f"impl:{impl.start_byte}:{impl.end_byte}",
                context_start=body.start_byte + 1,
                context_end=body.end_byte - 1,
                wrapper_start=impl_start,
                wrapper_end=body.start_byte + 1,
                include_byte=impl.end_byte,
                ordinal=ordinal + len(result),
            )
        )
    return result


def _rust_item(
    source: bytes,
    node: Node,
    *,
    start: int,
    kind: str,
    name: str,
    context: str,
    context_start: int,
    context_end: int,
    wrapper_start: int | None,
    wrapper_end: int | None,
    include_byte: int,
    ordinal: int,
) -> RustItem:
    start_line = source.count(b"\n", 0, start) + 1
    end_line = source.count(b"\n", 0, node.end_byte) + 1
    code_lines = _code_lines(source[start : node.end_byte])
    symbol = SourceSymbol(
        name=name,
        kind=kind,
        signature=_signature(source, node),
        start_line=start_line,
        end_line=end_line,
        code_lines=code_lines,
        meta={
            "context": context,
            "context_start_byte": context_start,
            "context_end_byte": context_end,
            "wrapper_start_byte": wrapper_start,
            "wrapper_end_byte": wrapper_end,
            "include_byte": include_byte,
            "ordinal": ordinal,
        },
    )
    return RustItem(
        symbol=symbol,
        span=SourceSpan(start, node.end_byte, start_line, end_line),
        context=context,
        context_start_byte=context_start,
        context_end_byte=context_end,
        wrapper_start_byte=wrapper_start,
        wrapper_end_byte=wrapper_end,
        include_byte=include_byte,
        ordinal=ordinal,
    )


def _resolve_references(items: list[RustItem], source: bytes) -> list[RustItem]:
    leaf_to_names: dict[str, list[str]] = {}
    for item in items:
        leaf_to_names.setdefault(item.symbol.name.rsplit("::", 1)[-1], []).append(item.symbol.name)
    resolved: list[RustItem] = []
    parser = Parser(Language(tree_sitter_rust.language()))
    for item in items:
        fragment = source[item.span.start_byte : item.span.end_byte]
        tree = parser.parse(fragment)
        candidates = {
            _text(fragment, node) for node in _walk(tree.root_node) if node.type in _REFERENCE_NODES
        }
        references: list[str] = []
        for leaf in sorted(candidates):
            for name in leaf_to_names.get(leaf, ()):
                if name != item.symbol.name and name not in references:
                    references.append(name)
        resolved.append(replace(item, symbol=replace(item.symbol, references=tuple(references))))
    return resolved


def _attached_start(source: bytes, siblings: list[Node], index: int, default: int) -> int:
    start = default
    cursor = index - 1
    while cursor >= 0 and siblings[cursor].type in _TRIVIA_NODES:
        candidate = siblings[cursor]
        between = source[candidate.end_byte : start]
        text = _text(source, candidate).lstrip()
        attachable = candidate.type == "attribute_item" or text.startswith(("///", "/**"))
        if not attachable or between.count(b"\n") > 1:
            break
        start = candidate.start_byte
        cursor -= 1
    return start


def _item_name(source: bytes, node: Node) -> str:
    name = node.child_by_field_name("name")
    if name is None:
        raise ValueError(f"Rust {node.type} has no name")
    return _text(source, name)


def _signature(source: bytes, node: Node) -> str:
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    value = source[node.start_byte : end].decode("utf-8").strip().rstrip(";").strip()
    return " ".join(value.split())


def _walk(node: Node) -> list[Node]:
    nodes = [node]
    for child in node.children:
        nodes.extend(_walk(child))
    return nodes


def _text(source: bytes, node: Node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8")


def _code_lines(source: bytes) -> int:
    return sum(
        1
        for line in source.decode("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("//", "/*", "*"))
    )


__all__ = ("RustItem", "parse_rust_items")
