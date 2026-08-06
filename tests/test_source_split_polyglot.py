import pytest
from test_source_split_planning import _assessment_plan

from katana import (
    apply_source_split,
    outline_source_file,
    parse_move_plan,
    source_parser_capabilities,
)


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
