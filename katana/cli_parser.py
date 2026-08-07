from __future__ import annotations

import argparse

from katana import SOURCE_SPLIT_EXTENSIONS, SOURCE_SPLIT_PROFILES


def _add_katana_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    schema = commands.add_parser(
        "schema",
        help="Print the split plan JSON Schema.",
        description="Print the split plan JSON Schema.",
    )
    schema.add_argument("--json", action="store_true")

    adapters = commands.add_parser(
        "adapters",
        help="List installed language adapters and their capabilities.",
        description="List installed Katana language adapters.",
    )
    adapters.add_argument(
        "source",
        nargs="?",
        help="Optional source file used to resolve dynamic parser capabilities.",
    )
    adapters.add_argument(
        "--schema",
        action="store_true",
        help="Print the project command-adapter manifest JSON Schema.",
    )
    adapters.add_argument(
        "--check",
        action="store_true",
        help="Validate the selected adapter's DocumentIR against the source.",
    )
    adapters.add_argument("--json", action="store_true")

    source_map = commands.add_parser(
        "map",
        help="Build a compact, source-free architecture map for one file.",
        description=(
            "Emit signatures, LOC, dependencies, exact spans and move constraints "
            "without returning source bodies."
        ),
    )
    source_map.add_argument("source")
    source_map.add_argument("--json", action="store_true")

    outline = commands.add_parser(
        "outline",
        help="List top-level symbols in one source file.",
        description="List top-level symbols in one source file.",
    )
    outline.add_argument("source")
    outline.add_argument("--json", action="store_true")

    assess = commands.add_parser(
        "assess",
        help="Assess one file and suggest a safe split plan.",
        description="Assess one file and suggest a safe split plan.",
    )
    assess.add_argument("source")
    assess.add_argument("--max-lines", type=int, default=500)
    assess.add_argument("--headroom", type=int, help="Planning margin below --max-lines.")
    assess.add_argument("--target-prefix")
    assess.add_argument(
        "--write-plan",
        action="store_true",
        help="Write the suggested plan to <source>.katana.json for apply --plan-file.",
    )
    assess.add_argument("--json", action="store_true")

    large = commands.add_parser(
        "large",
        help="Find files over the configured line budget.",
        description="Find files over the configured line budget.",
    )
    large.add_argument("roots", nargs="+")
    large.add_argument("--max-lines", type=int, default=500)
    large.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Directory name to exclude. May be repeated.",
    )
    large.add_argument(
        "--ext",
        action="append",
        default=[],
        help=(
            "Extra file extension to include, e.g. .tsx. "
            f"Supported extensions: {', '.join(SOURCE_SPLIT_EXTENSIONS)}."
        ),
    )
    large.add_argument(
        "--profile",
        action="append",
        default=[],
        help=(
            "Source family to include. Defaults to auto, which always includes core "
            "Python/Markdown and detects admin/next/flutter markers. May be repeated. "
            f"Known profiles: auto, {', '.join(sorted(SOURCE_SPLIT_PROFILES))}."
        ),
    )
    large.add_argument(
        "--assess",
        action="store_true",
        help="Include full agent assessment for each oversized file.",
    )
    large.add_argument(
        "--detail",
        action="store_true",
        help="Include full outlines per file. Default output is a compact list.",
    )
    large.add_argument("--json", action="store_true")

    project = commands.add_parser(
        "project",
        help="Assess oversized files across a project.",
        description="Assess oversized files across a project.",
    )
    project.add_argument("roots", nargs="+")
    project.add_argument("--max-lines", type=int, default=500)
    project.add_argument("--headroom", type=int, help="Planning margin below --max-lines.")
    project.add_argument(
        "--profile",
        action="append",
        default=[],
        help=(
            "Source family to include. Defaults to auto. May be repeated. "
            f"Known profiles: auto, {', '.join(sorted(SOURCE_SPLIT_PROFILES))}."
        ),
    )
    project.add_argument(
        "--ext",
        action="append",
        default=[],
        help=f"Extra extension to include. Supported: {', '.join(SOURCE_SPLIT_EXTENSIONS)}.",
    )
    project.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Directory name to exclude. May be repeated.",
    )
    project.add_argument("--limit", type=int)
    project.add_argument(
        "--write-plans",
        action="store_true",
        help="Write .katana.json files for suggested plans.",
    )
    project.add_argument(
        "--detail",
        action="store_true",
        help=(
            "Include full symbols and safe-move menus. Default JSON is compact "
            "so project-wide scans stay readable."
        ),
    )
    project.add_argument("--json", action="store_true")

    plan = commands.add_parser(
        "plan",
        help="Validate and echo an explicit move plan.",
        description="Validate and echo an explicit move plan.",
    )
    plan.add_argument("source")
    plan.add_argument(
        "--move",
        action="append",
        default=[],
        metavar="TARGET.ext:SYMBOL[,SYMBOL...]",
        help="Move top-level symbols into a target file relative to the source file.",
    )
    plan.add_argument("--plan-file", help="JSON move plan with moves[].target and moves[].symbols.")
    plan.add_argument("--json", action="store_true")

    apply = commands.add_parser(
        "apply", help="Apply an explicit split plan.", description="Apply an explicit split plan."
    )
    apply.add_argument("source")
    apply.add_argument(
        "--move",
        action="append",
        default=[],
        metavar="TARGET.ext:SYMBOL[,SYMBOL...]",
        help="Move top-level symbols into a target file relative to the source file.",
    )
    apply.add_argument(
        "--plan-file", help="JSON move plan with moves[].target and moves[].symbols."
    )
    apply.add_argument("--force", action="store_true")
    apply.add_argument("--check", action="store_true")
    apply.add_argument("--max-lines", type=int, default=None)
    apply.add_argument(
        "--no-compat-imports",
        action="store_true",
        help="Do not leave from .target import symbol compatibility imports in the source file.",
    )
    apply.add_argument(
        "--no-lint-fix",
        action="store_true",
        help="Skip detected project formatter/linter adapters over the split files.",
    )
    apply.add_argument(
        "--plain-imports",
        action="store_true",
        help=(
            "Generate plain sibling imports instead of package-relative imports. "
            "Use for standalone Python files in directories without __init__.py."
        ),
    )
    apply.add_argument(
        "--typecheck", action="store_true", help="Run optional check-only tsc/mypy after apply."
    )
    apply.add_argument("--json", action="store_true")
