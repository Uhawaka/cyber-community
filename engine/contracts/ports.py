"""Dependency-free ports shared by engine layers.

The type variables deliberately avoid importing domain objects.  Concrete
layers bind them structurally, keeping this package at the dependency root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypeVar


WorldT = TypeVar("WorldT", contravariant=True)
StateT = TypeVar("StateT", contravariant=True)
OpportunityT = TypeVar("OpportunityT", contravariant=True)
ActionT = TypeVar("ActionT", covariant=True)
DigestT = TypeVar("DigestT", contravariant=True)
RenderedT = TypeVar("RenderedT", covariant=True)
RunT = TypeVar("RunT")
CompiledT = TypeVar("CompiledT", contravariant=True)
PresentationT = TypeVar("PresentationT", covariant=True)
SceneContextT = TypeVar("SceneContextT", contravariant=True)
SceneT = TypeVar("SceneT", covariant=True)
PerceptionT = TypeVar("PerceptionT", contravariant=True)
IntentT = TypeVar("IntentT", covariant=True)
AdjudicationT = TypeVar("AdjudicationT", covariant=True)


class TextModel(Protocol):
    """Smallest model surface accepted by explicit model adapters."""

    def complete(self, prompt: str, timeout_seconds: float | None = None) -> str: ...


class ActorPolicy(Protocol[WorldT, StateT, OpportunityT, ActionT]):
    def choose(
        self,
        world: WorldT,
        state: StateT,
        actor_id: str,
        opportunities: tuple[OpportunityT, ...],
    ) -> ActionT: ...


class SceneGenerator(Protocol[SceneContextT, SceneT]):
    def generate(self, context: SceneContextT) -> SceneT: ...


class IntentPolicy(Protocol[WorldT, StateT, PerceptionT, IntentT]):
    def decide(
        self,
        world: WorldT,
        state: StateT,
        perception: PerceptionT,
    ) -> IntentT: ...


class WorldAdjudicator(
    Protocol[WorldT, StateT, IntentT, AdjudicationT]
):
    def adjudicate(
        self,
        world: WorldT,
        state: StateT,
        intent: IntentT,
    ) -> AdjudicationT: ...


class NarrativeRenderer(Protocol[DigestT, RenderedT]):
    def render(self, digest: DigestT) -> RenderedT: ...


class RunStorage(Protocol[CompiledT, RunT]):
    def create(self, compiled: CompiledT, seed: int) -> RunT: ...

    def load(self, compiled: CompiledT) -> RunT: ...

    def save(self, run: RunT, destination: str | Path | None = None) -> Path: ...


class PresentationStorage(Protocol[DigestT, RenderedT, PresentationT]):
    def cursor_for(self, audience_id: str) -> int: ...

    def publish(
        self,
        digest: DigestT,
        rendered: RenderedT,
        *,
        cursor_after: int,
        audience_id: str = "omniscient",
        diagnostics: tuple[object, ...] = (),
    ) -> PresentationT: ...

    def get(self, presentation_id: str) -> PresentationT: ...

    def rerender(
        self,
        presentation_id: str,
        rendered: RenderedT,
        *,
        diagnostics: tuple[object, ...] = (),
    ) -> PresentationT: ...
