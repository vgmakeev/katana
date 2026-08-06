from __future__ import annotations

from pathlib import Path

from katana.toolchains.base import Diagnostic, SkippedTool, ToolchainContext
from katana.toolchains.support import (
    file_args,
    missing_binary,
    process_diagnostic,
    run,
    tool_command,
)


class DartFmtAdapter:
    id = "dart-format"
    kind = "formatter"
    extensions = (".dart",)
    default_enabled = True

    def __init__(self) -> None:
        self._command: list[str] | None = None
        self._cwd: Path | None = None

    def detect(self, context: ToolchainContext) -> SkippedTool | None:
        self._cwd = context.repo_root
        self._command = tool_command(context, "dart")
        return None if self._command else missing_binary("dart", context)

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        if files and self._command is not None:
            run([*self._command, "format", *file_args(files)], cwd=self._cwd)
        return []

    def check(self, files: list[Path]) -> list[Diagnostic]:
        if not files or self._command is None:
            return []
        completed = run(
            [
                *self._command,
                "format",
                "--output=none",
                "--set-exit-if-changed",
                *file_args(files),
            ],
            cwd=self._cwd,
        )
        return (
            []
            if completed.returncode == 0
            else [process_diagnostic(self.id, completed.stderr or completed.stdout)]
        )


def dart_toolchain_adapters() -> tuple[DartFmtAdapter, ...]:
    return (DartFmtAdapter(),)


__all__ = ("DartFmtAdapter", "dart_toolchain_adapters")
