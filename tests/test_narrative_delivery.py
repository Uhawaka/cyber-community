import time
from dataclasses import replace

from engine.narrative import (
    CurationPolicy,
    DeliveryPolicy,
    DeterministicNarrativeRenderer,
    NarrativeChange,
    NarrativeDelivery,
    NarrativeRenderRequest,
    NarrativeStyleProfile,
    PresentationStore,
    RenderedNarrative,
    RenderedParagraph,
    SourceEventView,
    StructuredLiteraryRenderer,
    build_narrative_plan,
    build_narrative_digest,
    is_reader_visible_source,
    validate_literary_quality,
    validate_rendered_facts,
)


def test_ambient_turn_without_explicit_progress_is_not_reader_material():
    source = replace(
        _event(1, kind="turn_resolved"),
        actor_ids=("scene:probe:ambient",),
        facts={},
    )

    assert not is_reader_visible_source(source)


def test_rejected_scene_turn_is_not_reader_material():
    source = replace(
        _event(1, kind="turn_resolved"),
        facts={"status": "rejected", "dramatic_progress": "none"},
    )

    assert not is_reader_visible_source(source)


def _event(
    number: int,
    *,
    kind: str = "observed",
    summary: str | None = None,
    utterance: str | None = None,
    target: str | None = None,
) -> SourceEventView:
    return SourceEventView(
        source_event_id=f"world-{number:06d}",
        world_time=float(number),
        kind=kind,
        actor_ids=("lin",),
        observer_ids=("wei",),
        location_id="quay",
        target_id=target,
        goal=None,
        summary=summary or f"lin {kind}",
        utterance=utterance,
        causal_source_ids=(),
        changes=(
            NarrativeChange("relationship", "lin", "wei", "+1"),
        ),
        unresolved_points=(),
        facts={},
    )


def test_digest_preserves_committed_provenance_and_utterance():
    digest = build_narrative_digest(
        (_event(1, utterance="灯还亮着。"), _event(2))
    )

    assert digest.source_event_ids == ("world-000001", "world-000002")
    assert digest.utterances == ("灯还亮着。",)
    assert digest.character_ids == ("lin", "wei")


def test_delivery_publishes_and_rerenders_without_changing_sources():
    events = (_event(1), _event(2))
    snapshot = tuple(events)
    store = PresentationStore()
    delivery = NarrativeDelivery(
        store,
        DeliveryPolicy(unpresented_event_threshold=2),
    )

    published = delivery.publish(events)
    rerendered = delivery.rerender(published.presentation_id)

    assert tuple(events) == snapshot
    assert store.cursor == 2
    assert rerendered.render_version == 2
    assert rerendered.source_event_ids == published.source_event_ids


def test_deterministic_renderer_only_repeats_committed_facts():
    digest = build_narrative_digest(
        (_event(1, utterance="不要补写。"),)
    )

    rendered = DeterministicNarrativeRenderer().render(digest)

    assert "lin observed" in rendered.body
    assert "不要补写。" in rendered.body
    assert validate_rendered_facts(rendered, digest)


def test_structured_renderer_uses_committed_changes():
    digest = build_narrative_digest(
        (
            _event(
                1,
                kind="dialogue",
                summary="lin addressed wei",
                utterance="灯还亮着。",
                target="wei",
            ),
        )
    )

    rendered = StructuredLiteraryRenderer().render(digest)

    assert 'lin对wei说：“灯还亮着。”' in rendered.body
    assert "发生关系变化" not in rendered.body
    assert validate_rendered_facts(rendered, digest)
    assert validate_literary_quality(rendered, digest)


def test_registered_world_styles_produce_distinct_expression():
    digest = build_narrative_digest((_event(1), _event(2)))
    plan = build_narrative_plan(digest)
    restrained = StructuredLiteraryRenderer().render(
        NarrativeRenderRequest(
            digest,
            plan,
            NarrativeStyleProfile(voice_id="restrained-mystery-v1"),
        )
    )
    strange = StructuredLiteraryRenderer().render(
        NarrativeRenderRequest(
            digest,
            plan,
            NarrativeStyleProfile(
                voice_id="demythologized-dark-myth-v1"
            ),
        )
    )

    assert restrained.title != strange.title
    assert restrained.body != strange.body
    assert validate_rendered_facts(restrained, digest)
    assert validate_rendered_facts(strange, digest)


def test_plan_and_fallback_group_events_into_scene_beats():
    digest = build_narrative_digest(
        tuple(_event(index) for index in range(1, 7))
    )
    plan = build_narrative_plan(digest)
    rendered = StructuredLiteraryRenderer().render(
        NarrativeRenderRequest(
            digest,
            plan,
            NarrativeStyleProfile(
                voice_id="demythologized-dark-myth-v1"
            ),
        )
    )

    assert len(plan.beats) < len(digest.entries)
    assert len(rendered.paragraphs) < len(digest.entries)
    assert not any(
        paragraph.text.startswith(("却说，", "正此时，", "未几，", "少顷，"))
        for paragraph in rendered.paragraphs
    )
    assert validate_literary_quality(rendered, digest)


def test_literary_gate_rejects_event_log_prose():
    digest = build_narrative_digest(
        tuple(_event(index) for index in range(1, 5))
    )
    rendered = RenderedNarrative(
        "片段",
        "\n\n".join(
            f"正此时，lin观察了quay。"
            for _ in range(4)
        ),
        paragraphs=tuple(
            # Unique source ids do not make one-event-per-paragraph prose valid.
            RenderedParagraph(
                (f"world-{index:06d}",),
                f"正此时，lin观察了quay。{index}",
            )
            for index in range(1, 5)
        ),
    )

    assert not validate_literary_quality(rendered, digest)


def test_curator_filters_internal_events_and_publishes_bounded_episodes():
    events = (
        _event(1),
        _event(2, kind="action_rejected"),
        _event(3),
        _event(4),
        _event(5),
    )
    store = PresentationStore()
    delivery = NarrativeDelivery(
        store,
        DeliveryPolicy(unpresented_event_threshold=1),
        curation_policy=CurationPolicy(
            max_events=2,
            max_world_time_span=10,
            min_narrative_events=1,
            max_repeated_action=10,
        ),
    )

    published = delivery.publish_all_if_due(events)

    assert len(published) == 2
    assert store.cursor == len(events)
    source_ranges = [item.source_event_ids for item in published]
    assert not set(source_ranges[0]).intersection(source_ranges[1])
    assert all(len(items) <= 2 for items in source_ranges)
    assert all(
        "action_rejected" not in item.rendered.body for item in published
    )


def test_fact_validation_rejects_invented_quote_and_entity():
    digest = build_narrative_digest((_event(1, utterance="原话"),))

    assert not validate_rendered_facts(
        RenderedNarrative("lin", 'lin：“新增台词”'),
        digest,
    )
    assert not validate_rendered_facts(
        RenderedNarrative("lin", "lin说：「新增台词」"),
        digest,
    )
    assert not validate_rendered_facts(
        RenderedNarrative("lin", "lin心想，来者不善"),
        digest,
    )
    assert not validate_rendered_facts(
        RenderedNarrative("lin", "lin addressed intruder"),
        digest,
    )
    factual_term_digest = build_narrative_digest(
        (
            replace(
                _event(1, summary="残片留有入供旧印"),
                facts={"mark": "入供"},
            ),
        )
    )
    assert validate_rendered_facts(
        RenderedNarrative("lin", "残片上留着“入供”旧印。"),
        factual_term_digest,
    )
    assert not validate_rendered_facts(
        RenderedNarrative("lin", "lin说：“这是新增的整句台词。”"),
        factual_term_digest,
    )
    plan = build_narrative_plan(digest)
    request = NarrativeRenderRequest(
        digest,
        replace(plan, turning_point_source_id="world-999999"),
        NarrativeStyleProfile(),
    )
    assert not validate_rendered_facts(
        DeterministicNarrativeRenderer().render(digest),
        request,
    )


class _FailingRenderer:
    def render(self, digest):
        raise RuntimeError("model unavailable")


class _SlowRenderer:
    def render(self, digest):
        time.sleep(0.05)
        return RenderedNarrative("lin", "lin observed")


class _EventLogProseRenderer:
    def render(self, request):
        paragraphs = tuple(
            RenderedParagraph(
                (entry.source_event_id,),
                "正此时，lin查看了quay。",
            )
            for entry in request.digest.entries
        )
        return RenderedNarrative(
            "lin",
            "\n\n".join(item.text for item in paragraphs),
            paragraphs=paragraphs,
        )


def test_renderer_exception_and_timeout_record_deterministic_fallback():
    events = (_event(1),)
    policy = DeliveryPolicy(unpresented_event_threshold=1)
    failing = NarrativeDelivery(
        PresentationStore(), policy, _FailingRenderer()
    ).publish(events)
    slow = NarrativeDelivery(
        PresentationStore(),
        policy,
        _SlowRenderer(),
        render_timeout=0.001,
    ).publish(events)

    assert failing.render_diagnostics[0].status == "exception"
    assert slow.render_diagnostics[0].status == "timeout"
    assert failing.render_diagnostics[-1].status == "fallback"
    assert slow.render_diagnostics[-1].status == "fallback"
    assert failing.rendered.body == slow.rendered.body


def test_event_log_prose_is_rejected_before_publication():
    presentation = NarrativeDelivery(
        PresentationStore(),
        DeliveryPolicy(unpresented_event_threshold=4),
        _EventLogProseRenderer(),
        curation_policy=CurationPolicy(max_repeated_action=10),
    ).publish(tuple(_event(index) for index in range(1, 5)))

    assert presentation.render_diagnostics[0].status == (
        "literary_quality_failed"
    )
    assert presentation.render_diagnostics[-1].status == "fallback"
    assert "正此时" not in presentation.rendered.body
