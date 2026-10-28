"""Public contracts for directory-authored world packages."""

from engine.world.community_authoring import (
    AUTHOR_SCHEMA_VERSION,
    build_community_package,
    load_community_source,
)
from engine.world.package_compiler import (
    SUPPORTED_PACKAGE_CAPABILITIES,
    compile_package,
)
from engine.world.package_spec import (
    AutonomousWorldSpec,
    CapabilityHandshake,
    CompiledWorld,
    DramaticHorizon,
    PackageCharacter,
    PackageCompileResult,
    PackageDiagnostic,
    PackageLocation,
    PackageManifest,
    PackagePassage,
    PackageResource,
    PackageSceneSeed,
    WorkflowDefinition,
    WorkflowIR,
    WorkflowStep,
    canonical_compiled_json,
)

__all__ = [
    "AUTHOR_SCHEMA_VERSION",
    "build_community_package",
    "load_community_source",
    "SUPPORTED_PACKAGE_CAPABILITIES",
    "AutonomousWorldSpec",
    "CapabilityHandshake",
    "CompiledWorld",
    "DramaticHorizon",
    "PackageCharacter",
    "PackageCompileResult",
    "PackageDiagnostic",
    "PackageLocation",
    "PackageManifest",
    "PackagePassage",
    "PackageResource",
    "PackageSceneSeed",
    "WorkflowDefinition",
    "WorkflowIR",
    "WorkflowStep",
    "canonical_compiled_json",
    "compile_package",
]
