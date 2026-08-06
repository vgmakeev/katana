from __future__ import annotations

from pathlib import Path


def read_source_text(path: Path) -> str:
    """Decode UTF-8 source without universal-newline translation."""

    return path.read_bytes().decode("utf-8")


def source_newline(path: Path) -> str:
    """Return the dominant newline sequence, defaulting to LF."""

    data = path.read_bytes()
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    if crlf > lf and crlf >= cr:
        return "\r\n"
    if cr > lf:
        return "\r"
    return "\n"


def encode_source_text(text: str, *, newline: str) -> bytes:
    """Encode generated text using one explicit, platform-neutral newline style."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline != "\n":
        normalized = normalized.replace("\n", newline)
    return normalized.encode("utf-8")
