from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from katana import (
    SourceSplitMove,
    apply_source_split,
    assess_source_split,
    parse_move_plan,
)
from katana.cli import add_source_split_parser, handle_source_split_command, main
from katana.toolchain import run_toolchain_after_split


def test_typescript_split_uses_type_imports_and_reexports(tmp_path: Path) -> None:
    source = tmp_path / "logic.ts"
    source.write_text(
        "export interface Props {\n"
        "  label: string\n"
        "}\n\n"
        "export function build(props: Props) {\n"
        "  return props.label\n"
        "}\n\n"
        "export function render(props: Props) {\n"
        "  return build(props)\n"
        "}\n"
    )

    apply_source_split(source, parse_move_plan(source, ["logic_part.ts:Props,build"], None))

    source_text = source.read_text()
    assert 'import { build } from "./logic_part"' in source_text
    assert 'import type { Props } from "./logic_part"' in source_text
    assert 'export { build } from "./logic_part"' in source_text
    assert 'export type { Props } from "./logic_part"' in source_text
    assert "export interface Props" in (tmp_path / "logic_part.ts").read_text()

    tsc = shutil.which("tsc")
    if tsc is None:
        pytest.skip("tsc binary is not available")
    (tmp_path / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "module": "ESNext",
                    "target": "ES2022",
                    "verbatimModuleSyntax": True,
                    "strict": True,
                    "skipLibCheck": True,
                }
            }
        )
    )
    completed = subprocess.run(
        [tsc, "--noEmit"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout


def test_toolchain_resolves_hoisted_workspace_binaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log = tmp_path / "tool.log"
    root_bin = tmp_path / "node_modules" / ".bin"
    root_bin.mkdir(parents=True)
    _write_fake_tool(root_bin / "eslint", log, json_when="--format json")
    _write_fake_tool(root_bin / "prettier", log)
    (tmp_path / ".git").mkdir()
    package = tmp_path / "packages" / "admin"
    package.mkdir(parents=True)
    (package / "package.json").write_text("{}\n")
    (package / "eslint.config.js").write_text("export default []\n")
    (package / ".prettierrc").write_text("{}\n")
    source = package / "view.ts"
    target = package / "view_part.ts"
    source.write_text("export const keep = 1\n")
    target.write_text("export const moved = 1\n")
    monkeypatch.setenv("PATH", "")

    payload = run_toolchain_after_split(source, (SourceSplitMove(target, ("moved",)),))

    assert payload["adapters"] == ["prettier", "eslint"]
    assert payload["skipped"] == []
    assert "prettier --write" in log.read_text()


def test_toolchain_reports_missing_workspace_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    package = tmp_path / "packages" / "admin"
    package.mkdir(parents=True)
    (package / "eslint.config.js").write_text("export default []\n")
    source = package / "view.ts"
    target = package / "view_part.ts"
    source.write_text("export const keep = 1\n")
    target.write_text("export const moved = 1\n")
    monkeypatch.setenv("PATH", "")

    payload = run_toolchain_after_split(source, (SourceSplitMove(target, ("moved",)),))

    skipped = payload["skipped"]
    assert isinstance(skipped, list)
    assert any(item["tool"] == "eslint" and "config found" in item["reason"] for item in skipped)


def test_verification_commands_use_existing_workspace_scripts(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"admin:lint": "x", "admin:test": "x", "admin:build": "x"}})
    )
    package = tmp_path / "mini-admin"
    package.mkdir()
    (package / "package.json").write_text(
        json.dumps({"scripts": {"lint": "x", "test": "x", "build": "x"}})
    )
    ts = package / "view.ts"
    ts.write_text("\n\n".join(f"export function fn{i}() {{ return {i} }}" for i in range(5)))
    css = package / "view.css"
    css.write_text("\n\n".join(f".c{i} {{ color: red; }}" for i in range(5)))

    ts_payload = assess_source_split(ts, max_lines=2)
    css_payload = assess_source_split(css, max_lines=2)

    commands = (
        ts_payload["agent"]["verification_commands"] + css_payload["agent"]["verification_commands"]
    )
    assert "npm run admin:lint" in commands
    assert "npm run admin:test" in commands
    assert "npm run admin:build" in commands
    assert "npm run lint" not in commands
    assert "npm test" not in commands
    assert "npm run build" not in commands


def test_mini_source_split_payload_uses_delegate_prefix(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    )
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    add_source_split_parser(subparsers)

    main(["assess", str(source), "--max-lines", "2", "--json"])
    katana_payload = json.loads(capsys.readouterr().out)
    args = parser.parse_args(["source-split", "assess", str(source), "--max-lines", "2", "--json"])
    assert handle_source_split_command(args) is True
    mini_payload = json.loads(capsys.readouterr().out)

    assert katana_payload["commands"]["apply"].startswith("katana apply")
    assert mini_payload["commands"]["apply"].startswith("mini source-split apply")


def test_help_describes_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    top_help = capsys.readouterr().out
    assert "large -> find oversized files" in top_help
    assert "assess --write-plan" in top_help

    with pytest.raises(SystemExit):
        main(["assess", "--help"])
    assess_help = capsys.readouterr().out
    assert "Assess one file" in assess_help
    assert "--headroom" in assess_help


def test_apply_warns_about_placeholder_targets(tmp_path: Path) -> None:
    source = tmp_path / "mod.py"
    source.write_text("def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return 2\n")

    plan = apply_source_split(source, parse_move_plan(source, ["mod_part1.py:moved"], None))

    assert any("placeholder names" in warning for warning in plan.warnings)


def test_headroom_payload_reports_projected_lines(tmp_path: Path) -> None:
    source = tmp_path / "large.ts"
    source.write_text(
        "\n\n".join(f"export function fn{i}() {{\n  return {i}\n}}" for i in range(8))
    )

    payload = assess_source_split(source, max_lines=10, headroom_lines=2)
    move = payload["suggested_plan"]["moves"][-1]

    source_projection = move["produced_files"][0]
    assert source_projection["path"] == str(source)
    assert source_projection["projected_lines"] <= 8
    assert source_projection["headroom"] >= 2


def test_typecheck_adapter_runs_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    log = tmp_path / "tool.log"
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    _write_fake_tool(bin_dir / "tsc", log)
    (tmp_path / ".git").mkdir()
    (tmp_path / "tsconfig.json").write_text("{}\n")
    source = tmp_path / "view.ts"
    target = tmp_path / "view_part.ts"
    source.write_text("export const keep = 1\n")
    target.write_text("export const moved = 1\n")
    monkeypatch.setenv("PATH", "")

    payload = run_toolchain_after_split(
        source,
        (SourceSplitMove(target, ("moved",)),),
        typecheck=True,
    )

    assert "tsc" in cast(list[str], payload["checkers"])
    assert "tsc --noEmit" in log.read_text()


def test_tsx_mixed_component_split_warns_about_fast_refresh(tmp_path: Path) -> None:
    source = tmp_path / "view.tsx"
    source.write_text(
        "export function Widget() {\n"
        "  return <div />\n"
        "}\n\n"
        "export function helper() {\n"
        "  return 1\n"
        "}\n"
    )

    plan = apply_source_split(
        source, parse_move_plan(source, ["view_part.tsx:Widget,helper"], None)
    )

    assert any("react-refresh/only-export-components" in warning for warning in plan.warnings)


def _write_fake_tool(
    path: Path,
    log: Path,
    *,
    json_when: str | None = None,
) -> None:
    script = path.with_name(f"_{path.name}_fake.py")
    script.write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = ' '.join(sys.argv[1:])\n"
        f"with Path({str(log)!r}).open('a', encoding='utf-8') as stream:\n"
        f"    stream.write({path.name!r} + ' ' + args + '\\n')\n"
        f"if {json_when!r} is not None and {json_when!r} in args:\n"
        "    print(json.dumps([]))\n",
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
