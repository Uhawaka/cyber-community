"""Read-only source-connected threads, not a director of community actions."""

from __future__ import annotations

from collections import defaultdict

from engine.contracts.community_history import CommunityFact, StoryThread


def project_threads(facts, *, max_threads=8, max_evidence=24, stances=()):
    if max_threads < 0 or max_evidence < 1:
        raise ValueError("invalid story observation budget")
    stances = frozenset((str(left), str(right)) for left, right in stances)
    ordered = tuple(sorted(facts, key=lambda f: f.sequence))
    groups, membership = defaultdict(list), {}
    environment = []
    for fact in ordered:
        if fact.kind == "process_settled":
            environment.append(fact)
            continue
        if fact.kind in {"cognition_recorded", "waited", "rested"}:
            continue
        if fact.kind == "commitment_updated":
            key = f"commitment:{fact.object_id}"
        elif fact.kind == "exchange_updated":
            key = f"exchange:{fact.object_id}"
        elif fact.kind == "request_updated":
            key = f"request:{fact.object_id}"
        else:
            inherited = [membership[s] for s in fact.source_sequences if s in membership]
            key = inherited[0] if inherited else f"person:{fact.actor_id}:target:{fact.target_id}"
        groups[key].append(fact)
        membership[fact.sequence] = key
    threads = []
    for key, evidence in groups.items():
        significant = any(
            f.kind in {"commitment_updated", "exchange_updated", "request_updated", "action_rejected"}
            or f.kind == "activity_finished" and f.action_verb in {"repair", "learn"}
            and f.status in {"completed", "failed"}
            for f in evidence
        ) or _dialogue_carries_authored_stake(evidence, stances)
        if not significant:
            continue
        targets = [f.target_id for f in evidence if f.target_id]
        target = targets[0] if targets else ""
        relevant_environment = [
            f for f in environment if f.target_id == target
            and evidence[0].tick <= f.tick <= evidence[-1].tick
        ]
        full = sorted((*evidence, *relevant_environment), key=lambda f: f.sequence)
        goals, obligations = {}, {}
        for fact in evidence:
            if fact.goal_id:
                goals[fact.goal_id] = fact.status
            if fact.kind in {"commitment_updated", "exchange_updated", "request_updated"}:
                obligations[fact.object_id] = fact.status
        unresolved = tuple(sorted(
            [goal_id for goal_id, status in goals.items() if status == "active"]
            + [record_id for record_id, status in obligations.items() if status in {"proposed", "accepted", "open"}
               and not (key.startswith("exchange:") and status == "accepted")]
        ))
        importance = sum(
            6 if f.status in {"fulfilled", "breached", "failed"}
            else 4 if f.kind == "activity_finished" and f.action_verb in {"repair", "learn"}
            else 2 if f.kind == "dialogue" else 1
            for f in evidence
        )
        threads.append(StoryThread(
            key, tuple(sorted({p for f in evidence for p in f.participants})), target,
            tuple(f.sequence for f in full), full[0].tick, full[-1].tick,
            unresolved, importance, tuple(full[-max_evidence:]),
        ))
    threads.sort(key=lambda t: (-t.significance, -t.to_tick, t.thread_id))
    return tuple(threads[:max_threads])


def _dialogue_carries_authored_stake(evidence, stances):
    """A back-and-forth between two people the author gave a stake in each other.

    Dialogue alone is not an event: the selector only promotes a spoken
    exchange when it has at least one answer and the author declared a
    stance between the speakers. Nothing here invents a transition or a
    consequence; it only decides whether the material is worth showing.
    """
    if not stances:
        return False
    dialogues = [f for f in evidence if f.kind == "dialogue"]
    if len(dialogues) < 2:
        return False
    for fact in dialogues:
        people = tuple(dict.fromkeys(fact.participants))
        for left in people:
            for right in people:
                if left != right and (left, right) in stances:
                    return True
    return False


def render_thread(thread: StoryThread, *, names=None):
    """A factual reading window; no invented transitions, thoughts or dialogue."""
    names = names or {}
    lines = []
    for fact in thread.evidence:
        if not fact.summary or fact.kind in {"plan_updated", "process_settled"}:
            continue
        speaker = names.get(fact.actor_id, fact.actor_id or "世界")
        text = f"{speaker}：{fact.utterance}" if fact.utterance else fact.summary
        lines.append(f"[Tick {fact.tick}, event:{fact.sequence}] {text}")
    return "\n".join(lines)
