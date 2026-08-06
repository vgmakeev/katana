from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import KATANA_PLAN_SUFFIX, SPLIT_PLAN_VERSION, SourceSplitPlan, SourceSymbol


def write_assessment_plan_file(assessment: dict[str, Any]) -> Path:
    source = Path(str(assessment["source"]))
    destination = source.with_suffix(KATANA_PLAN_SUFFIX)
    suggested = assessment.get("suggested_plan")
    if not isinstance(suggested, dict):
        raise TypeError(f"Assessment has no suggested plan: {source}")
    # Targets are stored relative to the source directory so the plan resolves
    # the same way from any working directory.
    moves = [
        {
            "target": os.path.relpath(str(move["target"]), start=str(source.parent)),
            "symbols": move["symbols"],
        }
        for move in suggested.get("moves") or []
    ]
    payload = {
        "version": SPLIT_PLAN_VERSION,
        "source": str(source),
        "moves": moves,
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return destination


def project_plan_summary(assessments: list[dict[str, Any]]) -> dict[str, object]:
    by_decision: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    total_code_lines = 0
    total_excess_lines = 0
    estimated_moved_lines = 0
    for assessment in assessments:
        code_lines = int(assessment.get("code_lines") or 0)
        max_lines = int(assessment.get("max_lines") or 0)
        total_code_lines += code_lines
        total_excess_lines += max(code_lines - max_lines, 0)
        risk = str(assessment.get("risk") or "unknown")
        by_risk[risk] = by_risk.get(risk, 0) + 1
        agent_payload = assessment.get("agent")
        agent = agent_payload if isinstance(agent_payload, dict) else {}
        decision = str(agent.get("decision") or assessment.get("status") or "unknown")
        by_decision[decision] = by_decision.get(decision, 0) + 1
        suggested = assessment.get("suggested_plan")
        if isinstance(suggested, dict):
            for move in suggested.get("moves") or []:
                if isinstance(move, dict):
                    estimated_moved_lines += int(move.get("moved_code_lines") or 0)
    return {
        "oversized_files": len(assessments),
        "by_decision": by_decision,
        "by_risk": by_risk,
        "total_code_lines": total_code_lines,
        "total_excess_lines": total_excess_lines,
        "estimated_moved_code_lines": estimated_moved_lines,
    }


def project_agent_workflow(
    roots: list[Path],
    *,
    max_lines: int,
    profiles: tuple[str, ...],
    headroom_lines: int | None = None,
    command_prefix: str = "katana",
) -> dict[str, object]:
    roots_text = " ".join(str(root) for root in roots)
    profile_flags = " ".join(f"--profile {profile}" for profile in profiles)
    headroom_flag = f" --headroom {headroom_lines}" if headroom_lines is not None else ""
    scan = (
        f"{command_prefix} project {roots_text} --max-lines {max_lines}"
        f"{headroom_flag} {profile_flags} --json"
    )
    write = f"{scan} --write-plans"
    return {
        "minimal_steps": [
            {
                "step": "scan",
                "command": scan,
                "purpose": "Get prioritized project-wide assessments.",
            },
            {
                "step": "write_plans",
                "command": write,
                "purpose": "Materialize deterministic .katana.json files.",
            },
            {
                "step": "apply",
                "command": "Run each assessment.commands.apply in priority order.",
                "purpose": "Apply explicit plans one file at a time and stop on check failure.",
            },
            {
                "step": "verify",
                "command": "Run assessment.agent.verification_commands after each apply.",
                "purpose": "Use parser-specific checks instead of guessing.",
            },
        ],
        "safety_rule": "Apply one plan at a time; do not auto-apply high-risk or blocked assessments.",
    }


def agent_guidance(
    source: Path,
    *,
    status: str,
    risk: str,
    reason: str,
    parser: dict[str, object],
    symbols: list[SourceSymbol],
    plan: SourceSplitPlan | None,
    code_lines: int,
    max_lines: int,
    commands: dict[str, str],
) -> dict[str, object]:
    decision = _agent_decision(status)
    confidence = _agent_confidence(status, risk, parser, plan)
    verification_commands = _verification_commands(source, parser, commands, plan)
    review_notes = _review_notes(parser, plan)
    largest = max(symbols, key=lambda symbol: symbol.code_lines, default=None)
    return {
        "decision": decision,
        "confidence": confidence,
        "next_step": _agent_next_step(decision),
        "summary": _agent_summary(
            source,
            decision=decision,
            parser=parser,
            code_lines=code_lines,
            max_lines=max_lines,
            largest=largest,
        ),
        "reason": reason,
        "requires_human_review": risk in {"high", "review"} or decision == "manual_review",
        "parser_precision": parser.get("precision"),
        "parser_available": parser.get("adapter_available", True),
        "review_notes": review_notes,
        "verification_commands": verification_commands,
    }


def _agent_decision(status: str) -> str:
    if status == "ok":
        return "skip"
    if status == "split_recommended":
        return "apply_suggested_plan"
    if status == "blocked":
        return "blocked"
    return "manual_review"


def _agent_confidence(
    status: str,
    risk: str,
    parser: dict[str, object],
    plan: SourceSplitPlan | None,
) -> str:
    if status == "ok":
        return "high"
    if status == "blocked" or risk == "high":
        return "low"
    if plan is not None and plan.warnings:
        return "medium"
    if parser.get("precision") == "semantic_top_level":
        return "high"
    return "medium"


def _agent_next_step(decision: str) -> str:
    return {
        "skip": "No split needed.",
        "apply_suggested_plan": (
            "The suggested plan is one valid composition of agent.safe_moves groups; "
            "keep it or recompose from the menu, materialize with commands.write_plan, "
            "rename the mechanical _part target placeholders in the .katana.json "
            "to module names that describe the moved responsibility, then run "
            "commands.apply."
        ),
        "manual_review": (
            "Inspect agent.safe_moves and the outline, then create an explicit move plan manually."
        ),
        "blocked": "Fix parser or syntax errors before attempting a split.",
    }[decision]


def _agent_summary(
    source: Path,
    *,
    decision: str,
    parser: dict[str, object],
    code_lines: int,
    max_lines: int,
    largest: SourceSymbol | None,
) -> str:
    parser_name = str(parser.get("parser") or "unknown")
    largest_text = (
        f"; largest symbol is {largest.name} ({largest.code_lines} code lines)"
        if largest is not None
        else ""
    )
    return (
        f"{source} has {code_lines}/{max_lines} code lines; "
        f"parser={parser_name}; decision={decision}{largest_text}."
    )


def _review_notes(
    parser: dict[str, object],
    plan: SourceSplitPlan | None,
) -> list[str]:
    notes: list[str] = []
    if parser.get("adapter_available") is False:
        notes.append("Using structural fallback because the language AST adapter is unavailable.")
    limitations = parser.get("limitations")
    for limitation in limitations if isinstance(limitations, list | tuple) else ():
        notes.append(str(limitation))
    if plan is not None:
        notes.extend(plan.warnings)
        if plan.moves:
            if any("_part" in move.target.stem for move in plan.moves):
                notes.append(
                    "Suggested target names are mechanical placeholders; rename them "
                    "in the plan file to describe the moved responsibility before "
                    "applying."
                )
            notes.append(
                "Moved files copy the source import block minus obviously unused "
                "imports; run the project linter/import cleaner afterwards."
            )
    return list(dict.fromkeys(notes))


def _verification_commands(
    source: Path,
    parser: dict[str, object],
    commands: dict[str, str],
    plan: SourceSplitPlan | None,
) -> list[str]:
    # The apply command references the plan file, which only makes sense while
    # there is a split plan to apply.
    commands_out = [commands["apply"]] if plan is not None and plan.moves else []
    verifications = parser.get("verifications")
    for verification in verifications if isinstance(verifications, list | tuple) else ():
        if verification == "py_compile":
            commands_out.append(f"python -m py_compile {source}")
        elif verification == "typescript_check":
            commands_out.extend(_npm_commands(source, "lint"))
        elif verification == "frontend_tests":
            commands_out.extend(_npm_commands(source, "test"))
        elif verification == "frontend_build":
            commands_out.extend(_npm_commands(source, "build"))
        elif verification == "dart_analyze":
            if _nearest_up(source, "pubspec.yaml") is not None:
                commands_out.append("dart analyze")
        elif verification == "flutter_tests":
            if _nearest_up(source, "pubspec.yaml") is not None:
                commands_out.append("flutter test")
        elif verification == "project_tests":
            commands_out.append(_python_test_command(source))
        elif verification == "docs_render":
            commands_out.append("run the project docs/render check")
    return list(dict.fromkeys(commands_out))


def _npm_commands(source: Path, kind: str) -> list[str]:
    packages = _nearest_and_root_package_json(source)
    if not packages:
        return []
    aliases = _workspace_aliases(source, packages)
    preferred = [f"{alias}:{kind}" for alias in aliases]
    for package_json in packages:
        payload = _read_json(package_json)
        raw_scripts = payload.get("scripts")
        scripts = raw_scripts if isinstance(raw_scripts, dict) else {}
        for name in preferred:
            if name in scripts:
                return [f"npm run {name}"]
    for package_json in packages:
        payload = _read_json(package_json)
        raw_scripts = payload.get("scripts")
        scripts = raw_scripts if isinstance(raw_scripts, dict) else {}
        if kind in scripts:
            return [f"npm run {kind}"]
    return []


def _nearest_and_root_package_json(source: Path) -> list[Path]:
    nearest = _nearest_up(source, "package.json")
    root = _root_package_json(source)
    return list(dict.fromkeys(path for path in (nearest, root) if path is not None))


def _workspace_aliases(source: Path, packages: list[Path]) -> list[str]:
    aliases: list[str] = []
    root = packages[-1].parent
    try:
        relative = source.resolve().relative_to(root.resolve())
    except ValueError:
        relative = source
    for part in relative.parts[:-1]:
        if part.startswith("mini-"):
            aliases.append(part.removeprefix("mini-"))
        aliases.append(part)
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _python_test_command(source: Path) -> str:
    pyproject = _nearest_up(source, "pyproject.toml")
    if pyproject is None:
        return "pytest"
    package = _pyproject_name(pyproject)
    tests = pyproject.parent / "tests"
    if package and tests.exists():
        return f"uv run --package {package} pytest {tests}"
    return "pytest"


def _pyproject_name(path: Path) -> str | None:
    for line in path.read_text().splitlines():
        if line.strip().startswith("name ="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def _nearest_up(source: Path, name: str) -> Path | None:
    start = source if source.is_dir() else source.parent
    for candidate in (start, *start.parents):
        path = candidate / name
        if path.exists():
            return path
    return None


def _root_package_json(source: Path) -> Path | None:
    start = source if source.is_dir() else source.parent
    root_package: Path | None = None
    for candidate in (start, *start.parents):
        package = candidate / "package.json"
        if package.exists():
            root_package = package
        if (candidate / ".git").exists():
            break
    return root_package


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except OSError, json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
