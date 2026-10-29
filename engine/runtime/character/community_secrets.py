"""Who said what they had kept to themselves, and who heard it.

Read-only: derived from committed dialogue events, never written back to the fact layer.
"""

from __future__ import annotations

from engine.contracts.community_text import REVEAL_OVERLAP, shared_phrase
from engine.runtime.kernel.event_types import EventType

COOLDOWN_TICKS = 8


def _secrets_of(run, actor_id):
    for character in run.compiled.world.characters:
        if character.id != actor_id:
            continue
        for item in character.memory_seed:
            if str(item.get("kind")) != "secret":
                continue
            text = str(item.get("summary") or "").strip()
            if text:
                yield text


def revealed_secrets(run, actor_id, utterance):
    """Secret texts of this actor that the utterance repeats closely enough to be a telling."""
    return tuple(
        text for text in _secrets_of(run, actor_id)
        if shared_phrase(text, utterance) >= REVEAL_OVERLAP
    )


def secret_ledger(run):
    """(owner_id, secret_text) -> tuple of (tick, listener_id) it was told to."""
    ledger = {}
    for event in run.events:
        if event.event_type != EventType.DIALOGUE:
            continue
        utterance = str(event.data.get("utterance") or "")
        if not utterance:
            continue
        listener = event.data.get("listener_id")
        for text in revealed_secrets(run, event.actor_id, utterance):
            ledger.setdefault((event.actor_id, text), []).append((event.tick, listener))
    return {key: tuple(value) for key, value in ledger.items()}


def secret_relays(run):
    """Secrets spoken by somebody other than their owner: (owner, speaker, listener, tick)."""
    owned = {
        character.id: tuple(
            str(item.get("summary") or "").strip() for item in character.memory_seed
            if str(item.get("kind")) == "secret"
        )
        for character in run.compiled.world.characters
    }
    relays = []
    for event in run.events:
        if event.event_type != EventType.DIALOGUE:
            continue
        utterance = str(event.data.get("utterance") or "")
        if not utterance:
            continue
        listener = event.data.get("listener_id")
        for owner, texts in owned.items():
            if owner in (event.actor_id, listener):
                # 说给本人听不算外传；本人重复自己的事由 told_secrets 负责
                continue
            if any(shared_phrase(text, utterance) >= REVEAL_OVERLAP for text in texts):
                relays.append((owner, event.actor_id, listener, event.tick))
    return tuple(relays)


def leaked_by(run, owner_id, *, limit=3):
    """(speaker, listener) pairs where somebody else told this character's secret."""
    rows = [(tick, speaker, listener) for owner, speaker, listener, tick in secret_relays(run)
            if owner == owner_id]
    rows.sort(reverse=True)
    return tuple((speaker, listener) for _tick, speaker, listener in rows[:limit])


def told_secrets(run, actor_id, *, limit=4):
    """What this character has already said out loud, with the last listener."""
    rows = [
        (entries[-1][0], entries[-1][1], text)
        for (owner, text), entries in secret_ledger(run).items() if owner == actor_id
    ]
    rows.sort(reverse=True)
    return tuple(text for _tick, _listener, text in rows[:limit])


def confidences(run, actor_id, *, limit=4):
    """Secrets other characters told this character directly."""
    rows = [
        (entries[-1][0], owner, text)
        for (owner, text), entries in secret_ledger(run).items()
        if any(listener == actor_id for _tick, listener in entries)
    ]
    rows.sort(reverse=True)
    return tuple((owner, text) for _tick, owner, text in rows[:limit])


def told_recently(run, actor_id, *, window=COOLDOWN_TICKS):
    """Whether this character said a secret out loud within the window."""
    last = [
        entries[-1][0]
        for (owner, _text), entries in secret_ledger(run).items() if owner == actor_id
    ]
    return bool(last) and run.state.tick - max(last) < window
