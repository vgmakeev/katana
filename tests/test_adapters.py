from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from katana import (
    AdapterCapabilities,
    AnalysisLanguageAdapter,
    SourceSymbol,
    analyze_source_file,
    apply_source_split,
    assess_source_split,
    outline_source_file,
    resolve_source_split_extensions,
    source_parser_capabilities,
    source_split_extensions_for_profiles,
)
from katana.adapters import (
    CommandAdapterError,
    command_adapters_from_manifest,
    temporary_language_adapter,
    validate_document_ir,
)
from katana.cli import main


class _GoMapAdapter(AnalysisLanguageAdapter):
    id = "test-tree-sitter-go"
    extensions: tuple[str, ...] = (".go",)
    profiles: tuple[str, ...] = ("go", "all")

    def language_for(self, path: Path) -> str:
        return "go"

    def capabilities(self, path: Path) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id=self.id,
            language="go",
            parser="test_tree_sitter",
            strategy="query_capture",
            precision="syntax_top_level",
            safe_apply=False,
            hierarchy=True,
        )

    def outline(self, path: Path) -> list[SourceSymbol]:
        return [
            SourceSymbol(
                name="main",
                kind="function",
                signature="func main()",
                start_line=1,
                end_line=3,
                code_lines=3,
            )
        ]


def test_analysis_adapter_extends_profiles_but_fails_rewrite_closed(tmp_path: Path) -> None:
    source = tmp_path / "main.go"
    source.write_text('func main() {\n\tprintln("hi")\n}\n')
    adapter = _GoMapAdapter()

    with temporary_language_adapter(adapter):
        document = analyze_source_file(source)
        validate_document_ir(document)
        extensions = source_split_extensions_for_profiles(("go",))

        assert document.adapter_id == adapter.id
        assert document.symbols[0].constraints.movability == "pinned"
        assert ".go" in extensions
        with pytest.raises(ValueError, match="does not support rewrite"):
            apply_source_split(source, ())


def test_builtin_profile_extension_order_remains_v1_compatible() -> None:
    assert source_split_extensions_for_profiles(("admin",)) == (
        ".py",
        ".md",
        ".mdx",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".css",
    )
    assert source_split_extensions_for_profiles(("all",)) == (
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".dart",
        ".css",
        ".md",
        ".mdx",
    )


def test_v1_parser_payloads_remain_compatible(tmp_path: Path) -> None:
    python = tmp_path / "module.py"
    python.write_text("def value() -> int:\n    return 1\n")
    markdown = tmp_path / "guide.md"
    markdown.write_text("# Guide\nText\n\n## More\nMore text\n")
    typescript = tmp_path / "module.ts"
    typescript.write_text("export const value = 1\n")

    assert source_parser_capabilities(python) == {
        "language": "python",
        "parser": "python_ast",
        "strategy": "stdlib_ast",
        "precision": "semantic_top_level",
        "safe_apply": True,
        "verifications": ["py_compile", "project_tests"],
        "limitations": [],
    }
    assert source_parser_capabilities(markdown) == {
        "language": "markdown",
        "parser": "markdown_headings",
        "strategy": "heading_outline",
        "precision": "document_sections",
        "safe_apply": True,
        "verifications": ["docs_render"],
        "limitations": ["does not validate links or MDX imports"],
    }
    ts_payload = source_parser_capabilities(typescript)
    assert ts_payload["adapter"] == "node_typescript"
    assert "capabilities" not in ts_payload
    bridge = ts_payload["bridge"]
    assert isinstance(bridge, dict)
    assert "tanstack_markdown" not in bridge

    assessment = assess_source_split(markdown, max_lines=2)
    assert assessment["reason"] == "Markdown split is heading-based and deterministic"


def test_v1_outline_allows_duplicate_top_level_names(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("def value() -> int:\n    return 1\n\ndef value() -> int:\n    return 2\n")

    assert [symbol.name for symbol in outline_source_file(source)] == ["value", "value"]


def test_map_cli_returns_signatures_spans_and_loc_without_source_body(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        'def greeting(name: str) -> str:\n    return "секрет:" + name\n',
        encoding="utf-8",
    )

    main(["map", str(source), "--json"])
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert payload["protocol_version"] == 2
    assert payload["code_lines"] == 2
    assert payload["symbols"][0]["signature"] == "def greeting(name: str) -> str"
    assert payload["symbols"][0]["span"] == {
        "start_byte": 0,
        "end_byte": len(source.read_bytes()),
        "start_line": 1,
        "end_line": 2,
    }
    assert "секрет:" not in output


def test_document_ir_preserves_utf8_crlf_byte_coordinates(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source_bytes = "def café() -> str:\r\n    return 'кофе'\r\n".encode()
    source.write_bytes(source_bytes)

    document = analyze_source_file(source)
    validate_document_ir(document)

    assert document.content_hash == hashlib.sha256(source_bytes).hexdigest()
    assert document.symbols[0].span.start_byte == 0
    assert document.symbols[0].span.end_byte == len(source_bytes)


def test_document_ir_gives_duplicate_bindings_distinct_ids(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("def value():\n    return 1\n\ndef value():\n    return 2\n")

    document = analyze_source_file(source)

    assert [symbol.name for symbol in document.symbols] == ["value", "value"]
    assert len({symbol.id for symbol in document.symbols}) == 2


def test_document_ir_keeps_nested_symbol_summaries(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        "class Service:\n    def execute(self, value: int) -> int:\n        return value\n"
    )

    payload = analyze_source_file(source).to_payload()

    [service] = payload["symbols"]
    assert service["children"][0]["signature"] == "def execute(self, value: int) -> int"


def test_adapter_cli_runs_ir_conformance(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = tmp_path / "module.py"
    source.write_text("def value() -> int:\n    return 1\n")

    main(["adapters", str(source), "--check", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["selected"] == "python-stdlib"
    assert payload["conformance"]["ok"] is True
    assert payload["conformance"]["symbol_count"] == 1

    main(["adapters", "--json"])
    registry_payload = json.loads(capsys.readouterr().out)
    adapter_ids = {item["id"] for item in registry_payload["adapters"]}
    assert {"node_typescript", "dart_analyzer", "node_postcss"} <= adapter_ids
    toolchain_ids = {item["id"] for item in registry_payload["toolchains"]}
    assert {"ruff", "prettier", "eslint", "dart-format", "tsc", "mypy"} <= toolchain_ids
    assert registry_payload["toolchain_entry_point"] == "katana.toolchains"


def test_markdown_uses_exact_sections_and_optional_ast_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from katana.adapters import markdown

    source = tmp_path / "guide.md"
    source.write_text("# Intro\nText\n\n## Install\nRun it\n")
    monkeypatch.setattr(markdown, "markdown_ast_available", lambda path: True)
    monkeypatch.setattr(
        markdown,
        "markdown_document_metadata",
        lambda path: {"node_count": 7, "max_depth": 2, "node_types": {"heading": 2}},
    )

    document = analyze_source_file(source)

    assert document.capabilities.parser == "tanstack_markdown_ast+katana_heading_spans"
    assert document.meta == {
        "document_ast": {
            "node_count": 7,
            "max_depth": 2,
            "node_types": {"heading": 2},
        }
    }
    assert [symbol.name for symbol in document.symbols] == ["intro", "install"]
    validate_document_ir(document)


def test_project_command_adapter_maps_an_unknown_language_without_rewrite(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    adapter_script = tmp_path / "zig_adapter.py"
    adapter_script.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "source_size = len(open(request['path'], 'rb').read())\n"
        "print(json.dumps({\n"
        "    'protocol_version': 1,\n"
        "    'content_hash': request['content_hash'],\n"
        "    'capabilities': {\n"
        "        'parser': 'tree_sitter_zig',\n"
        "        'strategy': 'tree_sitter_query',\n"
        "        'precision': 'syntax_top_level',\n"
        "        'safe_apply': False,\n"
        "        'capabilities': {\n"
        "            'outline': True,\n"
        "            'source_locations': True,\n"
        "            'hierarchy': True,\n"
        "        },\n"
        "        'limitations': ['analysis-only fixture'],\n"
        "    },\n"
        "    'symbols': [{\n"
        "        'name': 'main',\n"
        "        'kind': 'function',\n"
        "        'signature': 'pub fn main() void',\n"
        "        'start_line': 1,\n"
        "        'end_line': 3,\n"
        "        'start_byte': 0,\n"
        "        'end_byte': source_size,\n"
        "        'code_lines': 3,\n"
        "        'references': [],\n"
        "        'tags': [],\n"
        "        'meta': {'operation': request['operation']},\n"
        "    }],\n"
        "    'meta': {'backend': 'tree-sitter'},\n"
        "}))\n"
    )
    config = tmp_path / ".katana"
    config.mkdir()
    (config / "adapters.json").write_text(
        json.dumps(
            {
                "protocol_version": 1,
                "adapters": [
                    {
                        "id": "fixture_tree_sitter_zig",
                        "language": "zig",
                        "extensions": [".zig"],
                        "profiles": ["zig", "all"],
                        "command": [sys.executable, "../zig_adapter.py"],
                    }
                ],
            }
        )
    )
    source = tmp_path / "main.zig"
    source.write_text('pub fn main() void {\n    @import("std");\n}\n')

    main(["map", str(source), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["adapter_id"] == "fixture_tree_sitter_zig"
    assert payload["symbols"][0]["signature"] == "pub fn main() void"
    assert payload["symbols"][0]["span"]["end_byte"] == len(source.read_bytes())
    assert payload["symbols"][0]["constraints"]["movability"] == "pinned"
    assert payload["meta"] == {"backend": "tree-sitter"}
    assert "@import" not in json.dumps(payload)
    assert ".zig" in resolve_source_split_extensions(("zig",), roots=[tmp_path])

    with pytest.raises(ValueError, match="does not support rewrite"):
        apply_source_split(source, ())


def test_command_adapter_manifest_schema_is_available(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["adapters", "--schema", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["properties"]["protocol_version"]["const"] == 1
    assert payload["properties"]["adapters"]["items"]["additionalProperties"] is False


def test_shipped_command_adapter_example(
    capsys: pytest.CaptureFixture[str],
) -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / "command-adapter"

    main(["map", str(example / "main.demo"), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["adapter_id"] == "example_demo_adapter"
    assert [symbol["name"] for symbol in payload["symbols"]] == [
        "introduction",
        "architecture",
    ]


def test_command_protocol_v1_rejects_rewrite_capability(tmp_path: Path) -> None:
    script = tmp_path / "unsafe_adapter.py"
    script.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "print(json.dumps({\n"
        "    'protocol_version': 1,\n"
        "    'content_hash': request['content_hash'],\n"
        "    'capabilities': {\n"
        "        'parser': 'unsafe',\n"
        "        'strategy': 'unsafe',\n"
        "        'precision': 'unknown',\n"
        "        'safe_apply': True,\n"
        "    },\n"
        "    'symbols': [],\n"
        "}))\n"
    )
    manifest = tmp_path / "adapters.json"
    manifest.write_text(
        json.dumps(
            {
                "protocol_version": 1,
                "adapters": [
                    {
                        "id": "unsafe_fixture",
                        "language": "unsafe",
                        "extensions": [".unsafe"],
                        "command": [sys.executable, str(script)],
                    }
                ],
            }
        )
    )
    source = tmp_path / "source.unsafe"
    source.write_text("unsafe\n")
    [adapter] = command_adapters_from_manifest(manifest)

    with pytest.raises(CommandAdapterError, match="cannot advertise safe_apply"):
        adapter.analyze(source)
