"""Offline community diagnostics, deliberately separate from literary quality."""

from __future__ import annotations

from collections import Counter

from engine.runtime.character.community_projection import community_projection

IMPORTANT = {"repair", "learn", "take", "transfer", "offer", "accept", "commit", "pursue", "abandon", "request", "handoff",
             "lend", "repay"}


def evaluate_community(run):
    if run.compiled.community is None:
        raise ValueError("community evaluation requires a versioned community package")
    events = tuple(run.events)
    projection = community_projection(run)
    actions = [(e, a) for e in events for a in e.delta.actions]
    important = [(e, a) for e, a in actions if a.kind in IMPORTANT]
    sourced = sum(bool(e.data.get("source_refs")) for e, _ in important)
    reasoned = sum(bool(e.data.get("summary") or e.data.get("utterance")) for e, _ in important)
    per_actor = {}
    for actor_id in sorted(run.state.characters):
        owned = [(e, a) for e, a in actions if a.character_id == actor_id]
        per_actor[actor_id] = {
            "actions": len(owned),
            "verbs": dict(sorted(Counter(a.kind for _, a in owned).items())),
            "rejections": sum(e.actor_id == actor_id and e.event_type.value == "action_rejected" for e in events),
            "learned_skills": sorted(projection.learned_skills.get(actor_id, ())),
            "active_goals": sum(g.owner_id == actor_id and g.status == "active" for g in projection.goals.values()),
            "active_intent_plans": len(projection.intent_plans.pending_owned(actor_id)),
            "pending_activities": len(projection.pending_for(actor_id)),
        }
    negative = [
        f"resource:{item}" for item, value in run.state.resources.items() if value < 0
    ] + [
        f"inventory:{owner}:{item}" for owner, items in run.state.inventories.items()
        for item, value in items.items() if value < 0
    ]
    missing_sources = [e.sequence for e, _ in actions if not e.data.get("source_refs")]
    bad_links = [
        e.sequence for e in events for ref in e.data.get("source_refs", ())
        if ref.startswith("event:") and (
            not ref[6:].isdigit() or not 0 <= int(ref[6:]) < e.sequence
        )
    ]
    replay_matches = run.replay() == run.state
    return {
        "schema_version": "community-evaluation/v1",
        "world_hash": run.compiled.content_hash,
        "history_hash": run.history_hash(),
        "seed": run.state.seed,
        "ticks": run.state.tick,
        "event_count": len(events),
        "mechanism_gates": {
            "replay": replay_matches,
            "nonnegative_inventory": not negative,
            "action_sources": not missing_sources,
            "past_event_references": not bad_links,
        },
        "violations": {
            "negative_inventory": negative,
            "missing_action_sources": missing_sources,
            "invalid_event_references": bad_links,
        },
        "important_actions": {
            "count": len(important),
            "with_sources": sourced,
            "with_reason_text": reasoned,
            "source_coverage": sourced / len(important) if important else None,
            "reason_text_coverage": reasoned / len(important) if important else None,
        },
        "repetition": repetition_diagnostics(events),
        "source_connected_cross_day_candidates": causal_candidates(events),
        "per_actor": per_actor,
        "collaboration": {
            "loans": dict(sorted(Counter(r.status for r in projection.loans.values()).items())),
            "requests": dict(sorted(Counter(r.status for r in projection.requests.values()).items())),
            "offers": dict(sorted(Counter(o.status for o in projection.offers.values()).items())),
            "commitments": dict(sorted(Counter(c.status for c in projection.commitments.values()).items())),
            "handoffs": dict(sorted(Counter(h.status for h in projection.handoffs.values()).items())),
            "responsibilities": sorted(projection.responsibilities),
            "commitment_responses": dict(sorted(Counter(
                "unanswered_expired" if e.data.get("system_update") and e.data["commitment"]["status"] == "rejected"
                else "declined" if e.data["commitment"]["status"] == "rejected"
                else e.data["commitment"]["status"]
                for e in events if e.event_type.value == "commitment_updated"
                and e.data["commitment"]["status"] != "proposed"
            ).items())),
            "labor_commitments": [
                {"commitment_id": c.commitment_id, "promisor_id": c.promisor_id,
                 "beneficiary_id": c.beneficiary_id, "target_id": c.target_id,
                 "deadline_tick": c.deadline_tick, "status": c.status, "source_refs": c.source_refs}
                for c in projection.commitments.values() if c.action_verb == "repair"
            ],
            "personal_repair_contributions": [
                {"sequence": e.sequence, "tick": e.tick, "actor_id": e.actor_id,
                 "target_id": e.target_entity_id, "ledger": e.data["material_ledger"],
                 "receipt_refs": [
                     ref for ref in e.data["source_refs"] if ref.startswith("event:")
                     and events[int(ref[6:])].event_type.value == "exchange_updated"
                     and events[int(ref[6:])].data["offer"]["status"] == "accepted"
                 ]}
                for e in events if e.event_type.value == "activity_started" and e.data.get("material_ledger")
            ],
            "scope": "custody and receipt links, not literary quality or exact lot attribution",
        },
        "projection_size": {
            "memories": len(projection.memories), "claims": len(projection.claims),
            "goals": len(projection.goals), "plans": len(projection.plans),
            "intent_plans": len(projection.intent_plans),
            "pending_activities": len(projection.activities),
            "requests": len(projection.requests),
            "handoffs": len(projection.handoffs),
            "loans": len(projection.loans),
        },
        "quality_gates": {
            "action_explanation": "not_evaluated",
            "unproductive_repetition": "not_evaluated",
            "independent_cross_day_story_chains": "not_evaluated",
            "character_and_literary_blind_review": "not_evaluated",
            "real_model_behavior": "not_evaluated",
        },
    }


def repetition_diagnostics(events, *, window_ticks=20):
    """Flag unchanged inspections/waits, not recurring productive work."""
    previous, signals, suspects, action_ticks = {}, Counter(), [], []
    for e in events:
        kind = e.event_type.value
        if kind in {"dialogue", "activity_finished", "exchange_updated", "commitment_updated",
                    "cognition_recorded", "goal_updated", "process_settled", "request_updated", "responsibility_updated"}:
            for actor_id in e.observers:
                signals[actor_id] += 1
        for action in e.delta.actions:
            action_ticks.append(e.tick)
            if action.kind not in {"inspect", "wait"}:
                continue
            signature = (action.kind, action.target_id, e.data.get("condition"), e.data.get("finding"))
            key = (action.character_id, signature)
            old = previous.get(key)
            if old and e.tick - old[0] < window_ticks and old[1] == signals[action.character_id]:
                suspects.append({"sequence": e.sequence, "tick": e.tick, "actor_id": action.character_id})
            previous[key] = (e.tick, signals[action.character_id])
    worst = None
    for end in sorted(set(action_ticks)):
        denominator = sum(end - window_ticks < tick <= end for tick in action_ticks)
        numerator = sum(end - window_ticks < item["tick"] <= end for item in suspects)
        value = {"from_tick": max(1, end - window_ticks + 1), "to_tick": end,
                 "suspects": numerator, "actions": denominator, "rate": numerator / denominator}
        if worst is None or value["rate"] > worst["rate"]:
            worst = value
    return {"window_ticks": window_ticks, "suspected_events": suspects, "worst_window": worst,
            "scope": "unchanged inspect/wait heuristic; not the frozen semantic repetition gate"}


def causal_candidates(events):
    """Distinct source-connected components, never joined just by target/time."""
    parent = {e.sequence: e.sequence for e in events}

    def root(sequence):
        while parent[sequence] != sequence:
            parent[sequence] = parent[parent[sequence]]
            sequence = parent[sequence]
        return sequence

    for e in events:
        for ref in e.data.get("source_refs", ()):
            if ref.startswith("event:") and ref[6:].isdigit():
                source = int(ref[6:])
                if source in parent and source < e.sequence:
                    parent[root(e.sequence)] = root(source)
    groups = {}
    for e in events:
        groups.setdefault(root(e.sequence), []).append(e)
    result = []
    for group in groups.values():
        initiators = [
            e for e in group if e.delta.actions and any(
                a.kind in {"pursue", "commit", "offer", "transfer", "request"} for a in e.delta.actions
            )
        ]
        consequences = [
            e for e in group if e.event_type.value == "activity_finished"
            and e.data.get("status") == "completed"
            and (e.delta.entity_patches or e.delta.moves or e.data.get("learned_skill"))
            or e.event_type.value == "exchange_updated" and e.data["offer"]["status"] == "accepted"
            or e.event_type.value == "commitment_updated" and e.data["commitment"]["status"] in {"fulfilled", "breached"}
        ]
        if not initiators or not consequences:
            continue
        start = min(e.tick for e in initiators)
        end = max(e.tick for e in consequences)
        if end < start or (end - 1) // 24 <= (start - 1) // 24:
            continue
        result.append({
            "initiator_sequences": [e.sequence for e in initiators],
            "initiators": sorted({e.actor_id for e in initiators}),
            "from_tick": start, "to_tick": end,
            "source_sequences": [e.sequence for e in group],
            "consequence_sequences": [e.sequence for e in consequences],
        })
    return sorted(result, key=lambda item: (item["from_tick"], item["initiator_sequences"]))
