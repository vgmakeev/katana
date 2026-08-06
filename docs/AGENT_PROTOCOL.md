# Agent protocol

Katana's primary user is an AI coding agent. The agent decides architecture;
Katana supplies bounded context and performs deterministic mechanics.

## Canonical loop

```text
1. katana large --json
2. katana map <file> --json
3. agent designs responsibility boundaries
4. katana assess <file> --write-plan --json
5. agent edits the explicit split plan
6. katana apply <file> --plan-file ... --check --json
7. katana apply <file> --plan-file ... --typecheck --json
8. agent reviews diagnostics and fresh maps
```

The agent must not need the complete source body to propose a split. It receives
signatures, LOC, relationships, exact spans, constraints, capabilities, and safe
move groups through `DocumentIR`.

## Contract rules

- Commands do not prompt for input.
- JSON schemas and protocol versions change explicitly.
- Paths, diagnostics, skipped tools, and capability gaps are observable.
- Analysis-only adapters pin symbols instead of guessing at rewrites.
- `apply --check` exercises the complete rewrite in a temporary tree.
- Formatters and safe lint fixes run before final compiler/type checks.
- Source bodies never appear in an agent map.

Humans configure adapters, approve trust boundaries, and review commits. They do
not manually shuttle source between files on behalf of the agent.
