"""Personal experience and fallible knowledge, never objective world truth."""

from __future__ import annotations

from dataclasses import dataclass
import math

from engine.contracts.community import require_int, require_sources, require_text


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    owner_id: str
    tick: int
    summary: str
    source_refs: tuple[str, ...]
    kind: str = "experience"
    participants: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    importance: int = 50
    tier: str = "episodic"

    def __post_init__(self) -> None:
        for field in ("memory_id", "owner_id", "summary"):
            require_text(getattr(self, field), field)
        require_int(self.tick, "tick")
        require_sources(self.source_refs)
        require_int(self.importance, "importance")
        if self.importance > 100:
            raise ValueError("importance exceeds 100")
        if self.kind not in {"experience", "observation", "heard", "inference", "reflection"}:
            raise ValueError("invalid memory kind")
        if self.tier not in {"working", "episodic", "semantic", "autobiographical"}:
            raise ValueError("invalid memory tier")
        if any(len(items) > 32 for items in (self.participants, self.entity_ids, self.topics)):
            raise ValueError("memory tags exceed budget")


@dataclass(frozen=True)
class KnowledgeClaim:
    claim_id: str
    owner_id: str
    subject: str
    predicate: str
    content: str
    source_refs: tuple[str, ...]
    acquired_tick: int
    channel: str
    confidence: float = 0.5
    source_person: str = ""
    contradicts: tuple[str, ...] = ()
    expires_tick: int | None = None

    def __post_init__(self) -> None:
        for field in ("claim_id", "owner_id", "subject", "predicate", "content"):
            require_text(getattr(self, field), field)
        require_sources(self.source_refs)
        require_int(self.acquired_tick, "acquired_tick")
        if self.channel not in {"observation", "heard", "inference", "seed", "learned"}:
            raise ValueError("invalid claim channel")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(self.confidence)
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be finite and between 0 and 1")
        if self.expires_tick is not None:
            require_int(self.expires_tick, "expires_tick")
            if self.expires_tick <= self.acquired_tick:
                raise ValueError("claim must expire after acquisition")
        if len(self.contradicts) > 16 or self.claim_id in self.contradicts:
            raise ValueError("invalid contradiction references")
