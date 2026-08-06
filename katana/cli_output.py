from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import cast

from katana import (
    SourceSplitMove,
    apply_source_split,
    check_split_result,
    import_impact_report,
    outline_source_file,
    source_code_line_count,
)
from katana.toolchain import skipped_toolchain_payload


def _check_apply_source_split(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    *,
    keep_compat_imports: bool,
    force: bool,
    package_relative: bool,
    max_lines: int | None,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="katana-apply-check-") as tmp:
        sandbox_dir = Path(tmp) / "source"
        sandbox_dir.mkdir(parents=True)
        sandbox_source = sandbox_dir / source.name
        shutil.copy2(source, sandbox_source)

        path_map: dict[Path, Path] = {sandbox_source: source}
        sandbox_moves: list[SourceSplitMove] = []
        for move in moves:
            try:
                target_relative = move.target.relative_to(source.parent)
            except ValueError as error:
                raise ValueError(
                    "Split targets must be inside the source module directory"
                ) from error
            sandbox_target = sandbox_dir / target_relative
            sandbox_target.parent.mkdir(parents=True, exist_ok=True)
            if move.target.exists():
                shutil.copy2(move.target, sandbox_target)
            path_map[sandbox_target] = move.target
            sandbox_moves.append(SourceSplitMove(sandbox_target, move.symbols))

        sandbox_move_tuple = tuple(sandbox_moves)
        plan = apply_source_split(
            sandbox_source,
            sandbox_move_tuple,
            keep_compat_imports=keep_compat_imports,
            force=force,
            package_relative=package_relative,
        )
        payload = cast(dict[str, object], _remap_split_payload_paths(plan.to_payload(), path_map))
        payload["dry_run"] = True
        payload["result_outline"] = _remap_split_payload_paths(
            _result_outline(sandbox_source, sandbox_move_tuple),
            path_map,
        )
        payload["import_impact"] = _remap_split_payload_paths(
            import_impact_report(sandbox_source, sandbox_move_tuple),
            path_map,
        )
        payload["review_command"] = _review_command(source, moves)
        payload["lint"] = skipped_toolchain_payload("skipped during --check dry-run")
        payload["review_notes"] = [
            "Dry-run only: no source or target files were written.",
            "Review moved lines with the review_command before semantic edits.",
            "Commit the split as its own clean commit so git blame -C -C keeps attribution across files.",
        ]
        check = check_split_result(sandbox_source, sandbox_move_tuple, max_lines=max_lines)
        payload["check"] = _remap_split_payload_paths(check.to_payload(), path_map)
        return payload


def _remap_split_payload_paths(value: object, path_map: dict[Path, Path]) -> object:
    if isinstance(value, dict):
        return {key: _remap_split_payload_paths(item, path_map) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap_split_payload_paths(item, path_map) for item in value]
    if isinstance(value, str):
        result = value
        for sandbox_path, real_path in sorted(
            path_map.items(),
            key=lambda item: len(str(item[0])),
            reverse=True,
        ):
            result = result.replace(str(sandbox_path), str(real_path))
        return result
    return value


def _result_outline(source: Path, moves: tuple[SourceSplitMove, ...]) -> list[dict[str, object]]:
    # Structural control for the agent: signatures and sizes of every touched
    # file after the split, without reading the code.
    outline: list[dict[str, object]] = []
    for path in (source, *(move.target for move in moves)):
        entry: dict[str, object] = {
            "path": str(path),
            "code_lines": source_code_line_count(path),
        }
        try:
            entry["symbols"] = [
                {
                    "name": symbol.name,
                    "kind": symbol.kind,
                    "signature": symbol.signature,
                    "code_lines": symbol.code_lines,
                }
                for symbol in outline_source_file(path)
            ]
        except (SyntaxError, ValueError) as error:
            entry["error"] = str(error)
        outline.append(entry)
    return outline


def _review_command(source: Path, moves: tuple[SourceSplitMove, ...]) -> str:
    paths = " ".join(str(path) for path in (source, *(move.target for move in moves)))
    return f"git diff --color-moved=dimmed-zebra -- {paths}"


def _print_source_split_payload(payload: dict[str, object]) -> None:
    if "source" in payload:
        print(f"Source: {payload['source']}")
    agent = payload.get("agent")
    if isinstance(agent, dict):
        print(f"Decision: {agent.get('decision')} confidence={agent.get('confidence')}")
        print(f"Summary: {agent.get('summary')}")
        print(f"Next: {agent.get('next_step')}")
        safe_moves = agent.get("safe_moves")
        if isinstance(safe_moves, dict):
            groups = safe_moves.get("groups") or []
            for raw in groups if isinstance(groups, list) else []:
                if isinstance(raw, dict):
                    print(
                        f"Safe move {raw.get('seed')}: {raw.get('code_lines')} lines -> "
                        f"{', '.join(str(name) for name in raw.get('symbols') or [])}"
                    )
        notes = agent.get("review_notes") or []
        if isinstance(notes, list):
            for note in notes:
                print(f"Review: {note}")
        verifications = agent.get("verification_commands") or []
        if isinstance(verifications, list):
            for command in verifications:
                print(f"Verify: {command}")
        return
    symbols = payload.get("symbols")
    if isinstance(symbols, list):
        for raw in symbols:
            if not isinstance(raw, dict):
                continue
            refs = raw.get("references") or []
            refs_text = f" refs={','.join(refs)}" if refs else ""
            tags = raw.get("tags") or []
            tags_text = f" tags={','.join(tags)}" if tags else ""
            print(
                f"{raw['start_line']:>5}-{raw['end_line']:<5} "
                f"{raw['code_lines']:>4} {raw['kind']:<16} "
                f"{raw['signature']}{tags_text}{refs_text}"
            )
        return

    files = payload.get("files")
    if isinstance(files, list):
        for raw in files:
            if not isinstance(raw, dict):
                continue
            print(f"{raw['code_lines']:>5} {raw['path']}")
        return

    assessments = payload.get("assessments")
    if isinstance(assessments, list):
        summary = payload.get("summary")
        if isinstance(summary, dict):
            print(
                f"Oversized: {summary.get('oversized_files')} "
                f"excess={summary.get('total_excess_lines')} "
                f"estimated_moved={summary.get('estimated_moved_code_lines')}"
            )
        for raw in assessments:
            if not isinstance(raw, dict):
                continue
            agent_value = raw.get("agent")
            agent = agent_value if isinstance(agent_value, dict) else {}
            print(
                f"{raw.get('code_lines'):>5} {raw.get('source')} "
                f"decision={agent.get('decision')} confidence={agent.get('confidence')}"
            )
        return

    moves = payload.get("moves")
    for raw in moves if isinstance(moves, list | tuple) else ():
        if isinstance(raw, dict):
            print(f"Move -> {raw['target']}: {', '.join(raw['symbols'])}")
    warnings = payload.get("warnings")
    for warning in warnings if isinstance(warnings, list | tuple) else ():
        print(f"Warning: {warning}")
