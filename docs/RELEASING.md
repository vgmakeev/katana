# Release checklist

1. Choose and add the project license.
2. Confirm that the `katana-agent` distribution name is available on PyPI.
3. Confirm standalone repository URLs in `pyproject.toml`.
4. Run `make check` on Python 3.14.
5. Run `make markdown-check`.
6. Run compatibility snapshots against the previous release.
7. Build with `uv build` and inspect with `uvx twine check dist/*`.
8. Review `CHANGELOG.md`, tag the release, and publish with trusted publishing.

The PyPI distribution is `katana-agent`; the import package, CLI, and entry
point groups remain `katana`.

The PyPI trusted publisher is intentionally secretless:

- owner: `vgmakeev`;
- repository: `kanata`;
- workflow: `publish.yml`;
- environment: `pypi`.

For the first upload, register those values as a pending publisher in PyPI.
Later GitHub releases trigger publishing automatically. A previously created
tag can be published from the workflow's manual `tag` input.
