"""Compatibility facade for the bundled language adapters."""

from __future__ import annotations

from ._builtin import BundledLanguageAdapter
from .css import CssAdapter
from .dart import DartAdapter
from .markdown import MarkdownAdapter
from .python import PythonAdapter
from .typescript import TypeScriptAdapter

_BuiltinAdapter = BundledLanguageAdapter


def builtin_language_adapters() -> tuple[BundledLanguageAdapter, ...]:
    return (
        PythonAdapter(),
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
    "TypeScriptAdapter",
    "builtin_language_adapters",
)
