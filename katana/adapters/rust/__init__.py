from __future__ import annotations

from pathlib import Path
from typing import Any

from katana.adapters._builtin import BundledLanguageAdapter
from katana.ir import AdapterCapabilities, MoveConstraints, build_document_ir
from katana.models import SourceSplitMove, SourceSplitPlan, SourceSymbol

from .apply import apply_rust_split, plan_rust_split
from .parser import RustItem, parse_rust_items


class RustAdapter(BundledLanguageAdapter):
    id = "tree-sitter-rust"
    extensions = (".rs",)
    profiles = ("rust",)

    def language_for(self, path: Path) -> str:
        return "rust"

    def capabilities(self, path: Path) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id=self.id,
            language="rust",
            parser="tree_sitter_rust",
            strategy="tree_sitter_items",
            precision="syntax_top_level_and_impl_items",
            safe_apply=True,
            hierarchy=True,
            comments=True,
            local_bindings=False,
            module_rewrite=True,
            formatting=True,
            validation=True,
            verifications=("cargo_fmt", "cargo_check"),
            limitations=("moves preserve lexical scope through Rust include! fragments",),
        )

    def analyze(self, path: Path):  # type: ignore[no-untyped-def]
        items = parse_rust_items(path)
        symbols = [item.symbol for item in items]
        return build_document_ir(
            path,
            language="rust",
            adapter_id=self.id,
            capabilities=self.capabilities(path),
            symbols=symbols,
            constraints=self.constraints(path, symbols),
            source_spans=[item.span for item in items],
        )

    def outline(self, path: Path) -> list[SourceSymbol]:
        return [item.symbol for item in parse_rust_items(path)]

    def constraints(self, path: Path, symbols: list[SourceSymbol]) -> dict[str, MoveConstraints]:
        return {
            symbol.name: MoveConstraints(movability="free", order_policy="preserve")
            for symbol in symbols
        }

    def build_plan(
        self,
        source: Path,
        symbols: list[SourceSymbol],
        *,
        code_lines: int,
        max_lines: int,
        headroom_lines: int,
        target_prefix: str | None,
    ) -> SourceSplitPlan:
        items = parse_rust_items(source)
        if code_lines <= max_lines or not items:
            return SourceSplitPlan(source, (), (), ())
        target_lines = max(max_lines - headroom_lines, 1)
        runs = _context_runs(items)
        chunks = _chunks(runs, target_lines)
        remaining = code_lines
        selected: list[list[RustItem]] = []
        for chunk in sorted(chunks, key=lambda part: -_item_lines(part)):
            if remaining <= target_lines:
                break
            selected.append(chunk)
            remaining -= _item_lines(chunk)
        selected.sort(key=lambda part: part[0].ordinal)
        prefix = target_prefix or source.stem
        moves = tuple(
            SourceSplitMove(
                target=source.with_name(f"{prefix}_part{index}.rs"),
                symbols=tuple(item.symbol.name for item in chunk),
            )
            for index, chunk in enumerate(selected, start=1)
        )
        plan = plan_rust_split(source, moves)
        warnings = list(plan.warnings)
        if remaining > max_lines:
            warnings.append(
                f"suggested Rust include fragments leave source near {remaining} code lines"
            )
        return SourceSplitPlan(source, moves, plan.moved_symbols, tuple(warnings))

    def safe_move_groups(self, source: Path, symbols: list[SourceSymbol]) -> dict[str, Any]:
        items = parse_rust_items(source)
        return {
            "composition": (
                "compose targets from contiguous symbols inside one module or impl context; "
                "include! preserves the original lexical scope and item order"
            ),
            "groups": [
                {
                    "seed": run[0].symbol.name,
                    "kind": run[0].symbol.kind,
                    "visibility": "lexical",
                    "code_lines": _item_lines(run),
                    "symbols": [item.symbol.name for item in run],
                    "tags": [],
                }
                for run in _context_runs(items)
            ],
            "pinned": [],
        }

    def plan_split(self, source: Path, moves: tuple[SourceSplitMove, ...]) -> SourceSplitPlan:
        return plan_rust_split(source, moves)

    def apply_split(
        self,
        source: Path,
        moves: tuple[SourceSplitMove, ...],
        *,
        keep_compat_imports: bool,
        force: bool,
        package_relative: bool,
    ) -> SourceSplitPlan:
        return apply_rust_split(source, moves, force=force)

    def split_reason(self, capabilities: AdapterCapabilities) -> str:
        return "Rust uses Tree-sitter item spans and lexical-scope-preserving include! fragments"


def _context_runs(items: list[RustItem]) -> list[list[RustItem]]:
    runs: list[list[RustItem]] = []
    for item in items:
        if not runs or runs[-1][-1].context != item.context:
            runs.append([item])
        else:
            runs[-1].append(item)
    return runs


def _chunks(runs: list[list[RustItem]], max_lines: int) -> list[list[RustItem]]:
    chunks: list[list[RustItem]] = []
    for run in runs:
        chunk: list[RustItem] = []
        lines = 0
        for item in run:
            if chunk and lines + item.symbol.code_lines > max_lines:
                chunks.append(chunk)
                chunk = []
                lines = 0
            chunk.append(item)
            lines += item.symbol.code_lines
        if chunk:
            chunks.append(chunk)
    return chunks


def _item_lines(items: list[RustItem]) -> int:
    return sum(item.symbol.code_lines for item in items)


__all__ = ("RustAdapter",)
