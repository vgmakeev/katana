"""Compatibility facade for the bundled language adapters."""

from __future__ import annotations

from ._builtin import BundledLanguageAdapter
from .css import CssAdapter
from .dart import DartAdapter
from .markdown import MarkdownAdapter
from .python import PythonAdapter
from .rust import RustAdapter
from .typescript import TypeScriptAdapter

_BuiltinAdapter = BundledLanguageAdapter


def builtin_language_adapters() -> tuple[BundledLanguageAdapter, ...]:
    return (
        PythonAdapter(),
        RustAdapter(),
        TypeScriptAdapter(),
        DartAdapter(),
        CssAdapter(),
        MarkdownAdapter(),
    )


__all__ = (
    "CssAdapter",
    "DartAdapter",
    "MarkdownAdapter",
    "PythonAdapter",
    "RustAdapter",
    "TypeScriptAdapter",
    "builtin_language_adapters",
)
