from __future__ import annotations

from pathlib import Path

from katana.adapters._builtin import BundledLanguageAdapter
from katana.external import source_ast_bridge_capabilities, typescript_ast_available
from katana.ir import AdapterCapabilities, MoveConstraints
from katana.models import SourceSymbol


class TypeScriptAdapter(BundledLanguageAdapter):
    id = "node_typescript"
    extensions = (".ts", ".tsx", ".js", ".jsx")
    profiles = ("web", "admin", "next", "all")
    reference_aware = True
    legacy_adapter_payload = True

    def language_for(self, path: Path) -> str:
        return {
            ".ts": "typescript",
            ".tsx": "typescriptreact",
            ".js": "javascript",
            ".jsx": "javascriptreact",
        }[path.suffix]

    def capabilities(self, path: Path) -> AdapterCapabilities:
        bridge = source_ast_bridge_capabilities(path)
        available = typescript_ast_available(path)
        return AdapterCapabilities(
            adapter_id=self.id,
            language=self.language_for(path),
            parser="typescript_compiler_ast" if available else "typescript_structural",
            strategy=(
                "typescript_compiler_api_source_file"
                if available
                else "top_level_declarations_and_braces"
            ),
            precision="semantic_top_level" if available else "structural_top_level",
            safe_apply=False,
            hierarchy=available,
            comments=available,
            local_bindings=available,
            module_rewrite=True,
            formatting=True,
            validation=True,
            adapter_available=available,
            verifications=("typescript_check", "frontend_tests"),
            limitations=(
                ("does not rewrite project-wide imports",)
                if available
                else (
                    "TypeScript compiler API is not available",
                    "does not rewrite project-wide imports",
                )
            ),
            bridge=bridge,
        )

    def outline(self, path: Path) -> list[SourceSymbol]:
        from katana.outline import outline_typescript_module

        return outline_typescript_module(path)

    def constraints(self, path: Path, symbols: list[SourceSymbol]) -> dict[str, MoveConstraints]:
        return {
            symbol.name: MoveConstraints(
                movability=("pinned" if (symbol.meta or {}).get("default_export") else "closure"),
                pinned_reason=(
                    "default export" if (symbol.meta or {}).get("default_export") else None
                ),
            )
            for symbol in symbols
        }


__all__ = ("TypeScriptAdapter",)
