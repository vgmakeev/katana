import json
import py_compile
import shutil
from pathlib import Path

from katana import (
    SourceSplitMove,
    SourceSplitPlan,
    apply_source_split,
    assess_source_split,
    outline_source_file,
    parse_move_plan,
    split_plan_json_schema,
)


def _assessment_plan(source: Path, *, max_lines: int) -> SourceSplitPlan:
    payload = assess_source_split(source, max_lines=max_lines)
    raw_plan = payload["suggested_plan"]
    return SourceSplitPlan(
        source=Path(raw_plan["source"]),
        moves=tuple(
            SourceSplitMove(
                target=Path(move["target"]),
                symbols=tuple(move["symbols"]),
            )
            for move in raw_plan["moves"]
        ),
        moved_symbols=tuple(raw_plan["moved_symbols"]),
        warnings=tuple(raw_plan["warnings"]),
    )


def _symbol_body(path: Path, name: str) -> str:
    lines = path.read_text().splitlines(keepends=True)
    symbol = next(symbol for symbol in outline_source_file(path) if symbol.name == name)
    return "".join(lines[symbol.start_line - 1 : symbol.end_line])


def _normalized_body(path: Path, name: str) -> str:
    body = _symbol_body(path, name)
    if path.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs") and body.startswith("export "):
        return body.removeprefix("export ")
    return body


def _assert_round_trip_invariants(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
) -> None:
    original_symbols = outline_source_file(source)
    original_names = [symbol.name for symbol in original_symbols]
    original_bodies = {name: _normalized_body(source, name) for name in original_names}

    apply_source_split(source, moves)

    produced = (source, *(move.target for move in moves))
    seen: dict[str, int] = {}
    for path in produced:
        for symbol in outline_source_file(path):
            seen[symbol.name] = seen.get(symbol.name, 0) + 1
        if path.suffix == ".py":
            py_compile.compile(str(path), doraise=True)

    assert set(seen) == set(original_names)
    assert all(count == 1 for count in seen.values())
    assert {symbol.name for path in produced for symbol in outline_source_file(path)} == set(
        original_names
    )
    for move in moves:
        for name in move.symbols:
            assert _normalized_body(move.target, name) == original_bodies[name]


def test_source_split_assess_reports_parser_strategy_and_line_occupancy(tmp_path) -> None:
    source = tmp_path / "large.py"
    source.write_text(
        "VALUE = 1\n"
        "\n"
        "def api() -> int:\n"
        "    return _compute(VALUE)\n"
        "\n"
        "def _compute(value: int) -> int:\n"
        "    total = value\n"
        "    total += _step(total)\n"
        "    return total\n"
        "\n"
        "def _step(value: int) -> int:\n"
        "    return value + 1\n"
    )

    payload = assess_source_split(source, max_lines=6)

    assert payload["status"] == "split_recommended"
    assert payload["parser"]["parser"] == "python_ast"
    assert payload["line_summary"]["total_code_lines"] == 9
    assert payload["line_summary"]["largest_symbol"] == "_compute"
    assert payload["agent"]["decision"] == "apply_suggested_plan"
    assert payload["agent"]["confidence"] == "high"
    assert payload["agent"]["review_notes"]
    assert any("placeholders" in note for note in payload["agent"]["review_notes"])
    assert payload["agent"]["verification_commands"][0].startswith("katana apply")
    safe_moves = payload["agent"]["safe_moves"]
    assert "whole groups" in safe_moves["composition"]
    compute_group = next(group for group in safe_moves["groups"] if group["seed"] == "_compute")
    assert compute_group["visibility"] == "private"
    assert compute_group["symbols"] == ["_compute", "_step"]
    assert compute_group["in_suggested_plan"] is True
    assert not any("api" in group["symbols"] for group in safe_moves["groups"])
    assert payload["suggested_plan"]["warnings"] == []
    [move] = payload["suggested_plan"]["moves"]
    assert move["target"] == str(tmp_path / "large_part1.py")
    assert move["symbols"] == ["_compute", "_step"]
    assert move["estimated_source_code_lines_after_move"] == 3
    assert move["moved_code_lines"] == 6
    assert "connected symbol" in move["reason"]
    assert "api" not in payload["suggested_plan"]["moved_symbols"]
    compute_symbol = next(symbol for symbol in payload["symbols"] if symbol["name"] == "_compute")
    assert compute_symbol["span_lines"] == 4
    assert compute_symbol["code_lines"] == 4
    assert compute_symbol["code_lines_pct"] == 44.4

    plan_path = source.with_suffix(".katana.json")
    assert not plan_path.exists()
    payload = assess_source_split(source, max_lines=6, write_plan=True)
    assert payload["plan_file"] == str(plan_path)
    assert payload["agent"]["plan_file"] == str(plan_path)
    plan_payload = json.loads(plan_path.read_text())
    assert plan_payload["version"] == 1
    schema = split_plan_json_schema()
    assert set(plan_payload) <= set(schema["properties"])
    assert set(plan_payload["moves"][0]) <= set(
        schema["properties"]["moves"]["items"]["properties"]
    )
    assert plan_payload["moves"][0]["target"] == "large_part1.py"

    moves = parse_move_plan(source, [], plan_path)
    assert moves[0].target == tmp_path / "large_part1.py"
    apply_source_split(source, moves)
    assert (tmp_path / "large_part1.py").exists()
    assert "def api" in source.read_text()


def test_source_split_suggest_keeps_public_api_and_module_state_in_source(tmp_path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        "import re\n"
        "\n"
        '_PATTERN = re.compile("v")\n'
        "_registry: dict[str, str] = {}\n"
        "\n"
        "def register(code: str) -> None:\n"
        "    _registry[code] = code\n"
        "\n"
        "def cache(name: str) -> str:\n"
        "    value = _fingerprint(name)\n"
        "    value += _fingerprint(name)\n"
        "    return value\n"
        "\n"
        "def _fingerprint(name: str) -> str:\n"
        "    parts = _stable(name)\n"
        "    parts += _PATTERN.pattern\n"
        "    return parts\n"
        "\n"
        "def _stable(name: str) -> str:\n"
        "    return name.lower()\n"
    )

    plan = _assessment_plan(source, max_lines=8)

    assert plan.warnings == ()
    [move] = plan.moves
    assert move.symbols == ("_PATTERN", "_fingerprint", "_stable")
    assert "cache" not in plan.moved_symbols
    assert "register" not in plan.moved_symbols
    assert "_registry" not in plan.moved_symbols

    apply_source_split(source, plan.moves)
    part_text = (tmp_path / "sample_part1.py").read_text()
    source_text = source.read_text()
    assert "from .sample import" not in part_text
    assert '_PATTERN = re.compile("v")' in part_text
    assert "def _fingerprint" in part_text
    assert "from .sample_part1 import" in source_text
    assert "def cache" in source_text
    assert "_registry: dict[str, str] = {}" in source_text


def test_source_split_round_trip_invariants_for_representative_files(tmp_path) -> None:
    py_source = tmp_path / "sample.py"
    py_source.write_text(
        "VALUE = 1\n"
        "\n"
        "def alpha() -> int:\n"
        "    return VALUE\n"
        "\n"
        "def beta() -> int:\n"
        "    return alpha() + 1\n"
        "\n"
        "def gamma() -> int:\n"
        "    return 3\n"
    )
    _assert_round_trip_invariants(
        py_source,
        parse_move_plan(py_source, ["sample_part1.py:beta", "sample_part2.py:gamma"], None),
    )

    ts_source = tmp_path / "sample.ts"
    ts_source.write_text(
        "function first() {\n"
        "  return 1\n"
        "}\n"
        "\n"
        "function second() {\n"
        "  return first()\n"
        "}\n"
        "\n"
        "function third() {\n"
        "  return 3\n"
        "}\n"
    )
    _assert_round_trip_invariants(
        ts_source,
        parse_move_plan(ts_source, ["sample_one.ts:first", "sample_two.ts:second"], None),
    )

    real_source = tmp_path / "source_split_models.py"
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "katana" / "models.py",
        real_source,
    )
    _assert_round_trip_invariants(
        real_source,
        parse_move_plan(
            real_source,
            ["source_split_model_profiles.py:source_split_extensions_for_profiles"],
            None,
        ),
    )


def test_source_split_dart_moves_private_helpers_with_all_consumers(tmp_path) -> None:
    source = tmp_path / "screen.dart"
    source.write_text(
        "import 'package:flutter/widgets.dart';\n"
        "\n"
        "void main() {\n"
        "  runApp(const HomeScreen());\n"
        "}\n"
        "\n"
        "class HomeScreen extends StatelessWidget {\n"
        "  const HomeScreen({super.key});\n"
        "\n"
        "  @override\n"
        "  Widget build(BuildContext context) {\n"
        "    return _title('home');\n"
        "  }\n"
        "}\n"
        "\n"
        "Widget _title(String value) {\n"
        "  return Text(value);\n"
        "}\n"
        "\n"
        "class AboutScreen extends StatelessWidget {\n"
        "  const AboutScreen({super.key});\n"
        "\n"
        "  @override\n"
        "  Widget build(BuildContext context) {\n"
        "    return const Text('about');\n"
        "  }\n"
        "}\n"
    )

    plan = _assessment_plan(source, max_lines=18)

    assert "main" not in plan.moved_symbols
    moved = set(plan.moved_symbols)
    # _title may only move together with its consumer HomeScreen
    if "_title" in moved:
        assert "HomeScreen" in moved
        [move] = [move for move in plan.moves if "_title" in move.symbols]
        assert "HomeScreen" in move.symbols

    apply_source_split(source, plan.moves)
    source_text = source.read_text()
    assert "show" in source_text
    assert "_title" not in source_text.split("show", 1)[1].splitlines()[0]
