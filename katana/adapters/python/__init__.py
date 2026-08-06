from __future__ import annotations

from pathlib import Path
from typing import Any

from katana.adapters._builtin import BundledLanguageAdapter
from katana.ir import AdapterCapabilities, MoveConstraints
from katana.models import SourceSplitMove, SourceSplitPlan, SourceSymbol


class PythonAdapter(BundledLanguageAdapter):
    id = "python-stdlib"
    extensions = (".py",)
    profiles = ("core", "python", "all")

    def language_for(self, path: Path) -> str:
        return "python"

    def capabilities(self, path: Path) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id=self.id,
            language=self.language_for(path),
            parser="python_ast",
            strategy="stdlib_ast",
            precision="semantic_top_level",
            safe_apply=True,
            hierarchy=True,
            comments=True,
            local_bindings=True,
            module_rewrite=True,
            formatting=True,
            validation=True,
            verifications=("py_compile", "project_tests"),
        )

    def outline(self, path: Path) -> list[SourceSymbol]:
        from katana.outline import outline_python_module

        return outline_python_module(path)

    def constraints(self, path: Path, symbols: list[SourceSymbol]) -> dict[str, MoveConstraints]:
        constraints: dict[str, MoveConstraints] = {}
        for symbol in symbols:
            module_state = symbol.kind in {"assign", "annassign"} and not symbol.name.startswith(
                "_"
            )
            constraints[symbol.name] = MoveConstraints(
                movability="pinned" if module_state else "closure",
                pinned_reason="public module state" if module_state else None,
            )
        return constraints

    def code_line_count(self, text: str) -> int:
        return sum(
            1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
        )

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
        from katana.planning import _build_python_split_plan

        return _build_python_split_plan(
            source,
            symbols,
            code_lines=code_lines,
            max_lines=max_lines,
            headroom_lines=headroom_lines,
            target_prefix=target_prefix,
        )

    def safe_move_groups(self, source: Path, symbols: list[SourceSymbol]) -> dict[str, Any]:
        from katana.planning import _python_safe_move_payload

        return _python_safe_move_payload(symbols)

    def plan_split(self, source: Path, moves: tuple[SourceSplitMove, ...]) -> SourceSplitPlan:
        from katana.apply import plan_python_split

        return plan_python_split(source, moves)

    def apply_split(
        self,
        source: Path,
        moves: tuple[SourceSplitMove, ...],
        *,
        keep_compat_imports: bool,
        force: bool,
        package_relative: bool,
    ) -> SourceSplitPlan:
        from katana.apply import apply_python_split

        return apply_python_split(
            source,
            moves,
            keep_compat_imports=keep_compat_imports,
            force=force,
            package_relative=package_relative,
        )

    def split_reason(self, capabilities: AdapterCapabilities) -> str:
        return "Python uses stdlib AST and source-local dependency checks"

    def command_flags(self, source: Path) -> tuple[str, ...]:
        return ("--plain-imports",) if not (source.parent / "__init__.py").exists() else ()


__all__ = ("PythonAdapter",)
