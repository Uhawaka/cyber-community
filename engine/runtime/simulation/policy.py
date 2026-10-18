"""Deterministic policy gates for detailed and coarse simulation."""

from __future__ import annotations

from dataclasses import dataclass

from engine.runtime.kernel.state import WorldState
from engine.world.package_spec import CompiledWorld


@dataclass(frozen=True)
class SimulationPolicy:
    """Bounds work and selects the characters eligible for detailed simulation.

    Empty hot selections preserve the small-world default: every NPC is hot.
    When either selection is populated, their union is hot.
    """

    max_catchup_ticks: int = 24
    hot_character_ids: tuple[str, ...] = ()
    hot_location_ids: tuple[str, ...] = ()
    action_budget: int | None = None
    opportunity_budget: int | None = None
    incident_budget: int = 1
    memory_budget: int = 1
    need_decay: tuple[tuple[str, int], ...] = (
        ("fatigue", 2),
        ("social", 2),
        ("resources", 1),
        ("knowledge", 1),
        ("exploration", 1),
    )

    def __post_init__(self) -> None:
        values = {
            "max_catchup_ticks": self.max_catchup_ticks,
            "incident_budget": self.incident_budget,
            "memory_budget": self.memory_budget,
        }
        if self.action_budget is not None:
            values["action_budget"] = self.action_budget
        if self.opportunity_budget is not None:
            values["opportunity_budget"] = self.opportunity_budget
        if any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for value in values.values()
        ):
            raise ValueError("simulation budgets must be non-negative integers")
        object.__setattr__(
            self, "hot_character_ids", tuple(sorted(set(self.hot_character_ids)))
        )
        object.__setattr__(
            self, "hot_location_ids", tuple(sorted(set(self.hot_location_ids)))
        )
        if any(
            not isinstance(name, str) or not isinstance(amount, int) or amount < 0
            for name, amount in self.need_decay
        ):
            raise ValueError("need decay must contain non-negative integer values")
        object.__setattr__(self, "need_decay", tuple(sorted(self.need_decay)))

    @classmethod
    def from_compiled(cls, compiled: CompiledWorld) -> "SimulationPolicy":
        policy = dict(compiled.workflow.evolution.policy)
        return cls(
            max_catchup_ticks=int(policy["max_catchup_ticks"]),
            hot_character_ids=tuple(policy["hot_character_ids"]),
            hot_location_ids=tuple(policy["hot_location_ids"]),
            action_budget=int(policy["action_budget"]),
            opportunity_budget=int(policy["opportunity_budget"]),
            incident_budget=int(policy["incident_budget"]),
            memory_budget=int(policy["memory_budget"]),
            need_decay=tuple(
                (str(name), int(amount))
                for name, amount in dict(policy["need_decay"]).items()
            ),
        )

    def hot_characters(self, state: WorldState) -> tuple[str, ...]:
        npc_ids = {
            character_id
            for character_id, character in state.characters.items()
            if character.participant_kind == "npc"
        }
        if not self.hot_character_ids and not self.hot_location_ids:
            return tuple(sorted(npc_ids))
        selected = npc_ids.intersection(self.hot_character_ids)
        selected.update(
            character_id
            for character_id in npc_ids
            if state.characters[character_id].location_id in self.hot_location_ids
        )
        return tuple(sorted(selected))

    def cold_characters(self, state: WorldState) -> tuple[str, ...]:
        hot = set(self.hot_characters(state))
        return tuple(
            sorted(
                character_id
                for character_id, character in state.characters.items()
                if character.participant_kind == "npc" and character_id not in hot
            )
        )
