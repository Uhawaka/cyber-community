"""Typed experience contracts selected by world packages."""

from __future__ import annotations

from dataclasses import dataclass


EXPERIENCE_PROFILE_SCHEMA_VERSION = "experience-profile/v1"
EDITORIAL_STAGE_GRAPH = (
    "developmental_edit",
    "scene_draft",
    "line_edit",
    "fact_continuity",
)


@dataclass(frozen=True)
class RuntimeNarrativeContract:
    mode_id: str
    pressure_escalation_turns: int
    max_pressure_level: int
    decision_pressure_level: int
    resolution_modes: tuple[str, ...]


@dataclass(frozen=True)
class CharacterVoiceRegisterSpec:
    character_id: str
    first_attentions: tuple[str, ...]
    diction: str
    syntax: str
    withheld: tuple[str, ...] = ()


@dataclass(frozen=True)
class EditorialBundleDefaults:
    bundle_id: str
    genre_id: str
    voice_id: str
    pipeline: tuple[str, ...]
    style: tuple[tuple[str, object], ...]
    episode: tuple[tuple[str, object], ...]
    narrative_functions: tuple[str, ...] = ()
    quality_dimensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class EditorialExperienceContract:
    bundle_id: str
    genre_id: str
    voice_id: str
    pipeline: tuple[str, ...]
    style: tuple[tuple[str, object], ...]
    episode: tuple[tuple[str, object], ...]
    character_voice_registers: tuple[
        CharacterVoiceRegisterSpec, ...
    ] = ()
    narrative_functions: tuple[str, ...] = ()
    quality_dimensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompiledExperienceContract:
    schema_version: str
    runtime: RuntimeNarrativeContract
    editorial: EditorialExperienceContract
