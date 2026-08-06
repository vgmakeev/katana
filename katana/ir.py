from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .models import SourceSymbol, SourceSymbolChild

ReferenceConfidence = Literal["resolved", "lexical", "textual"]
Movability = Literal["free", "closure", "required_group", "pinned"]
OrderPolicy = Literal["any", "preserve", "prefix_only"]


@dataclass(frozen=True)
class SourceSpan:
    """A byte-exact, end-exclusive source span with display line coordinates."""

    start_byte: int
    end_byte: int
    start_line: int
    end_line: int

    def to_payload(self) -> dict[str, int]:
        return {
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


@dataclass(frozen=True)
class SymbolReference:
    name: str
    target_id: str | None
    confidence: ReferenceConfidence

    def to_payload(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "target_id": self.target_id,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class MoveConstraints:
    movability: Movability = "closure"
    order_policy: OrderPolicy = "any"
    required_with: tuple[str, ...] = ()
    pinned_reason: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "movability": self.movability,
            "order_policy": self.order_policy,
            "required_with": list(self.required_with),
            "pinned_reason": self.pinned_reason,
        }


@dataclass(frozen=True)
class AdapterCapabilities:
    adapter_id: str
    language: str
    parser: str
    strategy: str
    precision: str
    safe_apply: bool
    outline: bool = True
    source_locations: bool = True
    hierarchy: bool = False
    comments: bool = False
    local_bindings: bool = False
    module_rewrite: bool = False
    workspace_rewrite: bool = False
    formatting: bool = False
    validation: bool = False
    adapter_available: bool = True
    verifications: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    bridge: dict[str, bool] | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "language": self.language,
            "parser": self.parser,
            "strategy": self.strategy,
            "precision": self.precision,
            "safe_apply": self.safe_apply,
            "adapter": self.adapter_id,
            "adapter_available": self.adapter_available,
            "capabilities": {
                "outline": self.outline,
                "source_locations": self.source_locations,
                "hierarchy": self.hierarchy,
                "comments": self.comments,
                "local_bindings": self.local_bindings,
                "module_rewrite": self.module_rewrite,
                "workspace_rewrite": self.workspace_rewrite,
                "formatting": self.formatting,
                "validation": self.validation,
            },
            "verifications": list(self.verifications),
            "limitations": list(self.limitations),
        }
        if self.bridge is not None:
            payload["bridge"] = dict(self.bridge)
        return payload

    def to_legacy_payload(
        self,
        *,
        include_adapter: bool = False,
        parser: str | None = None,
        strategy: str | None = None,
        precision: str | None = None,
        limitations: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        """Payload shape used by the production v1 outline/assess commands."""
        payload: dict[str, object] = {
            "language": self.language,
            "parser": parser or self.parser,
            "strategy": strategy or self.strategy,
            "precision": precision or self.precision,
            "safe_apply": self.safe_apply,
            "verifications": list(self.verifications),
            "limitations": list(self.limitations if limitations is None else limitations),
        }
        if include_adapter:
            payload["adapter"] = self.adapter_id
            payload["adapter_available"] = self.adapter_available
            if self.bridge is not None:
                legacy_bridge_keys = (
                    "node",
                    "typescript",
                    "postcss",
                    "dart",
                    "dart_analyzer",
                )
                payload["bridge"] = {
                    key: self.bridge[key] for key in legacy_bridge_keys if key in self.bridge
                }
        return payload


@dataclass(frozen=True)
class IRSymbol:
    id: str
    name: str
    kind: str
    signature: str
    span: SourceSpan
    code_lines: int
    references: tuple[SymbolReference, ...]
    constraints: MoveConstraints
    tags: tuple[str, ...] = ()
    meta: dict[str, Any] | None = None
    children: tuple[SourceSymbolChild, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "signature": self.signature,
            "span": self.span.to_payload(),
            "code_lines": self.code_lines,
            "references": [reference.to_payload() for reference in self.references],
            "constraints": self.constraints.to_payload(),
            "tags": list(self.tags),
            "meta": self.meta or {},
            "children": [
                child.to_payload(total_code_lines=self.code_lines) for child in self.children
            ],
        }


@dataclass(frozen=True)
class DocumentIR:
    protocol_version: int
    path: Path
    language: str
    adapter_id: str
    content_hash: str
    capabilities: AdapterCapabilities
    symbols: tuple[IRSymbol, ...]
    source_symbols: tuple[SourceSymbol, ...]
    meta: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "path": str(self.path),
            "language": self.language,
            "adapter_id": self.adapter_id,
            "content_hash": self.content_hash,
            "capabilities": self.capabilities.to_payload(),
            "symbols": [symbol.to_payload() for symbol in self.symbols],
            "meta": self.meta or {},
        }


@dataclass(frozen=True)
class TextEdit:
    start_byte: int
    end_byte: int
    replacement: str


@dataclass(frozen=True)
class FileEdit:
    path: Path
    expected_hash: str | None
    edits: tuple[TextEdit, ...]
    create: bool = False


@dataclass(frozen=True)
class EditSet:
    """Adapter-produced edits that core may validate and commit atomically."""

    adapter_id: str
    files: tuple[FileEdit, ...]


def build_document_ir(
    path: Path,
    *,
    language: str,
    adapter_id: str,
    capabilities: AdapterCapabilities,
    symbols: list[SourceSymbol],
    constraints: dict[str, MoveConstraints] | None = None,
    source_spans: list[SourceSpan] | None = None,
    meta: dict[str, Any] | None = None,
) -> DocumentIR:
    source_bytes = path.read_bytes()
    text = source_bytes.decode("utf-8")
    line_offsets = _line_byte_offsets(text)
    if source_spans is not None and len(source_spans) != len(symbols):
        raise ValueError("source_spans must align one-to-one with symbols")
    symbol_ids = [
        _symbol_id(
            path,
            symbol,
            line_offsets,
            start_byte=(source_spans[index].start_byte if source_spans is not None else None),
        )
        for index, symbol in enumerate(symbols)
    ]
    reference_ids = {
        symbol.name: symbol_id for symbol, symbol_id in zip(symbols, symbol_ids, strict=True)
    }
    ir_symbols: list[IRSymbol] = []
    for index, symbol in enumerate(symbols):
        span = (
            source_spans[index]
            if source_spans is not None
            else _symbol_span(symbol, line_offsets, len(source_bytes))
        )
        ir_symbols.append(
            IRSymbol(
                id=symbol_ids[index],
                name=symbol.name,
                kind=symbol.kind,
                signature=symbol.signature,
                span=span,
                code_lines=symbol.code_lines,
                references=tuple(
                    SymbolReference(
                        name=reference,
                        target_id=reference_ids.get(reference),
                        confidence="lexical",
                    )
                    for reference in symbol.references
                ),
                constraints=(constraints or {}).get(symbol.name, MoveConstraints()),
                tags=symbol.tags,
                meta=symbol.meta,
                children=symbol.children,
            )
        )
    return DocumentIR(
        protocol_version=2,
        path=path,
        language=language,
        adapter_id=adapter_id,
        content_hash=hashlib.sha256(source_bytes).hexdigest(),
        capabilities=capabilities,
        symbols=tuple(ir_symbols),
        source_symbols=tuple(symbols),
        meta=meta,
    )


def _line_byte_offsets(text: str) -> list[int]:
    offsets = [0]
    current = 0
    byte_length = len(text.encode("utf-8"))
    for line in text.splitlines(keepends=True):
        current += len(line.encode("utf-8"))
        offsets.append(current)
    if offsets[-1] != byte_length:
        offsets.append(byte_length)
    return offsets


def _symbol_span(symbol: SourceSymbol, offsets: list[int], byte_length: int) -> SourceSpan:
    start_index = max(symbol.start_line - 1, 0)
    end_index = max(symbol.end_line, 0)
    return SourceSpan(
        start_byte=offsets[start_index] if start_index < len(offsets) else byte_length,
        end_byte=offsets[end_index] if end_index < len(offsets) else byte_length,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
    )


def _symbol_id(
    path: Path,
    symbol: SourceSymbol,
    offsets: list[int],
    *,
    start_byte: int | None = None,
) -> str:
    start_index = max(symbol.start_line - 1, 0)
    if start_byte is not None:
        resolved_start = start_byte
    elif start_index < len(offsets):
        resolved_start = offsets[start_index]
    else:
        resolved_start = 0
    return f"{path.as_posix()}::{symbol.kind}:{symbol.name}@{resolved_start}"
