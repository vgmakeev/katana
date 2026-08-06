# Command adapter example

This fixture demonstrates the stack-neutral JSON protocol, not a production
parser. From this directory run:

```bash
katana map main.demo --json
katana adapters main.demo --check --json
```

A real adapter would replace the short Python scanner with Tree-sitter, a
compiler API, ast-grep, LSP/SCIP data, or another parser available in its stack.
