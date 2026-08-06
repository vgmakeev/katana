# Katana

Katana is a refactoring executor for coding agents. It lets an agent redesign a
large file without reading the whole file into its context:

```text
source file -> compact architecture map -> agent-authored split plan
            -> deterministic rewrite -> formatter/linter/typecheck -> report
```

Katana does not ask an LLM to copy code between files. Language adapters inspect
the source with the best parser available, expose signatures and constraints,
and move the selected source ranges byte-for-byte.

The primary user is an AI agent, not a human at a terminal. Commands are
non-interactive, JSON contracts are stable, maps are source-free, and every
mutation can be checked before it is committed.

Katana requires Python 3.14 and has no mandatory runtime dependencies.

## Install from GitHub

```bash
uv tool install git+https://github.com/vgmakeev/kanata.git
katana --help
```

The repository is named `kanata`; the established Python import and CLI remain
`katana`. The PyPI distribution remains `mini-katana` for compatibility until a
standalone distribution name is selected.

## Quick start

```bash
# Find oversized files using language-aware LOC counters.
katana large src docs --max-lines 750 --json

# Give the agent a compact map, not the source body.
katana map src/big_module.py --json

# Produce a safe-move menu and an editable plan.
katana assess src/big_module.py --max-lines 750 --write-plan --json

# Validate without writing, then apply and run detected project tools.
katana apply src/big_module.py --plan-file src/big_module.katana.json --check --json
katana apply src/big_module.py --plan-file src/big_module.katana.json --typecheck --json
```

The agent owns architecture: responsibility boundaries, target names, and the
final choice of move groups. Katana owns mechanics: spans, dependency closure,
import surgery, collision checks, formatting, diagnostics, and post-write maps.

## Agent contract

`katana map` emits `DocumentIR` version 2. It contains:

- physical and code LOC;
- symbol signatures and nested symbol summaries;
- deterministic symbol ids and byte-exact, end-exclusive source spans;
- local references with an explicit confidence level;
- move constraints such as `closure`, `pinned`, and `preserve` order;
- parser capabilities and limitations;
- safe move groups the agent may compose.

It deliberately contains no source bodies. The existing `outline` payload and
split-plan version 1 remain supported for compatibility.

The canonical agent loop is documented in
[the agent protocol](docs/AGENT_PROTOCOL.md).

## Polyglot adapters

There is no honest universal AST: parsers disagree on trivia, scopes, bindings,
module systems, and error recovery. Katana makes the intermediate representation
universal instead. An adapter may use:

1. a native compiler API for the highest semantic precision;
2. Tree-sitter or ast-grep for broad concrete-syntax coverage;
3. LSP/SCIP for resolved symbols and workspace references;
4. a conservative structural scanner as a read-only fallback.

Every adapter reports capabilities separately for source locations, hierarchy,
comments, local bindings, module/workspace rewrites, formatting, and validation.
Missing semantics therefore degrade visibly instead of pretending to be safe.

Built-ins cover Python, TypeScript/JavaScript, Dart, CSS, Markdown, and MDX.
Run `katana adapters --json` or `katana adapters path/to/file --check --json` to
inspect parser availability and validate an adapter's output.

Bundled languages use the same public contracts as third-party packages. Their
adapter boundaries live under `katana.adapters.<stack>` and their
post-processing under `katana.toolchains.<stack>`; core contains no
stack-selection branches.

| Stack | Preferred backend | Conservative fallback |
| --- | --- | --- |
| Python | stdlib AST | none required |
| TypeScript/JavaScript | TypeScript compiler API | structural scanner |
| Dart | analyzer package | structural scanner |
| CSS | PostCSS | structural scanner |
| Markdown/MDX | exact heading spans + optional TanStack AST | heading spans |
| Any other stack | Python entry point or JSON command adapter | analysis-only |

### Adding a language

Analysis-only adapters are intentionally small and cannot rewrite files:

```python
from katana import AnalysisLanguageAdapter

class GoAdapter(AnalysisLanguageAdapter):
    id = "tree-sitter-go"
    extensions = (".go",)
    profiles = ("go", "all")

    def language_for(self, path):
        return "go"

    def capabilities(self, path):
        ...

    def outline(self, path):
        ...  # Return ordered SourceSymbol values with exact line spans.
```

Publish the instance or class through the Python entry-point group
`katana.adapters`:

```toml
[project.entry-points."katana.adapters"]
go = "katana_go:GoAdapter"
```

For adapters written in Go, Rust, Node, JVM languages, or any other stack, add
`.katana/adapters.json` and implement the versioned stdin/stdout JSON protocol.
Command protocol v1 is deliberately analysis-only and refuses rewrite. See
[the adapter SDK](docs/ADAPTERS.md).

Formatter, lint-fix, and checker integrations are independent toolchain
adapters. Publish them through `katana.toolchains`; see
[the toolchain SDK](docs/TOOLCHAINS.md).

Start with map/LOC support. Implement rewrite only after the adapter can prove
source locations, dependency closure, module edits, formatting, and validation.
Katana's conformance checker rejects stale hashes, duplicate ids, invalid spans,
and dangling reference targets.

## Markdown

Markdown is a document language, so Katana maps and moves heading sections just
like code symbols. Exact spans come from Katana's source scanner. If
`@tanstack/markdown` is installed, its deterministic AST enriches the map with a
compact node summary. It is not used as the span authority because its heading
callbacks are not a general source-location API.

```bash
npm install                         # installs the optional AST enrichment here
katana map docs/long-guide.md --json
katana assess docs/long-guide.md --max-lines 500 --write-plan --json
```

MDX remains conservative: Katana can split heading sections, but reports that
imports and rendered links still require project validation.

## Split plan

```json
{
  "version": 1,
  "source": "src/big_module.py",
  "moves": [
    {"target": "billing.py", "symbols": ["Invoice", "charge"]}
  ]
}
```

Targets are resolved relative to the source directory. Existing targets are
merged only after collision and cycle checks. `--force` accepts warnings where
the language adapter allows it. Run `katana schema --json` for the full schema.

## Safety model

- Source bodies are moved byte-for-byte.
- Unsupported semantics are capabilities and warnings, never hidden guesses.
- `apply --check` performs the rewrite in a temporary tree first.
- Targets, collisions, cycles, parser output, and line budgets are validated.
- Project-local formatters, linters, and optional typecheckers are detected and
  their normalized diagnostics are returned to the agent.
- External parser/tool processes are timeout-bounded and failures fall back or
  become explicit diagnostics.

Katana currently performs one-file architectural splits. Workspace-wide import
rewrites and richer Tree-sitter/LSP adapters are the next protocol layer, not an
implicit promise of the current adapters.

## Project documents

- [Architecture](ARCHITECTURE.md)
- [Agent protocol](docs/AGENT_PROTOCOL.md)
- [Adapter SDK](docs/ADAPTERS.md)
- [Toolchain SDK](docs/TOOLCHAINS.md)
- [Compatibility policy](docs/COMPATIBILITY.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Release checklist](docs/RELEASING.md)
