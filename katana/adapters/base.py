from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from katana.ir import AdapterCapabilities, DocumentIR, MoveConstraints, build_document_ir
from katana.models import SourceSplitMove, SourceSplitPlan, SourceSymbol


class LanguageAdapter(Protocol):
    """Complete language boundary used by the language-neutral Katana core."""

    id: str
    extensions: tuple[str, ...]
    profiles: tuple[str, ...]

    def language_for(self, path: Path) -> str: ...

    def capabilities(self, path: Path) -> AdapterCapabilities: ...

    def analyze(self, path: Path) -> DocumentIR: ...

    def code_line_count(self, text: str) -> int: ...

    def build_plan(
        self,
        source: Path,
        symbols: list[SourceSymbol],
        *,
        code_lines: int,
        max_lines: int,
        headroom_lines: int,
        target_prefix: str | None,
    ) -> SourceSplitPlan: ...

    def safe_move_groups(self, source: Path, symbols: list[SourceSymbol]) -> dict[str, Any]: ...

    def plan_split(self, source: Path, moves: tuple[SourceSplitMove, ...]) -> SourceSplitPlan: ...

    def apply_split(
        self,
        source: Path,
        moves: tuple[SourceSplitMove, ...],
        *,
        keep_compat_imports: bool,
        force: bool,
        package_relative: bool,
    ) -> SourceSplitPlan: ...

    def split_risk(self, warnings: tuple[str, ...], capabilities: AdapterCapabilities) -> str: ...

    def split_reason(self, capabilities: AdapterCapabilities) -> str: ...

    def command_flags(self, source: Path) -> tuple[str, ...]: ...


def legacy_capabilities_for(
    adapter: LanguageAdapter,
    path: Path,
    capabilities: AdapterCapabilities | None = None,
) -> dict[str, object]:
    resolved = capabilities or adapter.capabilities(path)
    legacy_builder = getattr(adapter, "legacy_capabilities", None)
    if callable(legacy_builder):
        payload = legacy_builder(path, resolved)
        if isinstance(payload, dict):
            return payload
    return resolved.to_legacy_payload()


class AnalysisLanguageAdapter:
    """Safe SDK base for adapters that only expose an agent-readable map.

    A new language can start with ``language_for``, ``capabilities`` and
    ``outline``. Rewrite stays disabled until the adapter deliberately
    implements the split methods.
    """

    id = ""
    extensions: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()

    def language_for(self, path: Path) -> str:
        raise NotImplementedError

    def capabilities(self, path: Path) -> AdapterCapabilities:
        raise NotImplementedError

    def outline(self, path: Path) -> list[SourceSymbol]:
        raise NotImplementedError

    def constraints(self, path: Path, symbols: list[SourceSymbol]) -> dict[str, MoveConstraints]:
        return {
            symbol.name: MoveConstraints(
                movability="pinned",
                pinned_reason="adapter provides analysis only",
            )
            for symbol in symbols
        }

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
        return sum(1 for line in text.splitlines() if line.strip())

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
        return SourceSplitPlan(
            source=source,
            moves=(),
            moved_symbols=(),
            warnings=(f"adapter {self.id!r} provides analysis but not rewrite",),
        )

    def safe_move_groups(self, source: Path, symbols: list[SourceSymbol]) -> dict[str, Any]:
        return {
            "composition": "analysis-only adapter; no executable moves are advertised",
            "groups": [],
            "pinned": [
                {"symbol": symbol.name, "reason": "adapter provides analysis only"}
                for symbol in symbols
            ],
        }

    def plan_split(self, source: Path, moves: tuple[SourceSplitMove, ...]) -> SourceSplitPlan:
        raise ValueError(f"Katana adapter {self.id!r} does not support rewrite")

    def apply_split(
        self,
        source: Path,
        moves: tuple[SourceSplitMove, ...],
        *,
        keep_compat_imports: bool,
        force: bool,
        package_relative: bool,
    ) -> SourceSplitPlan:
        raise ValueError(f"Katana adapter {self.id!r} does not support rewrite")

    def split_risk(self, warnings: tuple[str, ...], capabilities: AdapterCapabilities) -> str:
        return "review"

    def split_reason(self, capabilities: AdapterCapabilities) -> str:
        return f"{capabilities.parser} provides an architecture map but not rewrite"

    def command_flags(self, source: Path) -> tuple[str, ...]:
        return ()
