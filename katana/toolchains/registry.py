from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import entry_points
from typing import cast

from .base import ToolchainAdapter

_ADAPTERS: dict[str, ToolchainAdapter] = {}
_BUILTINS_LOADED = False
_ENTRY_POINTS_LOADED = False
_LOAD_ERRORS: list[str] = []


def register_toolchain_adapter(adapter: ToolchainAdapter, *, replace: bool = False) -> None:
    _validate_adapter(adapter)
    current = _ADAPTERS.get(adapter.id)
    if current is not None and current is not adapter and not replace:
        raise ValueError(f"Katana toolchain adapter id {adapter.id!r} is already registered")
    _ADAPTERS[adapter.id] = adapter


def unregister_toolchain_adapter(adapter: ToolchainAdapter) -> None:
    if _ADAPTERS.get(adapter.id) is adapter:
        del _ADAPTERS[adapter.id]


@contextmanager
def temporary_toolchain_adapter(adapter: ToolchainAdapter) -> Iterator[ToolchainAdapter]:
    _ensure_loaded()
    register_toolchain_adapter(adapter)
    try:
        yield adapter
    finally:
        unregister_toolchain_adapter(adapter)


def toolchain_adapters() -> tuple[ToolchainAdapter, ...]:
    _ensure_loaded()
    return tuple(_ADAPTERS.values())


def toolchain_load_errors() -> tuple[str, ...]:
    _ensure_loaded()
    return tuple(_LOAD_ERRORS)


def _ensure_loaded() -> None:
    global _BUILTINS_LOADED, _ENTRY_POINTS_LOADED
    if not _BUILTINS_LOADED:
        from .dart import DartFmtAdapter
        from .python import MypyAdapter, RuffAdapter
        from .typescript import EslintAdapter, OxlintAdapter, PrettierAdapter, TscAdapter

        for adapter in (
            PrettierAdapter(),
            DartFmtAdapter(),
            RuffAdapter(),
            EslintAdapter(),
            OxlintAdapter(),
            TscAdapter(),
            MypyAdapter(),
        ):
            register_toolchain_adapter(cast(ToolchainAdapter, adapter))
        _BUILTINS_LOADED = True
    if not _ENTRY_POINTS_LOADED:
        _ENTRY_POINTS_LOADED = True
        for entry_point in entry_points(group="katana.toolchains"):
            try:
                loaded = entry_point.load()
                candidate = loaded() if isinstance(loaded, type) else loaded
                register_toolchain_adapter(cast(ToolchainAdapter, candidate))
            except Exception as error:  # noqa: BLE001 - isolate third-party plugin failures
                _LOAD_ERRORS.append(f"{entry_point.name}: {error}")


def _validate_adapter(adapter: ToolchainAdapter) -> None:
    if not getattr(adapter, "id", ""):
        raise TypeError("Katana toolchain adapter must declare a non-empty id")
    if getattr(adapter, "kind", None) not in {"formatter", "linter", "checker"}:
        raise TypeError(f"Katana toolchain adapter {adapter.id!r} has an invalid kind")
    if not getattr(adapter, "extensions", ()):
        raise TypeError(f"Katana toolchain adapter {adapter.id!r} must declare extensions")
    missing = [
        name for name in ("detect", "fix", "check") if not callable(getattr(adapter, name, None))
    ]
    if missing:
        raise TypeError(
            f"Katana toolchain adapter {adapter.id!r} is missing methods: {', '.join(missing)}"
        )
