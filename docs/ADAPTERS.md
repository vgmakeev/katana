# Adapter SDK

Katana standardizes the map, not the parser. Native compiler APIs, Tree-sitter,
ast-grep, LSP/SCIP indexes, and proprietary analyzers can all feed the same
`DocumentIR`.

## Capability levels

1. **LOC** — identify oversized files.
2. **Map** — return ordered signatures and exact locations.
3. **Relations** — return local bindings and dependency confidence.
4. **Module rewrite** — update imports and exports in one module.
5. **Workspace rewrite** — update consumers across a project.
6. **Verify** — format and run the language's compiler or analyzer.

Adapters must advertise each capability independently. Parser availability does
not imply safe rewrite.

## Python entry points

Subclass `AnalysisLanguageAdapter` for a safe starting point and publish it under
the `katana.adapters` entry-point group:

```toml
[project.entry-points."katana.adapters"]
go = "katana_go:GoAdapter"
```

Run the conformance check against a fixture:

```bash
katana adapters fixtures/example.go --check --json
```

## Stack-neutral command adapters

A project can connect an executable written in any language without a Python
plugin. Add `.katana/adapters.json`:

```json
{
  "protocol_version": 1,
  "adapters": [
    {
      "id": "tree_sitter_go",
      "language": "go",
      "extensions": [".go"],
      "profiles": ["go", "all"],
      "command": ["../tools/katana-go-adapter"],
      "timeout_seconds": 8
    }
  ]
}
```

Paths beginning with `./` or `../` are resolved relative to the manifest.
Print the exact manifest schema with `katana adapters --schema --json`.
Use `@python` as the executable to select the interpreter running Katana.

Katana sends one JSON object on stdin:

```json
{
  "protocol_version": 1,
  "operation": "analyze",
  "adapter_id": "tree_sitter_go",
  "path": "/absolute/project/main.go",
  "content_hash": "sha256..."
}
```

The command returns:

```json
{
  "protocol_version": 1,
  "content_hash": "the request content_hash",
  "capabilities": {
    "parser": "tree_sitter_go",
    "strategy": "tree_sitter_query",
    "precision": "syntax_top_level",
    "safe_apply": false,
    "capabilities": {
      "outline": true,
      "source_locations": true,
      "hierarchy": true,
      "local_bindings": false
    },
    "limitations": ["syntax references are not resolved bindings"]
  },
  "symbols": [
    {
      "name": "main",
      "kind": "function",
      "signature": "func main()",
      "start_line": 3,
      "end_line": 8,
      "start_byte": 42,
      "end_byte": 137,
      "code_lines": 6,
      "references": [],
      "tags": [],
      "meta": {}
    }
  ],
  "meta": {"backend": "tree-sitter"}
}
```

Command protocol v1 is intentionally analysis-only. Katana pins every returned
symbol and rejects `safe_apply: true`. A future rewrite protocol will return
hash-guarded edit sets rather than allowing an adapter to write files directly.

Command adapters are trusted project tooling. They control signatures, tags, and
metadata returned to the agent, so do not enable a manifest from an untrusted
repository. The protocol is fail-closed, but it is not an operating-system
sandbox.

## Backend guidance

- Use a native compiler API when bindings and module semantics are required.
- Use Tree-sitter queries for broad, error-tolerant syntax maps.
- Use ast-grep when structural matching or rewriting is already available in the
  project toolchain.
- Use LSP or SCIP data to enrich workspace references, not as a replacement for
  byte-exact source locations.
- Fall back to a structural scanner only for mapping and report the limitation.
