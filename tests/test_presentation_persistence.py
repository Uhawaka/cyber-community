import json
import os
import stat

import pytest

from engine.narrative import (
    AudienceMode,
    DeliveryPolicy,
    NarrativeChange,
    NarrativeDelivery,
    PresentationPersistenceError,
    PresentationStore,
    SourceEventView,
)


def _event(number: int) -> SourceEventView:
    return SourceEventView(
        source_event_id=f"world-{number:06d}",
        world_time=float(number),
        kind="observed",
        actor_ids=("lin",),
        observer_ids=("lin",),
        location_id="quay",
        target_id=None,
        goal=None,
        summary=f"lin observed {number}",
        utterance=None,
        causal_source_ids=(),
        changes=(NarrativeChange("state", "lin", None, str(number)),),
        unresolved_points=(),
        facts={},
    )


def test_store_round_trips_atomically_with_private_permissions(tmp_path):
    path = tmp_path / "presentation.json"
    store = PresentationStore(path)
    delivery = NarrativeDelivery(
        store, DeliveryPolicy(unpresented_event_threshold=2)
    )
    published = delivery.publish((_event(1), _event(2)))

    loaded = PresentationStore.load(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert loaded.cursor == 2
    assert loaded.get(published.presentation_id) == published
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["schema_version"] == "presentation-store.v1"
    assert record["render_version"] == 1


def test_corrupt_store_fails_closed(tmp_path):
    path = tmp_path / "presentation.json"
    path.write_text('{"schema_version":"presentation-store.v1"}')

    with pytest.raises(PresentationPersistenceError):
        PresentationStore.load(path)


def test_clear_and_rebuild_preserves_source_ranges_and_body(tmp_path):
    events = tuple(_event(index) for index in range(1, 5))
    policy = DeliveryPolicy(unpresented_event_threshold=2)
    store = PresentationStore(tmp_path / "presentation.json")
    delivery = NarrativeDelivery(store, policy)
    original = delivery.rebuild(events)
    original_values = tuple(
        (item.source_event_ids, item.rendered.body) for item in original
    )

    store.clear()
    rebuilt = NarrativeDelivery(store, policy).rebuild(events)

    assert tuple(
        (item.source_event_ids, item.rendered.body) for item in rebuilt
    ) == original_values


def test_persistence_failures_leave_store_memory_unchanged(tmp_path, monkeypatch):
    events = (_event(1), _event(2))
    store = PresentationStore(tmp_path / "presentation.json")
    delivery = NarrativeDelivery(
        store, DeliveryPolicy(unpresented_event_threshold=2)
    )
    published = delivery.publish(events)
    before = (store.cursor, store.presentations, store.episodes)

    def fail_replace(*args, **kwargs):
        raise OSError("disk failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(PresentationPersistenceError):
        delivery.rerender(published.presentation_id)
    assert (store.cursor, store.presentations, store.episodes) == before

    with pytest.raises(PresentationPersistenceError):
        store.clear()
    assert (store.cursor, store.presentations, store.episodes) == before

    with pytest.raises(PresentationPersistenceError):
        delivery.rebuild(events)
    assert (store.cursor, store.presentations, store.episodes) == before


def test_rebuild_replaces_only_selected_audience():
    events = tuple(_event(index) for index in range(1, 5))
    policy = DeliveryPolicy(unpresented_event_threshold=2)
    store = PresentationStore()
    avatar = NarrativeDelivery(
        store,
        policy,
        audience_id="lin",
        observer_mode=AudienceMode.AVATAR,
    )
    creator = NarrativeDelivery(
        store,
        policy,
        audience_id="creator",
        observer_mode=AudienceMode.OMNISCIENT,
    )
    avatar.rebuild(events)
    creator.rebuild(events)
    creator_before = tuple(
        item for item in store.presentations if item.audience_id == "creator"
    )

    avatar.rebuild(events)

    assert tuple(
        item for item in store.presentations if item.audience_id == "creator"
    ) == creator_before
    assert store.cursor_for("creator") == len(events)


def test_avatar_mode_requires_explicit_audience():
    with pytest.raises(ValueError, match="requires audience_id"):
        NarrativeDelivery(
            PresentationStore(),
            observer_mode=AudienceMode.AVATAR,
        )
