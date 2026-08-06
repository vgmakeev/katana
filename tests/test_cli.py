from __future__ import annotations

import json
import os

import pytest

from katana.cli import build_parser, main


@pytest.mark.parametrize("command", ("assess", "large", "project"))
def test_source_commands_default_to_the_500_line_target(command: str) -> None:
    roots = ["source.py"] if command == "assess" else ["."]
    args = build_parser().parse_args([command, *roots])

    assert args.max_lines == 500


def test_katana_cli_outline_assess_and_apply(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    source = tmp_path / "mod.py"
    source.write_text(
        "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    )
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"moves": [{"target": "mod_moved.py", "symbols": ["moved"]}]}))

    main(["outline", str(source), "--json"])
    outline_payload = json.loads(capsys.readouterr().out)
    assert [symbol["name"] for symbol in outline_payload["symbols"]] == ["moved", "keep"]

    main(["assess", str(source), "--max-lines", "2", "--json"])
    assess_payload = json.loads(capsys.readouterr().out)
    assert assess_payload["source"] == str(source)
    assert assess_payload["oversized"] is True

    main(
        [
            "apply",
            str(source),
            "--plan-file",
            str(plan),
            "--no-lint-fix",
            "--json",
        ]
    )
    apply_payload = json.loads(capsys.readouterr().out)
    assert apply_payload["moves"][0]["target"] == str(tmp_path / "mod_moved.py")
    assert "def moved() -> int:" in (tmp_path / "mod_moved.py").read_text()
    assert plan.exists()


def test_katana_cli_schema_json(capsys: pytest.CaptureFixture[str]) -> None:
    main(["schema", "--json"])

    schema = json.loads(capsys.readouterr().out)
    assert schema["properties"]["version"]["const"] == 1
    assert schema["properties"]["moves"]["items"]["additionalProperties"] is False


def test_katana_cli_apply_reports_lint_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ruff = bin_dir / "ruff"
    ruff.write_text(
        '#!/bin/sh\ncase "$*" in *"--output-format=json"*) printf \'[]\';; esac\nexit 0\n'
    )
    ruff.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
    source = tmp_path / "mod.py"
    source.write_text(
        "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    )
    plan = tmp_path / "mod.katana.json"
    plan.write_text(json.dumps({"moves": [{"target": "mod_moved.py", "symbols": ["moved"]}]}))

    main(["apply", str(source), "--plan-file", str(plan), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["lint"]["adapters"] == ["ruff"]
    assert payload["lint"]["diagnostics"] == []
    assert payload["plan_file_removed"] == str(plan)
    assert not plan.exists()


def test_katana_cli_apply_keeps_plan_when_check_fails(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    source = tmp_path / "mod.py"
    source.write_text("def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return 2\n")
    plan = tmp_path / "mod.katana.json"
    plan.write_text(json.dumps({"moves": [{"target": "mod_moved.py", "symbols": ["moved"]}]}))

    with pytest.raises(SystemExit):
        main(
            [
                "apply",
                str(source),
                "--plan-file",
                str(plan),
                "--no-lint-fix",
                "--check",
                "--max-lines",
                "1",
                "--json",
            ]
        )

    payload = json.loads(capsys.readouterr().out)
    assert payload["check"]["ok"] is False
    assert "plan_file_removed" not in payload
    assert plan.exists()


def test_katana_cli_apply_check_is_dry_run(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    source = tmp_path / "mod.py"
    original = "def moved() -> int:\n    return 1\n\ndef keep() -> int:\n    return moved()\n"
    source.write_text(original)
    target = tmp_path / "mod_moved.py"
    plan = tmp_path / "mod.katana.json"
    plan.write_text(json.dumps({"moves": [{"target": target.name, "symbols": ["moved"]}]}))

    main(
        [
            "apply",
            str(source),
            "--plan-file",
            str(plan),
            "--no-lint-fix",
            "--check",
            "--max-lines",
            "10",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["check"]["ok"] is True
    assert source.read_text() == original
    assert not target.exists()
    assert plan.exists()
