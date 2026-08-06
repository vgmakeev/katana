# Katana architecture

Katana separates agent reasoning from deterministic refactoring.

Its primary consumer is an AI agent. Human-readable output is a convenience;
versioned JSON, deterministic behavior, bounded context, and non-interactive
execution are the product contracts.

## Pipeline

1. Discovery counts language-aware LOC and selects oversized documents.
2. A language adapter parses one document and produces `DocumentIR` v2.
3. The agent sees signatures, references, constraints, and safe groups only.
4. The agent writes the stable split-plan v1 format.
5. The adapter validates and projects the plan.
6. Core applies it in a dry-run or the working tree.
7. Project tool adapters format, lint, validate, and return diagnostics.
8. Katana returns a fresh map of every touched file.

`DocumentIR` is the anti-corruption boundary. Parser-specific node objects must
not cross it, and source bodies must not be added to agent-facing payloads.

## Package boundaries

```text
katana core                 stable IR, planning, apply, conformance, CLI
katana.adapters.<stack>     parsing, symbols, imports, rewrite capabilities
katana.toolchains.<stack>   format, lint-fix, check integrations
external packages           the same contracts via Python entry points
```

Python and TypeScript are bundled reference adapters, not privileged branches
inside core. Compatibility facades keep the established public functions while
delegating to registered adapters.

## Capability ladder

Adapter backends may be native compiler APIs, Tree-sitter/ast-grep, LSP/SCIP,
or structural scanners. Backend choice is private to the adapter. The public
contract reports independent capabilities instead of a single "AST available"
flag.

An analysis-only adapter is useful: it enables project LOC and architecture maps
while making rewrite fail closed. Rewrite support requires exact spans plus
language-specific dependency, module, formatting, and validation behavior.

## Versioning

- Split plan v1 is the durable command contract.
- DocumentIR v2 is the agent map and adapter interchange contract.
- Python entry points under `katana.adapters` are the in-process extension API.
- Python entry points under `katana.toolchains` add formatter/linter/checker
  integrations without changing core.
- Project manifests under `.katana/adapters.json` connect analysis commands
  implemented in any language through command protocol v1.

Protocol additions should be backward-compatible. Semantic changes require a
new protocol version and conformance fixtures.

## External tools

Compiler bridges, formatters, linters, and typecheckers are local subprocess
boundaries. Calls must be timeout-bounded, capture diagnostics, avoid shell
execution, and never keep mutable Katana state across the call.

Command protocol v1 is analysis-only: Katana never asks it to mutate files and
rejects safe rewrite. Commands are trusted project tooling, not a sandbox. A
future rewrite protocol must return hash-guarded edits for Katana core to
validate and commit; conforming adapters must not write the working tree.
