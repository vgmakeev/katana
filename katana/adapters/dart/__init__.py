from __future__ import annotations

from pathlib import Path

from katana.adapters._builtin import BundledLanguageAdapter
from katana.external import dart_analyzer_ast_available, source_ast_bridge_capabilities
from katana.ir import AdapterCapabilities, MoveConstraints
from katana.models import SourceSymbol


class DartAdapter(BundledLanguageAdapter):
    id = "dart_analyzer"
    extensions = (".dart",)
    profiles = ("flutter", "all")
    reference_aware = True
    legacy_adapter_payload = True

    def language_for(self, path: Path) -> str:
        return "dart"

    def capabilities(self, path: Path) -> AdapterCapabilities:
        bridge = source_ast_bridge_capabilities(path)
        available = dart_analyzer_ast_available(path)
        return AdapterCapabilities(
            adapter_id=self.id,
            language="dart",
            parser="dart_analyzer_ast" if available else "dart_structural",
            strategy=(
                "package_analyzer_parse_file" if available else "top_level_declarations_and_braces"
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
            verifications=("dart_analyze", "flutter_tests"),
            limitations=(
                ("does not rewrite project-wide imports",)
                if available
                else (
                    "Dart analyzer package is not available to the project",
                    "does not rewrite project-wide imports",
                )
            ),
            bridge=bridge,
        )

    def outline(self, path: Path) -> list[SourceSymbol]:
        from katana.outline import outline_dart_file

        return outline_dart_file(path)

    def constraints(self, path: Path, symbols: list[SourceSymbol]) -> dict[str, MoveConstraints]:
        return {
            symbol.name: MoveConstraints(
                movability="pinned" if symbol.name == "main" else "closure",
                required_with=tuple(
                    consumer.name
                    for consumer in symbols
                    if symbol.name.startswith("_") and symbol.name in consumer.references
                ),
                pinned_reason="Dart entrypoint" if symbol.name == "main" else None,
            )
            for symbol in symbols
        }


__all__ = ("DartAdapter",)
