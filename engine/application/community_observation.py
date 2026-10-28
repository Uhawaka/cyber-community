"""Public read-only community windows, without exposing private cognition."""

from __future__ import annotations

from dataclasses import asdict

from engine.narrative.community_threads import project_threads, render_thread
from engine.runtime.simulation.community_history import community_history


def observe_community(run, *, max_threads=8, max_events=20):
    if run.compiled.community is None:
        raise ValueError("community observation requires a versioned community package")
    if isinstance(max_events, bool) or not isinstance(max_events, int) or not 0 <= max_events <= 100:
        raise ValueError("timeline budget must be an integer between 0 and 100")
    names = {character.id: character.name for character in run.compiled.world.characters}
    history = community_history(run, audience="observer")
    threads = project_threads(history, max_threads=max_threads)
    recent = history[-max_events:] if max_events else ()
    return {
        "schema_version": "community-observation/v1",
        "world_title": run.compiled.world.title,
        "world_hash": run.compiled.content_hash,
        "history_hash": run.history_hash(),
        "runtime_version": run.compiled.community.runtime_version,
        "seed": run.state.seed,
        "tick": run.state.tick,
        "world_time_minutes": run.state.world_time,
        "event_count": len(run.events),
        "audience": "observer",
        "recent_events": [{
            "sequence": fact.sequence, "tick": fact.tick, "kind": fact.kind,
            "actor_id": fact.actor_id, "action_verb": fact.action_verb,
            "changed_world": fact.changed_world,
            "utterance": fact.utterance if fact.kind == "dialogue" else "",
        } for fact in recent],
        "threads": [{**asdict(thread), "text": render_thread(thread, names=names)} for thread in threads],
        "quality_status": "not_evaluated",
    }
