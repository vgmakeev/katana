from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from katana.external import source_symbols_from_payload
from katana.ir import AdapterCapabilities, DocumentIR, SourceSpan, build_document_ir
from katana.models import SourceSymbol

from .base import AnalysisLanguageAdapter

COMMAND_ADAPTER_PROTOCOL_VERSION = 1
DEFAULT_COMMAND_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_OUTPUT_BYTES = 5 * 1024 * 1024


class CommandAdapterError(ValueError):
    """Raised when a project-local adapter violates the command protocol."""


@dataclass(frozen=True)
class CommandAdapterSpec:
    id: str
    language: str
    extensions: tuple[str, ...]
    profiles: tuple[str, ...]
    command: tuple[str, ...]
    working_directory: Path
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES


class CommandAnalysisAdapter(AnalysisLanguageAdapter):
    """Language-neutral, analysis-only adapter backed by a local JSON command."""

    def __init__(self, spec: CommandAdapterSpec) -> None:
        if not spec.id or not spec.language or not spec.extensions or not spec.command:
            raise CommandAdapterError(
                "command adapter requires id, language, extensions and command"
            )
        if spec.timeout_seconds <= 0 or spec.max_output_bytes < 1024:
            raise CommandAdapterError(
                "command adapter timeout must be positive and output limit at least 1024 bytes"
            )
        self.spec = spec
        self.id = spec.id
        self.extensions = spec.extensions
        self.profiles = spec.profiles
        self._cached_key: tuple[Path, str] | None = None
        self._cached_payload: dict[str, Any] | None = None

    def language_for(self, path: Path) -> str:
        return self.spec.language

    def capabilities(self, path: Path) -> AdapterCapabilities:
        return self._capabilities_from_payload(self._analysis_payload(path))

    def outline(self, path: Path) -> list[SourceSymbol]:
        payload = self._analysis_payload(path)
        self._assert_source_unchanged(path, payload)
        return self._symbols_from_payload(payload)

    def analyze(self, path: Path) -> DocumentIR:
        payload = self._analysis_payload(path)
        capabilities = self._capabilities_from_payload(payload)
        symbols = self._symbols_from_payload(payload)
        source_spans = self._source_spans_from_payload(payload)
        document = build_document_ir(
            path,
            language=self.language_for(path),
            adapter_id=self.id,
            capabilities=capabilities,
            symbols=symbols,
            constraints=self.constraints(path, symbols),
            source_spans=source_spans,
            meta=payload.get("meta") if isinstance(payload.get("meta"), dict) else None,
        )
        if document.content_hash != payload["content_hash"]:
            raise CommandAdapterError(f"source changed while adapter {self.id!r} was analyzing it")
        return document

    def _analysis_payload(self, path: Path) -> dict[str, Any]:
        resolved = path.resolve()
        try:
            source_bytes = resolved.read_bytes()
        except OSError as error:
            raise CommandAdapterError(f"cannot read adapter source {path}: {error}") from error
        content_hash = hashlib.sha256(source_bytes).hexdigest()
        cache_key = (resolved, content_hash)
        if cache_key == self._cached_key and self._cached_payload is not None:
            return self._cached_payload

        command = self.spec.command
        executable = command[0]
        if os.sep not in executable and shutil.which(executable) is None:
            raise CommandAdapterError(
                f"adapter {self.id!r} executable is not available: {executable}"
            )
        request = {
            "protocol_version": COMMAND_ADAPTER_PROTOCOL_VERSION,
            "operation": "analyze",
            "adapter_id": self.id,
            "path": str(resolved),
            "content_hash": content_hash,
        }
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(request),
                check=False,
                capture_output=True,
                cwd=self.spec.working_directory,
                encoding="utf-8",
                text=True,
                timeout=self.spec.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
            raise CommandAdapterError(f"adapter {self.id!r} failed: {error}") from error
        captured_bytes = len(completed.stdout.encode("utf-8")) + len(
            completed.stderr.encode("utf-8")
        )
        if captured_bytes > self.spec.max_output_bytes:
            raise CommandAdapterError(f"adapter {self.id!r} response exceeds output limit")
        if completed.returncode != 0:
            diagnostic = completed.stderr.strip()[:1000] or "no diagnostic"
            raise CommandAdapterError(
                f"adapter {self.id!r} exited with {completed.returncode}: {diagnostic}"
            )
        try:
            raw = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise CommandAdapterError(f"adapter {self.id!r} returned invalid JSON") from error
        if not isinstance(raw, dict):
            raise CommandAdapterError(f"adapter {self.id!r} response must be an object")
        if raw.get("protocol_version") != COMMAND_ADAPTER_PROTOCOL_VERSION:
            raise CommandAdapterError(
                f"adapter {self.id!r} must return protocol_version "
                f"{COMMAND_ADAPTER_PROTOCOL_VERSION}"
            )
        if raw.get("content_hash") != content_hash:
            raise CommandAdapterError(
                f"adapter {self.id!r} response content_hash does not match the request"
            )
        if not isinstance(raw.get("symbols"), list):
            raise CommandAdapterError(f"adapter {self.id!r} response must contain symbols[]")
        self._cached_key = cache_key
        self._cached_payload = raw
        return raw

    def _capabilities_from_payload(self, payload: dict[str, Any]) -> AdapterCapabilities:
        raw = payload.get("capabilities")
        if not isinstance(raw, dict):
            raise CommandAdapterError(f"adapter {self.id!r} response must contain capabilities")
        feature_payload = raw.get("capabilities")
        features = feature_payload if isinstance(feature_payload, dict) else {}
        raw_symbols = payload.get("symbols")
        exact_spans = (
            bool(raw_symbols)
            and isinstance(raw_symbols, list)
            and all(
                isinstance(symbol, dict) and "start_byte" in symbol and "end_byte" in symbol
                for symbol in raw_symbols
            )
        )
        source_locations = bool(features.get("source_locations", exact_spans))
        if source_locations and raw_symbols and not exact_spans:
            raise CommandAdapterError(
                f"adapter {self.id!r} advertises source_locations without byte spans"
            )
        safe_apply = bool(raw.get("safe_apply", False))
        if safe_apply:
            raise CommandAdapterError(
                f"command adapter {self.id!r} uses analysis protocol v1 and cannot advertise safe_apply"
            )
        bridge_payload = raw.get("bridge")
        bridge = (
            {str(key): bool(value) for key, value in bridge_payload.items()}
            if isinstance(bridge_payload, dict)
            else None
        )
        return AdapterCapabilities(
            adapter_id=self.id,
            language=self.spec.language,
            parser=_required_string(raw, "parser", self.id),
            strategy=_required_string(raw, "strategy", self.id),
            precision=_required_string(raw, "precision", self.id),
            safe_apply=False,
            outline=bool(features.get("outline", True)),
            source_locations=source_locations,
            hierarchy=bool(features.get("hierarchy", False)),
            comments=bool(features.get("comments", False)),
            local_bindings=bool(features.get("local_bindings", False)),
            module_rewrite=False,
            workspace_rewrite=False,
            formatting=False,
            validation=bool(features.get("validation", False)),
            adapter_available=bool(raw.get("adapter_available", True)),
            verifications=_string_tuple(raw.get("verifications")),
            limitations=_string_tuple(raw.get("limitations")),
            bridge=bridge,
        )

    def _symbols_from_payload(self, payload: dict[str, Any]) -> list[SourceSymbol]:
        try:
            return source_symbols_from_payload(payload)
        except (KeyError, TypeError, ValueError) as error:
            raise CommandAdapterError(
                f"adapter {self.id!r} returned invalid symbol data: {error}"
            ) from error

    def _assert_source_unchanged(self, path: Path, payload: dict[str, Any]) -> None:
        current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if current_hash != payload["content_hash"]:
            raise CommandAdapterError(f"source changed while adapter {self.id!r} was analyzing it")

    def _source_spans_from_payload(self, payload: dict[str, Any]) -> list[SourceSpan] | None:
        raw_symbols = payload["symbols"]
        if not raw_symbols:
            return []
        assert isinstance(raw_symbols, list)  # checked at the protocol boundary
        has_exact_span = [
            isinstance(raw, dict) and "start_byte" in raw and "end_byte" in raw
            for raw in raw_symbols
        ]
        if not any(has_exact_span):
            return None
        if not all(has_exact_span):
            raise CommandAdapterError(
                f"adapter {self.id!r} must provide byte spans for every symbol or none"
            )
        spans: list[SourceSpan] = []
        for raw in raw_symbols:
            assert isinstance(raw, dict)
            try:
                spans.append(
                    SourceSpan(
                        start_byte=int(raw["start_byte"]),
                        end_byte=int(raw["end_byte"]),
                        start_line=int(raw["start_line"]),
                        end_line=int(raw["end_line"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise CommandAdapterError(
                    f"adapter {self.id!r} returned invalid byte span: {error}"
                ) from error
        return spans


def command_adapter_manifest_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Katana command adapter manifest",
        "type": "object",
        "additionalProperties": False,
        "required": ["protocol_version", "adapters"],
        "properties": {
            "protocol_version": {"type": "integer", "const": 1},
            "adapters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "language", "extensions", "command"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "language": {"type": "string", "minLength": 1},
                        "extensions": {
                            "type": "array",
                            "items": {"type": "string", "pattern": "^\\."},
                            "minItems": 1,
                        },
                        "profiles": {"type": "array", "items": {"type": "string"}},
                        "command": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                        },
                        "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                        "max_output_bytes": {"type": "integer", "minimum": 1024},
                    },
                },
            },
        },
    }


def command_adapters_from_manifest(path: Path) -> tuple[CommandAnalysisAdapter, ...]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise CommandAdapterError(f"cannot read adapter manifest {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("protocol_version") != 1:
        raise CommandAdapterError("adapter manifest protocol_version must be 1")
    unknown_root = set(payload).difference({"protocol_version", "adapters"})
    if unknown_root:
        raise CommandAdapterError(
            f"adapter manifest has unknown keys: {', '.join(sorted(unknown_root))}"
        )
    raw_adapters = payload.get("adapters")
    if not isinstance(raw_adapters, list):
        raise CommandAdapterError("adapter manifest must contain adapters[]")
    working_directory = path.parent.parent if path.parent.name == ".katana" else path.parent
    adapters: list[CommandAnalysisAdapter] = []
    for raw in raw_adapters:
        if not isinstance(raw, dict):
            raise CommandAdapterError("adapter manifest entries must be objects")
        allowed = {
            "id",
            "language",
            "extensions",
            "profiles",
            "command",
            "timeout_seconds",
            "max_output_bytes",
        }
        unknown = set(raw).difference(allowed)
        if unknown:
            raise CommandAdapterError(
                f"adapter manifest entry has unknown keys: {', '.join(sorted(unknown))}"
            )
        command = _manifest_command(raw.get("command"), path.parent)
        extensions = _required_string_tuple(raw, "extensions", str(path))
        if any(not extension.startswith(".") for extension in extensions):
            raise CommandAdapterError("adapter extensions must start with '.'")
        adapters.append(
            CommandAnalysisAdapter(
                CommandAdapterSpec(
                    id=_required_string(raw, "id", str(path)),
                    language=_required_string(raw, "language", str(path)),
                    extensions=extensions,
                    profiles=_string_tuple(raw.get("profiles")) or ("all",),
                    command=command,
                    working_directory=working_directory,
                    timeout_seconds=float(
                        raw.get("timeout_seconds", DEFAULT_COMMAND_TIMEOUT_SECONDS)
                    ),
                    max_output_bytes=int(raw.get("max_output_bytes", DEFAULT_MAX_OUTPUT_BYTES)),
                )
            )
        )
    return tuple(adapters)


def _manifest_command(value: object, base: Path) -> tuple[str, ...]:
    command = _required_string_tuple({"command": value}, "command", str(base))
    resolved: list[str] = []
    for index, part in enumerate(command):
        if part == "@python":
            resolved.append(sys.executable)
        elif part.startswith(("./", "../")) or (
            index == 0 and os.sep in part and not Path(part).is_absolute()
        ):
            resolved.append(str((base / part).resolve()))
        else:
            resolved.append(part)
    return tuple(resolved)


def _required_string(payload: dict[str, Any], key: str, owner: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise CommandAdapterError(f"{owner} requires non-empty {key}")
    return value


def _required_string_tuple(payload: dict[str, Any], key: str, owner: str) -> tuple[str, ...]:
    value = payload.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise CommandAdapterError(f"{owner} requires non-empty {key}[]")
    return tuple(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str))
