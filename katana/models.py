from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CORE_SOURCE_SPLIT_EXTENSIONS = (
    ".py",
    ".md",
    ".mdx",
)

WEB_SOURCE_SPLIT_EXTENSIONS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".css",
)

FLUTTER_SOURCE_SPLIT_EXTENSIONS = (".dart",)

ADMIN_SOURCE_SPLIT_EXTENSIONS = WEB_SOURCE_SPLIT_EXTENSIONS

NEXT_SOURCE_SPLIT_EXTENSIONS = WEB_SOURCE_SPLIT_EXTENSIONS

SOURCE_SPLIT_EXTENSIONS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".dart",
    ".css",
    ".md",
    ".mdx",
)

SOURCE_SPLIT_PROFILES = {
    "core": CORE_SOURCE_SPLIT_EXTENSIONS,
    "python": (".py",),
    "web": WEB_SOURCE_SPLIT_EXTENSIONS,
    "admin": WEB_SOURCE_SPLIT_EXTENSIONS,
    "next": NEXT_SOURCE_SPLIT_EXTENSIONS,
    "flutter": FLUTTER_SOURCE_SPLIT_EXTENSIONS,
    "all": SOURCE_SPLIT_EXTENSIONS,
}

DEFAULT_SOURCE_SPLIT_PROFILES = ("core",)

TEXT_SPLIT_EXTENSIONS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".dart",
    ".css",
    ".md",
    ".mdx",
)

SPLIT_PLAN_VERSION = 1
KATANA_PLAN_SUFFIX = ".katana.json"
LEGACY_SOURCE_SPLIT_PLAN_SUFFIX = ".source-split.json"

_TS_SYMBOL_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:(?P<async>async)\s+)?"
    r"(?:(?P<kind>function|class|interface|type|enum|const|let|var)\s+)"
    r"(?P<name>[A-Za-z_$][\w$]*)"
)


def source_split_extensions_for_profiles(
    profiles: tuple[str, ...] = DEFAULT_SOURCE_SPLIT_PROFILES,
) -> tuple[str, ...]:
    from .adapters import language_adapters

    if not profiles:
        profiles = DEFAULT_SOURCE_SPLIT_PROFILES
    adapters = language_adapters()
    known_profiles = set(SOURCE_SPLIT_PROFILES)
    known_profiles.update(profile for adapter in adapters for profile in adapter.profiles)
    unknown = set(profiles).difference(known_profiles)
    if unknown:
        known = ", ".join(sorted((*known_profiles, "auto")))
        raise ValueError(f"Unknown source-split profile {min(unknown)!r}; expected one of: {known}")

    extensions: list[str] = list(SOURCE_SPLIT_EXTENSIONS) if "all" in profiles else []
    if "all" in profiles:
        for adapter in adapters:
            if "all" not in adapter.profiles:
                continue
            for extension in adapter.extensions:
                if extension not in extensions:
                    extensions.append(extension)
        return tuple(extensions)

    selected = ("core", *profiles)
    for profile in selected:
        for extension in SOURCE_SPLIT_PROFILES.get(profile, ()):
            if extension not in extensions:
                extensions.append(extension)
        for adapter in adapters:
            if profile not in adapter.profiles:
                continue
            for extension in adapter.extensions:
                if extension not in extensions:
                    extensions.append(extension)
    return tuple(extensions)


@dataclass(frozen=True)
class SourceSymbolChild:
    name: str
    kind: str
    signature: str
    start_line: int
    end_line: int
    code_lines: int
    tags: tuple[str, ...] = ()
    meta: dict[str, Any] | None = None

    def to_payload(self, *, total_code_lines: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "signature": self.signature,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "span_lines": self.end_line - self.start_line + 1,
            "code_lines": self.code_lines,
            "tags": list(self.tags),
            "meta": self.meta or {},
        }
        if total_code_lines and total_code_lines > 0:
            payload["code_lines_pct"] = round(self.code_lines * 100 / total_code_lines, 1)
        return payload


@dataclass(frozen=True)
class SourceSymbol:
    name: str
    kind: str
    signature: str
    start_line: int
    end_line: int
    code_lines: int
    references: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    meta: dict[str, Any] | None = None
    children: tuple[SourceSymbolChild, ...] = ()

    def to_payload(self, *, total_code_lines: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "signature": self.signature,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "span_lines": self.end_line - self.start_line + 1,
            "code_lines": self.code_lines,
            "references": list(self.references),
            "tags": list(self.tags),
            "meta": self.meta or {},
            "children": [
                child.to_payload(total_code_lines=self.code_lines) for child in self.children
            ],
        }
        if total_code_lines and total_code_lines > 0:
            payload["code_lines_pct"] = round(self.code_lines * 100 / total_code_lines, 1)
        return payload


@dataclass(frozen=True)
class SourceSplitMove:
    target: Path
    symbols: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {"target": str(self.target), "symbols": list(self.symbols)}


@dataclass(frozen=True)
class SourceSplitPlan:
    source: Path
    moves: tuple[SourceSplitMove, ...]
    moved_symbols: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": SPLIT_PLAN_VERSION,
            "source": str(self.source),
            "moves": [move.to_payload() for move in self.moves],
            "moved_symbols": list(self.moved_symbols),
            "warnings": list(self.warnings),
        }


def split_plan_json_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://mini.dev/katana/split-plan.schema.json",
        "title": "katana SplitPlan",
        "type": "object",
        "additionalProperties": False,
        "required": ["moves"],
        "properties": {
            "version": {
                "type": "integer",
                "const": SPLIT_PLAN_VERSION,
                "default": SPLIT_PLAN_VERSION,
            },
            "source": {
                "type": "string",
                "description": "Optional source path used to rebase relative target paths.",
            },
            "moves": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["target", "symbols"],
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "Target file relative to the source directory.",
                        },
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                        },
                    },
                },
            },
            "moved_symbols": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional metadata emitted by katana plan/apply.",
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional metadata emitted by katana plan/apply.",
            },
        },
    }


@dataclass(frozen=True)
class SourceSplitCheck:
    files: tuple[Path, ...]
    max_lines: int | None
    oversized: tuple[tuple[Path, int], ...]

    @property
    def ok(self) -> bool:
        return not self.oversized

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "files": [str(path) for path in self.files],
            "max_lines": self.max_lines,
            "oversized": [
                {"path": str(path), "code_lines": code_lines} for path, code_lines in self.oversized
            ],
        }
