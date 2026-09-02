from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .base import Diagnostic, SkippedTool, ToolchainContext

DEFAULT_TOOL_TIMEOUT_SECONDS = 300.0


def tool_command(context: ToolchainContext, tool: str) -> list[str] | None:
    for ancestor in context.ancestors:
        local_bin = ancestor / "node_modules" / ".bin"
        resolved = shutil.which(tool, path=str(local_bin))
        if resolved:
            return [resolved]
    resolved = shutil.which(tool)
    return [resolved] if resolved else None


def nearest_config(context: ToolchainContext, names: tuple[str, ...]) -> Path | None:
    for ancestor in context.ancestors:
        for name in names:
            candidate = ancestor / name
            if candidate.exists():
                return candidate
    return None


def nearest_mypy_config(context: ToolchainContext, names: tuple[str, ...]) -> Path | None:
    for ancestor in context.ancestors:
        for name in names:
            candidate = ancestor / name
            if not candidate.exists():
                continue
            if name == "pyproject.toml" and "[tool.mypy" not in read_text(candidate):
                continue
            return candidate
    return None


def missing_binary(tool: str, context: ToolchainContext) -> SkippedTool:
    return SkippedTool(
        tool=tool,
        reason=f"no {tool} binary in node_modules/.bin up to repo root {context.repo_root}",
    )


def missing_config_or_binary(
    tool: str,
    context: ToolchainContext,
    config: Path | None,
    command: list[str] | None,
) -> SkippedTool:
    if config is not None and command is None:
        return SkippedTool(
            tool=tool,
            reason=(
                f"config found at {config} but no {tool} binary in node_modules/.bin "
                f"up to repo root {context.repo_root}"
            ),
        )
    if config is None and command is not None:
        return SkippedTool(
            tool=tool,
            reason=f"no {tool} config found up to repo root {context.repo_root}",
        )
    return SkippedTool(
        tool=tool,
        reason=f"no {tool} config or binary found up to repo root {context.repo_root}",
    )


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        encoding="utf-8",
        text=True,
        timeout=DEFAULT_TOOL_TIMEOUT_SECONDS,
    )


def file_args(files: list[Path]) -> list[str]:
    """Stringify file paths for a toolchain subprocess argv.

    Every toolchain adapter runs its subprocess with ``cwd=context.repo_root``
    (see e.g. EslintAdapter/RuffAdapter.detect), not the caller's own working
    directory. A relative Path here (exactly what a CLI invocation like
    ``katana apply pkg/sub/mod.py`` from a non-repo-root directory produces,
    since the split logic itself just resolves relative-to-cwd for file I/O
    and never re-anchors the Path object) would then be resolved by the
    *subprocess* against repo_root instead — silently linting/formatting the
    wrong file, or nothing at all if repo_root has no file by that relative
    name. Resolving to an absolute path here removes the ambiguity: it is
    correct regardless of which directory the tool subprocess's cwd is set
    to, or which directory katana itself was invoked from.
    """
    return [str(path.resolve()) for path in files]


def diagnostics_from_process(
    source: str, completed: subprocess.CompletedProcess[str]
) -> list[Diagnostic]:
    if completed.returncode == 0:
        return []
    return [process_diagnostic(source, completed.stderr or completed.stdout)]


def process_diagnostic(source: str, message: str) -> Diagnostic:
    return Diagnostic(
        source=source,
        severity="error",
        file="",
        line=None,
        column=None,
        code=None,
        message=message.strip(),
        fixable=False,
    )


def int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) else None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
