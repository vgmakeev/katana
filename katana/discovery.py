from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent import (
    agent_guidance,
    project_agent_workflow,
    project_plan_summary,
    write_assessment_plan_file,
)
from .models import (
    CORE_SOURCE_SPLIT_EXTENSIONS,
    KATANA_PLAN_SUFFIX,
    SourceSymbol,
    source_split_extensions_for_profiles,
)
from .outline import outline_source_file, source_language, source_parser_capabilities
from .planning import (
    _build_source_split_plan,
    _suggested_plan_payload,
)
from .planning import (
    source_safe_move_groups as source_safe_move_groups,  # noqa: PLC0414 (explicit re-export, checked by mypy)
)
from .source_io import read_source_text


def large_source_files(
    roots: list[Path],
    *,
    max_lines: int,
    extensions: tuple[str, ...] = CORE_SOURCE_SPLIT_EXTENSIONS,
    exclude_dirs: tuple[str, ...] = (
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        "reference",
    ),
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    wanted = set(extensions)
    for root in roots:
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix not in wanted or _is_excluded(path, exclude_dirs):
                continue
            try:
                text = read_source_text(path)
            except UnicodeDecodeError:
                continue
            code_lines = _source_code_line_count(path, text)
            if code_lines > max_lines:
                try:
                    symbols = outline_source_file(path)
                except SyntaxError, ValueError:
                    symbols = []
                results.append(
                    {
                        "path": str(path),
                        "language": source_language(path),
                        "parser": source_parser_capabilities(path),
                        "code_lines": code_lines,
                        "line_summary": _line_summary(symbols, code_lines),
                        "symbols": [
                            symbol.to_payload(total_code_lines=code_lines) for symbol in symbols
                        ],
                    }
                )
    return sorted(results, key=lambda item: (-int(item["code_lines"]), str(item["path"])))


def detect_source_split_profiles(
    roots: list[Path],
    *,
    exclude_dirs: tuple[str, ...] = (
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        "reference",
    ),
) -> tuple[str, ...]:
    profiles: list[str] = []
    for root in roots:
        scan_root = root if root.is_dir() else root.parent
        if _has_next_project(scan_root, exclude_dirs) and "next" not in profiles:
            profiles.append("next")
        if _has_flutter_project(scan_root, exclude_dirs) and "flutter" not in profiles:
            profiles.append("flutter")
        if _has_mini_admin_project(scan_root, exclude_dirs) and "admin" not in profiles:
            profiles.append("admin")
    return tuple(profiles)


def resolve_source_split_extensions(
    profiles: tuple[str, ...],
    *,
    roots: list[Path] | None = None,
    extensions: tuple[str, ...] = (),
) -> tuple[str, ...]:
    from .adapters import discover_adapter_manifests

    discover_adapter_manifests(tuple(roots or ()))
    selected_profiles: list[str] = []
    for profile in profiles or ("core",):
        if profile == "auto":
            selected_profiles.extend(detect_source_split_profiles(roots or [Path.cwd()]))
            continue
        selected_profiles.append(profile)

    resolved = list(source_split_extensions_for_profiles(tuple(selected_profiles)))
    for extension in extensions:
        normalized = extension if extension.startswith(".") else f".{extension}"
        from .adapters import language_adapter_for_extension

        if language_adapter_for_extension(normalized) is None:
            raise ValueError(f"Unsupported source-split extension: {extension}")
        if normalized not in resolved:
            resolved.append(normalized)
    return tuple(resolved)


def project_source_split_plan(
    roots: list[Path],
    *,
    max_lines: int = 500,
    profiles: tuple[str, ...] = ("auto",),
    extensions: tuple[str, ...] = (),
    exclude_dirs: tuple[str, ...] = (
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        "reference",
    ),
    limit: int | None = None,
    write_plans: bool = False,
    headroom_lines: int | None = None,
    command_prefix: str = "katana",
) -> dict[str, Any]:
    resolved_extensions = resolve_source_split_extensions(
        profiles,
        roots=roots,
        extensions=extensions,
    )
    files = large_source_files(
        roots,
        max_lines=max_lines,
        extensions=resolved_extensions,
        exclude_dirs=exclude_dirs,
    )
    if limit is not None:
        files = files[:limit]

    assessments: list[dict[str, Any]] = []
    for item in files:
        assessments.append(
            assess_source_split(
                Path(str(item["path"])),
                max_lines=max_lines,
                write_plan=write_plans,
                headroom_lines=headroom_lines,
                command_prefix=command_prefix,
            )
        )

    return {
        "roots": [str(root) for root in roots],
        "profiles": list(profiles),
        "extensions": list(resolved_extensions),
        "max_lines": max_lines,
        "headroom_lines": _default_headroom(max_lines, headroom_lines),
        "summary": project_plan_summary(assessments),
        "agent_workflow": project_agent_workflow(
            roots,
            max_lines=max_lines,
            profiles=profiles,
            headroom_lines=headroom_lines,
            command_prefix=command_prefix,
        ),
        "assessments": assessments,
    }


def assess_source_split(
    source: Path,
    *,
    max_lines: int = 500,
    target_prefix: str | None = None,
    write_plan: bool = False,
    headroom_lines: int | None = None,
    command_prefix: str = "katana",
) -> dict[str, Any]:
    from .adapters import language_adapter_for, legacy_capabilities_for

    adapter = language_adapter_for(source)
    text = read_source_text(source)
    code_lines = adapter.code_line_count(text)
    capabilities = adapter.capabilities(source)
    parser = legacy_capabilities_for(adapter, source, capabilities)
    language = adapter.language_for(source)
    try:
        symbols = outline_source_file(source)
    except (SyntaxError, ValueError) as error:
        commands = _decision_commands(source, max_lines=max_lines, command_prefix=command_prefix)
        line_summary = _line_summary([], code_lines)
        reason = f"outline failed: {error}"
        return {
            "source": str(source),
            "language": language,
            "parser": parser,
            "code_lines": code_lines,
            "max_lines": max_lines,
            "line_summary": line_summary,
            "oversized": code_lines > max_lines,
            "status": "blocked",
            "risk": "high",
            "reason": reason,
            "symbols": [],
            "suggested_plan": None,
            "commands": commands,
            "agent": agent_guidance(
                source,
                status="blocked",
                risk="high",
                reason=reason,
                parser=parser,
                symbols=[],
                plan=None,
                code_lines=code_lines,
                max_lines=max_lines,
                commands=commands,
            ),
        }

    plan = _build_source_split_plan(
        source,
        symbols,
        code_lines=code_lines,
        max_lines=max_lines,
        headroom_lines=_default_headroom(max_lines, headroom_lines),
        target_prefix=target_prefix,
    )
    oversized = code_lines > max_lines
    if not oversized:
        status = "ok"
        risk = "none"
        reason = "file is within the configured line budget"
    elif not symbols:
        status = "manual_review"
        risk = "high"
        reason = "file is oversized but no movable top-level symbols were detected"
    elif not plan.moves:
        status = "manual_review"
        risk = "high"
        reason = "file is oversized but no deterministic split plan was produced"
    else:
        status = "split_recommended"
        risk = adapter.split_risk(plan.warnings, capabilities)
        reason = adapter.split_reason(capabilities)

    commands = _decision_commands(source, max_lines=max_lines, command_prefix=command_prefix)
    agent_payload = agent_guidance(
        source,
        status=status,
        risk=risk,
        reason=reason,
        parser=parser,
        symbols=symbols,
        plan=plan,
        code_lines=code_lines,
        max_lines=max_lines,
        commands=commands,
    )
    safe_moves = source_safe_move_groups(source, symbols)
    moved_set = set(plan.moved_symbols)
    for group in safe_moves["groups"]:
        group["in_suggested_plan"] = set(group["symbols"]) <= moved_set
    agent_payload["safe_moves"] = safe_moves
    payload = {
        "source": str(source),
        "language": language,
        "parser": parser,
        "code_lines": code_lines,
        "max_lines": max_lines,
        "headroom_lines": _default_headroom(max_lines, headroom_lines),
        "line_summary": _line_summary(symbols, code_lines),
        "oversized": oversized,
        "status": status,
        "risk": risk,
        "reason": reason,
        "symbols": [symbol.to_payload(total_code_lines=code_lines) for symbol in symbols],
        "suggested_plan": _suggested_plan_payload(
            plan,
            symbols,
            code_lines,
            max_lines=max_lines,
            headroom_lines=_default_headroom(max_lines, headroom_lines),
        ),
        "commands": commands,
        "agent": agent_payload,
    }
    if write_plan and status == "split_recommended" and plan.moves:
        plan_path = write_assessment_plan_file(payload)
        payload["plan_file"] = str(plan_path)
        agent_payload["plan_file"] = str(plan_path)
    return payload


def source_code_line_count(path: Path, text: str | None = None) -> int:
    return _source_code_line_count(path, read_source_text(path) if text is None else text)


def _python_code_line_count(text: str) -> int:
    return sum(
        1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )


def _source_code_line_count(path: Path, text: str) -> int:
    from .adapters import language_adapter_for

    return language_adapter_for(path).code_line_count(text)


def _split_risk(source: Path, warnings: tuple[str, ...], parser: dict[str, object]) -> str:
    from .adapters import language_adapter_for

    adapter = language_adapter_for(source)
    return adapter.split_risk(warnings, adapter.capabilities(source))


def _split_reason(source: Path, parser: dict[str, object]) -> str:
    from .adapters import language_adapter_for

    adapter = language_adapter_for(source)
    return adapter.split_reason(adapter.capabilities(source))


def _default_headroom(max_lines: int, override: int | None) -> int:
    if override is not None:
        return max(override, 0)
    return min(max_lines // 10, 75)


def _decision_commands(
    source: Path,
    *,
    max_lines: int,
    command_prefix: str,
) -> dict[str, str]:
    from .adapters import language_adapter_for

    flags = language_adapter_for(source).command_flags(source)
    import_flags = "" if not flags else " " + " ".join(flags)
    return {
        "outline": f"{command_prefix} outline {source} --json",
        "write_plan": (
            f"{command_prefix} assess {source} --max-lines {max_lines} --write-plan --json"
        ),
        "plan": (
            f"{command_prefix} plan {source} --plan-file "
            f"{source.with_suffix(KATANA_PLAN_SUFFIX)} --json"
        ),
        "apply": (
            f"{command_prefix} apply {source} --plan-file "
            f"{source.with_suffix(KATANA_PLAN_SUFFIX)} --check "
            f"--max-lines {max_lines}{import_flags} --json"
        ),
    }


def _line_summary(symbols: list[SourceSymbol], total_code_lines: int) -> dict[str, object]:
    symbol_code_lines = sum(symbol.code_lines for symbol in symbols)
    largest = max(symbols, key=lambda symbol: symbol.code_lines, default=None)
    return {
        "total_code_lines": total_code_lines,
        "symbol_count": len(symbols),
        "symbol_code_lines": symbol_code_lines,
        "symbol_code_lines_pct": round(symbol_code_lines * 100 / total_code_lines, 1)
        if total_code_lines
        else 0,
        "non_symbol_code_lines": max(total_code_lines - symbol_code_lines, 0),
        "largest_symbol": largest.name if largest is not None else None,
        "largest_symbol_code_lines": largest.code_lines if largest is not None else 0,
        "largest_symbol_code_lines_pct": round(largest.code_lines * 100 / total_code_lines, 1)
        if largest is not None and total_code_lines
        else 0,
    }


def _is_excluded(path: Path, exclude_dirs: tuple[str, ...]) -> bool:
    excluded = set(exclude_dirs)
    return any(part in excluded for part in path.parts)


def _has_next_project(root: Path, exclude_dirs: tuple[str, ...]) -> bool:
    for marker in ("next.config.js", "next.config.mjs", "next.config.ts"):
        if (root / marker).exists():
            return True
    return _package_json_has_dependency(root, "next", exclude_dirs)


def _has_flutter_project(root: Path, exclude_dirs: tuple[str, ...]) -> bool:
    pubspec = root / "pubspec.yaml"
    if not pubspec.exists():
        return False
    try:
        text = pubspec.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    return "flutter:" in text or "sdk: flutter" in text


def _has_mini_admin_project(root: Path, exclude_dirs: tuple[str, ...]) -> bool:
    return _package_json_has_dependency(
        root, "@mini/admin", exclude_dirs
    ) or _package_json_has_workspace(
        root,
        "mini-admin",
    )


def _package_json_has_dependency(
    root: Path,
    dependency: str,
    exclude_dirs: tuple[str, ...],
) -> bool:
    for package_json in _package_json_files(root, exclude_dirs):
        payload = _read_json_object(package_json)
        if not payload:
            continue
        for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            values = payload.get(key)
            if isinstance(values, dict) and dependency in values:
                return True
    return False


def _package_json_has_workspace(root: Path, workspace: str) -> bool:
    package_json = root / "package.json"
    payload = _read_json_object(package_json)
    workspaces = payload.get("workspaces") if payload else None
    if isinstance(workspaces, list):
        return workspace in {str(item).rstrip("/") for item in workspaces}
    if isinstance(workspaces, dict):
        packages = workspaces.get("packages")
        if isinstance(packages, list):
            return workspace in {str(item).rstrip("/") for item in packages}
    return False


def _package_json_files(root: Path, exclude_dirs: tuple[str, ...]) -> list[Path]:
    if not root.exists():
        return []
    candidates = [root] if root.is_file() else root.rglob("package.json")
    return [
        path
        for path in candidates
        if path.name == "package.json" and not _is_excluded(path, exclude_dirs)
    ]


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, UnicodeDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


_RUFF_EXPLICIT_EXPORTS = (source_safe_move_groups,)
