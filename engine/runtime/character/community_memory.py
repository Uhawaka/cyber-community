"""Deterministic, owned memory indexing with relevance and size budgets."""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heapify, heappop

from engine.contracts.cognition import MemoryRecord
from engine.runtime.character.community_event_view import visible_event_summary


@dataclass(frozen=True)
class RetrievedMemory:
    record: MemoryRecord
    score: int
    reasons: tuple[str, ...]


class MemoryIndex:
    def __init__(self):
        self.records = {}
        self.by_owner = {}
        self.by_entity = {}
        self.by_person = {}
        self.by_topic = {}

    def add(self, record: MemoryRecord):
        old = self.records.get(record.memory_id)
        if old is not None:
            self._update(old, remove=True)
        self.records[record.memory_id] = record
        self._update(record)

    def _update(self, record, remove=False):
        keys = (
            (self.by_owner, (record.owner_id,)),
            (self.by_entity, record.entity_ids),
            (self.by_person, record.participants),
            (self.by_topic, record.topics),
        )
        for index, values in keys:
            for key in values:
                ids = index.setdefault(key, set())
                ids.discard(record.memory_id) if remove else ids.add(record.memory_id)

    def retrieve(self, owner_id, *, tick, entity_ids=(), participant_ids=(),
                 topics=(), query="", limit=12, character_budget=3000):
        if limit < 0 or character_budget < 0:
            raise ValueError("memory budgets must be non-negative")
        if limit == 0 or character_budget == 0:
            return ()
        owned = self.by_owner.get(owner_id, set())
        entities, people, subjects = set(entity_ids), set(participant_ids), set(topics)
        words = tuple(word for word in query.split() if len(word) > 1)
        # All owned memories remain eligible; recency-only truncation loses old relevant evidence.
        ranked = []
        for memory_id in owned:
            record = self.records[memory_id]
            reasons = []
            score = record.importance
            if entities.intersection(record.entity_ids):
                score += 160
                reasons.append("related entity")
            if people.intersection(record.participants):
                score += 120
                reasons.append("related person")
            if subjects.intersection(record.topics):
                score += 80
                reasons.append("related topic")
            if query and (query in record.summary or any(word in record.summary for word in words)):
                score += 100
                reasons.append("related goal text")
            age = max(0, tick - record.tick)
            score += max(0, 30 - age)
            if age <= 5:
                reasons.append("recent")
            if record.importance >= 70:
                reasons.append("important")
            item = RetrievedMemory(record, score, tuple(reasons))
            ranked.append((-score, -record.tick, record.memory_id, item))
        heapify(ranked)
        selected, used, texts = [], 0, set()
        while ranked and len(selected) < limit:
            item = heappop(ranked)[-1]
            cost = len(item.record.summary) + sum(map(len, item.record.source_refs))
            if used + cost > character_budget or item.record.summary in texts:
                continue
            selected.append(item)
            used += cost
            texts.add(item.record.summary)
        return tuple(selected)


def memory_from_event(event, owner_id):
    kind = event.event_type.value
    if kind in {"run_created", "community_tick", "environment_decayed", "waited", "cognition_recorded",
                "model_decision_requested", "model_decision_resolved"}:
        return None
    summary = visible_event_summary(event, owner_id).strip()
    if not summary:
        return None
    channel = "heard" if kind in {"dialogue", "organization_read", "organization_censured"} else "observation" if kind == "inspected" else "experience"
    importance = {
        "activity_finished": 75, "action_rejected": 60, "dialogue": 55,
        "commitment_updated": 85, "inspected": 70, "rested": 25,
        "activity_started": 45, "process_settled": 40,
    }.get(kind, 50)
    participants = tuple(sorted({
        person for person in (event.actor_id, event.data.get("listener_id"),
                              *event.data.get("participant_ids", ()))
        if isinstance(person, str)
    }))
    entities = tuple(sorted({
        entity for entity in (event.target_entity_id, event.data.get("resource_id"))
        if isinstance(entity, str)
    }))
    return MemoryRecord(
        f"memory:{owner_id}:{event.sequence}", owner_id, event.tick, summary[:2000],
        (f"event:{event.sequence}",), channel, participants, entities,
        (kind,), importance,
    )
