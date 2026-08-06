from pathlib import Path

from katana import large_source_files, source_split_extensions_for_profiles

BASE_SOURCE_LINES = 500
MAX_SOURCE_LINES = BASE_SOURCE_LINES + BASE_SOURCE_LINES // 10
ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "katana", ROOT / "tests", ROOT / "examples")
SOURCE_EXTENSIONS = source_split_extensions_for_profiles(("all",))


def test_repository_code_files_fit_the_agent_budget() -> None:
    oversized = large_source_files(
        list(SOURCE_ROOTS),
        max_lines=MAX_SOURCE_LINES,
        extensions=SOURCE_EXTENSIONS,
    )

    assert not oversized, [
        (Path(str(item["path"])).relative_to(ROOT).as_posix(), item["code_lines"])
        for item in oversized
    ]


def test_repository_source_files_fit_the_physical_line_ceiling() -> None:
    oversized = sorted(
        (
            path.relative_to(ROOT).as_posix(),
            len(path.read_text(encoding="utf-8").splitlines()),
        )
        for source_root in SOURCE_ROOTS
        for path in source_root.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_EXTENSIONS
        and len(path.read_text(encoding="utf-8").splitlines()) > MAX_SOURCE_LINES
    )

    assert not oversized
