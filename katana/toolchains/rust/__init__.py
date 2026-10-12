from __future__ import annotations

from pathlib import Path

from katana.toolchains.base import Diagnostic, SkippedTool, ToolchainContext
from katana.toolchains.support import (
    diagnostics_from_process,
    missing_config_or_binary,
    nearest_config,
    run,
    tool_command,
)


class _CargoAdapter:
    id: str
    extensions = (".rs",)
    default_enabled = True

    def __init__(self) -> None:
        self._command: list[str] | None = None
        self._cwd: Path | None = None

    def detect(self, context: ToolchainContext) -> SkippedTool | None:
        manifest = nearest_config(context, ("Cargo.toml",))
        self._command = tool_command(context, "cargo")
        self._cwd = manifest.parent if manifest is not None else context.repo_root
        if manifest is not None and self._command is not None:
            return None
        return missing_config_or_binary(self.id, context, manifest, self._command)


class CargoFmtAdapter(_CargoAdapter):
    id = "cargo-fmt"
    kind = "formatter"

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        if files and self._command is not None:
            run([*self._command, "fmt", "--all"], cwd=self._cwd)
        return []

    def check(self, files: list[Path]) -> list[Diagnostic]:
        if not files or self._command is None:
            return []
        completed = run([*self._command, "fmt", "--all", "--", "--check"], cwd=self._cwd)
        return diagnostics_from_process(self.id, completed)


class CargoCheckAdapter(_CargoAdapter):
    id = "cargo-check"
    kind = "checker"

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        return []

    def check(self, files: list[Path]) -> list[Diagnostic]:
        if not files or self._command is None:
            return []
        completed = run([*self._command, "check", "--all-targets"], cwd=self._cwd)
        return diagnostics_from_process(self.id, completed)


__all__ = ("CargoCheckAdapter", "CargoFmtAdapter")
