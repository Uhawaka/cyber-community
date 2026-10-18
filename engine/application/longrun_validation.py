"""Topic-neutral diagnostics for autonomous long-form world runs."""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any, Iterable

from engine.runtime.kernel.events import EventType
from engine.runtime.scene.egress import egress_candidates


def evaluate_longrun(
    run: Any,
    presentations: Iterable[Any],
    *,
    fallback_rate: float,
    position_sync_violations: Iterable[str],
) -> dict[str, object]:
    events = tuple(run.events)
    chapters = tuple(presentations)
    turns = tuple(
        item
        for item in events
        if item.event_type is EventType.TURN_RESOLVED
        and item.actor_id in run.state.characters
    )
    signatures = Counter(
        (
            item.actor_id or "",
            _normalize(item.data.get("goal")),
            _normalize(item.data.get("public_action")),
        )
        for item in turns
    )
    progress = Counter(
        str(item.data.get("dramatic_progress", "none")) for item in turns
    )
    visited: dict[str, set[str]] = defaultdict(set)
    revisits = 0
    for actor_id, character in run.initial_state.characters.items():
        visited[actor_id].add(character.location_id)
    for event in events:
        if event.event_type is not EventType.MOVED or not event.actor_id:
            continue
        destination = str(event.data.get("destination_id", ""))
        if destination in visited[event.actor_id]:
            revisits += 1
        visited[event.actor_id].add(destination)
    scene_ids = {
        str(item.data.get("scene_id", ""))
        for item in events
        if item.event_type
        in {EventType.SCENE_INSTANTIATED, EventType.SCENE_ENTERED, EventType.TURN_RESOLVED}
        and item.data.get("scene_id")
    }
    frozen = _resolved_without_egress(run, events)
    episode_ids = [item.episode_id for item in chapters]
    presentation_ids = [item.presentation_id for item in chapters]
    chapter_sources = [
        source_id for item in chapters for source_id in item.source_event_ids
    ]
    continuity_ok = (
        len(episode_ids) == len(set(episode_ids))
        and len(presentation_ids) == len(set(presentation_ids))
        and len(chapter_sources) == len(set(chapter_sources))
    )
    replay_ok = run.replay() == run.state
    location_count = len(
        {
            location
            for actor_locations in visited.values()
            for location in actor_locations
            if location
        }
    )
    movement_count = sum(
        item.event_type is EventType.MOVED for item in events
    )
    none_ratio = (
        progress.get("none", 0) / len(turns) if turns else 0.0
    )
    max_signature_repeat = max(signatures.values(), default=0)
    gates = {
        "position_sync": _gate(not tuple(position_sync_violations), 0, 0),
        "replay_consistency": _gate(replay_ok, replay_ok, True),
        "episode_continuity": _gate(continuity_ok, continuity_ok, True),
        "fallback_rate": _gate(fallback_rate <= 0.1, fallback_rate, "<=0.1"),
        "location_exploration": _gate(location_count >= 2, location_count, ">=2"),
        "scene_exploration": _gate(len(scene_ids) >= 3, len(scene_ids), ">=3"),
        "autonomous_movement": _gate(movement_count >= 1, movement_count, ">=1"),
        "resolved_scene_egress": _gate(not frozen, len(frozen), 0),
        "dramatic_progress": _gate(none_ratio <= 0.75, none_ratio, "<=0.75"),
        "action_repetition": _gate(
            max_signature_repeat <= 3, max_signature_repeat, "<=3"
        ),
    }
    return {
        "passed": all(bool(item["passed"]) for item in gates.values()),
        "gates": gates,
        "metrics": {
            "turn_count": len(turns),
            "dramatic_progress_counts": dict(sorted(progress.items())),
            "dramatic_none_rate": none_ratio,
            "max_repeated_action_signature": max_signature_repeat,
            "disclosure_count": sum(
                len(item.delta.disclosures) for item in events
            ),
            "location_count": location_count,
            "scene_count": len(scene_ids),
            "movement_count": movement_count,
            "revisit_count": revisits,
            "scene_revision_count": sum(
                item.event_type is EventType.SCENE_EVOLVED for item in events
            ),
            "resolved_without_egress": frozen,
            "episode_continuity": continuity_ok,
            "replay_consistent": replay_ok,
        },
    }


def _resolved_without_egress(
    run: Any, events: tuple[Any, ...]
) -> list[dict[str, object]]:
    frozen: list[dict[str, object]] = []
    for index, event in enumerate(events):
        if (
            event.event_type is not EventType.TURN_RESOLVED
            or event.data.get("dramatic_progress") != "resolved"
            or not event.actor_id
        ):
            continue
        later = events[index + 1 :]
        departed = any(
            candidate.tick <= event.tick + 2
            and (
                (
                    candidate.actor_id == event.actor_id
                    and candidate.event_type
                    in {EventType.MOVED, EventType.SCENE_ENTERED}
                )
                or (
                    candidate.event_type is EventType.SCENE_INSTANTIATED
                    and event.actor_id in candidate.observers
                )
            )
            for candidate in later
        )
        has_two_later_ticks = any(
            candidate.tick > event.tick + 2 for candidate in later
        )
        still_has_exit = bool(egress_candidates(run, event.actor_id))
        if has_two_later_ticks and not departed and still_has_exit:
            frozen.append(
                {
                    "actor_id": event.actor_id,
                    "scene_id": event.data.get("scene_id"),
                    "resolved_tick": event.tick,
                }
            )
    return frozen


def _normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _gate(passed: bool, observed: object, expected: object) -> dict[str, object]:
    return {"passed": passed, "observed": observed, "expected": expected}
