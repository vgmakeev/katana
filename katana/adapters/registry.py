from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import entry_points
from pathlib import Path
from typing import cast

from .base import LanguageAdapter

_ADAPTERS: dict[str, LanguageAdapter] = {}
_BUILTINS_LOADED = False
_ENTRY_POINTS_LOADED = False
_LOAD_ERRORS: list[str] = []
_LOADED_MANIFESTS: set[Path] = set()


def register_language_adapter(adapter: LanguageAdapter, *, replace: bool = False) -> None:
    _validate_adapter(adapter)
    for extension in adapter.extensions:
        normalized = _normalize_extension(extension)
        current = _ADAPTERS.get(normalized)
        if current is not None and current is not adapter and not replace:
            raise ValueError(
                f"Katana adapter extension {normalized} is already owned by {current.id!r}"
            )
    for extension in adapter.extensions:
        _ADAPTERS[_normalize_extension(extension)] = adapter


def unregister_language_adapter(adapter: LanguageAdapter) -> None:
    for extension, current in tuple(_ADAPTERS.items()):
        if current is adapter:
            del _ADAPTERS[extension]


@contextmanager
def temporary_language_adapter(
    adapter: LanguageAdapter, *, replace: bool = False
) -> Iterator[LanguageAdapter]:
    _ensure_loaded()
    previous = {
        _normalize_extension(ext): _ADAPTERS.get(_normalize_extension(ext))
        for ext in adapter.extensions
    }
    register_language_adapter(adapter, replace=replace)
    try:
        yield adapter
    finally:
        unregister_language_adapter(adapter)
        for extension, current in previous.items():
            if current is not None:
                _ADAPTERS[extension] = current


def language_adapter_for(path: Path) -> LanguageAdapter:
    adapter = language_adapter_for_extension(path.suffix)
    if adapter is None:
        discover_adapter_manifests((path,))
        adapter = language_adapter_for_extension(path.suffix)
    if adapter is None:
        suffix = path.suffix or path.name
        raise ValueError(f"Unsupported source-split file type: {suffix}")
    return adapter


def language_adapter_for_extension(extension: str) -> LanguageAdapter | None:
    _ensure_loaded()
    return _ADAPTERS.get(_normalize_extension(extension))


def language_adapters() -> tuple[LanguageAdapter, ...]:
    _ensure_loaded()
    unique: dict[str, LanguageAdapter] = {}
    for adapter in _ADAPTERS.values():
        unique.setdefault(adapter.id, adapter)
    return tuple(unique.values())


def supported_extensions() -> tuple[str, ...]:
    _ensure_loaded()
    return tuple(_ADAPTERS)


def extensions_for_profiles(profiles: tuple[str, ...]) -> tuple[str, ...]:
    _ensure_loaded()
    selected = set(profiles)
    extensions: list[str] = []
    for adapter in language_adapters():
        if selected.intersection(adapter.profiles):
            extensions.extend(
                extension for extension in adapter.extensions if extension not in extensions
            )
    return tuple(extensions)


def adapter_load_errors() -> tuple[str, ...]:
    _ensure_loaded()
    return tuple(_LOAD_ERRORS)


def load_adapter_manifest(path: Path) -> tuple[LanguageAdapter, ...]:
    from .command import command_adapters_from_manifest

    resolved = path.resolve()
    if resolved in _LOADED_MANIFESTS:
        return ()
    adapters = command_adapters_from_manifest(resolved)
    registered: list[LanguageAdapter] = []
    try:
        for adapter in adapters:
            register_language_adapter(adapter)
            registered.append(adapter)
    except TypeError, ValueError:
        for registered_adapter in registered:
            unregister_language_adapter(registered_adapter)
        raise
    _LOADED_MANIFESTS.add(resolved)
    return adapters


def discover_adapter_manifests(roots: tuple[Path, ...]) -> tuple[LanguageAdapter, ...]:
    loaded: list[LanguageAdapter] = []
    manifests: set[Path] = set()
    for root in roots:
        start = root if root.is_dir() else root.parent
        for current in (start, *start.parents):
            candidate = current / ".katana" / "adapters.json"
            if candidate.is_file():
                manifests.add(candidate)
                break
    for manifest in sorted(manifests):
        loaded.extend(load_adapter_manifest(manifest))
    return tuple(loaded)


def _ensure_loaded() -> None:
    global _BUILTINS_LOADED, _ENTRY_POINTS_LOADED
    if not _BUILTINS_LOADED:
        from .builtin import builtin_language_adapters

        for adapter in builtin_language_adapters():
            register_language_adapter(adapter)
        _BUILTINS_LOADED = True
    if not _ENTRY_POINTS_LOADED:
        _ENTRY_POINTS_LOADED = True
        for entry_point in entry_points(group="katana.adapters"):
            try:
                loaded = entry_point.load()
                candidate = loaded() if isinstance(loaded, type) else loaded
                register_language_adapter(cast(LanguageAdapter, candidate))
            except Exception as error:  # noqa: BLE001 - isolate third-party plugin failures
                _LOAD_ERRORS.append(f"{entry_point.name}: {error}")


def _validate_adapter(adapter: LanguageAdapter) -> None:
    if not getattr(adapter, "id", ""):
        raise TypeError("Katana language adapter must declare a non-empty id")
    if not getattr(adapter, "extensions", ()):
        raise TypeError(f"Katana language adapter {adapter.id!r} must declare extensions")
    required = (
        "language_for",
        "capabilities",
        "analyze",
        "code_line_count",
        "build_plan",
        "safe_move_groups",
        "plan_split",
        "apply_split",
        "split_risk",
        "split_reason",
        "command_flags",
    )
    missing = [name for name in required if not callable(getattr(adapter, name, None))]
    if missing:
        raise TypeError(
            f"Katana language adapter {adapter.id!r} is missing methods: {', '.join(missing)}"
        )


def _normalize_extension(extension: str) -> str:
    normalized = extension if extension.startswith(".") else f".{extension}"
    return normalized.lower()
