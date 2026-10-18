from engine.narrative import (
    AudienceMode,
    DeliveryPolicy,
    NarrativeChange,
    NarrativeDelivery,
    PresentationStore,
    RenderedNarrative,
    RenderedParagraph,
    SourceEventView,
    build_narrative_digest,
    validate_rendered_facts,
)


def _event(number: int, observers: tuple[str, ...]) -> SourceEventView:
    return SourceEventView(
        source_event_id=f"world-{number:06d}",
        world_time=float(number),
        kind="secret_revealed",
        actor_ids=("npc",),
        observer_ids=observers,
        location_id="vault",
        target_id=None,
        goal=None,
        summary=f"secret-{number}",
        utterance=None,
        causal_source_ids=(),
        changes=(NarrativeChange("knowledge", "npc", None, str(number)),),
        unresolved_points=(),
        facts={"seed": "private"},
    )


def test_avatar_only_consumes_observed_events_and_cursors_are_independent():
    events = (_event(1, ("avatar-a",)), _event(2, ("avatar-b",)))
    policy = DeliveryPolicy(unpresented_event_threshold=1)
    store = PresentationStore()

    for audience in ("avatar-a", "avatar-b"):
        NarrativeDelivery(
            store,
            policy,
            audience_id=audience,
            observer_mode=AudienceMode.AVATAR,
        ).publish(events)
    omniscient = NarrativeDelivery(
        store,
        policy,
        audience_id="creator",
        observer_mode=AudienceMode.OMNISCIENT,
    ).publish(events)

    assert store.presentations[0].source_event_ids == ("world-000001",)
    assert store.presentations[1].source_event_ids == ("world-000002",)
    assert omniscient.source_event_ids == (
        "world-000001",
        "world-000002",
    )
    assert store.cursor_for("avatar-a") == 2
    assert store.cursor_for("avatar-b") == 2
    assert store.cursor_for("creator") == 2
    assert "private" not in store.presentations[0].rendered.body


def test_validator_rejects_atmosphere_and_reverse_citations():
    digest = build_narrative_digest(
        (_event(1, ("avatar",)), _event(2, ("avatar",)))
    )

    assert not validate_rendered_facts(
        RenderedNarrative(
            "secret-1",
            "[world-000002] secret-2\n[world-000001] secret-1",
        ),
        digest,
    )
    assert not validate_rendered_facts(
        RenderedNarrative(
            "secret-1",
            "secret-2\n\nsecret-1",
            paragraphs=(
                RenderedParagraph(("world-000002",), "secret-2"),
                RenderedParagraph(("world-000001",), "secret-1"),
            ),
        ),
        digest,
    )
    assert not validate_rendered_facts(
        RenderedNarrative(
            "secret-1",
            "secret-1",
            non_factual_atmosphere="空气中弥漫着并未发生的恐惧",
        ),
        digest,
    )
