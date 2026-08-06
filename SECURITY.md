# Security policy

## Reporting

Report vulnerabilities privately through the repository's GitHub Security
Advisory form. Do not open a public issue for command execution, path traversal,
source disclosure, or unsafe rewrite findings.

Include the Katana version, operating system, command, smallest reproducer, and
whether the project contained a `.katana/adapters.json` manifest.

## Trust model

Katana reads and rewrites local source files and may invoke project-local parser,
formatter, linter, and typechecker commands. Running Katana on an untrusted
repository is equivalent to running that repository's development toolchain.

Python packages registered under `katana.adapters` or `katana.toolchains` are
trusted executable code and run with the permissions of the Katana process.

Command adapters are never executed through a shell. They receive a JSON request
on stdin, run with a timeout, and their output is size-limited and validated.
Protocol v1 command adapters are analysis-only and cannot advertise safe rewrite.
They are nevertheless trusted project tooling: a malicious adapter can read the
repository and falsify or disclose metadata.

Katana must not include source bodies in agent-facing maps. Byte spans,
signatures, names, tags, and explicitly adapter-provided metadata are expected.
