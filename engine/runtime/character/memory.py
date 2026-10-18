"""Character memory is a projection, never an objective event source."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from engine.runtime.kernel.events import EventType, WorldEvent
from engine.world.package_spec import PackageCharacter


class MemoryTier(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    CORE = "core"


@dataclass(frozen=True)
class Memory:
    tier: MemoryTier
    summary: str
    source_sequence: int | None
    confidence: float
    belief_type: str = "observation"
    source: str = "event_log"
    seeded: bool = False
    source_sequences: tuple[int, ...] = ()


class MemoryProjection:
    WORKING_BUDGET = 5
    EPISODIC_BUDGET = 24
    SEMANTIC_BUDGET = 12
    CORE_BUDGET = 16

    def __init__(self, characters: Iterable[PackageCharacter]) -> None:
        self._seed: dict[str, tuple[Memory, ...]] = {}
        for character in characters:
            self._seed[character.id] = tuple(
                Memory(
                    tier=MemoryTier.CORE,
                    summary=str(item.get("summary") or item.get("kind") or "seed memory"),
                    source_sequence=None,
                    confidence=float(item.get("confidence", 0.5)),
                    belief_type=str(item.get("kind", "belief")),
                    source=str(item.get("source", "character_seed")),
                    seeded=True,
                )
                for item in character.memory_seed
            )

    def register_avatar(
        self, character_id: str, memory_seed: Iterable[Mapping[str, Any]]
    ) -> None:
        """Install only the Avatar's private, validated seed projection."""

        if character_id in self._seed:
            return
        self._seed[character_id] = tuple(
            Memory(
                tier=MemoryTier.CORE,
                summary=str(item.get("summary", "seed memory")),
                source_sequence=None,
                confidence=float(item.get("confidence", 0.5)),
                belief_type=str(item.get("kind", "belief")),
                source=str(item.get("source", "avatar_seed")),
                seeded=True,
            )
            for item in memory_seed
        )

    def for_character(
        self, character_id: str, events: Iterable[WorldEvent]
    ) -> Mapping[MemoryTier, tuple[Memory, ...]]:
        event_values = tuple(events)
        visible = [
            event
            for event in event_values
            if character_id in event.observers
            and event.event_type is not EventType.MEMORY_CONSOLIDATED
        ]
        visible_sequences = {event.sequence for event in visible}
        consolidated = tuple(
            self._consolidated_memory(event)
            for event in event_values
            if event.event_type is EventType.MEMORY_CONSOLIDATED
            and character_id in event.observers
            and set(event.data.get("source_sequences", ())).issubset(visible_sequences)
        )
        episodic = tuple(
            self._event_memory(event, MemoryTier.EPISODIC)
            for event in visible[-self.EPISODIC_BUDGET :]
        )
        semantic = tuple(
            memory for memory in consolidated if memory.tier is MemoryTier.SEMANTIC
        )[-self.SEMANTIC_BUDGET :]
        runtime_core = tuple(
            memory for memory in consolidated if memory.tier is MemoryTier.CORE
        )
        working = tuple(
            self._event_memory(event, MemoryTier.WORKING)
            for event in visible[-self.WORKING_BUDGET :]
        )
        return {
            MemoryTier.WORKING: working,
            MemoryTier.EPISODIC: episodic,
            MemoryTier.SEMANTIC: semantic,
            MemoryTier.CORE: (
                self._seed.get(character_id, ()) + runtime_core
            )[-self.CORE_BUDGET :],
        }

    @staticmethod
    def _event_memory(event: WorldEvent, tier: MemoryTier) -> Memory:
        summary = str(
            event.data.get("utterance")
            or event.data.get("summary")
            or event.data.get("description")
            or event.event_type.value
        )
        return Memory(
            tier,
            summary,
            event.sequence,
            float(event.data.get("confidence", 1.0)),
            str(event.data.get("belief_type", "observation")),
            str(event.data.get("source", f"event:{event.sequence}")),
            source_sequences=(event.sequence,),
        )

    @staticmethod
    def _consolidated_memory(event: WorldEvent) -> Memory:
        sequences = tuple(int(item) for item in event.data["source_sequences"])
        tier = MemoryTier(str(event.data["target_tier"]))
        return Memory(
            tier=tier,
            summary=str(event.data["summary"]),
            source_sequence=sequences[0],
            confidence=float(event.data["confidence"]),
            belief_type=str(event.data["belief_type"]),
            source="consolidation:" + ",".join(str(item) for item in sequences),
            source_sequences=sequences,
        )
