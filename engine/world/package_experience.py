"""Compile authored experience profiles into closed runtime/editorial contracts."""

from __future__ import annotations

from typing import Any

from engine.catalogs import (
    literary_skill_ids,
    literary_skill_stage,
)
from engine.contracts.experience import (
    EDITORIAL_STAGE_GRAPH,
    EXPERIENCE_PROFILE_SCHEMA_VERSION,
    CompiledExperienceContract,
    EditorialExperienceContract,
)
from engine.contracts.literary import DEFAULT_EDITORIAL_PIPELINE
from engine.world.experience_catalog import (
    EDITORIAL_BUNDLE_CATALOG,
    REGISTERED_GENRE_IDS,
    RUNTIME_MODE_CATALOG,
)
from engine.world.package_spec import (
    AutonomousWorldSpec,
    PackageDiagnostic,
    WorkflowDefinition,
)
from engine.world.package_experience_validation import (
    EPISODE_FIELDS,
    STYLE_FIELDS,
    compile_voice_registers,
    typed_overrides,
    validate_episode,
    validate_style,
)
from engine.world.package_validation import _reject_unknown_fields


def compile_experience_profile(
    value: Any,
    *,
    world: AutonomousWorldSpec,
    presentation: WorkflowDefinition,
    diagnostics: list[PackageDiagnostic],
) -> CompiledExperienceContract:
    if value is None:
        return _legacy_contract(presentation)
    path = "world.yaml.experience_profile"
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_EXPERIENCE_PROFILE", path, "profile must be an object"
            )
        )
        return _fallback_contract()
    _reject_unknown_fields(
        value,
        {"schema_version", "genre_id", "runtime", "editorial"},
        path,
        diagnostics,
    )
    if value.get("schema_version") != EXPERIENCE_PROFILE_SCHEMA_VERSION:
        diagnostics.append(
            PackageDiagnostic(
                "UNSUPPORTED_EXPERIENCE_SCHEMA",
                f"{path}.schema_version",
                f"expected {EXPERIENCE_PROFILE_SCHEMA_VERSION}",
            )
        )
    genre_id = value.get("genre_id")
    if genre_id not in REGISTERED_GENRE_IDS:
        diagnostics.append(
            PackageDiagnostic(
                "UNKNOWN_GENRE",
                f"{path}.genre_id",
                f"genre is not registered: {genre_id}",
            )
        )

    runtime = _compile_runtime(value.get("runtime"), path, diagnostics)
    editorial = _compile_editorial(
        value.get("editorial"),
        genre_id=str(genre_id or ""),
        character_ids={item.id for item in world.characters},
        path=path,
        diagnostics=diagnostics,
    )
    _validate_runtime_material(runtime.mode_id, world, diagnostics)
    _validate_workflow_consistency(editorial, presentation, diagnostics)
    return CompiledExperienceContract(
        schema_version=EXPERIENCE_PROFILE_SCHEMA_VERSION,
        runtime=runtime,
        editorial=editorial,
    )


def _validate_runtime_material(
    mode_id: str,
    world: AutonomousWorldSpec,
    diagnostics: list[PackageDiagnostic],
) -> None:
    if mode_id != "scene-pressure-v1":
        return
    if world.dramatic_horizon is None:
        diagnostics.append(
            PackageDiagnostic(
                "INCOMPLETE_RUNTIME_CONTRACT_INPUT",
                "world.yaml.dramatic_horizon",
                "scene-pressure-v1 requires a dramatic horizon",
            )
        )
    for location in world.locations:
        path = f"locations.yaml.locations.{location.id}.scene_seeds"
        if not location.scene_seeds:
            diagnostics.append(
                PackageDiagnostic(
                    "INCOMPLETE_RUNTIME_CONTRACT_INPUT",
                    path,
                    "scene-pressure-v1 requires at least one scene seed",
                )
            )
        for seed in location.scene_seeds:
            if not (
                seed.dramatic_question
                and seed.failure_pressure
                and seed.closure_signals
            ):
                diagnostics.append(
                    PackageDiagnostic(
                        "INCOMPLETE_RUNTIME_CONTRACT_INPUT",
                        f"{path}.{seed.key}",
                        "scene seed requires question, pressure, and closure signals",
                    )
                )
    for character in world.characters:
        if not isinstance(dict(character.profile).get("motivation"), dict):
            diagnostics.append(
                PackageDiagnostic(
                    "INCOMPLETE_RUNTIME_CONTRACT_INPUT",
                    f"characters.{character.id}.profile.yaml.motivation",
                    "scene-pressure-v1 requires typed character motivation",
                )
            )


def _compile_runtime(
    value: Any, parent: str, diagnostics: list[PackageDiagnostic]
):
    path = f"{parent}.runtime"
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_EXPERIENCE_PROFILE", path, "runtime must be an object"
            )
        )
        return next(iter(RUNTIME_MODE_CATALOG.values()))
    _reject_unknown_fields(value, {"mode_id"}, path, diagnostics)
    mode_id = value.get("mode_id")
    selected = RUNTIME_MODE_CATALOG.get(str(mode_id))
    if selected is None:
        diagnostics.append(
            PackageDiagnostic(
                "UNKNOWN_RUNTIME_MODE",
                f"{path}.mode_id",
                f"runtime mode is not registered: {mode_id}",
            )
        )
        return next(iter(RUNTIME_MODE_CATALOG.values()))
    return selected


def _compile_editorial(
    value: Any,
    *,
    genre_id: str,
    character_ids: set[str],
    path: str,
    diagnostics: list[PackageDiagnostic],
) -> EditorialExperienceContract:
    editorial_path = f"{path}.editorial"
    if not isinstance(value, dict):
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_EXPERIENCE_PROFILE",
                editorial_path,
                "editorial must be an object",
            )
        )
        return _fallback_contract().editorial
    _reject_unknown_fields(
        value,
        {
            "bundle_id",
            "style_overrides",
            "episode_overrides",
            "editorial_pipeline",
            "character_voice_registers",
        },
        editorial_path,
        diagnostics,
    )
    bundle_id = str(value.get("bundle_id") or "")
    bundle = EDITORIAL_BUNDLE_CATALOG.get(bundle_id)
    if bundle is None:
        diagnostics.append(
            PackageDiagnostic(
                "UNKNOWN_EDITORIAL_BUNDLE",
                f"{editorial_path}.bundle_id",
                f"editorial bundle is not registered: {bundle_id}",
            )
        )
        bundle = next(iter(EDITORIAL_BUNDLE_CATALOG.values()))
    if genre_id and bundle.genre_id != genre_id:
        diagnostics.append(
            PackageDiagnostic(
                "EXPERIENCE_POLICY_CONFLICT",
                f"{editorial_path}.bundle_id",
                f"bundle genre {bundle.genre_id} conflicts with {genre_id}",
            )
        )

    style = dict(bundle.style)
    overrides = typed_overrides(
        value.get("style_overrides"),
        STYLE_FIELDS,
        f"{editorial_path}.style_overrides",
        diagnostics,
    )
    style.update(overrides)
    validate_style(style, f"{editorial_path}.style_overrides", diagnostics)

    episode = dict(bundle.episode)
    episode.update(
        typed_overrides(
            value.get("episode_overrides"),
            EPISODE_FIELDS,
            f"{editorial_path}.episode_overrides",
            diagnostics,
        )
    )
    validate_episode(episode, f"{editorial_path}.episode_overrides", diagnostics)

    raw_pipeline = value.get("editorial_pipeline")
    valid_pipeline_shape = isinstance(raw_pipeline, list) and all(
        isinstance(item, str) for item in raw_pipeline
    )
    pipeline = tuple(raw_pipeline) if valid_pipeline_shape else bundle.pipeline
    if raw_pipeline is not None and not valid_pipeline_shape:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_EDITORIAL_PIPELINE",
                f"{editorial_path}.editorial_pipeline",
                "pipeline must be an array of registered skill ids",
            )
        )
    for skill_id in pipeline:
        if skill_id not in literary_skill_ids():
            diagnostics.append(
                PackageDiagnostic(
                    "UNKNOWN_LITERARY_SKILL",
                    f"{editorial_path}.editorial_pipeline",
                    f"literary skill is not registered: {skill_id}",
                )
            )
    known_pipeline = tuple(
        skill_id for skill_id in pipeline if skill_id in literary_skill_ids()
    )
    if len(known_pipeline) == len(pipeline) and tuple(
        literary_skill_stage(skill_id) for skill_id in known_pipeline
    ) != EDITORIAL_STAGE_GRAPH:
        diagnostics.append(
            PackageDiagnostic(
                "INVALID_EDITORIAL_PIPELINE",
                f"{editorial_path}.editorial_pipeline",
                "editorial skills must fill the four registered stages in order",
            )
        )
    registers = compile_voice_registers(
        value.get("character_voice_registers"),
        character_ids,
        f"{editorial_path}.character_voice_registers",
        diagnostics,
    )
    return EditorialExperienceContract(
        bundle_id=bundle.bundle_id,
        genre_id=bundle.genre_id,
        voice_id=str(style.get("voice_id") or bundle.voice_id),
        pipeline=pipeline,
        style=tuple(sorted(style.items())),
        episode=tuple(sorted(episode.items())),
        character_voice_registers=registers,
        narrative_functions=bundle.narrative_functions,
        quality_dimensions=bundle.quality_dimensions,
    )


def _validate_workflow_consistency(
    editorial: EditorialExperienceContract,
    presentation: WorkflowDefinition,
    diagnostics: list[PackageDiagnostic],
) -> None:
    policy = dict(presentation.policy)
    expected = {
        "style": dict(editorial.style),
        "episode": dict(editorial.episode),
        "editorial_pipeline": list(editorial.pipeline),
    }
    for field, resolved in expected.items():
        authored = policy.get(field)
        if authored is not None and _normalized(authored) != _normalized(resolved):
            diagnostics.append(
                PackageDiagnostic(
                    "EXPERIENCE_POLICY_CONFLICT",
                    f"{presentation.ref}.policy.{field}",
                    f"{field} conflicts with world.yaml experience profile",
                )
            )


def _normalized(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return tuple(_normalized(item) for item in value)
    return value


def _legacy_contract(
    presentation: WorkflowDefinition,
) -> CompiledExperienceContract:
    policy = dict(presentation.policy)
    default_bundle = EDITORIAL_BUNDLE_CATALOG["neutral-observer-v1"]
    style = dict(default_bundle.style)
    if isinstance(policy.get("style"), dict):
        style.update(policy["style"])
    episode = dict(default_bundle.episode)
    if isinstance(policy.get("episode"), dict):
        episode.update(policy["episode"])
    pipeline = policy.get("editorial_pipeline")
    if not isinstance(pipeline, list):
        pipeline = list(DEFAULT_EDITORIAL_PIPELINE)
    editorial = EditorialExperienceContract(
        bundle_id="legacy-workflow-v1",
        genre_id="neutral",
        voice_id=str(style["voice_id"]),
        pipeline=tuple(pipeline),
        style=tuple(sorted(style.items())),
        episode=tuple(sorted(episode.items())),
    )
    return CompiledExperienceContract(
        EXPERIENCE_PROFILE_SCHEMA_VERSION,
        next(iter(RUNTIME_MODE_CATALOG.values())),
        editorial,
        legacy=True,
    )


def _fallback_contract() -> CompiledExperienceContract:
    bundle = EDITORIAL_BUNDLE_CATALOG["neutral-observer-v1"]
    return CompiledExperienceContract(
        EXPERIENCE_PROFILE_SCHEMA_VERSION,
        next(iter(RUNTIME_MODE_CATALOG.values())),
        EditorialExperienceContract(
            bundle.bundle_id,
            bundle.genre_id,
            bundle.voice_id,
            bundle.pipeline,
            bundle.style,
            bundle.episode,
            narrative_functions=bundle.narrative_functions,
            quality_dimensions=bundle.quality_dimensions,
        ),
    )
