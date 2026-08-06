# Contributing

Katana is a production refactoring tool. Compatibility and fail-closed behavior
matter more than accepting a larger set of files optimistically.

## Setup

```bash
uv sync --all-groups
make check
```

Python 3.14 is the supported runtime. Node is optional for the Python core and
required only for TypeScript, PostCSS, and TanStack Markdown bridges.

## Change rules

- Do not change split-plan v1 or existing CLI JSON values without a versioned
  compatibility layer.
- Keep commands non-interactive and make agent-facing state machine-readable.
- Maps must not contain source bodies.
- Analysis-only adapters must reject rewrite.
- External commands run without a shell, with a timeout, and must return
  versioned JSON.
- Language parsing and toolchain execution stay in their separate adapter
  contracts.
- Add a conformance or snapshot test for every adapter contract change.
- Preserve source bytes during a mechanical move; semantic edits belong in a
  separate change.

Before opening a pull request, run:

```bash
make check
make markdown-check  # when Node bridge behavior changed
uv build
```

## Adapter contributions

Start with an analysis-only adapter. A rewrite capability is accepted only when
the adapter proves exact locations, dependency closure, module edits, formatter
integration, and language validation. See [docs/ADAPTERS.md](docs/ADAPTERS.md).

Formatter, linter, and checker integrations use the independent
[`ToolchainAdapter` contract](docs/TOOLCHAINS.md).
