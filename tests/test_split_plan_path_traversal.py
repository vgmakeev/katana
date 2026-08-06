"""VVAH-3: katana/katana/apply.py:81 — запись за пределы дерева источника.

Инвариант: цель move из файла плана не может выйти за каталог источника
через `../` — ни для питоновых источников, ни для текстовых.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from katana.apply import apply_source_split, parse_move_plan


def _plan_with_escaping_target(source: Path, target: str) -> Path:
    plan = source.with_suffix(".katana.json")
    plan.write_text(
        json.dumps(
            {
                "version": 1,
                "source": str(source),
                "moves": [{"target": target, "symbols": ["moved"]}],
            }
        )
    )
    return plan


def test_text_split_plan_target_may_not_escape_source_tree(tmp_path: Path) -> None:
    outside = tmp_path / "outside.ts"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "mod.ts"
    source.write_text("export function moved() {\n  return 1\n}\n")
    plan = _plan_with_escaping_target(source, "../outside.ts")

    moves = parse_move_plan(source, [], plan)
    with pytest.raises(ValueError):
        apply_source_split(source, moves)
    assert not outside.exists()


def test_python_split_plan_target_may_not_escape_source_tree(tmp_path: Path) -> None:
    """Питоновая ветка закрыта побочно: `_relative_module_name` требует
    импортируемого имени модуля и валит apply до записи."""
    outside = tmp_path / "outside.py"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "mod.py"
    source.write_text("def moved():\n    return 1\n")
    plan = _plan_with_escaping_target(source, "../outside.py")

    moves = parse_move_plan(source, [], plan)
    with pytest.raises(ValueError):
        apply_source_split(source, moves)
    assert not outside.exists()
