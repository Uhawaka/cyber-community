"""Fallible personal claims derived only from owned seeds or received events."""

from __future__ import annotations

from collections.abc import MutableMapping

from engine.contracts.cognition import KnowledgeClaim
from engine.runtime.character.community_event_view import visible_event_summary


class OwnedClaims(MutableMapping):
    """Index ownership on every mapping write, including corrections and rebuilds."""

    def __init__(self):
        self._items = {}
        self.by_owner = {}

    def __getitem__(self, key):
        return self._items[key]

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __setitem__(self, key, claim):
        if key != claim.claim_id:
            raise ValueError("claim key must match immutable claim identity")
        old = self._items.get(key)
        if old is not None and old.owner_id != claim.owner_id:
            self.by_owner[old.owner_id].pop(key)
        self._items[key] = claim
        self.by_owner.setdefault(claim.owner_id, {})[key] = None

    def __delitem__(self, key):
        claim = self._items.pop(key)
        self.by_owner[claim.owner_id].pop(key)

    def owned(self, owner):
        return (self._items[key] for key in self.by_owner.get(owner, ()))


def owned_claims(claims, owner):
    if isinstance(claims, OwnedClaims):
        return claims.owned(owner)
    return (c for c in claims.values() if c.owner_id == owner)


def skill_claims(character):
    """A person's authored abilities are private self-knowledge, not public facts."""
    return tuple(KnowledgeClaim(
        f"claim:skill-seed:{character.id}:{number}", character.id,
        character.id, f"skill:{skill}", "acquired",
        (f"soul:{character.id}:skill:{number}",), 0, "seed", 1.0,
    ) for number, skill in enumerate(sorted(set(dict(character.profile).get("skills", ())))))


def is_capability(claim):
    return claim.predicate.startswith("skill:") and claim.content == "acquired"


def visible_capabilities(projection, actor_id, tick, people, *, limit=16, character_budget=3000):
    latest = {}
    for claim in owned_claims(projection.claims, actor_id):
        if (claim.owner_id != actor_id or not is_capability(claim)
                or claim.expires_tick is not None and claim.expires_tick <= tick):
            continue
        key = (claim.subject, claim.predicate)
        old = latest.get(key)
        # Repeated testimony at equal confidence is not newly acquired ability information.
        if old is None or (claim.confidence, -claim.acquired_tick) > (
            old.confidence, -old.acquired_tick,
        ):
            latest[key] = claim
    ordered = sorted(latest.values(), key=lambda c: (
        c.subject not in {*people, actor_id}, -c.acquired_tick, -c.confidence, c.claim_id,
    ))
    result, used = [], 0
    for claim in ordered:
        cost = len(claim.subject) + len(claim.predicate) + len(claim.content) + sum(map(len, claim.source_refs))
        if len(result) >= limit:
            break
        if used + cost <= character_budget:
            result.append(claim)
            used += cost
    return tuple(result)


def seed_claim(character, number, item):
    summary = str(item.get("summary") or "").strip()
    if not summary:
        return None
    return KnowledgeClaim(
        f"claim:seed:{character.id}:{number}", character.id,
        str(item.get("subject") or character.id),
        str(item.get("predicate") or "background"), summary,
        (f"seed:{character.id}:{number}",), 0, "seed",
        float(item.get("confidence", 0.6)),
    )


def public_claim(actor_id, world_id, number, text):
    return KnowledgeClaim(
        f"claim:public:{actor_id}:{number}", actor_id, world_id, "public_knowledge",
        text, (f"public:{number}",), 0, "seed", 0.6,
    )


def claims_from_event(event, owner_id, previous):
    kind = event.event_type.value
    if kind == "inspected":
        subject = event.data["resource_id"]
        predicate, content, channel, confidence, person = (
            "condition", str(event.data["condition"]), "observation", 1.0, "",
        )
    elif kind == "activity_finished" and event.data.get("status") == "completed" and event.delta.entity_patches:
        patch = event.delta.entity_patches[0]
        attributes = patch.component.data if patch.component else {}
        if "condition" not in attributes:
            return ()
        subject, predicate, content, channel, confidence, person = (
            patch.entity_id, "condition", str(attributes["condition"]), "observation", 1.0, "",
        )
    elif kind == "activity_finished" and event.data.get("learned_skill") and owner_id == event.actor_id:
        subject, predicate, content, channel, confidence, person = (
            event.data["resource_id"], "skill", event.data["learned_skill"], "learned", 1.0, "",
        )
    elif kind == "dialogue" and owner_id != event.actor_id:
        reported = event.data.get("reported_claim")
        if reported:
            subject, predicate, content = (
                reported["subject"], reported["predicate"], reported["content"],
            )
            confidence = min(0.8, reported["confidence"]) * 0.9
        else:
            subject, predicate, content = (
                event.actor_id, "said", event.data.get("utterance", ""),
            )
            confidence = 0.5
        channel, person = "heard", event.actor_id
    elif kind == "organization_censured" and owner_id != event.actor_id:
        subject, predicate, content = event.actor_id, "said", event.data["censure"]["statement"]
        channel, confidence, person = "heard", 0.5, event.actor_id
    elif kind == "organization_read" and owner_id != event.data["record"]["author_id"]:
        reported = event.data["record"]["claim"]
        if reported.get("expires_tick") is not None and reported["expires_tick"] <= event.tick:
            return ()
        subject, predicate, content = reported["subject"], reported["predicate"], reported["content"]
        channel, confidence, person = "heard", min(0.8, reported["confidence"]) * 0.9, event.data["record"]["author_id"]
    else:
        return ()
    if not content:
        return ()
    contradictions = tuple(sorted(
        c.claim_id for c in owned_claims(previous, owner_id)
        if c.owner_id == owner_id and c.subject == subject
        and c.predicate == predicate and c.content != content
    ))[-16:]
    result = (KnowledgeClaim(
        f"claim:{owner_id}:{event.sequence}", owner_id, subject, predicate,
        content, (f"event:{event.sequence}",), event.tick, channel,
        confidence, person, contradictions,
        event.data["record"]["claim"].get("expires_tick") if kind == "organization_read" else None,
    ),)
    if kind == "activity_finished" and event.data.get("learned_skill") and owner_id == event.actor_id:
        result += (KnowledgeClaim(
            f"claim:skill:{owner_id}:{event.sequence}", owner_id, owner_id,
            f"skill:{event.data['learned_skill']}", "acquired",
            (f"event:{event.sequence}",), event.tick, "learned", 1.0,
        ),)
    return result


def visible_claims(projection, actor_id, tick, entity_ids=(), limit=12, character_budget=3000):
    candidates = [
        c for c in owned_claims(projection.claims, actor_id)
        if c.owner_id == actor_id
        and (c.expires_tick is None or c.expires_tick > tick)
    ]
    candidates.sort(key=lambda c: (
        c.subject not in entity_ids, c.source_refs[0].startswith("public:"),
        -c.acquired_tick, -c.confidence, c.claim_id,
    ))
    selected, used = [], 0
    for claim in candidates:
        text = (
            f"{claim.claim_id} [{claim.channel}; confidence={claim.confidence:.2f}; "
            f"from={claim.source_person or 'self'}] "
            f"{claim.subject}.{claim.predicate}: {claim.content}"
        )
        if claim.contradicts:
            text += f"; contradicts={','.join(claim.contradicts)}"
        cost = len(text) + sum(map(len, claim.source_refs))
        if len(selected) >= limit:
            break
        if used + cost <= character_budget:
            selected.append((claim.source_refs[0], text))
            used += cost
    return tuple(selected)


def expand_sources(run, actor_id, source_refs, *, limit=32):
    """Expand provenance with visibility stops rather than reading private origins."""
    pending, result, seen = list(source_refs), [], set()
    while pending and len(result) < limit:
        source = pending.pop(0)
        if source in seen:
            continue
        seen.add(source)
        if source.startswith("event:"):
            sequence = int(source.split(":", 1)[1])
            if not 0 <= sequence < len(run.events):
                raise ValueError("unknown source")
            event = run.events[sequence]
            if actor_id not in event.observers and event.actor_id != actor_id:
                result.append((source, "private origin"))
                continue
            result.append((source, visible_event_summary(event, actor_id) or event.event_type.value))
            pending.extend(event.data.get("source_refs", ()))
        elif source.startswith("public:"):
            number = source.removeprefix("public:")
            knowledge = run.compiled.community.public_knowledge
            if not number.isascii() or not number.isdigit() or len(number) > 2:
                raise ValueError("unknown public knowledge source")
            index = int(number)
            if source != f"public:{index}" or index >= len(knowledge):
                raise ValueError("unknown public knowledge source")
            result.append((source, knowledge[index]))
        elif source.startswith((f"seed:{actor_id}:", f"soul:{actor_id}:")):
            result.append((source, "owned author seed"))
        else:
            result.append((source, "unavailable origin"))
    return tuple(result)
