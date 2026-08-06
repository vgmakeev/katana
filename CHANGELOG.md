# Changelog

Katana follows semantic versioning after its standalone `1.0` release. Until
then, compatibility promises are scoped explicitly below.

## Unreleased

## 0.4.67 - 2026-08-06

### Added

- `DocumentIR` v2 and the source-free `katana map` command.
- Python entry-point adapters under `katana.adapters`.
- Project-local command adapters through `.katana/adapters.json`.
- Optional TanStack Markdown AST enrichment.
- Python 3.14 support and standalone CI across Linux, macOS, and Windows.
- Bundled language adapters under `katana.adapters.<stack>`.
- Public toolchain adapters and the `katana.toolchains` entry-point group.

### Changed

- The standalone distribution is named `katana-agent`; the import package,
  CLI, and adapter entry points remain `katana`.

### Compatibility

- Split-plan v1 remains unchanged.
- Existing `schema`, `outline`, `assess`, `plan`, `apply`, `large`, and `project`
  payloads remain compatible.
- Existing adapter ids remain `node_typescript`, `dart_analyzer`, and
  `node_postcss`.
- UTF-8 byte spans and hashes now remain exact for CRLF files, and mechanical
  split output preserves the source newline style.
