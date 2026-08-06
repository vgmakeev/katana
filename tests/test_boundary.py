from __future__ import annotations

import ast
from pathlib import Path


def test_katana_does_not_import_mini_or_app_modules() -> None:
    package_root = Path(__file__).resolve().parents[1] / "katana"
    offenders: list[str] = []

    for path in sorted(package_root.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name == "app" or name.startswith(("app.", "mini_")):
                    offenders.append(f"{path.name}: {name}")

    assert offenders == []
