from __future__ import annotations

import hashlib
from pathlib import Path

from katana.ir import DocumentIR

from .base import LanguageAdapter


class AdapterConformanceError(ValueError):
    """Raised when an adapter returns an unsafe or internally inconsistent map."""


def validate_document_ir(document: DocumentIR) -> None:
    source_bytes = document.path.read_bytes()
    text = source_bytes.decode("utf-8")
    byte_length = len(source_bytes)
    line_count = max(len(text.splitlines()), 1)
    expected_hash = hashlib.sha256(source_bytes).hexdigest()
    if document.protocol_version != 2:
        raise AdapterConformanceError("DocumentIR protocol_version must be 2")
    if document.content_hash != expected_hash:
        raise AdapterConformanceError("DocumentIR content_hash does not match the source")
    if document.capabilities.adapter_id != document.adapter_id:
        raise AdapterConformanceError("capability adapter_id does not match DocumentIR")

    known_ids = {symbol.id for symbol in document.symbols}
    ids: set[str] = set()
    previous_start = -1
    for symbol in document.symbols:
        if symbol.id in ids:
            raise AdapterConformanceError(f"duplicate symbol id: {symbol.id}")
        ids.add(symbol.id)
        span = symbol.span
        if not (0 <= span.start_byte <= span.end_byte <= byte_length):
            raise AdapterConformanceError(f"invalid source span for symbol {symbol.name!r}")
        if not (1 <= span.start_line <= span.end_line <= line_count):
            raise AdapterConformanceError(f"invalid line span for symbol {symbol.name!r}")
        try:
            source_bytes[span.start_byte : span.end_byte].decode("utf-8")
        except UnicodeDecodeError as error:
            raise AdapterConformanceError(
                f"source span for symbol {symbol.name!r} splits a UTF-8 code point"
            ) from error
        if span.start_byte < previous_start:
            raise AdapterConformanceError("symbols must be ordered by source position")
        previous_start = span.start_byte
        for child in symbol.children:
            if not (span.start_line <= child.start_line <= child.end_line <= span.end_line):
                raise AdapterConformanceError(
                    f"child {child.name!r} escapes parent symbol {symbol.name!r}"
                )
        for reference in symbol.references:
            if reference.target_id is not None and reference.target_id not in known_ids:
                raise AdapterConformanceError(
                    f"reference from {symbol.name!r} has an unknown target id"
                )


def check_language_adapter(adapter: LanguageAdapter, path: Path) -> dict[str, object]:
    document = adapter.analyze(path)
    validate_document_ir(document)
    return {
        "ok": True,
        "adapter": adapter.id,
        "path": str(path),
        "protocol_version": document.protocol_version,
        "symbol_count": len(document.symbols),
    }
