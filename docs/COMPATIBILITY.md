# Compatibility policy

Katana has two independently versioned contracts.

## Production v1

The existing CLI commands, split-plan v1 schema, adapter ids, and JSON payloads
are compatibility surfaces used by real projects. Changes must be additive or
introduced under a new explicit version.

The compatibility suite fixes v1 adapter ids, extension order, payload shapes,
schema invariants, and mechanical apply behavior. Before a release, compare the
complete `schema`, `outline`, and `assess` JSON with the previous release as
described in the release checklist.

## DocumentIR v2

`katana map` and adapter conformance use DocumentIR v2. New optional fields may
be added. Removing fields, changing span semantics, returning source bodies, or
weakening fail-closed constraints requires a new protocol version.

## Deprecation

A deprecated field or command remains supported for at least one standalone
minor release and emits a machine-readable replacement before removal.
