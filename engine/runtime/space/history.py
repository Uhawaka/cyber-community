"""Location-local public history projected only from committed events."""

from __future__ import annotations

from typing import Any, Iterable

from engine.runtime.kernel.events import WorldEvent


def project_location_history(
    events: Iterable[WorldEvent],
    location_id: str,
    *,
    limit: int = 12,
) -> tuple[dict[str, Any], ...]:
    if limit < 0:
        raise ValueError("history limit must be non-negative")
    traces: list[dict[str, Any]] = []
    for event in events:
        if not event.data.get("public_trace"):
            continue
        locations = event.data.get("location_ids")
        applies = (
            event.data.get("location_id") == location_id
            or isinstance(locations, (list, tuple)) and location_id in locations
        )
        if not applies:
            continue
        traces.append(
            {
                "sequence": event.sequence,
                "tick": event.tick,
                "kind": event.event_type.value,
                "actor_id": event.actor_id,
                "target_entity_id": event.target_entity_id,
            }
        )
    return tuple(traces[-limit:])
