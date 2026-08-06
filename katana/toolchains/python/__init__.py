from __future__ import annotations

import json
from pathlib import Path

from katana.toolchains.base import Diagnostic, SkippedTool, ToolchainContext
from katana.toolchains.support import (
    diagnostics_from_process,
    file_args,
    int_or_none,
    missing_binary,
    missing_config_or_binary,
    nearest_mypy_config,
    process_diagnostic,
    run,
    tool_command,
)


class RuffAdapter:
    id = "ruff"
    kind = "linter"
    extensions = (".py",)
    default_enabled = True

    def __init__(self) -> None:
        self._command: list[str] | None = None
        self._cwd: Path | None = None

    def detect(self, context: ToolchainContext) -> SkippedTool | None:
        self._cwd = context.repo_root
        self._command = tool_command(context, "ruff")
        return None if self._command else missing_binary(self.id, context)

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        if files and self._command is not None:
            run([*self._command, "check", "--fix", *file_args(files)], cwd=self._cwd)
            run([*self._command, "format", *file_args(files)], cwd=self._cwd)
        return []

    def check(self, files: list[Path]) -> list[Diagnostic]:
        if not files or self._command is None:
            return []
        completed = run(
            [*self._command, "check", "--output-format=json", *file_args(files)],
            cwd=self._cwd,
        )
        if not completed.stdout.strip():
            return []
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return [process_diagnostic(self.id, completed.stderr or completed.stdout)]
        diagnostics: list[Diagnostic] = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, dict):
                continue
            raw_location = item.get("location")
            location = raw_location if isinstance(raw_location, dict) else {}
            diagnostics.append(
                Diagnostic(
                    source=self.id,
                    severity="error",
                    file=str(item.get("filename") or ""),
                    line=int_or_none(location.get("row")),
                    column=int_or_none(location.get("column")),
                    code=str(item.get("code")) if item.get("code") else None,
                    message=str(item.get("message") or ""),
                    fixable=item.get("fix") is not None,
                )
            )
        return diagnostics


class MypyAdapter:
    id = "mypy"
    kind = "checker"
    extensions = (".py",)
    default_enabled = False
    config_names = ("mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg")

    def __init__(self) -> None:
        self._command: list[str] | None = None
        self._cwd: Path | None = None

    def detect(self, context: ToolchainContext) -> SkippedTool | None:
        self._cwd = context.repo_root
        config = nearest_mypy_config(context, self.config_names)
        self._command = tool_command(context, "mypy")
        if config and self._command:
            return None
        return missing_config_or_binary(self.id, context, config, self._command)

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        return []

    def check(self, files: list[Path]) -> list[Diagnostic]:
        if not files or self._command is None:
            return []
        completed = run([*self._command, *file_args(files)], cwd=self._cwd)
        return diagnostics_from_process(self.id, completed)


def python_toolchain_adapters() -> tuple[RuffAdapter | MypyAdapter, ...]:
    return RuffAdapter(), MypyAdapter()


__all__ = ("MypyAdapter", "RuffAdapter", "python_toolchain_adapters")
