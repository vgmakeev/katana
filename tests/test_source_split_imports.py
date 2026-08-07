import json

import pytest

from katana import SourceSplitMove, apply_source_split, parse_move_plan


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
