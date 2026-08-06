from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

Severity = Literal["error", "warning", "info"]
AdapterKind = Literal["formatter", "linter", "checker"]


@dataclass(frozen=True)
class Diagnostic:
    source: str
    severity: Severity
    file: str
    line: int | None
    column: int | None
    code: str | None
    message: str
    fixable: bool

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SkippedTool:
    tool: str
    reason: str

    def to_payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ToolchainContext:
    source_dir: Path
    repo_root: Path
    ancestors: tuple[Path, ...]


class ToolchainAdapter(Protocol):
    """Formatter, linter, or checker contributed by a stack adapter."""

    id: str
    kind: AdapterKind
    extensions: tuple[str, ...]
    default_enabled: bool

    def detect(self, context: ToolchainContext) -> SkippedTool | None: ...

    def fix(self, files: list[Path]) -> list[Diagnostic]: ...

    def check(self, files: list[Path]) -> list[Diagnostic]: ...


ToolAdapter = ToolchainAdapter

__all__ = (
    "AdapterKind",
    "Diagnostic",
    "Severity",
    "SkippedTool",
    "ToolAdapter",
    "ToolchainAdapter",
    "ToolchainContext",
)
