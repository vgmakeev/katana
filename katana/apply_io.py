from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import SPLIT_PLAN_VERSION, SourceSplitMove
from .source_io import encode_source_text, source_newline


def _load_split_plan_payload(plan_file: Path) -> dict[str, Any]:
    import json

    payload = json.loads(plan_file.read_text())
    if not isinstance(payload, dict):
        raise TypeError("Split plan must be a JSON object")

    allowed_top_level = {"version", "source", "moves", "moved_symbols", "warnings"}
    for key in payload:
        if key not in allowed_top_level:
            raise ValueError(f"Unknown split plan key: {key}")

    version = int(payload.get("version", SPLIT_PLAN_VERSION))
    if version != SPLIT_PLAN_VERSION:
        raise ValueError(f"Unsupported split plan version {version}; expected {SPLIT_PLAN_VERSION}")

    if "moves" not in payload:
        raise ValueError("Split plan must include moves")
    raw_moves = payload["moves"]
    if not isinstance(raw_moves, list):
        raise TypeError("Split plan moves must be an array")

    allowed_move_keys = {"target", "symbols"}
    for index, raw in enumerate(raw_moves):
        if not isinstance(raw, dict):
            raise TypeError(f"Split plan moves[{index}] must be an object")
        for key in raw:
            if key not in allowed_move_keys:
                raise ValueError(f"Unknown split plan moves[{index}] key: {key}")
        for key in ("target", "symbols"):
            if key not in raw:
                raise ValueError(f"Split plan moves[{index}] must include {key}")

    return payload


def _write_split_outputs(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
    outputs: dict[Path, str],
) -> None:
    init_outputs = _package_init_outputs(source, moves)
    write_outputs = {**init_outputs, **outputs}
    target_paths = [path for path in (move.target for move in moves) if path in outputs]
    paths = list(dict.fromkeys([*init_outputs, *target_paths, source]))
    for path in paths:
        parent = path.parent
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"Split target parent is not a directory: {parent}")
        if path.exists() and not path.is_file():
            raise ValueError(f"Split output is not a file: {path}")
        _validate_writable_output(path)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        newline_owner = path if path.exists() and path.stat().st_size else source
        path.write_bytes(
            encode_source_text(write_outputs[path], newline=source_newline(newline_owner))
        )


def _package_init_outputs(
    source: Path,
    moves: tuple[SourceSplitMove, ...],
) -> dict[Path, str]:
    outputs: dict[Path, str] = {}
    for move in moves:
        if move.target.suffix != ".py":
            continue
        parent = move.target.parent
        while source.parent in parent.parents:
            init = parent / "__init__.py"
            if not init.exists():
                outputs[init] = ""
            parent = parent.parent
    return outputs


def _validate_writable_output(path: Path) -> None:
    if path.exists():
        if not os.access(path, os.W_OK):
            raise ValueError(f"Split output is not writable: {path}")
        return
    parent = path.parent
    while not parent.exists():
        parent = parent.parent
    if not os.access(parent, os.W_OK):
        raise ValueError(f"Split output parent is not writable: {parent}")
