# Toolchain SDK

Language analysis and post-processing are separate extension points. A
`LanguageAdapter` understands source structure; a `ToolchainAdapter` invokes a
stack's formatter, linter, or checker after a split.

## Contract

```python
from pathlib import Path

from katana import Diagnostic
from katana.toolchains import SkippedTool, ToolchainContext


class GoFmtAdapter:
    id = "gofmt"
    kind = "formatter"
    extensions = (".go",)
    default_enabled = True

    def detect(self, context: ToolchainContext) -> SkippedTool | None:
        ...

    def fix(self, files: list[Path]) -> list[Diagnostic]:
        ...

    def check(self, files: list[Path]) -> list[Diagnostic]:
        ...
```

The runner executes enabled adapters in three phases:

1. formatters mutate touched files;
2. linters apply their safe fixes;
3. every adapter checks the resulting files and returns normalized diagnostics.

Checkers with `default_enabled = False` run when the agent passes
`katana apply --typecheck`.

## Publishing

Expose an adapter instance or class through the `katana.toolchains` entry-point
group:

```toml
[project.entry-points."katana.toolchains"]
gofmt = "katana_go:GofmtAdapter"
golangci = "katana_go:GolangciLintAdapter"
go_check = "katana_go:GoCheckAdapter"
```

Run `katana adapters --json` to inspect loaded language and toolchain adapters.
Third-party load failures are isolated and reported in
`toolchain_load_errors`.

## Design rules

- Invoke commands as argument arrays, never through a shell.
- Detect project-local binaries and configuration before global tools.
- Limit mutations to files Katana reports as touched.
- Use formatter and safe lint fixes by default; semantic or unsafe fixes require
  explicit project configuration.
- Normalize diagnostics instead of exposing tool-specific output to the agent.
- Keep compiler/test adapters check-only.

Bundled reference implementations live under `katana.toolchains.python`,
`katana.toolchains.typescript`, and `katana.toolchains.dart`.
