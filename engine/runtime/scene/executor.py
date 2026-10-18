"""Bounded scene-turn execution for the evolution workflow."""

from __future__ import annotations

from dataclasses import dataclass

from engine.contracts import BuiltinComponent
from engine.runtime.scene.generation import (
    DeterministicSceneGenerator,
    ensure_scene,
)
from engine.runtime.scene.egress import (
    deterministic_egress,
    egress_candidates,
)
from engine.runtime.scene.lifecycle import (
    enter_scene,
    evolve_scene_time,
    travel_to_scene,
)
from engine.runtime.scene.dispatch import resolve_dispatched_intent
from engine.runtime.scene.npc import resolve_ambient_npc_requests
from engine.runtime.scene.perception import project_perception
from engine.runtime.scene.policies import (
    DeterministicIntentPolicy,
    DeterministicWorldAdjudicator,
)
from engine.runtime.simulation.run import AutonomousRun


@dataclass(frozen=True)
class SceneTurnUsage:
    character_turns: int = 0
    ambient_npc_turns: int = 0

    @property
    def total_turns(self) -> int:
        return self.character_turns + self.ambient_npc_turns


def _unlanded_location(
    run: AutonomousRun, actor_ids: tuple[str, ...]
) -> str | None:
    """Location of an open scene that still has no committed decision."""

    focus_scene_id = _focus_scene(run, actor_ids)
    fallback = None
    for actor_id in actor_ids:
        actor = run.state.entities.get(actor_id)
        if actor is None:
            continue
        presence = actor.components.get(BuiltinComponent.PRESENCE.value, {})
        scene_id = str(presence.get("scene_id", ""))
        scene = run.state.entities.get(scene_id)
        if scene is None:
            continue
        dramatic = scene.components.get(BuiltinComponent.DRAMATIC.value, {})
        if dramatic.get("status") == "resolved" or dramatic.get("decisions"):
            continue
        location_id = str(presence.get("location_id", ""))
        if scene_id == focus_scene_id:
            return location_id
        fallback = fallback or location_id
    return fallback


def _focus_scene(
    run: AutonomousRun, actor_ids: tuple[str, ...]
) -> str:
    """Follow one open place until it lands, instead of braiding every place."""

    ranked: list[tuple[bool, int, int, str]] = []
    seen: set[str] = set()
    for actor_id in actor_ids:
        actor = run.state.entities.get(actor_id)
        if actor is None:
            continue
        scene_id = str(
            actor.components.get(BuiltinComponent.PRESENCE.value, {}).get(
                "scene_id", ""
            )
        )
        if not scene_id or scene_id in seen:
            continue
        seen.add(scene_id)
        scene = run.state.entities.get(scene_id)
        if scene is None:
            continue
        dramatic = scene.components.get(BuiltinComponent.DRAMATIC.value, {})
        if dramatic.get("status") == "resolved":
            continue
        attributes = scene.components.get(
            BuiltinComponent.ATTRIBUTES.value, {}
        )
        pressure = int(dramatic.get("pressure_level", 0) or 0)
        turn_count = int(attributes.get("turn_count", 0) or 0)
        ranked.append((turn_count > 0, pressure, turn_count, scene_id))
    if not ranked:
        return ""
    return max(ranked)[3]


def run_scene_turns(
    run: AutonomousRun,
    actor_ids: tuple[str, ...],
    *,
    turn_budget: int,
) -> SceneTurnUsage:
    if turn_budget < 0:
        raise ValueError("scene turn budget must be non-negative")
    generator = run.scene_generator or DeterministicSceneGenerator()
    intent_policy = run.intent_policy or DeterministicIntentPolicy()
    adjudicator = (
        run.world_adjudicator or DeterministicWorldAdjudicator()
    )
    for location_id in sorted(
        {
            run.state.characters[actor_id].location_id
            for actor_id in actor_ids
        }
    ):
        ensure_scene(run, location_id, generator)
    active_scene_ids = {
        str(
            run.state.entities[actor_id]
            .components["presence"]["scene_id"]
        )
        for actor_id in actor_ids
        if actor_id in run.state.entities
        and "presence" in run.state.entities[actor_id].components
    }
    for scene_id in sorted(active_scene_ids):
        evolve_scene_time(run, scene_id)
    used = 0
    spoken: set[str] = set()
    focus_scene_id = _focus_scene(run, actor_ids)
    landing_location = _unlanded_location(run, actor_ids)
    egress_destination: tuple[str, str] | None = None
    for actor_id in actor_ids:
        if used >= turn_budget:
            break
        actor = run.state.entities.get(actor_id)
        if actor is not None:
            presence = actor.components.get(
                BuiltinComponent.PRESENCE.value, {}
            )
            scene_id = str(presence.get("scene_id", ""))
            scene = run.state.entities.get(scene_id)
            if (
                scene is not None
                and scene.components.get(
                    BuiltinComponent.DRAMATIC.value, {}
                ).get("status")
                == "resolved"
            ):
                candidates = egress_candidates(run, actor_id)
                if not candidates:
                    continue
                perception = project_perception(run.state, actor_id)
                selected = None
                decide_egress = getattr(
                    intent_policy, "decide_egress", None
                )
                if callable(decide_egress):
                    selected = decide_egress(
                        run.compiled.world,
                        run.state,
                        perception,
                        candidates,
                    )
                if selected is None:
                    transition = deterministic_egress(
                        run, actor_id, candidates
                    )
                    reason = (
                        "目标、公开决定与探索需求的确定性回退选择"
                    )
                else:
                    transition, reason = selected
                if transition is None:
                    continue
                destination = (transition.location_id, transition.scene_key)
                if (
                    landing_location
                    and transition.location_id != landing_location
                ):
                    continue
                if egress_destination is None:
                    egress_destination = destination
                elif destination != egress_destination:
                    continue
                current_location = run.state.characters[
                    actor_id
                ].location_id
                if transition.location_id == current_location:
                    enter_scene(
                        run,
                        actor_id,
                        transition.location_id,
                        generator,
                        scene_key=transition.scene_key,
                        egress_reason=reason,
                    )
                else:
                    travel_to_scene(
                        run,
                        actor_id,
                        transition.location_id,
                        generator,
                        scene_key=transition.scene_key,
                        egress_reason=reason,
                    )
                used += 1
                continue
            if focus_scene_id and scene_id != focus_scene_id:
                continue
        if actor_id in spoken:
            continue
        perception = project_perception(run.state, actor_id)
        intent = intent_policy.decide(
            run.compiled.world, run.state, perception
        )
        resolve_dispatched_intent(
            run,
            intent,
            intent_policy=intent_policy,
            adjudicator=adjudicator,
            generator=generator,
            depth=0,
            spoken=spoken,
        )
        used += 1
    npc_events = resolve_ambient_npc_requests(
        run, limit=max(0, turn_budget - used)
    )
    return SceneTurnUsage(used, len(npc_events))
