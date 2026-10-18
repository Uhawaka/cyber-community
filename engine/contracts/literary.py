"""Dependency-free contracts for literary editing and world voices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


DEFAULT_EDITORIAL_PIPELINE = (
    "developmental-editor-v1",
    "scene-writer-v1",
    "line-editor-v1",
    "fact-continuity-editor-v1",
)

class LiterarySkill(Protocol):
    """A versioned host-owned editing stage loaded from a resource."""

    skill_id: str
    stage: str
    input_schema: str
    output_schema: str
    instruction: str


@dataclass(frozen=True)
class EditorialBrief:
    focus: str
    goal: str
    conflict: str
    stakes: str
    turn_source_id: str
    selected_source_ids: tuple[str, ...]
    direct_quote_source_ids: tuple[str, ...]
    ending_source_id: str
    ending_fact_relation: str
    resolved_outcome: str | None = None


@dataclass(frozen=True)
class SourcedParagraph:
    source_event_ids: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class SourcedDraft:
    title: str
    paragraphs: tuple[SourcedParagraph, ...]


@dataclass(frozen=True)
class EditorialDiagnostic:
    skill_id: str
    stage: str
    status: str
    elapsed_ms: int
    detail: str = ""


class WorldVoice(Protocol):
    """A host-owned project voice; it never grants additional facts."""

    voice_id: str
    banned_constructions: tuple[str, ...]

    def model_instruction(
        self,
        focus_character_id: str | None = None,
        character_registers: tuple[object, ...] = (),
    ) -> str: ...

    def title(self, focus: str, location: str | None) -> str: ...

    def surface_term(self, key: str, default: str) -> str: ...

    def quality_gate(self, key: str) -> tuple[str, ...]: ...
