# Release checklist

1. Choose and add the project license.
2. Confirm the distribution name and reserve it on PyPI.
3. Confirm standalone repository URLs in `pyproject.toml`.
4. Run `make check` on Python 3.14.
5. Run `make markdown-check`.
6. Run compatibility snapshots against the previous release.
7. Build with `uv build` and inspect with `uvx twine check dist/*`.
8. Review `CHANGELOG.md`, tag the release, and publish with trusted publishing.

The import package and CLI remain `katana` even if the PyPI distribution uses a
more specific name.
