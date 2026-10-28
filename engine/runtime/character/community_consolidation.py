"""Budgeted, source-preserving reflection without model calls."""

from __future__ import annotations

from dataclasses import asdict

from engine.contracts.cognition import MemoryRecord
from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import EventType
from engine.runtime.simulation.community_events import commit


def consolidate(run, budget=1):
    if budget < 0:
        raise ValueError("memory budget must be non-negative")
    projection = community_projection(run)
    candidates = []
    for actor_id, actor in run.state.characters.items():
        if not actor.active:
            continue
        previous = max(
            (m.tick for m in projection.memories.values()
             if m.owner_id == actor_id and m.kind == "reflection"),
            default=0,
        )
        rested = any(
            e.tick > previous and e.actor_id == actor_id and e.event_type is EventType.RESTED
            for e in run.events
        )
        if run.state.tick <= previous or not (rested or run.state.tick - previous >= 24):
            continue
        sources = sorted(
            (m for m in projection.memories.values()
             if m.owner_id == actor_id and m.tick > previous and m.kind != "reflection"
             and m.source_refs[0].startswith("event:")),
            key=lambda m: (-m.importance, -m.tick, m.memory_id),
        )[:3]
        if not sources:
            continue
        candidates.append((previous, actor_id, sources))
    candidates.sort(key=lambda row: (row[0], row[1]))
    used = 0
    for _, actor_id, records in candidates[:budget]:
        refs = tuple(dict.fromkeys(source for record in records for source in record.source_refs))
        summary = " / ".join(record.summary[:500] for record in records)
        memory = MemoryRecord(
            f"reflection:{actor_id}:{run.state.tick}", actor_id, run.state.tick,
            summary, refs, "reflection",
            tuple(sorted({p for record in records for p in record.participants})),
            tuple(sorted({p for record in records for p in record.entity_ids})),
            tuple(sorted({p for record in records for p in record.topics})),
            max(record.importance for record in records), "semantic",
        )
        commit(
            run, EventType.COGNITION_RECORDED, actor_id=actor_id, observers=(actor_id,),
            data={"memories": (asdict(memory),), "claims": (), "trigger": "rest or elapsed day"},
            commit_id=memory.memory_id, sources=refs, target_id=actor_id,
            basis=("deterministic summary preserves lived sources; not new world truth",),
        )
        used += 1
    return used, len(candidates) > used
