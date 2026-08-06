import json
from pathlib import Path

import pytest
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
    parse_move_plan,
    project_source_split_plan,
    resolve_source_split_extensions,
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


_RUFF_EXPLICIT_EXPORTS = (test_source_split_safe_moves_menu_covers_text_languages,)
