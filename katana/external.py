from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import SourceSymbol, SourceSymbolChild

_BRIDGE_DIR = Path(__file__).resolve().parent
_NODE_BRIDGE = _BRIDGE_DIR / "ast_bridge.mjs"
_DART_BRIDGE = _BRIDGE_DIR / "dart_ast.dart"


def outline_typescript_with_ast(path: Path) -> list[SourceSymbol] | None:
    payload = _run_node_bridge("typescript", path)
    if payload is None:
        return None
    return source_symbols_from_payload(payload)


def outline_css_with_ast(path: Path) -> list[SourceSymbol] | None:
    payload = _run_node_bridge("css", path)
    if payload is None:
        return None
    return source_symbols_from_payload(payload)


def markdown_document_metadata(path: Path) -> dict[str, Any] | None:
    """Return compact TanStack Markdown metadata, never the potentially huge AST."""
    payload = _run_node_bridge("markdown", path)
    if payload is None:
        return None
    metadata = payload.get("document")
    return metadata if isinstance(metadata, dict) else None


def outline_dart_with_analyzer(path: Path) -> list[SourceSymbol] | None:
    if not dart_analyzer_ast_available(path):
        return None
    if shutil.which("dart") is None:
        return None
    try:
        completed = subprocess.run(
            ["dart", str(_DART_BRIDGE), str(path.resolve())],
            check=False,
            capture_output=True,
            cwd=_project_root_for(path),
            text=True,
            timeout=8,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return source_symbols_from_payload(payload)


def source_ast_bridge_capabilities(path: Path) -> dict[str, bool]:
    node_payload = _run_node_bridge("capabilities", path)
    return {
        "node": bool(node_payload and node_payload.get("node")),
        "typescript": bool(node_payload and node_payload.get("typescript")),
        "postcss": bool(node_payload and node_payload.get("postcss")),
        "tanstack_markdown": bool(node_payload and node_payload.get("tanstack_markdown")),
        "dart": shutil.which("dart") is not None,
        "dart_analyzer": dart_analyzer_ast_available(path),
    }


def typescript_ast_available(path: Path) -> bool:
    payload = _run_node_bridge("capabilities", path)
    return bool(payload and payload.get("typescript"))


def css_ast_available(path: Path) -> bool:
    payload = _run_node_bridge("capabilities", path)
    return bool(payload and payload.get("postcss"))


def markdown_ast_available(path: Path) -> bool:
    payload = _run_node_bridge("capabilities", path)
    return bool(payload and payload.get("tanstack_markdown"))


def dart_analyzer_ast_available(path: Path) -> bool:
    return _dart_package_has_analyzer(_project_root_for(path))


def _run_node_bridge(command: str, path: Path) -> dict[str, Any] | None:
    if shutil.which("node") is None:
        return None
    try:
        completed = subprocess.run(
            ["node", str(_NODE_BRIDGE), command, str(path.resolve())],
            check=False,
            capture_output=True,
            cwd=_project_root_for(path),
            text=True,
            timeout=8,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def source_symbols_from_payload(payload: dict[str, Any]) -> list[SourceSymbol]:
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list):
        return []
    symbols: list[SourceSymbol] = []
    for raw in raw_symbols:
        if not isinstance(raw, dict):
            continue
        symbols.append(
            SourceSymbol(
                name=str(raw["name"]),
                kind=str(raw["kind"]),
                signature=str(raw["signature"]),
                start_line=int(raw["start_line"]),
                end_line=int(raw["end_line"]),
                code_lines=int(raw["code_lines"]),
                references=tuple(str(item) for item in raw.get("references") or ()),
                tags=tuple(str(item) for item in raw.get("tags") or ()),
                meta=raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
                children=_children_from_payload(raw.get("children")),
            )
        )
    return symbols


def _children_from_payload(raw_children: Any) -> tuple[SourceSymbolChild, ...]:
    if not isinstance(raw_children, list):
        return ()
    children: list[SourceSymbolChild] = []
    for raw in raw_children:
        if not isinstance(raw, dict):
            continue
        children.append(
            SourceSymbolChild(
                name=str(raw["name"]),
                kind=str(raw["kind"]),
                signature=str(raw["signature"]),
                start_line=int(raw["start_line"]),
                end_line=int(raw["end_line"]),
                code_lines=int(raw["code_lines"]),
                tags=tuple(str(item) for item in raw.get("tags") or ()),
                meta=raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
            )
        )
    return tuple(children)


def _project_root_for(path: Path) -> Path:
    start = path if path.is_dir() else path.parent
    for current in (start, *start.parents):
        if (
            (current / "package.json").exists()
            or (current / "pubspec.yaml").exists()
            or (current / "pyproject.toml").exists()
            or (current / ".git").exists()
        ):
            return current
    return start


@lru_cache(maxsize=64)
def _dart_package_has_analyzer(root: Path) -> bool:
    package_config = root / ".dart_tool" / "package_config.json"
    if not package_config.exists():
        return False
    try:
        payload = json.loads(package_config.read_text())
    except json.JSONDecodeError, UnicodeDecodeError:
        return False
    packages = payload.get("packages")
    if not isinstance(packages, list):
        return False
    return any(isinstance(item, dict) and item.get("name") == "analyzer" for item in packages)
