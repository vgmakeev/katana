from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

from katana import (
    KATANA_PLAN_SUFFIX,
    LEGACY_SOURCE_SPLIT_PLAN_SUFFIX,
    analyze_source_file,
    apply_source_split,
    assess_source_split,
    check_split_result,
    fix_lint_after_split,
    import_impact_report,
    large_source_files,
    outline_source_file,
    parse_move_plan,
    plan_source_split,
    project_source_split_plan,
    resolve_source_split_extensions,
    source_code_line_count,
    source_language,
    source_parser_capabilities,
    source_safe_move_groups,
    split_plan_json_schema,
)
from katana.adapters import (
    adapter_load_errors,
    check_language_adapter,
    command_adapter_manifest_schema,
    discover_adapter_manifests,
    language_adapter_for,
    language_adapters,
)
from katana.source_io import read_source_text
from katana.toolchain import (
    skipped_toolchain_payload,
    toolchain_adapters,
    toolchain_load_errors,
)

from .cli_output import (
    _check_apply_source_split,
    _print_source_split_payload,
    _result_outline,
    _review_command,
)
from .cli_parser import _add_katana_commands

_FLOW_EPILOG = """canonical flow:
large -> find oversized files by language-aware LOC
map -> give the agent signatures, dependencies and constraints without source bodies
assess --write-plan -> produce a safe-moves menu and editable plan
apply --plan-file --check -> dry-run the byte-exact rewrite
apply --plan-file -> rewrite, format, lint and report; schema documents the plan contract"""


def add_source_split_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "source-split",
        help="Deterministic refactoring executor for coding agents.",
        description="Source-map, planning and rewrite tools for coding agents.",
        epilog=_FLOW_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="source_split_command", required=True)
    _add_katana_commands(commands)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="katana",
        description="Deterministic refactoring executor for coding agents.",
        epilog=_FLOW_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="katana_command", required=True)
    _add_katana_commands(commands)
    return parser


def handle_source_split_command(args: argparse.Namespace) -> bool:
    if getattr(args, "command", None) != "source-split":
        return False
    handle_katana_command(
        args,
        command_attr="source_split_command",
        command_prefix="mini source-split",
    )
    return True


def handle_katana_command(
    args: argparse.Namespace,
    *,
    command_attr: str = "katana_command",
    command_prefix: str = "katana",
) -> None:
    command = str(getattr(args, command_attr))

    if command == "schema":
        payload = split_plan_json_schema()
    elif command == "adapters":
        source = Path(args.source) if args.source else None
        if args.schema:
            if source is not None or args.check:
                raise ValueError("katana adapters --schema does not accept a source or --check")
            payload = command_adapter_manifest_schema()
        else:
            payload = _adapter_payload(source)
        if args.check and not args.schema:
            if source is None:
                raise ValueError("katana adapters --check requires a source file")
            payload["conformance"] = check_language_adapter(language_adapter_for(source), source)
    elif command == "map":
        source = Path(args.source)
        document = analyze_source_file(source)
        payload = document.to_payload()
        payload["physical_lines"] = len(read_source_text(source).splitlines())
        payload["code_lines"] = source_code_line_count(source)
        payload["safe_moves"] = source_safe_move_groups(source, list(document.source_symbols))
    elif command == "outline":
        source = Path(args.source)
        code_lines = source_code_line_count(source)
        symbols = outline_source_file(source)
        payload = {
            "source": str(source),
            "language": source_language(source),
            "parser": source_parser_capabilities(source),
            "code_lines": code_lines,
            "symbols": [symbol.to_payload(total_code_lines=code_lines) for symbol in symbols],
        }
    elif command == "assess":
        payload = assess_source_split(
            Path(args.source),
            max_lines=args.max_lines,
            target_prefix=args.target_prefix,
            write_plan=args.write_plan,
            headroom_lines=args.headroom,
            command_prefix=command_prefix,
        )
    elif command == "large":
        exclude_dirs = tuple(args.exclude_dir) if args.exclude_dir else ()
        roots = [Path(root) for root in args.roots]
        extensions = resolve_source_split_extensions(
            tuple(args.profile) if args.profile else ("auto",),
            roots=roots,
            extensions=tuple(args.ext),
        )
        files = large_source_files(
            roots,
            max_lines=args.max_lines,
            extensions=extensions,
            exclude_dirs=exclude_dirs
            or (
                ".git",
                ".venv",
                "venv",
                "__pycache__",
                "node_modules",
                "dist",
                "build",
                "reference",
            ),
        )
        if args.assess:
            for item in files:
                item["assessment"] = assess_source_split(
                    Path(str(item["path"])),
                    max_lines=args.max_lines,
                    command_prefix=command_prefix,
                )
        if not args.detail and not args.assess:
            files = [
                {
                    "path": item["path"],
                    "language": item["language"],
                    "code_lines": item["code_lines"],
                    "largest_symbol": item["line_summary"].get("largest_symbol"),
                    "symbol_count": item["line_summary"].get("symbol_count"),
                }
                for item in files
            ]
        payload = {
            "max_lines": args.max_lines,
            "profiles": list(args.profile) if args.profile else ["auto"],
            "extensions": list(extensions),
            "files": files,
        }
    elif command == "project":
        exclude_dirs = (
            tuple(args.exclude_dir)
            if args.exclude_dir
            else (
                ".git",
                ".venv",
                "venv",
                "__pycache__",
                "node_modules",
                "dist",
                "build",
                "reference",
            )
        )
        payload = project_source_split_plan(
            [Path(root) for root in args.roots],
            max_lines=args.max_lines,
            profiles=tuple(args.profile) if args.profile else ("auto",),
            extensions=tuple(args.ext),
            exclude_dirs=exclude_dirs,
            limit=args.limit,
            write_plans=args.write_plans,
            headroom_lines=args.headroom,
            command_prefix=command_prefix,
        )
        if not args.detail:
            payload = _compact_project_payload(payload)
    else:
        source = Path(args.source)
        plan_file = Path(args.plan_file) if args.plan_file else None
        cleanup_plan_file = _resolved_cleanup_plan_file(source, args.move, plan_file)
        moves = parse_move_plan(source, args.move, plan_file)
        if command == "plan":
            payload = plan_source_split(source, moves).to_payload()
        elif args.check:
            payload = _check_apply_source_split(
                source,
                moves,
                keep_compat_imports=not args.no_compat_imports,
                force=args.force,
                package_relative=not args.plain_imports,
                max_lines=args.max_lines,
            )
            check_payload = payload["check"]
            if not isinstance(check_payload, dict) or not check_payload.get("ok"):
                print(json.dumps(payload, indent=2, sort_keys=True) if args.json else "")
                raise SystemExit(1)
        else:
            plan = apply_source_split(
                source,
                moves,
                keep_compat_imports=not args.no_compat_imports,
                force=args.force,
                package_relative=not args.plain_imports,
            )
            payload = plan.to_payload()
            # Post-write reporting must never mask a successful apply.
            enrichments: dict[str, Callable[[], object]] = {
                "result_outline": lambda: _result_outline(source, moves),
                "import_impact": lambda: import_impact_report(source, moves),
                "review_command": lambda: _review_command(source, moves),
            }
            if not args.no_lint_fix:
                enrichments["lint"] = lambda: fix_lint_after_split(
                    source,
                    moves,
                    typecheck=args.typecheck,
                )
            else:
                payload["lint"] = skipped_toolchain_payload("skipped by --no-lint-fix")
            for key, build in enrichments.items():
                try:
                    payload[key] = build()
                except Exception as error:
                    logging.getLogger(__name__).warning("operation failed", exc_info=True)
                    payload[f"{key}_error"] = f"{type(error).__name__}: {error}"
            payload["review_notes"] = [
                "Review moved lines with the review_command before semantic edits.",
                "Commit the split as its own clean commit so git blame -C -C keeps attribution across files.",
            ]
            if args.check or args.max_lines is not None:
                check = check_split_result(source, moves, max_lines=args.max_lines)
                payload["check"] = check.to_payload()
                if not check.ok:
                    print(json.dumps(payload, indent=2, sort_keys=True) if args.json else "")
                    raise SystemExit(1)
            if cleanup_plan_file is not None and _split_apply_verified(payload):
                _cleanup_split_plan_file(payload, cleanup_plan_file)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_source_split_payload(payload)


def _adapter_payload(source: Path | None) -> dict[str, object]:
    discover_adapter_manifests((source or Path.cwd(),))
    installed = []
    selected = language_adapter_for(source) if source is not None else None
    for adapter in language_adapters():
        entry: dict[str, object] = {
            "id": adapter.id,
            "extensions": list(adapter.extensions),
            "profiles": list(adapter.profiles),
        }
        if source is not None and adapter is selected:
            entry["selected"] = True
            entry["capabilities"] = adapter.capabilities(source).to_payload()
        installed.append(entry)
    tools = [
        {
            "id": adapter.id,
            "kind": adapter.kind,
            "extensions": list(adapter.extensions),
            "default_enabled": adapter.default_enabled,
            "matched": source is not None and source.suffix in adapter.extensions,
        }
        for adapter in toolchain_adapters()
    ]
    return {
        "protocol_version": 2,
        "source": str(source) if source is not None else None,
        "selected": selected.id if selected is not None else None,
        "adapters": installed,
        "toolchains": tools,
        "load_errors": list(adapter_load_errors()),
        "toolchain_load_errors": list(toolchain_load_errors()),
        "plugin_entry_point": "katana.adapters",
        "toolchain_entry_point": "katana.toolchains",
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    handle_katana_command(args)


def _resolved_cleanup_plan_file(
    source: Path,
    move_specs: list[str],
    plan_file: Path | None,
) -> Path | None:
    if plan_file is not None:
        return plan_file if _is_ephemeral_split_plan(plan_file) else None
    if move_specs:
        return None
    for candidate in (
        source.with_suffix(KATANA_PLAN_SUFFIX),
        source.with_suffix(LEGACY_SOURCE_SPLIT_PLAN_SUFFIX),
    ):
        if candidate.exists():
            return candidate
    return None


def _is_ephemeral_split_plan(path: Path) -> bool:
    text = str(path)
    return text.endswith((KATANA_PLAN_SUFFIX, LEGACY_SOURCE_SPLIT_PLAN_SUFFIX))


def _split_apply_verified(payload: dict[str, object]) -> bool:
    if any(key.endswith("_error") for key in payload):
        return False
    check = payload.get("check")
    if isinstance(check, dict) and check.get("ok") is False:
        return False
    lint = payload.get("lint")
    if isinstance(lint, dict):
        diagnostics = lint.get("diagnostics")
        if isinstance(diagnostics, list) and diagnostics:
            return False
    return True


def _cleanup_split_plan_file(payload: dict[str, object], plan_file: Path) -> None:
    if not plan_file.exists():
        return
    try:
        plan_file.unlink()
    except OSError as error:
        payload["plan_file_cleanup_error"] = f"{type(error).__name__}: {error}"
    else:
        payload["plan_file_removed"] = str(plan_file)


def _compact_project_payload(payload: dict[str, object]) -> dict[str, object]:
    compact = dict(payload)
    assessments = compact.get("assessments")
    if isinstance(assessments, list):
        compact["assessments"] = [
            _compact_assessment(assessment)
            for assessment in assessments
            if isinstance(assessment, dict)
        ]
    return compact


def _compact_assessment(assessment: dict[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {
        key: assessment[key]
        for key in (
            "source",
            "language",
            "code_lines",
            "max_lines",
            "oversized",
            "status",
            "risk",
            "reason",
            "line_summary",
            "plan_file",
            "commands",
        )
        if key in assessment
    }
    agent_value = assessment.get("agent")
    if isinstance(agent_value, dict):
        compact["agent"] = {
            key: agent_value[key]
            for key in (
                "decision",
                "confidence",
                "summary",
                "next_step",
                "requires_human_review",
                "parser_precision",
                "parser_available",
                "review_notes",
                "verification_commands",
            )
            if key in agent_value
        }
    suggested = assessment.get("suggested_plan")
    if isinstance(suggested, dict):
        moves = suggested.get("moves")
        compact["suggested_plan"] = {
            "source": suggested.get("source"),
            "warnings": suggested.get("warnings", []),
            "moved_symbols_count": len(suggested.get("moved_symbols") or []),
            "moves": [_compact_suggested_move(move) for move in moves if isinstance(move, dict)]
            if isinstance(moves, list)
            else [],
        }
    return compact


def _compact_suggested_move(move: dict[str, object]) -> dict[str, object]:
    symbols = move.get("symbols")
    symbol_names = [str(symbol) for symbol in symbols] if isinstance(symbols, list) else []
    return {
        "target": move.get("target"),
        "symbol_count": len(symbol_names),
        "preview_symbols": symbol_names[:8],
        "moved_code_lines": move.get("moved_code_lines"),
        "estimated_source_code_lines_after_move": move.get(
            "estimated_source_code_lines_after_move"
        ),
        "produced_files": move.get("produced_files"),
        "reason": move.get("reason"),
    }
