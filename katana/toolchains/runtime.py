from __future__ import annotations

from pathlib import Path

from katana.models import SourceSplitMove

from .base import Diagnostic, SkippedTool, ToolchainAdapter, ToolchainContext
from .registry import toolchain_adapters


def run_toolchain_after_split(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    typecheck: bool = False,
) -> dict[str, object]:
    files = [source, *(move.target for move in moves)]
    context = _toolchain_context(source)
    adapters, skipped = _resolve_adapters(context, files, typecheck=typecheck)
    diagnostics: list[Diagnostic] = []
    formatter_ids: list[str] = []
    linter_ids: list[str] = []
    checker_ids: list[str] = []

    for adapter, adapter_files in adapters:
        if adapter.kind == "formatter":
            formatter_ids.append(adapter.id)
            diagnostics.extend(adapter.fix(adapter_files))
    for adapter, adapter_files in adapters:
        if adapter.kind == "linter":
            linter_ids.append(adapter.id)
            diagnostics.extend(adapter.fix(adapter_files))
    for adapter, adapter_files in adapters:
        if adapter.kind == "checker":
            checker_ids.append(adapter.id)
        diagnostics.extend(adapter.check(adapter_files))

    return {
        "adapters": [adapter.id for adapter, _files in adapters],
        "formatters": formatter_ids,
        "linters": linter_ids,
        "checkers": checker_ids,
        "diagnostics": [diagnostic.to_payload() for diagnostic in diagnostics],
        "skipped": [item.to_payload() for item in skipped],
    }


def skipped_toolchain_payload(reason: str) -> dict[str, object]:
    return {
        "adapters": [],
        "formatters": [],
        "linters": [],
        "checkers": [],
        "diagnostics": [],
        "skipped": [{"tool": "toolchain", "reason": reason}],
    }


def _resolve_adapters(
    context: ToolchainContext,
    files: list[Path],
    *,
    typecheck: bool,
) -> tuple[list[tuple[ToolchainAdapter, list[Path]]], list[SkippedTool]]:
    adapters: list[tuple[ToolchainAdapter, list[Path]]] = []
    skipped: list[SkippedTool] = []
    for adapter in toolchain_adapters():
        if not adapter.default_enabled and not typecheck:
            continue
        adapter_files = [path for path in files if path.suffix in adapter.extensions]
        if not adapter_files:
            continue
        skip = adapter.detect(context)
        if skip is None:
            adapters.append((adapter, adapter_files))
        else:
            skipped.append(skip)
    return adapters, skipped


def _toolchain_context(source: Path) -> ToolchainContext:
    source_dir = source.resolve().parent
    repo_root = _repo_root(source_dir)
    ancestors = []
    for candidate in (source_dir, *source_dir.parents):
        ancestors.append(candidate)
        if candidate == repo_root:
            break
    return ToolchainContext(source_dir=source_dir, repo_root=repo_root, ancestors=tuple(ancestors))


def _repo_root(source_dir: Path) -> Path:
    for candidate in (source_dir, *source_dir.parents):
        if (candidate / ".git").exists():
            return candidate
    return Path(source_dir.anchor) if source_dir.anchor else source_dir.parents[-1]
