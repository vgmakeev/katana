from __future__ import annotations

from typing import Any

from .models import SourceSplitPlan, SourceSymbol


def _suggested_plan_payload(
    plan: SourceSplitPlan,
    symbols: list[SourceSymbol],
    code_lines: int,
    *,
    max_lines: int,
    headroom_lines: int,
) -> dict[str, Any]:
    payload = plan.to_payload()
    by_name = {symbol.name: symbol for symbol in symbols}
    remaining = code_lines
    moves: list[dict[str, Any]] = []
    for move in plan.moves:
        move_payload = move.to_payload()
        move_symbols = [by_name[name] for name in move.symbols if name in by_name]
        moved_lines = sum(symbol.code_lines for symbol in move_symbols)
        remaining = max(remaining - moved_lines, 0)
        move_payload.update(
            {
                "symbol_payloads": [
                    symbol.to_payload(total_code_lines=code_lines) for symbol in move_symbols
                ],
                "moved_code_lines": moved_lines,
                "moved_code_lines_pct": round(moved_lines * 100 / code_lines, 1)
                if code_lines
                else 0,
                "estimated_source_code_lines_after_move": remaining,
                "produced_files": [
                    {
                        "path": str(plan.source),
                        "projected_lines": remaining,
                        "headroom": max_lines - remaining,
                    },
                    {
                        "path": str(move.target),
                        "projected_lines": moved_lines,
                        "headroom": max_lines - moved_lines,
                    },
                ],
                "reason": _move_reason(move_symbols),
            }
        )
        moves.append(move_payload)
    payload["moves"] = moves
    return payload


def _move_reason(symbols: list[SourceSymbol]) -> str:
    if not symbols:
        return "No matching symbols found for this move."
    tags = sorted({tag for symbol in symbols for tag in symbol.tags})
    refs = sorted({ref for symbol in symbols for ref in symbol.references})
    total_lines = sum(symbol.code_lines for symbol in symbols)
    parts = [f"Moves {len(symbols)} connected symbol(s) totaling {total_lines} code lines"]
    if tags:
        parts.append(f"tags={','.join(tags)}")
    if refs:
        parts.append(f"refs={','.join(refs)}")
    return "; ".join(parts)
