from __future__ import annotations

from pathlib import Path

from katana.adapters._builtin import BundledLanguageAdapter
from katana.external import css_ast_available, source_ast_bridge_capabilities
from katana.ir import AdapterCapabilities, MoveConstraints
from katana.models import SourceSymbol


class CssAdapter(BundledLanguageAdapter):
    id = "node_postcss"
    extensions = (".css",)
    profiles = ("web", "admin", "next", "all")
    legacy_adapter_payload = True

    def language_for(self, path: Path) -> str:
        return "css"

    def capabilities(self, path: Path) -> AdapterCapabilities:
        bridge = source_ast_bridge_capabilities(path)
        available = css_ast_available(path)
        return AdapterCapabilities(
            adapter_id=self.id,
            language="css",
            parser="postcss_ast" if available else "css_structural",
            strategy="postcss_stylesheet_ast" if available else "top_level_rules_and_braces",
            precision="css_ast_rules" if available else "structural_rules",
            safe_apply=False,
            hierarchy=available,
            comments=available,
            module_rewrite=True,
            formatting=True,
            validation=True,
            adapter_available=available,
            verifications=("frontend_build",),
            limitations=(
                ("does not resolve cascade or selector dependencies",)
                if available
                else (
                    "PostCSS is not available",
                    "does not resolve cascade or selector dependencies",
                )
            ),
            bridge=bridge,
        )

    def outline(self, path: Path) -> list[SourceSymbol]:
        from katana.outline import outline_css_file

        return outline_css_file(path)

    def constraints(self, path: Path, symbols: list[SourceSymbol]) -> dict[str, MoveConstraints]:
        return {
            symbol.name: MoveConstraints(movability="free", order_policy="prefix_only")
            for symbol in symbols
        }

    def code_line_count(self, text: str) -> int:
        return sum(
            1
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith(("/*", "*"))
        )


__all__ = ("CssAdapter",)
