from .base import AnalysisLanguageAdapter, LanguageAdapter, legacy_capabilities_for
from .command import (
    COMMAND_ADAPTER_PROTOCOL_VERSION,
    CommandAdapterError,
    CommandAdapterSpec,
    CommandAnalysisAdapter,
    command_adapter_manifest_schema,
    command_adapters_from_manifest,
)
from .conformance import (
    AdapterConformanceError,
    check_language_adapter,
    validate_document_ir,
)
from .registry import (
    adapter_load_errors,
    discover_adapter_manifests,
    extensions_for_profiles,
    language_adapter_for,
    language_adapter_for_extension,
    language_adapters,
    load_adapter_manifest,
    register_language_adapter,
    supported_extensions,
    temporary_language_adapter,
    unregister_language_adapter,
)

__all__ = (
    "COMMAND_ADAPTER_PROTOCOL_VERSION",
    "AdapterConformanceError",
    "AnalysisLanguageAdapter",
    "CommandAdapterError",
    "CommandAdapterSpec",
    "CommandAnalysisAdapter",
    "LanguageAdapter",
    "adapter_load_errors",
    "check_language_adapter",
    "command_adapter_manifest_schema",
    "command_adapters_from_manifest",
    "discover_adapter_manifests",
    "extensions_for_profiles",
    "language_adapter_for",
    "language_adapter_for_extension",
    "language_adapters",
    "legacy_capabilities_for",
    "load_adapter_manifest",
    "register_language_adapter",
    "supported_extensions",
    "temporary_language_adapter",
    "unregister_language_adapter",
    "validate_document_ir",
)
