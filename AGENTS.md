# Agent instructions

Katana is an agent-first, deterministic polyglot refactoring executor.

## Runtime

- Use Python 3.14.
- Install with `uv sync --all-groups`.
- Run the complete gate with `make check`.
- Run `make markdown-check` when the Node bridge changes.

## Boundaries

- Core owns `DocumentIR`, plans, conformance, apply orchestration, and the CLI.
- Language behavior belongs in `katana.adapters.<stack>` or an external package
  registered under `katana.adapters`.
- Formatter, lint-fix, and checker behavior belongs in
  `katana.toolchains.<stack>` or `katana.toolchains` entry points.
- Built-in adapters use the same public contracts as third-party adapters.
- Command adapter protocol v1 is analysis-only and must fail rewrite closed.

## Compatibility

- Preserve split-plan v1 and existing `schema`, `outline`, `assess`, `plan`,
  `apply`, `large`, and `project` JSON behavior.
- Keep legacy adapter ids `node_typescript`, `dart_analyzer`, and
  `node_postcss`.
- Existing public functions remain compatibility facades over adapters.
- Add conformance and regression tests for protocol changes.

## Agent contract

- Never include source bodies in `DocumentIR` or other agent maps.
- Keep commands non-interactive and machine-readable.
- Prefer exact hashes and byte spans over parser-specific node objects.
- Analysis-only support is useful; do not claim rewrite capabilities without
  dependency closure, import handling, formatting, and validation.
- Preserve source bytes during mechanical moves. Semantic changes are separate.

## Source budget

- Design source files around 500 physical and language-aware code lines.
- The hard repository ceiling is 550 lines: the 500-line target plus 10% headroom.
- `make size-check` enforces both measures across runtime, tests, and examples.
- Split by cohesive responsibility before raising the ceiling or adding exclusions.
