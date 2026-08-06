from __future__ import annotations

import json
from pathlib import Path

from katana.toolchains.base import Diagnostic, Severity, SkippedTool, ToolchainContext
from katana.toolchains.support import (
    diagnostics_from_process,
    file_args,
    int_or_none,
    missing_config_or_binary,
    nearest_config,
    process_diagnostic,
    run,
    tool_command,
)

_SCRIPT_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")
_PRETTIER_EXTENSIONS = (*_SCRIPT_EXTENSIONS, ".css", ".md", ".mdx")


class EslintAdapter:
    id = "eslint"
    kind = "linter"
    extensions = _SCRIPT_EXTENSIONS
    default_enabled = True
    config_names = (
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.config.cjs",
        ".eslintrc",
        ".eslintrc.json",
        ".eslintrc.js",
        ".eslintrc.cjs",
    )

    def __init__(self) -> None:
        self._command: list[str] | None = None
        self._cwd: Path | None = None

    def detect(self, context: ToolchainContext) -> SkippedTool | None:
        self._cwd = context.repo_root
        config = nearest_config(context, self.config_names)
        self._command = tool_command(context, "eslint")
        if config and self._command:
            return None
        return missing_config_or_binary(self.id, context, config, self._command)

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        if files and self._command is not None:
            run([*self._command, "--fix", *file_args(files)], cwd=self._cwd)
        return []

    def check(self, files: list[Path]) -> list[Diagnostic]:
        if not files or self._command is None:
            return []
        completed = run([*self._command, "--format", "json", *file_args(files)], cwd=self._cwd)
        if not completed.stdout.strip():
            return []
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return [process_diagnostic(self.id, completed.stderr or completed.stdout)]
        diagnostics: list[Diagnostic] = []
        for file_result in payload if isinstance(payload, list) else []:
            if not isinstance(file_result, dict):
                continue
            messages = file_result.get("messages")
            for message in messages if isinstance(messages, list) else []:
                if not isinstance(message, dict):
                    continue
                severity: Severity = "warning" if message.get("severity") == 1 else "error"
                diagnostics.append(
                    Diagnostic(
                        source=self.id,
                        severity=severity,
                        file=str(file_result.get("filePath") or ""),
                        line=int_or_none(message.get("line")),
                        column=int_or_none(message.get("column")),
                        code=str(message.get("ruleId")) if message.get("ruleId") else None,
                        message=str(message.get("message") or ""),
                        fixable=bool(message.get("fix")),
                    )
                )
        return diagnostics


class PrettierAdapter:
    id = "prettier"
    kind = "formatter"
    extensions = _PRETTIER_EXTENSIONS
    default_enabled = True
    config_names = (
        ".prettierrc",
        ".prettierrc.json",
        ".prettierrc.yml",
        ".prettierrc.yaml",
        ".prettierrc.js",
        "prettier.config.js",
        "prettier.config.mjs",
        "prettier.config.cjs",
    )

    def __init__(self) -> None:
        self._command: list[str] | None = None
        self._cwd: Path | None = None

    def detect(self, context: ToolchainContext) -> SkippedTool | None:
        self._cwd = context.repo_root
        config = nearest_config(context, self.config_names)
        self._command = tool_command(context, "prettier")
        if config and self._command:
            return None
        return missing_config_or_binary(self.id, context, config, self._command)

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        if files and self._command is not None:
            run([*self._command, "--write", *file_args(files)], cwd=self._cwd)
        return []

    def check(self, files: list[Path]) -> list[Diagnostic]:
        if not files or self._command is None:
            return []
        completed = run([*self._command, "--check", *file_args(files)], cwd=self._cwd)
        return (
            []
            if completed.returncode == 0
            else [process_diagnostic(self.id, completed.stderr or completed.stdout)]
        )


class TscAdapter:
    id = "tsc"
    kind = "checker"
    extensions = _SCRIPT_EXTENSIONS
    default_enabled = False

    def __init__(self) -> None:
        self._command: list[str] | None = None
        self._cwd: Path | None = None

    def detect(self, context: ToolchainContext) -> SkippedTool | None:
        self._cwd = context.repo_root
        config = nearest_config(context, ("tsconfig.json",))
        self._command = tool_command(context, "tsc")
        if config and self._command:
            return None
        return missing_config_or_binary(self.id, context, config, self._command)

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        return []

    def check(self, files: list[Path]) -> list[Diagnostic]:
        if self._command is None:
            return []
        completed = run([*self._command, "--noEmit"], cwd=self._cwd)
        return diagnostics_from_process(self.id, completed)


def typescript_toolchain_adapters() -> tuple[PrettierAdapter | EslintAdapter | TscAdapter, ...]:
    return PrettierAdapter(), EslintAdapter(), TscAdapter()


__all__ = (
    "EslintAdapter",
    "PrettierAdapter",
    "TscAdapter",
    "typescript_toolchain_adapters",
)
