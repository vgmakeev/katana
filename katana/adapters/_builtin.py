from __future__ import annotations

from pathlib import Path
from typing import Any

from katana.ir import AdapterCapabilities, DocumentIR, MoveConstraints, build_document_ir
from katana.models import SourceSplitMove, SourceSplitPlan, SourceSymbol


class BundledLanguageAdapter:
    """Shared mechanics for adapters distributed with Katana."""

    id = ""
    extensions: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()
    reference_aware = False
    legacy_adapter_payload = False

    def language_for(self, path: Path) -> str:
        raise NotImplementedError

    def capabilities(self, path: Path) -> AdapterCapabilities:
        raise NotImplementedError

    def legacy_capabilities(
        self,
        path: Path,
        capabilities: AdapterCapabilities | None = None,
    ) -> dict[str, object]:
        resolved = capabilities or self.capabilities(path)
        return resolved.to_legacy_payload(include_adapter=self.legacy_adapter_payload)

    def outline(self, path: Path) -> list[SourceSymbol]:
        raise NotImplementedError

    def constraints(self, path: Path, symbols: list[SourceSymbol]) -> dict[str, MoveConstraints]:
        return {symbol.name: MoveConstraints() for symbol in symbols}

    def analyze(self, path: Path) -> DocumentIR:
        symbols = self.outline(path)
        return build_document_ir(
            path,
            language=self.language_for(path),
            adapter_id=self.id,
            capabilities=self.capabilities(path),
            symbols=symbols,
            constraints=self.constraints(path, symbols),
        )

    def code_line_count(self, text: str) -> int:
        return sum(
            1
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(("//", "/*", "*"))
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
        from katana.planning import _build_text_split_plan

        return _build_text_split_plan(
            source,
            symbols,
            code_lines=code_lines,
            max_lines=max_lines,
            headroom_lines=headroom_lines,
            target_prefix=target_prefix,
            reference_aware=self.reference_aware,
        )

    def safe_move_groups(self, source: Path, symbols: list[SourceSymbol]) -> dict[str, Any]:
        from katana.planning import _text_safe_move_groups_payload

        return _text_safe_move_groups_payload(source, symbols, reference_aware=self.reference_aware)

    def plan_split(self, source: Path, moves: tuple[SourceSplitMove, ...]) -> SourceSplitPlan:
        from katana.apply import plan_text_split

        return plan_text_split(source, moves)

    def apply_split(
        self,
        source: Path,
        moves: tuple[SourceSplitMove, ...],
        *,
        keep_compat_imports: bool,
        force: bool,
        package_relative: bool,
    ) -> SourceSplitPlan:
        from katana.apply import apply_text_split

        return apply_text_split(
            source,
            moves,
            keep_compat_imports=keep_compat_imports,
            force=force,
        )

    def split_risk(self, warnings: tuple[str, ...], capabilities: AdapterCapabilities) -> str:
        if warnings:
            return "review"
        return "low" if capabilities.safe_apply else "medium"

    def split_reason(self, capabilities: AdapterCapabilities) -> str:
        if capabilities.safe_apply:
            return f"{capabilities.parser} provides a deterministic language adapter"
        verifications = ", ".join(capabilities.verifications)
        return (
            f"{capabilities.parser} is deterministic but structural; run "
            f"{verifications} after applying"
        )

    def command_flags(self, source: Path) -> tuple[str, ...]:
        return ()
