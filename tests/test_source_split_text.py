from katana import assess_source_split


def test_source_split_safe_moves_menu_covers_text_languages(tmp_path) -> None:
    source = tmp_path / "widget.tsx"
    source.write_text(
        "export default function Page() {\n"
        "  return Widget()\n"
        "}\n"
        "\n"
        "export const Widget = () => {\n"
        "  return formatLabel('w')\n"
        "}\n"
        "\n"
        "function formatLabel(value: string) {\n"
        "  return value.trim()\n"
        "}\n"
    )

    payload = assess_source_split(source, max_lines=4)
    safe_moves = payload["agent"]["safe_moves"]
    seeds = {group["seed"]: group for group in safe_moves["groups"]}
    assert "Page" not in seeds
    assert safe_moves["pinned"][0]["blockers"] == ["Page"]
    assert seeds["formatLabel"]["visibility"] == "local"
    assert seeds["Widget"]["visibility"] == "exported"
    assert seeds["Widget"]["symbols"] == ["Widget", "formatLabel"]

    css = tmp_path / "style.css"
    css.write_text(".a {\n  color: red;\n}\n\n.b {\n  color: green;\n}\n")
    css_payload = assess_source_split(css, max_lines=3)
    assert "cascade" in css_payload["agent"]["safe_moves"]["composition"]
    assert css_payload["agent"]["safe_moves"]["groups"] == []

    dart = tmp_path / "screen.dart"
    dart.write_text(
        "void main() {\n"
        "  runApp(const HomeScreen());\n"
        "}\n"
        "\n"
        "class HomeScreen {\n"
        "  String build() {\n"
        "    return _title();\n"
        "  }\n"
        "}\n"
        "\n"
        "String _title() {\n"
        "  return 'home';\n"
        "}\n"
        "\n"
        "class AboutScreen {}\n"
    )
    dart_payload = assess_source_split(dart, max_lines=6)
    dart_safe_moves = dart_payload["agent"]["safe_moves"]
    dart_seeds = {group["seed"]: group for group in dart_safe_moves["groups"]}
    assert "main" not in dart_seeds
    assert dart_safe_moves["pinned"][0]["blockers"] == ["main"]
    assert dart_seeds["HomeScreen"]["symbols"] == ["HomeScreen", "_title"]

    dart_private_first = tmp_path / "private_first.dart"
    dart_private_first.write_text(
        "String _title() {\n"
        "  return 'home';\n"
        "}\n"
        "\n"
        "class HomeScreen {\n"
        "  String build() {\n"
        "    return _title();\n"
        "  }\n"
        "}\n"
    )
    private_payload = assess_source_split(dart_private_first, max_lines=3)
    private_groups = private_payload["agent"]["safe_moves"]["groups"]
    assert private_groups[0]["seed"] == "_title"
    assert private_groups[0]["visibility"] == "private"
    assert private_groups[0]["symbols"] == ["_title", "HomeScreen"]
