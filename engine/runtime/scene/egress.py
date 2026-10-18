"""Generic post-closure choices without authored plot routing."""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from typing import Any

from engine.contracts import (
    BuiltinComponent,
    SceneTransition,
    scene_entity_id,
)
from engine.runtime.simulation.run import AutonomousRun


@dataclass(frozen=True)
class EgressCandidate:
    transition: SceneTransition
    kind: str
    name: str
    description: str
    passage_id: str | None = None


def egress_candidates(
    run: AutonomousRun, actor_id: str
) -> tuple[EgressCandidate, ...]:
    character = run.state.characters[actor_id]
    actor = run.state.entities.get(actor_id)
    if actor is None:
        return ()
    presence = actor.components.get(BuiltinComponent.PRESENCE.value, {})
    current_scene_id = str(presence.get("scene_id", ""))
    current_location = next(
        item
        for item in run.compiled.world.locations
        if item.id == character.location_id
    )
    candidates: list[EgressCandidate] = []
    for seed in current_location.scene_seeds:
        transition = SceneTransition(current_location.id, seed.key)
        scene_id = scene_entity_id(current_location.id, seed.key)
        if scene_id == current_scene_id:
            continue
        scene = run.state.entities.get(scene_id)
        if (
            scene is not None
            and scene.components.get(
                BuiltinComponent.DRAMATIC.value, {}
            ).get("status")
            == "resolved"
        ):
            continue
        candidates.append(
            EgressCandidate(
                transition,
                "scene",
                seed.name,
                seed.premise,
            )
        )
    routes = _routes_to_open_locations(run, character.location_id)
    for passage, goal_id in routes:
        destination = next(
            item
            for item in run.compiled.world.locations
            if item.id == passage.destination_id
        )
        goal = next(
            item
            for item in run.compiled.world.locations
            if item.id == goal_id
        )
        candidates.append(
            EgressCandidate(
                SceneTransition(destination.id, "default"),
                "travel" if destination.id == goal_id else "transit",
                destination.name,
                (
                    destination.description
                    if destination.id == goal_id
                    else f"经{destination.name}前往仍有未决场景的{goal.name}。"
                ),
                passage.id,
            )
        )
    return tuple(candidates)


def deterministic_egress(
    run: AutonomousRun,
    actor_id: str,
    candidates: tuple[EgressCandidate, ...],
) -> SceneTransition | None:
    if not candidates:
        return None
    actor = run.state.entities.get(actor_id)
    agent = (
        {}
        if actor is None
        else actor.components.get(BuiltinComponent.AGENT.value, {})
    )
    scene = (
        None
        if actor is None
        else run.state.entities.get(
            str(
                actor.components.get(
                    BuiltinComponent.PRESENCE.value, {}
                ).get("scene_id", "")
            )
        )
    )
    decisions = (
        {}
        if scene is None
        else scene.components.get(
            BuiltinComponent.DRAMATIC.value, {}
        ).get("decisions", {})
    )
    text = " ".join(
        (
            *run.state.characters[actor_id].goals,
            str(dict(decisions).get(actor_id, "")),
            str(agent.get("motivation", "")),
        )
    ).lower()
    exploration = int(
        run.state.characters[actor_id].needs.get("exploration", 0)
    )

    def score(candidate: EgressCandidate) -> tuple[int, int]:
        terms = (
            candidate.transition.location_id.lower(),
            candidate.transition.scene_key.lower(),
            candidate.name.lower(),
        )
        explicit = sum(80 for term in terms if term and term in text)
        novelty = 20 if candidate.kind == "scene" else exploration
        digest = int.from_bytes(
            hashlib.sha256(
                f"{actor_id}:{candidate.transition}".encode()
            ).digest()[:2],
            "big",
        )
        return explicit + novelty, -digest

    return max(candidates, key=score).transition


def _routes_to_open_locations(
    run: AutonomousRun, origin_id: str
) -> tuple[tuple[Any, str], ...]:
    """Return first authored hops on shortest routes to unfinished locations."""

    open_ids = {
        location.id
        for location in run.compiled.world.locations
        if location.id != origin_id and _has_open_scene(run, location)
    }
    if not open_ids:
        return ()
    outgoing: dict[str, list[Any]] = {}
    for passage in run.compiled.world.passages:
        outgoing.setdefault(passage.origin_id, []).append(passage)
    queue: deque[tuple[str, Any | None]] = deque([(origin_id, None)])
    distances = {origin_id: 0}
    found_distance: int | None = None
    routes: list[tuple[Any, str]] = []
    while queue:
        location_id, first_hop = queue.popleft()
        distance = distances[location_id]
        if found_distance is not None and distance >= found_distance:
            continue
        for passage in outgoing.get(location_id, ()):
            destination_id = passage.destination_id
            next_distance = distance + 1
            if (
                destination_id in distances
                and distances[destination_id] < next_distance
            ):
                continue
            hop = passage if first_hop is None else first_hop
            if destination_id in open_ids:
                found_distance = next_distance
                routes.append((hop, destination_id))
                continue
            if destination_id not in distances:
                distances[destination_id] = next_distance
                queue.append((destination_id, hop))
    unique: dict[tuple[str, str], tuple[Any, str]] = {}
    for passage, goal_id in routes:
        unique[(passage.id, goal_id)] = (passage, goal_id)
    return tuple(unique[key] for key in sorted(unique))


def _has_open_scene(run: AutonomousRun, location: Any) -> bool:
    for seed in location.scene_seeds:
        scene = run.state.entities.get(scene_entity_id(location.id, seed.key))
        if scene is None or scene.components.get(
            BuiltinComponent.DRAMATIC.value, {}
        ).get("status") != "resolved":
            return True
    return False
