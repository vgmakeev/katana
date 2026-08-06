import json
from pathlib import Path

import pytest
from test_source_split_planning import _assessment_plan
from test_source_split_text import (
    test_source_split_safe_moves_menu_covers_text_languages,
)

from katana import (
    SourceSplitMove,
    apply_source_split,
    assess_source_split,
    detect_source_split_profiles,
    large_source_files,
    outline_python_module,
    outline_source_file,
    parse_move_plan,
    project_source_split_plan,
    resolve_source_split_extensions,
    source_parser_capabilities,
    source_split_extensions_for_profiles,
)
from katana import discovery as source_split_discovery


def test_source_split_outline_reports_signatures_and_top_level_refs(tmp_path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "VALUE = 1\n"
        "\n"
        "def helper(value: int) -> int:\n"
        "    return value + VALUE\n"
        "\n"
        "def main(name: str, *, flag: bool = False) -> str:\n"
        "    return str(helper(1))\n"
    )

    symbols = outline_python_module(source)

    assert [symbol.name for symbol in symbols] == ["VALUE", "helper", "main"]
    assert symbols[1].signature == "def helper(value: int) -> int"
    assert symbols[2].signature == "def main(name: str, *, flag: bool) -> str"
    assert symbols[2].references == ("helper",)


def test_source_split_apply_moves_symbols_and_keeps_source_dependencies(tmp_path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "from __future__ import annotations\n"
        "\n"
        "def helper(value: int) -> int:\n"
        "    return value + 1\n"
        "\n"
        "def moved(value: int) -> int:\n"
        "    return helper(value)\n"
        "\n"
        "def remaining(value: int) -> int:\n"
        "    return moved(value)\n"
    )
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"moves": [{"target": "moved.py", "symbols": ["moved"]}]}))

    moves = parse_move_plan(source, [], plan)
    apply_source_split(source, moves, force=True)

    moved_text = (tmp_path / "moved.py").read_text()
    source_text = source.read_text()
    assert "from .sample import helper" in moved_text
    assert "def moved(value: int) -> int:" in moved_text
    assert "from .moved import moved" in source_text
    assert "def remaining(value: int) -> int:" in source_text


def test_source_split_apply_preserves_crlf_source_bytes(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    target = tmp_path / "moved.py"
    source.write_bytes(
        (
            "def moved() -> str:\r\n"
            "    return 'кофе'\r\n"
            "\r\n"
            "def remaining() -> str:\r\n"
            "    return moved()\r\n"
        ).encode()
    )

    apply_source_split(
        source,
        (SourceSplitMove(target=target, symbols=("moved",)),),
        force=True,
    )

    for output in (source.read_bytes(), target.read_bytes()):
        assert b"\r\n" in output
        assert b"\n" not in output.replace(b"\r\n", b"")
    assert "return 'кофе'\r\n".encode() in target.read_bytes()


def test_source_split_apply_rejects_python_plan_warnings_without_force(tmp_path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "def helper(value: int) -> int:\n"
        "    return value + 1\n"
        "\n"
        "def moved(value: int) -> int:\n"
        "    return helper(value)\n"
        "\n"
        "def remaining(value: int) -> int:\n"
        "    return moved(value)\n"
    )
    moves = parse_move_plan(source, ["moved.py:moved"], None)

    with pytest.raises(ValueError, match="Split plan has warnings"):
        apply_source_split(source, moves)

    assert not (tmp_path / "moved.py").exists()
    assert "def moved" in source.read_text()


def test_source_split_large_reports_files_over_budget(tmp_path) -> None:
    small = tmp_path / "small.py"
    large = tmp_path / "large.tsx"
    small.write_text("x = 1\n")
    large.write_text("\n".join(f"export const value{index} = {index}" for index in range(5)))

    payload = large_source_files([tmp_path], max_lines=3)

    assert payload == []

    payload = large_source_files(
        [tmp_path],
        max_lines=3,
        extensions=source_split_extensions_for_profiles(("admin",)),
    )

    assert [item["path"] for item in payload] == [str(large)]
    assert payload[0]["code_lines"] == 5


def test_source_split_outlines_and_moves_typescript_symbols(tmp_path) -> None:
    source = tmp_path / "component.tsx"
    source.write_text(
        'import { useMemo } from "react"\n'
        "\n"
        "export function Helper() {\n"
        "  return null\n"
        "}\n"
        "\n"
        "export const Widget = () => {\n"
        "  return Helper()\n"
        "}\n"
    )

    symbols = outline_source_file(source)
    assert [symbol.name for symbol in symbols] == ["Helper", "Widget"]
    assert symbols[1].references == ("Helper",)

    moves = parse_move_plan(source, ["widget.tsx:Widget"], None)
    apply_source_split(source, moves)

    widget_text = (tmp_path / "widget.tsx").read_text()
    assert "useMemo" not in widget_text  # unused imports are pruned
    assert "export const Widget" in (tmp_path / "widget.tsx").read_text()
    assert 'export { Widget } from "./widget"' in source.read_text()


def test_source_split_plan_targets_resolve_from_any_working_directory(tmp_path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    source = pkg / "mod.py"
    source.write_text("def helper() -> int:\n    return 1\n")
    plan = pkg / "mod.katana.json"
    plan.write_text(
        json.dumps(
            {
                "source": "repo/pkg/mod.py",
                "moves": [{"target": "repo/pkg/mod_part1.py", "symbols": ["helper"]}],
            }
        )
    )

    [move] = parse_move_plan(source, [], plan)

    assert move.target == pkg / "mod_part1.py"


def test_source_split_plan_validation_rejects_unknown_keys_and_versions(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text("def helper() -> int:\n    return 1\n")

    bad_top = tmp_path / "bad_top.katana.json"
    bad_top.write_text(
        json.dumps(
            {
                "version": 1,
                "source": str(source),
                "moves": [{"target": "mod_part1.py", "symbols": ["helper"]}],
                "surprise": True,
            }
        )
    )
    with pytest.raises(ValueError, match="Unknown split plan key: surprise"):
        parse_move_plan(source, [], bad_top)

    bad_move = tmp_path / "bad_move.katana.json"
    bad_move.write_text(
        json.dumps(
            {
                "version": 1,
                "moves": [{"target": "mod_part1.py", "symbols": ["helper"], "extra": True}],
            }
        )
    )
    with pytest.raises(ValueError, match=r"Unknown split plan moves\[0\] key: extra"):
        parse_move_plan(source, [], bad_move)

    bad_version = tmp_path / "bad_version.katana.json"
    bad_version.write_text(
        json.dumps(
            {
                "version": 2,
                "moves": [{"target": "mod_part1.py", "symbols": ["helper"]}],
            }
        )
    )
    with pytest.raises(ValueError, match="Unsupported split plan version 2; expected 1"):
        parse_move_plan(source, [], bad_version)


def test_source_split_apply_reads_default_and_legacy_plan_files(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text("def helper() -> int:\n    return 1\n")
    legacy = source.with_suffix(".source-split.json")
    legacy.write_text(json.dumps({"moves": [{"target": "mod_part1.py", "symbols": ["helper"]}]}))

    [move] = parse_move_plan(source, [], None)
    assert move.target == tmp_path / "mod_part1.py"

    current = source.with_suffix(".katana.json")
    current.write_text(json.dumps({"moves": [{"target": "mod_part2.py", "symbols": ["helper"]}]}))

    [move] = parse_move_plan(source, [], None)
    assert move.target == tmp_path / "mod_part2.py"


def test_source_split_apply_rejects_non_importable_targets_before_writing(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "def helper() -> int:\n    return 1\n\ndef api() -> int:\n    return helper()\n"
    )

    moves = parse_move_plan(source, ["bad-dir/mod_part1.py:helper"], None)
    with pytest.raises(ValueError, match="importable"):
        apply_source_split(source, moves)

    assert not (tmp_path / "bad-dir").exists()
    assert "def helper" in source.read_text()


def test_source_split_assess_pins_symbols_reaching_public_module_state(tmp_path) -> None:
    source = tmp_path / "pinned.py"
    source.write_text(
        "STATE: dict[str, int] = {}\n"
        "\n"
        "def read_state() -> int:\n"
        "    return len(STATE)\n"
        "\n"
        "def write_state(value: int) -> None:\n"
        '    STATE["value"] = value\n'
        '    STATE["other"] = value\n'
    )

    payload = assess_source_split(source, max_lines=3, write_plan=True)

    assert payload["status"] == "manual_review"
    assert payload["risk"] == "high"
    assert payload["agent"]["decision"] == "manual_review"
    assert payload["suggested_plan"]["moves"] == []
    assert any(
        "pinned by module-level state" in warning
        for warning in payload["suggested_plan"]["warnings"]
    )
    assert not source.with_suffix(".katana.json").exists()
    assert not any(
        command.startswith("katana apply") for command in payload["agent"]["verification_commands"]
    )
    assert payload["agent"]["safe_moves"]["groups"] == []
    assert "safe_moves" in payload["agent"]["next_step"]
    [hint] = payload["agent"]["safe_moves"]["pinned"]
    assert hint["blockers"] == ["STATE"]
    assert hint["symbol_count"] == 2
    assert set(hint["symbols"]) == {"read_state", "write_state"}


def test_source_split_apply_reports_unparseable_source(tmp_path) -> None:
    source = tmp_path / "broken.py"
    source.write_text("from .broken_part1 import (\n\ndef helper() -> int:\n    return 1\n")

    moves = parse_move_plan(source, ["part.py:helper"], None)
    with pytest.raises(ValueError, match="not parseable"):
        apply_source_split(source, moves)


def test_source_split_apply_prunes_unused_imports_in_target(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "import json\n"
        "import re\n"
        "\n"
        "def moved(value: str) -> bool:\n"
        "    return re.match('x', value) is not None\n"
        "\n"
        "def keep(value: dict) -> str:\n"
        "    return json.dumps(value)\n"
    )

    moves = parse_move_plan(source, ["mod_matchers.py:moved"], None)
    apply_source_split(source, moves)

    target_text = (tmp_path / "mod_matchers.py").read_text()
    assert "import re" in target_text
    assert "import json" not in target_text
    source_text = source.read_text()
    assert "import json" in source_text
    assert "import re" not in source_text


def test_source_split_inserts_dependency_import_in_sorted_position(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "from .alpha import helper_a\n"
        "from .zulu import helper_z\n"
        "\n"
        "def moved() -> int:\n"
        "    return 1\n"
        "\n"
        "def keep() -> int:\n"
        "    return moved() + helper_a() + helper_z()\n"
    )

    moves = parse_move_plan(source, ["mod_moved.py:moved"], None)
    apply_source_split(source, moves)

    source_text = source.read_text()
    assert (
        source_text.index(".alpha") < source_text.index(".mod_moved") < source_text.index(".zulu")
    )


def test_source_split_merges_into_existing_module(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "import re\n"
        "\n"
        "def moved(value: str) -> bool:\n"
        "    return re.match('x', value) is not None\n"
        "\n"
        "def keep(value: str) -> bool:\n"
        "    return moved(value)\n"
    )
    existing = tmp_path / "utils.py"
    existing.write_text(
        "import re\n"
        "\n"
        "def slugify(value: str) -> str:\n"
        "    return re.sub('[^a-z]', '-', value.lower())\n"
    )

    moves = parse_move_plan(source, ["utils.py:moved"], None)
    apply_source_split(source, moves)

    merged = existing.read_text()
    assert "def slugify" in merged
    assert "def moved" in merged
    assert merged.count("import re") == 1
    source_text = source.read_text()
    assert "def moved" not in source_text
    assert "from .utils import moved" in source_text


def test_source_split_merge_refuses_collisions_and_cycles(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    )
    collision = tmp_path / "collision.py"
    collision.write_text("def moved() -> int:\n    return 2\n")
    with pytest.raises(ValueError, match="already defines"):
        apply_source_split(source, parse_move_plan(source, ["collision.py:moved"], None))
    assert "def moved" in source.read_text()

    cyclic = tmp_path / "cyclic.py"
    cyclic.write_text("from .mod import keep\n\n\ndef uses_keep() -> int:\n    return keep()\n")
    with pytest.raises(ValueError, match="import cycle"):
        apply_source_split(source, parse_move_plan(source, ["cyclic.py:moved"], None))
    assert "def moved" in source.read_text()


def test_source_split_apply_is_atomic_when_later_move_collides(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text("def first() -> int:\n    return 1\n\ndef second() -> int:\n    return 2\n")
    collision = tmp_path / "collision.py"
    collision.write_text("def second() -> int:\n    return 20\n")
    first_target = tmp_path / "first_part.py"

    moves = parse_move_plan(
        source,
        ["first_part.py:first", "collision.py:second"],
        None,
    )
    original_source = source.read_text()
    original_collision = collision.read_text()
    with pytest.raises(ValueError, match="already defines"):
        apply_source_split(source, moves)

    assert source.read_text() == original_source
    assert collision.read_text() == original_collision
    assert not first_target.exists()


def test_source_split_apply_warns_about_textual_dotted_references(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    )
    consumer = tmp_path / "conftest.py"
    consumer.write_text('TARGET = "mod.moved"\n')

    plan = apply_source_split(source, parse_move_plan(source, ["mod_moved.py:moved"], None))

    assert any("mod.moved" in warning and "conftest.py" in warning for warning in plan.warnings)


def test_source_split_dynamic_reference_scan_caps_files_and_skips_large_files(
    monkeypatch,
    tmp_path,
) -> None:
    from katana import impact

    source = tmp_path / "mod.py"
    source.write_text("def moved() -> int:\n    return 1\n")
    target = tmp_path / "mod_moved.py"
    target.write_text("def moved() -> int:\n    return 1\n")
    large = tmp_path / "large.py"
    large.write_text("# mod.moved\n" * 20)
    monkeypatch.setattr(impact, "_SCAN_SIZE_CAP", 10)

    assert impact.dynamic_reference_warnings(source, (SourceSplitMove(target, ("moved",)),)) == []

    monkeypatch.setattr(impact, "_SCAN_SIZE_CAP", 1_000_000)
    monkeypatch.setattr(impact, "_SCAN_FILE_CAP", 1)
    first = tmp_path / "a_first.py"
    first.write_text("TEXT = 'mod.other'\n")
    second = tmp_path / "z_second.py"
    second.write_text("TEXT = 'mod.moved'\n")

    warnings = impact.dynamic_reference_warnings(source, (SourceSplitMove(target, ("moved",)),))

    assert any("textual reference scan stopped after 1 files" in warning for warning in warnings)


def test_source_split_prune_is_scope_aware_for_shadowed_names(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "from time import monotonic\n"
        "\n"
        "def moved(monotonic: float) -> float:\n"
        "    return monotonic + 1\n"
        "\n"
        "def keep() -> float:\n"
        "    return monotonic()\n"
    )

    moves = parse_move_plan(source, ["mod_helpers.py:moved"], None)
    apply_source_split(source, moves)

    assert "from time import monotonic" not in (tmp_path / "mod_helpers.py").read_text()
    assert "from time import monotonic" in source.read_text()


def test_source_split_detects_connected_profiles(tmp_path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {
                    "@mini/admin": "^0.3.0",
                    "next": "^16.0.0",
                },
            }
        )
    )
    (tmp_path / "pubspec.yaml").write_text("dependencies:\n  flutter:\n    sdk: flutter\n")

    profiles = detect_source_split_profiles([tmp_path])
    extensions = resolve_source_split_extensions(("auto",), roots=[tmp_path])

    assert profiles == ("next", "flutter", "admin")
    assert {".py", ".md", ".mdx", ".tsx", ".css", ".dart"}.issubset(set(extensions))


def test_source_split_project_plan_prioritizes_and_writes_plans(tmp_path) -> None:
    source = tmp_path / "big.py"
    source.write_text(
        "\n\n".join(
            f"def fn{index}() -> int:\n"
            f"    value = {index}\n"
            f"    value += {index}\n"
            f"    value += {index}\n"
            f"    value += {index}\n"
            f"    value += {index}\n"
            f"    value += {index}\n"
            f"    value += {index}\n"
            "    return value\n"
            for index in range(4)
        )
    )

    payload = project_source_split_plan(
        [tmp_path],
        max_lines=10,
        profiles=("core",),
        write_plans=True,
    )

    assert payload["summary"]["oversized_files"] == 1
    assert payload["summary"]["by_decision"]["apply_suggested_plan"] == 1
    [assessment] = payload["assessments"]
    assert assessment["suggested_plan"]["moves"][0]["moved_code_lines"]
    assert assessment["plan_file"] == str(source.with_suffix(".katana.json"))
    assert source.with_suffix(".katana.json").exists()


def test_source_split_assess_outlines_once(monkeypatch, tmp_path) -> None:
    source = tmp_path / "large.py"
    source.write_text(
        "\n\n".join(
            f"def fn{index}() -> int:\n"
            f"    value = {index}\n"
            f"    value += {index}\n"
            f"    return value\n"
            for index in range(4)
        )
    )
    calls = 0
    original = source_split_discovery.outline_source_file

    def counted(path: Path):
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(source_split_discovery, "outline_source_file", counted)

    payload = source_split_discovery.assess_source_split(source, max_lines=6)

    assert payload["status"] == "split_recommended"
    assert calls == 1


def test_source_split_outlines_next_and_admin_metadata(tmp_path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    source = app_dir / "page.tsx"
    source.write_text(
        '"use client"\n'
        'import { Button } from "@/components/ui/button"\n'
        'import Link from "next/link"\n'
        "\n"
        "export default function Page() {\n"
        "  const handleSubmit = () => {\n"
        "    return true\n"
        "  }\n"
        '  return <Button className="font-medium"><Link href="/">Home</Link></Button>\n'
        "}\n"
    )

    [symbol] = outline_source_file(source)
    parser = source_parser_capabilities(source)

    assert symbol.name == "Page"
    assert set(symbol.tags) >= {"react_component", "client_component", "next", "tailwind", "shadcn"}
    assert symbol.meta is not None
    assert symbol.meta["next_convention"] is True
    assert symbol.meta["shadcn_imports"] == ["button"]
    raw_children = symbol.to_payload()["children"]
    assert isinstance(raw_children, list)
    assert [child["name"] for child in raw_children if isinstance(child, dict)] == ["handleSubmit"]
    if parser["adapter_available"]:
        assert parser["parser"] == "typescript_compiler_ast"
        raw_tailwind = symbol.meta["tailwind"]
        assert isinstance(raw_tailwind, dict)
        assert raw_tailwind["classes"] == ["font-medium"]


def test_source_split_outlines_and_moves_dart_symbols(tmp_path) -> None:
    source = tmp_path / "screen.dart"
    source.write_text(
        "import 'package:flutter/widgets.dart';\n"
        "\n"
        "class ProfileScreen extends StatelessWidget {\n"
        "  const ProfileScreen({super.key});\n"
        "\n"
        "  @override\n"
        "  Widget build(BuildContext context) {\n"
        "    return const Text('Profile');\n"
        "  }\n"
        "}\n"
        "\n"
        "void main() {\n"
        "  runApp(const ProfileScreen());\n"
        "}\n"
    )

    symbols = outline_source_file(source)
    assert [symbol.name for symbol in symbols] == ["ProfileScreen", "main"]
    assert symbols[0].tags == ("flutter_widget",)
    children = symbols[0].to_payload()["children"]
    assert "build" in [child["name"] for child in children]
    assert "flutter_build" in next(child for child in children if child["name"] == "build")["tags"]

    moves = parse_move_plan(source, ["profile_screen.dart:ProfileScreen"], None)
    apply_source_split(source, moves)

    moved_text = (tmp_path / "profile_screen.dart").read_text()
    source_text = source.read_text()
    assert "import 'package:flutter/widgets.dart';" in moved_text
    assert "class ProfileScreen extends StatelessWidget" in moved_text
    assert "import 'profile_screen.dart' show ProfileScreen;" in source_text
    assert "export 'profile_screen.dart' show ProfileScreen;" in source_text


def test_source_split_merges_into_existing_typescript_and_dart_targets(tmp_path) -> None:
    ts_source = tmp_path / "component.ts"
    ts_source.write_text(
        "export function Helper() {\n"
        "  return 1\n"
        "}\n"
        "\n"
        "export function Widget() {\n"
        "  return Helper()\n"
        "}\n"
    )
    ts_target = tmp_path / "widgets.ts"
    ts_target.write_text("export function Existing() {\n  return 0\n}\n")

    apply_source_split(ts_source, parse_move_plan(ts_source, ["widgets.ts:Helper"], None))

    ts_text = ts_target.read_text()
    assert "export function Existing" in ts_text
    assert "export function Helper" in ts_text
    assert 'import { Helper } from "./widgets"' in ts_source.read_text()

    dart_source = tmp_path / "screen.dart"
    dart_source.write_text(
        "import 'package:flutter/widgets.dart';\n"
        "\n"
        "class ProfileScreen extends StatelessWidget {\n"
        "  const ProfileScreen({super.key});\n"
        "}\n"
        "\n"
        "void main() {\n"
        "  runApp(const ProfileScreen());\n"
        "}\n"
    )
    dart_target = tmp_path / "screens.dart"
    dart_target.write_text("class ExistingScreen {}\n")

    apply_source_split(
        dart_source,
        parse_move_plan(dart_source, ["screens.dart:ProfileScreen"], None),
    )

    dart_text = dart_target.read_text()
    assert "class ExistingScreen" in dart_text
    assert "class ProfileScreen extends StatelessWidget" in dart_text
    assert "import 'package:flutter/widgets.dart';" in dart_text


def test_source_split_text_merge_refuses_cycles(tmp_path) -> None:
    source = tmp_path / "component.ts"
    source.write_text(
        "export function Helper() {\n"
        "  return 1\n"
        "}\n"
        "\n"
        "export function Widget() {\n"
        "  return Helper()\n"
        "}\n"
    )
    target = tmp_path / "existing.ts"
    target.write_text(
        'import { Widget } from "./component"\n'
        "\n"
        "export function Existing() {\n"
        "  return Widget()\n"
        "}\n"
    )

    with pytest.raises(ValueError, match="import cycle"):
        apply_source_split(source, parse_move_plan(source, ["existing.ts:Helper"], None))

    assert "export function Helper" in source.read_text()


def test_source_split_typescript_explicit_cross_part_imports(tmp_path) -> None:
    source = tmp_path / "logic.ts"
    source.write_text(
        "function first() {\n  return 1\n}\n\nfunction second() {\n  return first()\n}\n"
    )

    apply_source_split(
        source,
        parse_move_plan(source, ["logic_part1.ts:first", "logic_part2.ts:second"], None),
    )

    assert 'import { first } from "./logic_part1"' in (tmp_path / "logic_part2.ts").read_text()


def test_source_split_outlines_css_and_markdown_sections(tmp_path) -> None:
    css = tmp_path / "style.css"
    css.write_text(
        '@import "base.css";\n\n.button {\n  color: red;\n}\n\n@media print {\n  .button { color: black; }\n}\n'
    )
    markdown = tmp_path / "README.md"
    markdown.write_text("# Intro\nText\n\n## Install\nRun it\n")

    css_symbols = outline_source_file(css)
    assert [symbol.name for symbol in css_symbols] == ["button", "media_print"]
    css_parser = source_parser_capabilities(css)
    if css_parser["adapter_available"]:
        assert css_parser["parser"] == "postcss_ast"
        assert css_symbols[1].kind == "CssAtRule"
    assert [symbol.name for symbol in outline_source_file(markdown)] == ["intro", "install"]

    moves = parse_move_plan(markdown, ["install.md:install"], None)
    apply_source_split(markdown, moves)
    assert "## Install" not in markdown.read_text()
    assert "## Install" in (tmp_path / "install.md").read_text()

    css_moves = parse_move_plan(css, ["print.css:media_print"], None)
    css_plan = apply_source_split(css, css_moves)
    assert '@import "print.css";' in css.read_text()
    assert "@media print" not in css.read_text()
    assert "@media print" in (tmp_path / "print.css").read_text()
    assert any("cascade order" in warning for warning in css_plan.warnings)


def test_source_split_suggests_moves_for_large_text_file(tmp_path) -> None:
    source = tmp_path / "large.ts"
    source.write_text(
        "\n\n".join(f"export function fn{index}() {{\n  return {index}\n}}" for index in range(8))
    )

    plan = _assessment_plan(source, max_lines=10)

    assert plan.moves
    assert plan.moves[0].target.suffix == ".ts"


def test_source_split_typescript_prefers_local_helpers_and_pins_default_export(tmp_path) -> None:
    source = tmp_path / "widget.tsx"
    source.write_text(
        'import { useMemo } from "react"\n'
        "\n"
        "export default function Page() {\n"
        "  return Widget()\n"
        "}\n"
        "\n"
        "export const Widget = () => {\n"
        "  return formatLabel('w')\n"
        "}\n"
        "\n"
        "function formatLabel(value: string) {\n"
        "  return trim(value)\n"
        "}\n"
        "\n"
        "function trim(value: string) {\n"
        "  return value.trim()\n"
        "}\n"
    )

    plan = _assessment_plan(source, max_lines=9)

    assert plan.warnings == ()
    assert "Page" not in plan.moved_symbols
    assert "formatLabel" in plan.moved_symbols
    assert "trim" in plan.moved_symbols

    apply_source_split(source, plan.moves)
    part_text = (tmp_path / "widget_part1.tsx").read_text()
    source_text = source.read_text()
    assert "export function formatLabel" in part_text
    assert 'import { formatLabel } from "./widget_part1"' in source_text
    assert 'export { formatLabel, trim } from "./widget_part1"' in source_text
    assert "export default function Page" in source_text


def test_source_split_css_prefix_moves_preserve_cascade_without_warning(tmp_path) -> None:
    css = tmp_path / "style.css"
    css.write_text(
        ".a {\n  color: red;\n}\n\n"
        ".b {\n  color: green;\n}\n\n"
        ".c {\n  color: blue;\n}\n\n"
        ".d {\n  color: black;\n}\n"
    )

    plan = _assessment_plan(css, max_lines=6)

    assert plan.moves
    outline_names = [symbol.name for symbol in outline_source_file(css)]
    moved_sequence = [name for move in plan.moves for name in move.symbols]
    assert moved_sequence == outline_names[: len(moved_sequence)]
    assert not any("cascade" in warning for warning in plan.warnings)

    tail_move = parse_move_plan(css, [f"tail.css:{outline_names[-1]}"], None)
    from katana import plan_source_split

    tail_plan = plan_source_split(css, tail_move)
    assert any("cascade" in warning for warning in tail_plan.warnings)


def test_source_split_markdown_moves_trailing_sections_in_order(tmp_path) -> None:
    markdown = tmp_path / "guide.md"
    markdown.write_text(
        "# Intro\nkeep\n\n"
        "## Usage\nline\nline\n\n"
        "## Reference\nline\nline\nline\n\n"
        "## Appendix\nline\nline\n"
    )

    plan = _assessment_plan(markdown, max_lines=6)

    assert plan.moves
    assert "intro" not in plan.moved_symbols
    outline_names = [symbol.name for symbol in outline_source_file(markdown)]
    moved_sequence = [name for move in plan.moves for name in move.symbols]
    assert moved_sequence == outline_names[len(outline_names) - len(moved_sequence) :]


def test_source_split_apply_moves_plan_file_symbols(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    )
    plan = tmp_path / "mod.katana.json"
    plan.write_text(json.dumps({"moves": [{"target": "mod_moved.py", "symbols": ["moved"]}]}))
    moves = parse_move_plan(source, [], plan)
    apply_source_split(source, moves)

    assert "def moved() -> int:" in (tmp_path / "mod_moved.py").read_text()
    assert "def keep() -> int:" in source.read_text()


def test_source_split_apply_plain_imports_for_standalone_python_files(tmp_path) -> None:
    source = tmp_path / "test_sample.py"
    source.write_text(
        "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    )
    plan = tmp_path / "test_sample.katana.json"
    plan.write_text(
        json.dumps({"moves": [{"target": "test_sample_moved.py", "symbols": ["moved"]}]})
    )

    apply_source_split(source, parse_move_plan(source, [], plan), package_relative=False)

    assert "from test_sample_moved import moved" in source.read_text()
    assert "from .test_sample_moved import moved" not in source.read_text()


def test_source_split_import_impact_reports_consumers_of_moved_symbols(tmp_path) -> None:
    from katana import import_impact_report

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    source = pkg / "mod.py"
    source.write_text(
        "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    )
    consumer = pkg / "consumer.py"
    consumer.write_text("from pkg.mod import keep, moved\n")
    relative_consumer = pkg / "relative_consumer.py"
    relative_consumer.write_text("from .mod import moved\n")

    moves = parse_move_plan(source, ["mod_moved.py:moved"], None)
    report = import_impact_report(source, moves)

    files = {entry["file"]: entry for entry in report}
    assert str(consumer) in files
    assert files[str(consumer)]["symbols"] == ["moved"]
    assert str(relative_consumer) in files
    assert files[str(relative_consumer)]["module"] == ".mod"
    new_homes = files[str(consumer)]["new_homes"]
    assert isinstance(new_homes, list)
    assert any("mod_moved.py" in home for home in new_homes)


def test_source_split_merge_resolves_imports_of_target_own_symbols(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "from .helpers import util\n"
        "\n"
        "def moved() -> int:\n"
        "    return util()\n"
        "\n"
        "def keep() -> int:\n"
        "    return moved()\n"
    )
    helpers = tmp_path / "helpers.py"
    helpers.write_text("def util() -> int:\n    return 1\n")

    moves = parse_move_plan(source, ["helpers.py:moved"], None)
    apply_source_split(source, moves)

    merged = helpers.read_text()
    assert "def moved" in merged
    assert "from .helpers import" not in merged


def test_source_split_creates_package_dirs_for_subpackage_targets(tmp_path) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    )

    moves = parse_move_plan(source, ["helpers/math/mod_moved.py:moved"], None)
    apply_source_split(source, moves)

    assert (tmp_path / "helpers" / "__init__.py").exists()
    assert (tmp_path / "helpers" / "math" / "__init__.py").exists()
    assert "def moved" in (tmp_path / "helpers" / "math" / "mod_moved.py").read_text()
    assert "from .helpers.math.mod_moved import moved" in source.read_text()


_RUFF_EXPLICIT_EXPORTS = (test_source_split_safe_moves_menu_covers_text_languages,)
