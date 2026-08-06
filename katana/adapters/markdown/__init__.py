from __future__ import annotations

from pathlib import Path

from katana.adapters._builtin import BundledLanguageAdapter
from katana.external import markdown_ast_available, markdown_document_metadata
from katana.ir import AdapterCapabilities, DocumentIR, MoveConstraints, build_document_ir
from katana.models import SourceSymbol


class MarkdownAdapter(BundledLanguageAdapter):
    id = "markdown-headings"
    extensions = (".md", ".mdx")
    profiles = ("core", "all")

    def language_for(self, path: Path) -> str:
        return "mdx" if path.suffix == ".mdx" else "markdown"

    def capabilities(self, path: Path) -> AdapterCapabilities:
        rich_ast = markdown_ast_available(path)
        return AdapterCapabilities(
            adapter_id=self.id,
            language=self.language_for(path),
            parser=(
                "tanstack_markdown_ast+katana_heading_spans" if rich_ast else "markdown_headings"
            ),
            strategy=(
                "tanstack_document_ast_with_exact_heading_outline"
                if rich_ast
                else "heading_outline"
            ),
            precision="document_sections_with_ast" if rich_ast else "document_sections",
            safe_apply=True,
            hierarchy=rich_ast,
            comments=rich_ast,
            adapter_available=True,
            verifications=("docs_render",),
            limitations=(
                (
                    "TanStack Markdown AST is enrichment, not a source-location API; "
                    "Katana heading spans remain authoritative"
                ),
                "does not validate links or MDX imports",
            ),
        )

    def legacy_capabilities(
        self,
        path: Path,
        capabilities: AdapterCapabilities | None = None,
    ) -> dict[str, object]:
        resolved = capabilities or self.capabilities(path)
        return resolved.to_legacy_payload(
            parser="markdown_headings",
            strategy="heading_outline",
            precision="document_sections",
            limitations=("does not validate links or MDX imports",),
        )

    def split_reason(self, capabilities: AdapterCapabilities) -> str:
        return "Markdown split is heading-based and deterministic"

    def analyze(self, path: Path) -> DocumentIR:
        symbols = self.outline(path)
        metadata = markdown_document_metadata(path)
        return build_document_ir(
            path,
            language=self.language_for(path),
            adapter_id=self.id,
            capabilities=self.capabilities(path),
            symbols=symbols,
            constraints=self.constraints(path, symbols),
            meta={"document_ast": metadata} if metadata is not None else None,
        )

    def outline(self, path: Path) -> list[SourceSymbol]:
        from katana.outline import outline_markdown_file

        return outline_markdown_file(path)

    def constraints(self, path: Path, symbols: list[SourceSymbol]) -> dict[str, MoveConstraints]:
        return {
            symbol.name: MoveConstraints(movability="free", order_policy="preserve")
            for symbol in symbols
        }

    def code_line_count(self, text: str) -> int:
        return sum(1 for line in text.splitlines() if line.strip())


__all__ = ("MarkdownAdapter",)
