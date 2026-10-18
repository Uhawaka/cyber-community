"""Application boundary for publishing autonomous history as narrative."""

from __future__ import annotations

from dataclasses import dataclass

from engine.narrative import (
    AudienceMode,
    CurationPolicy,
    DeliveryDecision,
    DeliveryPolicy,
    DeterministicNarrativeRenderer,
    NarrativeChange,
    NarrativeDelivery,
    NarrativeRenderer,
    NarrativeStyleProfile,
    Presentation,
    PresentationStore,
    SourceEventView,
    StructuredLiteraryRenderer,
    adapt_source_events,
    style_profile_from_contract,
)
from engine.narrative.division import ContentChapterDivider
from engine.runtime.autonomous_director import PendingUserGate, get_pending_user_gate
from engine.runtime.simulation.run import AutonomousRun
from engine.runtime.workflow import PresentationContext, execute_workflow


@dataclass(frozen=True)
class ObserverWorldSummary:
    world_id: str
    title: str
    premise: str
    tick: int
    world_time: int
    character_count: int
    location_count: int


@dataclass(frozen=True)
class ObserverHome:
    world: ObserverWorldSummary
    recent_key_changes: tuple[SourceEventView, ...]
    character_changes: tuple[NarrativeChange, ...]
    pending_gate: PendingUserGate | None
    due_episode: DeliveryDecision


def publish_due_episode(
    run: AutonomousRun,
    store: PresentationStore,
    policy: DeliveryPolicy | None = None,
    *,
    renderer: NarrativeRenderer | None = None,
    audience_id: str | None = None,
    observer_mode: AudienceMode | str | None = None,
    render_timeout: float = 2.0,
    release_tail: bool = True,
) -> Presentation | None:
    """Publish a read-only snapshot while preserving objective history."""

    events_before = run.events
    state_before = run.state
    history_before = run.history_hash()
    presentation_policy = dict(run.compiled.workflow.presentation.policy)
    selected_policy = policy or DeliveryPolicy(
        unpresented_event_threshold=int(
            presentation_policy["unpresented_event_threshold"]
        ),
        critical_event_threshold=int(
            presentation_policy["critical_event_threshold"]
        ),
    )
    default_renderer = StructuredLiteraryRenderer(
        {
            "world": "世界",
            run.compiled.world.world_id: run.compiled.world.title,
            **{
                character.id: character.name
                for character in run.compiled.world.characters
            },
            **{
                location.id: location.name
                for location in run.compiled.world.locations
            },
            **{
                resource.id: resource.name
                for resource in run.compiled.world.resources
            },
        }
    )
    if presentation_policy["renderer"] == "deterministic":
        default_renderer = DeterministicNarrativeRenderer()
    selected_renderer = renderer or default_renderer
    chapter_divider = ContentChapterDivider(
        model=getattr(selected_renderer, "model", None),
        timeout_seconds=render_timeout,
    )
    editorial_contract = run.compiled.experience.editorial
    curation_policy = CurationPolicy.from_mapping(
        dict(editorial_contract.episode)
    )
    style_profile = style_profile_from_contract(editorial_contract)
    if observer_mode is None:
        observer_mode = (
            AudienceMode.OMNISCIENT
            if presentation_policy["audience_default"] == "omniscient"
            else AudienceMode.AVATAR
        )
    execution: dict[str, object] = {}

    def source_filter() -> NarrativeDelivery:
        delivery = NarrativeDelivery(
            store,
            selected_policy,
            selected_renderer,
            audience_id=audience_id,
            observer_mode=observer_mode,
            render_timeout=render_timeout,
            curation_policy=curation_policy,
            style_profile=style_profile,
            fallback_renderer=default_renderer,
            release_tail=release_tail,
            chapter_divider=chapter_divider,
        )
        execution["delivery"] = delivery
        return delivery

    def curate() -> None:
        delivery = _delivery(execution)
        execution["window"] = delivery.curate_next(events_before)

    def plan() -> None:
        delivery = _delivery(execution)
        window = execution.get("window")
        execution["request"] = (
            None
            if window is None
            else delivery.prepare_request(window.sources)
        )

    def render() -> None:
        delivery = _delivery(execution)
        request = execution.get("request")
        execution["attempt"] = (
            None if request is None else delivery.render_candidate(request)
        )

    def validate() -> None:
        delivery = _delivery(execution)
        request = execution.get("request")
        attempt = execution.get("attempt")
        execution["validated"] = (
            None
            if request is None or attempt is None
            else delivery.validate_attempt(request, attempt)
        )

    def publish() -> Presentation | None:
        delivery = _delivery(execution)
        window = execution.get("window")
        request = execution.get("request")
        validated = execution.get("validated")
        if window is None or request is None or validated is None:
            result = None
        else:
            rendered, diagnostics = validated
            result = delivery.publish_rendered(
                request,
                rendered,
                diagnostics,
                cursor_after=window.cursor_after,
            )
        execution["result"] = result
        return result

    execute_workflow(
        run.compiled.workflow.presentation,
        PresentationContext(
            {
                "source_filter": source_filter,
                "curate": curate,
                "plan": plan,
                "render": render,
                "validate": validate,
                "publish": publish,
            }
        ),
    )
    result = execution.get("result")
    if (
        run.events != events_before
        or run.state != state_before
        or run.history_hash() != history_before
    ):
        raise RuntimeError("narrative publication mutated autonomous history")
    return result if isinstance(result, Presentation) else None


def _delivery(execution: dict[str, object]) -> NarrativeDelivery:
    value = execution.get("delivery")
    if not isinstance(value, NarrativeDelivery):
        raise RuntimeError("presentation source_filter step did not run")
    return value


def publish_due_episodes(
    run: AutonomousRun,
    store: PresentationStore,
    policy: DeliveryPolicy | None = None,
    *,
    renderer: NarrativeRenderer | None = None,
    audience_id: str | None = None,
    observer_mode: AudienceMode | str | None = None,
    render_timeout: float = 2.0,
    release_tail: bool = True,
) -> tuple[Presentation, ...]:
    """Publish every currently due bounded Episode window."""

    published: list[Presentation] = []
    while True:
        item = publish_due_episode(
            run,
            store,
            policy,
            renderer=renderer,
            audience_id=audience_id,
            observer_mode=observer_mode,
            render_timeout=render_timeout,
            release_tail=release_tail,
        )
        if item is None:
            return tuple(published)
        published.append(item)


def rerender_episode(
    store: PresentationStore,
    presentation_id: str,
    *,
    renderer: NarrativeRenderer | None = None,
    style_profile: NarrativeStyleProfile | None = None,
    render_timeout: float = 2.0,
    labels: dict[str, str] | None = None,
) -> Presentation:
    """Create a new render version without consuming source events."""

    return NarrativeDelivery(
        store,
        renderer=renderer,
        style_profile=style_profile,
        render_timeout=render_timeout,
        fallback_renderer=StructuredLiteraryRenderer(labels),
    ).rerender(presentation_id)


def get_observer_home(
    run: AutonomousRun,
    store: PresentationStore,
    policy: DeliveryPolicy | None = None,
    *,
    audience_id: str | None = None,
    observer_mode: AudienceMode | str | None = None,
    recent_limit: int = 5,
) -> ObserverHome:
    """Build a side-effect-free landing projection without advancing the run."""

    if recent_limit < 0:
        raise ValueError("recent_limit must be non-negative")
    events_before = run.events
    state_before = run.state
    history_before = run.history_hash()
    presentation_policy = dict(run.compiled.workflow.presentation.policy)
    selected_policy = policy or DeliveryPolicy(
        unpresented_event_threshold=int(presentation_policy["unpresented_event_threshold"]),
        critical_event_threshold=int(presentation_policy["critical_event_threshold"]),
    )
    if observer_mode is None:
        observer_mode = (
            AudienceMode.OMNISCIENT
            if presentation_policy["audience_default"] == "omniscient"
            else AudienceMode.AVATAR
        )
    delivery = NarrativeDelivery(
        store,
        selected_policy,
        audience_id=audience_id,
        observer_mode=observer_mode,
        curation_policy=CurationPolicy.from_mapping(
            presentation_policy.get("episode")
        ),
        style_profile=NarrativeStyleProfile.from_mapping(
            presentation_policy.get("style")
        ),
    )
    sources = adapt_source_events(events_before)
    if not delivery.omniscient:
        sources = tuple(
            event
            for event in sources
            if delivery.audience_id in event.observer_ids
        )
    selected_changes = tuple(
        event
        for event in sources
        if event.changes or event.unresolved_points
    )
    key_changes = selected_changes[-recent_limit:] if recent_limit else ()
    character_changes = tuple(
        change
        for event in key_changes
        for change in event.changes
        if change.subject_id != "world"
    )
    pending_gate = get_pending_user_gate(run)
    if pending_gate is not None and not delivery.omniscient:
        gate_is_visible = any(
            event.data.get("gate_id") == pending_gate.gate_id
            and delivery.audience_id in event.observers
            for event in events_before
        )
        if not gate_is_visible:
            pending_gate = None
    world = run.compiled.world
    result = ObserverHome(
        world=ObserverWorldSummary(
            world_id=world.world_id,
            title=world.title,
            premise=world.premise,
            tick=state_before.tick,
            world_time=state_before.world_time,
            character_count=len(state_before.characters),
            location_count=len(world.locations),
        ),
        recent_key_changes=key_changes,
        character_changes=character_changes,
        pending_gate=pending_gate,
        due_episode=delivery.decision(events_before),
    )
    if (
        run.events != events_before
        or run.state != state_before
        or run.history_hash() != history_before
    ):
        raise RuntimeError("observer home mutated autonomous history")
    return result
