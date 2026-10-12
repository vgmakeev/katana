<div align="center">

# Katana

**Give the agent structure. Let Katana move the code.**

Deterministic, polyglot refactoring infrastructure for coding agents.

[![CI](https://github.com/vgmakeev/katana/actions/workflows/ci.yml/badge.svg)](https://github.com/vgmakeev/katana/actions/workflows/ci.yml)
[![Apache-2.0](https://img.shields.io/github/license/vgmakeev/katana)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tree-sitter Rust](https://img.shields.io/badge/Rust-tree--sitter-dea584?logo=rust)](pyproject.toml)

</div>

Katana lets an AI agent redesign a large file without loading the whole file
into its context. It turns source into a compact architecture map, accepts an
explicit split plan, moves the selected source ranges byte-for-byte, and then
runs the project's own formatter, linter, and typechecker.

```text
large source file
      │
      ▼
source-free map ──► agent designs boundaries ──► explicit split plan
                                                        │
                                                        ▼
fresh maps ◄── format · lint · typecheck ◄── deterministic rewrite
```

The agent owns architecture. Katana owns mechanics.

## Why Katana?

Coding agents are good at architectural reasoning and bad at mechanically
copying thousands of tokens between files. Reading the entire source also
wastes context before the agent has decided what it needs.

Katana changes that boundary:

- **Small context:** the agent receives LOC, signatures, relationships,
  constraints, and exact spans—not source bodies.
- **Deterministic edits:** source ranges are moved byte-for-byte; Katana does
  not ask an LLM to reproduce code.
- **Fail-closed adapters:** unsupported semantics become visible limitations,
  never optimistic rewrite claims.
- **Native verification:** Katana invokes tools already configured by the
  project, such as Ruff, ESLint, Prettier, `tsc`, mypy, and `dart format`.
- **Agent-native protocol:** commands are non-interactive, JSON is versioned,
  and every mutation has a dry-run.
- **Small core:** Python 3.14 with focused Tree-sitter dependencies for safe Rust moves.

## Run with `uvx`

No installation is required:

```bash
uvx --from git+https://github.com/vgmakeev/katana.git katana --help
```

For a reproducible agent environment, pin a release tag or commit:

```bash
uvx --from git+https://github.com/vgmakeev/katana.git@<tag-or-commit> \
  katana map src/big_module.py --json
```

For a persistent installation:

```bash
uv tool install git+https://github.com/vgmakeev/katana.git
katana --help
```

The Python distribution is named `katana-agent`; the import package and CLI
remain `katana`. After the first PyPI release, the equivalent commands are:

```bash
uvx --from katana-agent katana --help
uv tool install katana-agent
```

> [!IMPORTANT]
> The unrelated `katana` name on PyPI belongs to another project. Use the
> `katana-agent` distribution or the GitHub source shown above; do not install
> the PyPI distribution named `katana`.

Katana runs inside the caller's working directory. It can inspect the project
paths passed to it even when executed from `uvx`'s isolated environment.

## The agent loop

### 1. Find files over the line budget

```bash
uvx --from git+https://github.com/vgmakeev/katana.git \
  katana large . --max-lines 500 --json
```

`large` scans project folders recursively and uses language-aware code LOC.
Generated and dependency directories such as `.git`, `.venv`, `node_modules`,
`dist`, and `build` are excluded by default.

Katana itself enforces a hard 500-line ceiling per source file.
The repository gate checks both language-aware code LOC and physical lines.

### 2. Map one file without exposing its body

```bash
uvx --from git+https://github.com/vgmakeev/katana.git \
  katana map src/big_module.py --json
```

`map` emits `DocumentIR` v2 with:

- physical and code LOC;
- top-level and nested signatures;
- deterministic symbol IDs;
- byte-exact, end-exclusive source spans;
- local references and confidence levels;
- move constraints and safe composition groups;
- parser capabilities and explicit limitations.

Source bodies are deliberately absent.

### 3. Produce and refine a plan

```bash
uvx --from git+https://github.com/vgmakeev/katana.git \
  katana assess src/big_module.py \
  --max-lines 500 --write-plan --json
```

The agent chooses responsibility boundaries, target names, and compatible move
groups. The plan is intentionally simple and reviewable:

```json
{
  "version": 1,
  "source": "src/big_module.py",
  "moves": [
    {"target": "billing.py", "symbols": ["Invoice", "charge"]}
  ]
}
```

### 4. Dry-run, apply, and verify

```bash
uvx --from git+https://github.com/vgmakeev/katana.git \
  katana apply src/big_module.py \
  --plan-file src/big_module.katana.json --check --json

uvx --from git+https://github.com/vgmakeev/katana.git \
  katana apply src/big_module.py \
  --plan-file src/big_module.katana.json --typecheck --json
```

The dry-run executes the rewrite in a temporary tree. The real apply checks
collisions and cycles, updates language-level imports/exports where supported,
runs detected project tools, and returns diagnostics plus fresh maps for every
touched file.

### A prompt you can give an agent

```text
Use Katana to find files over 500 code LOC. For each candidate, inspect the
source-free map before reading source. Design cohesive responsibility
boundaries, edit Katana's explicit plan, run apply --check, then apply with
typechecking. Keep the mechanical split separate from semantic changes.
```

The complete automation contract is in
[`docs/AGENT_PROTOCOL.md`](docs/AGENT_PROTOCOL.md).

## Supported stacks

| Stack | Architecture map | Rewrite posture | Detected project tools |
| --- | --- | --- | --- |
| Python | stdlib AST | safe top-level split | Ruff, optional mypy |
| Rust | Tree-sitter items and individual `impl` methods | safe lexical-scope-preserving fragments | `cargo fmt`, `cargo check` |
| TypeScript / JavaScript / TSX / JSX / ESM / CJS | TypeScript Compiler API or structural fallback | review + compiler validation | Prettier, ESLint, optional `tsc` |
| Dart | analyzer package or structural fallback | review + analyzer/tests | `dart format` |
| CSS | PostCSS or structural fallback | prefix/order constrained | Prettier |
| Markdown | exact heading spans, optional TanStack AST enrichment | safe section split | Prettier |
| MDX | heading structure, optional AST enrichment | conservative; verify imports and links | Prettier |
| Any other language | Python or JSON command adapter | analysis-only by default | external toolchain adapter |

Run the conformance check to see exactly what is available for a file:

```bash
katana adapters path/to/file --check --json
```

There is no honest universal AST. Compiler APIs, Tree-sitter, LSPs, and
document parsers disagree about trivia, scopes, bindings, and recovery. Katana
makes the intermediate representation universal instead and requires every
adapter to report its actual capabilities.

## Markdown is source too

Long documentation consumes agent context just like long code. Katana treats
Markdown headings as ordered symbols with exact spans:

```bash
katana map docs/long-guide.md --json
katana assess docs/long-guide.md --max-lines 500 --write-plan --json
```

If `@tanstack/markdown` is installed in the project, Katana enriches the map
with a compact document-AST summary. Exact move coordinates still come from
Katana's heading spans, so the optional parser never becomes an implicit source
rewriter.

## Safety invariants

- Mechanical moves preserve source bytes and newline style.
- Content hashes guard adapter input against stale files.
- `apply --check` never writes the working tree.
- Targets, duplicate symbols, collisions, cycles, and resulting line budgets
  are validated.
- Analysis-only adapters cannot advertise executable moves.
- External parser and tool processes are timeout-bounded and their diagnostics
  are normalized for the agent.
- Toolchain failures are reported; they do not disappear behind a successful
  rewrite.

Katana currently performs **one-file architectural splits**. Project-wide
import rewriting is deliberately outside the current contract. This boundary
keeps the tool predictable while richer workspace adapters evolve.

Running Katana on an untrusted repository is equivalent to running that
repository's development toolchain. Read the [security policy](SECURITY.md)
before enabling project-local command adapters.

## Extend Katana

Language analysis and post-processing are independent extension points:

```toml
[project.entry-points."katana.adapters"]
go = "katana_go:GoAdapter"

[project.entry-points."katana.toolchains"]
go = "katana_go:GofmtToolchain"
```

Adapters written in Go, Rust, Node, JVM languages, or any other stack can use
the versioned stdin/stdout JSON command protocol instead. Command protocol v1
is analysis-only and refuses rewrite by design.

Start with LOC and architecture maps. Add rewrite only after the adapter can
prove exact locations, dependency closure, module edits, formatting, and
validation.

- [Adapter SDK](docs/ADAPTERS.md)
- [Toolchain SDK](docs/TOOLCHAINS.md)
- [Architecture](ARCHITECTURE.md)
- [Compatibility policy](docs/COMPATIBILITY.md)

## Development

```bash
git clone https://github.com/vgmakeev/katana.git
cd katana
uv sync --all-groups
make check
make markdown-check
```

The complete gate covers Python 3.14, Ruff, formatting, strict mypy, pytest,
and the optional Node bridge. GitHub Actions runs the suite on Linux, macOS,
and Windows and validates both wheel and source distributions.

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and
keep protocol changes backward-compatible and fail-closed.

## License

Katana is licensed under [Apache-2.0](LICENSE). Commercial use, modification,
distribution, and inclusion in proprietary products are permitted, subject to
the license terms. Apache-2.0 also provides an explicit patent grant from
contributors.
