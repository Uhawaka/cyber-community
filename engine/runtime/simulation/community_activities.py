"""Explicit cancellation preserves already committed costs and provenance."""

from __future__ import annotations

from engine.runtime.character.community_projection import community_projection
from engine.runtime.kernel.events import EventType
from engine.runtime.simulation.community_events import commit


def cancel_activity(run, actor_id, activity_id):
    activity = community_projection(run).activities.get(activity_id)
    if activity is None or activity.actor_id != actor_id:
        raise ValueError("cancellation requires a pending owned activity")
    origin = run.log.activity_start(activity_id)
    return commit(
        run, EventType.ACTIVITY_FINISHED, actor_id=actor_id, observers=(actor_id,),
        data={"activity_id": activity_id, "status": "cancelled",
              "summary": "activity cancelled; committed inputs are not refunded"},
        commit_id=f"activity:{activity_id}:finish", target_id=activity.target_id,
        sources=(f"event:{origin.sequence}",),
    )
