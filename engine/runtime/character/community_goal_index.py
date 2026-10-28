"""Committed goal origins and actor/target evidence, preserving historical order."""

from dataclasses import dataclass, field

from engine.runtime.kernel.events import EventType


@dataclass
class GoalEvidenceIndex:
    origins: dict[str, int] = field(default_factory=dict)
    evidence: dict[tuple[str, str], list[int]] = field(default_factory=dict)

    def add(self, event):
        if event.event_type is EventType.GOAL_UPDATED:
            self.origins.setdefault(event.data["goal"]["goal_id"], event.sequence)
        if event.event_type in {
            EventType.INSPECTED, EventType.GATHERED, EventType.DIALOGUE, EventType.ACTIVITY_FINISHED,
        }:
            self.evidence.setdefault((event.actor_id, event.target_entity_id), []).append(event.sequence)

    def for_goal(self, goal, events):
        return tuple(events[n] for n in self.evidence.get((goal.owner_id, goal.target_id), ()))
