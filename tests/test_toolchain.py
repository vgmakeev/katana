from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from katana import Diagnostic, temporary_toolchain_adapter
from katana.models import SourceSplitMove
from katana.toolchain import run_toolchain_after_split


class _GoToolchainAdapter:
    id = "test-go-toolchain"
    kind = "formatter"
    extensions = (".go",)
    default_enabled = True

    def __init__(self) -> None:
        self.fixed: list[Path] = []

    def detect(self, context):
        return None

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        self.fixed.extend(files)
        return []

    def check(self, files: list[Path]) -> list[Diagnostic]:
        return []


def test_external_stack_can_register_a_toolchain_adapter(tmp_path: Path) -> None:
    source = tmp_path / "main.go"
    target = tmp_path / "service.go"
    source.write_text("package main\n")
    target.write_text("package main\n")
    adapter = _GoToolchainAdapter()

    with temporary_toolchain_adapter(adapter):
        payload = run_toolchain_after_split(source, (SourceSplitMove(target, ("Service",)),))

    assert payload["formatters"] == [adapter.id]
    assert adapter.fixed == [source, target]


def test_toolchain_runs_ruff_fix_format_and_check(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    log = tmp_path / "tool.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_tool(
        bin_dir / "ruff",
        log,
        json_when="--output-format=json",
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
    source = tmp_path / "mod.py"
    target = tmp_path / "mod_part.py"
    source.write_text("def keep() -> int:\n    return 1\n")
    target.write_text("def moved() -> int:\n    return 1\n")

    payload = run_toolchain_after_split(source, (SourceSplitMove(target, ("moved",)),))

    assert payload is not None
    assert payload["adapters"] == ["ruff"]
    assert payload["diagnostics"] == []
    log_text = log.read_text()
    assert "ruff check --fix" in log_text
    assert "ruff format" in log_text
    assert "ruff check --output-format=json" in log_text


def test_toolchain_runs_ruff_from_target_repo_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    log = tmp_path / "tool.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_tool(
        bin_dir / "ruff",
        log,
        json_when="--output-format=json",
        include_cwd=True,
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "target"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n'
    )
    source = tmp_path / "mod.py"
    target = tmp_path / "mod_part.py"
    source.write_text("def keep() -> int:\n    return 1\n")
    target.write_text("def moved() -> int:\n    return 1\n")

    run_toolchain_after_split(source, (SourceSplitMove(target, ("moved",)),))

    assert log.read_text().splitlines()
    assert all(line.startswith(f"{tmp_path} ::") for line in log.read_text().splitlines())


def test_real_ruff_keeps_output_compatible_with_target_python(tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "target"\nversion = "0.0.0"\nrequires-python = ">=3.11"\n'
    )
    source = tmp_path / "mod.py"
    target = tmp_path / "mod_part.py"
    multi_except = (
        "def parse() -> None:\n"
        "    try:\n"
        "        pass\n"
        "    except (ValueError, TypeError):\n"
        "        pass\n"
    )
    source.write_text(multi_except)
    target.write_text(multi_except)

    run_toolchain_after_split(source, (SourceSplitMove(target, ("parse",)),))

    ast.parse(source.read_text(), feature_version=(3, 11))
    ast.parse(target.read_text(), feature_version=(3, 11))


def test_toolchain_runs_prettier_then_eslint_with_configs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    log = tmp_path / "tool.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_tool(bin_dir / "prettier", log)
    _write_fake_tool(bin_dir / "eslint", log, json_when="--format json")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    (tmp_path / "package.json").write_text("{}\n")
    (tmp_path / "eslint.config.js").write_text("export default []\n")
    (tmp_path / ".prettierrc").write_text("{}\n")
    source = tmp_path / "view.ts"
    target = tmp_path / "view_part.ts"
    source.write_text("export const keep = 1\n")
    target.write_text("export const moved = 1\n")

    payload = run_toolchain_after_split(source, (SourceSplitMove(target, ("moved",)),))

    assert payload is not None
    assert payload["adapters"] == ["prettier", "eslint"]
    assert payload["diagnostics"] == []
    log_lines = log.read_text().splitlines()
    assert "prettier --write" in log_lines[0]
    assert any("eslint --fix" in line for line in log_lines)
    assert any("prettier --check" in line for line in log_lines)
    assert any("eslint --format json" in line for line in log_lines)


def test_toolchain_runs_dart_format_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    log = tmp_path / "tool.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_tool(bin_dir / "dart", log)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    (tmp_path / "pubspec.yaml").write_text("name: sample\n")
    source = tmp_path / "main.dart"
    target = tmp_path / "widgets.dart"
    source.write_text("void main() {}\n")
    target.write_text("class Widget {}\n")

    payload = run_toolchain_after_split(source, (SourceSplitMove(target, ("Widget",)),))

    assert payload is not None
    assert payload["adapters"] == ["dart-format"]
    assert payload["diagnostics"] == []
    log_text = log.read_text()
    assert "dart format " in log_text
    assert "dart format --output=none --set-exit-if-changed" in log_text


def test_toolchain_normalizes_ruff_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    log = tmp_path / "tool.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_tool(
        bin_dir / "ruff",
        log,
        json_when="--output-format=json",
        json_payload=[
            {
                "filename": str(tmp_path / "mod.py"),
                "code": "F401",
                "message": "unused import",
                "location": {"row": 1, "column": 8},
                "fix": {"applicability": "safe"},
            }
        ],
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    source = tmp_path / "mod.py"
    target = tmp_path / "mod_part.py"
    source.write_text("import os\n")
    target.write_text("def moved() -> int:\n    return 1\n")

    payload = run_toolchain_after_split(source, (SourceSplitMove(target, ("moved",)),))

    assert payload is not None
    diagnostics = payload["diagnostics"]
    assert isinstance(diagnostics, list)
    [diagnostic] = diagnostics
    assert diagnostic == {
        "source": "ruff",
        "severity": "error",
        "file": str(tmp_path / "mod.py"),
        "line": 1,
        "column": 8,
        "code": "F401",
        "message": "unused import",
        "fixable": True,
    }


def _write_fake_tool(
    path: Path,
    log: Path,
    *,
    json_when: str | None = None,
    json_payload: object | None = None,
    include_cwd: bool = False,
) -> None:
    payload = json_payload if json_payload is not None else []
    script = path.with_name(f"_{path.name}_fake.py")
    script.write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"args = ' '.join(sys.argv[1:])\n"
        f"prefix = f'{{Path.cwd()}} :: ' if {include_cwd!r} else ''\n"
        f"with Path({str(log)!r}).open('a', encoding='utf-8') as stream:\n"
        f"    stream.write(prefix + {path.name!r} + ' ' + args + '\\n')\n"
        f"if {json_when!r} is not None and {json_when!r} in args:\n"
        f"    print(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        wrapper = path.with_suffix(".cmd")
        wrapper.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        path.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
            encoding="utf-8",
        )
        path.chmod(0o755)
