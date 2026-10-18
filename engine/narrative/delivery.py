"""Narrative publication policy and orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from queue import Empty, Queue
from threading import Thread
import time
from typing import Sequence

from engine.narrative.curation import (
    CuratedEpisodeWindow,
    CurationPolicy,
    curate_episode_windows,
    is_reader_visible_source,
)
from engine.narrative.digest import build_narrative_digest
from engine.narrative.division import (
    ContentChapterDivider,
    divide_reader_windows,
)
from engine.narrative.planning import (
    NarrativeRenderRequest,
    NarrativeStyleProfile,
    build_narrative_plan,
)
from engine.narrative.rendering import AudienceMode, NarrativeRenderer, RenderDiagnostic, RenderedNarrative, StructuredLiteraryRenderer
from engine.narrative.source import adapt_source_events
from engine.narrative.store import Presentation, PresentationStore
from engine.narrative.validation import (
    literary_quality_issues,
    rendered_fact_issues,
    validate_literary_quality,
    validate_rendered_facts,
)

@dataclass(frozen=True)
class DeliveryDecision:
    should_publish: bool
    unpresented_event_count: int
    critical_event_count: int
    reason: str
    has_change: bool = False
    has_cost: bool = False
    has_unresolved_point: bool = False


@dataclass(frozen=True)
class DeliveryPolicy:
    """Publish after enough unseen events or enough critical unseen events."""

    unpresented_event_threshold: int = 3
    critical_event_threshold: int = 1
    critical_kinds: frozenset[str] = frozenset(
        {
            "secret_revealed",
            "obligation_breach",
            "stage_closed",
            "clock_fired",
        }
    )

    def __post_init__(self) -> None:
        if self.unpresented_event_threshold < 1:
            raise ValueError("unpresented_event_threshold must be positive")
        if self.critical_event_threshold < 1:
            raise ValueError("critical_event_threshold must be positive")

    def decide(self, unpresented_events: Sequence[object]) -> DeliveryDecision:
        events = adapt_source_events(unpresented_events)
        critical_count = sum(
            event.kind in self.critical_kinds for event in events
        )
        has_change = any(event.changes for event in events)
        has_cost = any(
            change.is_cost for event in events for change in event.changes
        )
        has_unresolved = any(event.unresolved_points for event in events)
        meaningful = has_change or has_cost or has_unresolved
        if critical_count >= self.critical_event_threshold:
            reason = "critical_event_threshold"
            should_publish = True
        elif len(events) >= self.unpresented_event_threshold and meaningful:
            reason = "unpresented_event_threshold"
            should_publish = True
        elif len(events) >= self.unpresented_event_threshold:
            reason = "no_narrative_change"
            should_publish = False
        else:
            reason = "below_threshold"
            should_publish = False
        return DeliveryDecision(
            should_publish=should_publish,
            unpresented_event_count=len(events),
            critical_event_count=critical_count,
            reason=reason,
            has_change=has_change,
            has_cost=has_cost,
            has_unresolved_point=has_unresolved,
        )


class DeliveryNotDue(ValueError):
    pass


@dataclass(frozen=True)
class RenderAttempt:
    rendered: RenderedNarrative | None
    diagnostic: RenderDiagnostic


class NarrativeDelivery:
    """Coordinates pure digest/render operations with PresentationStore."""

    def __init__(
        self,
        store: PresentationStore,
        policy: DeliveryPolicy | None = None,
        renderer: NarrativeRenderer | None = None,
        *,
        audience_id: str | None = None,
        omniscient: bool = False,
        observer_mode: AudienceMode | str | None = None,
        render_timeout: float = 2.0,
        curation_policy: CurationPolicy | None = None,
        style_profile: NarrativeStyleProfile | None = None,
        fallback_renderer: NarrativeRenderer | None = None,
        release_tail: bool = True,
        chapter_divider: ContentChapterDivider | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or DeliveryPolicy()
        self.renderer = renderer or StructuredLiteraryRenderer()
        self.fallback_renderer = (
            fallback_renderer or StructuredLiteraryRenderer()
        )
        self.audience_id = audience_id or "omniscient"
        if observer_mode is not None:
            mode = AudienceMode(observer_mode)
            if omniscient and mode is not AudienceMode.OMNISCIENT:
                raise ValueError("conflicting observer visibility mode")
            if mode is AudienceMode.AVATAR and audience_id is None:
                raise ValueError("avatar observer mode requires audience_id")
            self.omniscient = mode is AudienceMode.OMNISCIENT
        else:
            self.omniscient = omniscient or audience_id is None
        if render_timeout <= 0:
            raise ValueError("render_timeout must be positive")
        self.render_timeout = render_timeout
        self.curation_policy = curation_policy or CurationPolicy()
        self.style_profile = style_profile or NarrativeStyleProfile()
        self.release_tail = release_tail
        self.chapter_divider = chapter_divider

    def decision(self, events: Sequence[object]) -> DeliveryDecision:
        snapshot = tuple(events)
        self._validate_cursor(snapshot)
        unseen = tuple(
            source
            for source in self._visible_unseen(snapshot)
            if is_reader_visible_source(source)
        )
        return self.policy.decide(unseen)

    def publish_if_due(
        self,
        events: Sequence[object],
    ) -> Presentation | None:
        snapshot = tuple(events)
        self._validate_cursor(snapshot)
        selected = self.curate_next(snapshot)
        if selected is None:
            return None
        return self._publish(selected.sources, selected.cursor_after)

    def curate_next(
        self, events: Sequence[object]
    ) -> CuratedEpisodeWindow | None:
        snapshot = tuple(events)
        self._validate_cursor(snapshot)
        windows = self._curated_windows(snapshot)
        return windows[0] if windows else None

    def publish_all_if_due(
        self, events: Sequence[object]
    ) -> tuple[Presentation, ...]:
        snapshot = tuple(events)
        self._validate_cursor(snapshot)
        published: list[Presentation] = []
        while True:
            windows = self._curated_windows(snapshot)
            if not windows:
                break
            selected = windows[0]
            published.append(
                self._publish(selected.sources, selected.cursor_after)
            )
        return tuple(published)

    def publish(self, events: Sequence[object]) -> Presentation:
        snapshot = tuple(events)
        self._validate_cursor(snapshot)
        windows = self._curated_windows(snapshot)
        if not windows:
            raise DeliveryNotDue(self.decision(snapshot).reason)
        selected = windows[0]
        return self._publish(selected.sources, selected.cursor_after)

    def _publish(
        self,
        sources: tuple[object, ...],
        cursor_after: int,
    ) -> Presentation:
        request = self.prepare_request(sources)
        rendered, diagnostics = self._render_checked(request)
        return self.publish_rendered(
            request, rendered, diagnostics, cursor_after=cursor_after
        )

    def prepare_request(
        self, sources: tuple[object, ...]
    ) -> NarrativeRenderRequest:
        digest = build_narrative_digest(sources)
        return NarrativeRenderRequest(
            digest, build_narrative_plan(digest), self.style_profile
        )

    def publish_rendered(
        self,
        request: NarrativeRenderRequest,
        rendered: RenderedNarrative,
        diagnostics: tuple[RenderDiagnostic, ...],
        *,
        cursor_after: int,
    ) -> Presentation:
        return self.store.publish(
            request.digest,
            rendered,
            cursor_after=cursor_after,
            audience_id=self.audience_id,
            diagnostics=diagnostics,
        )

    def rerender(self, presentation_id: str) -> Presentation:
        presentation = self.store.get(presentation_id)
        request = NarrativeRenderRequest(
            presentation.digest,
            build_narrative_plan(presentation.digest),
            self.style_profile,
        )
        rendered, diagnostics = self._render_checked(request)
        return self.store.rerender(
            presentation_id,
            rendered,
            diagnostics=diagnostics,
        )

    def rebuild(self, events: Sequence[object]) -> tuple[Presentation, ...]:
        """Recreate deterministic publication ranges from the source log."""

        snapshot = tuple(events)
        shadow = PresentationStore()
        shadow._cursors = {
            key: value
            for key, value in self.store._cursors.items()
            if key != self.audience_id
        }
        shadow._presentations = {
            key: value
            for key, value in self.store._presentations.items()
            if value.audience_id != self.audience_id
        }
        retained_episode_ids = {
            value.episode_id for value in shadow._presentations.values()
        }
        shadow._episodes = {
            key: value
            for key, value in self.store._episodes.items()
            if key in retained_episode_ids
        }
        delivery = NarrativeDelivery(
            shadow,
            self.policy,
            self.renderer,
            audience_id=(
                None if self.omniscient and self.audience_id == "omniscient"
                else self.audience_id
            ),
            observer_mode=(
                AudienceMode.OMNISCIENT
                if self.omniscient
                else AudienceMode.AVATAR
            ),
            render_timeout=self.render_timeout,
            curation_policy=self.curation_policy,
            style_profile=self.style_profile,
            fallback_renderer=self.fallback_renderer,
            release_tail=self.release_tail,
            chapter_divider=self.chapter_divider,
        )
        rebuilt = list(delivery.publish_all_if_due(snapshot))
        self.store._commit(
            dict(shadow._cursors),
            dict(shadow._presentations),
            dict(shadow._episodes),
        )
        return tuple(rebuilt)

    def _render_checked(
        self, request: NarrativeRenderRequest
    ) -> tuple[RenderedNarrative, tuple[RenderDiagnostic, ...]]:
        return self.validate_attempt(request, self.render_candidate(request))

    def render_candidate(
        self, request: NarrativeRenderRequest
    ) -> RenderAttempt:
        started = time.monotonic()
        queue: Queue[tuple[bool, object]] = Queue(maxsize=1)

        def invoke() -> None:
            try:
                queue.put((True, self.renderer.render(request)))
            except BaseException as exc:
                queue.put((False, exc))

        Thread(target=invoke, daemon=True).start()
        status, detail = "ok", ""
        try:
            succeeded, result = queue.get(timeout=self.render_timeout)
            if not succeeded:
                status = "exception"
                message = str(result).strip()
                detail = type(result).__name__ + (
                    f": {message[:500]}" if message else ""
                )
                rendered: RenderedNarrative | None = None
            elif not isinstance(result, RenderedNarrative):
                status = "invalid_result"
                detail = type(result).__name__
                rendered = None
            else:
                rendered = result
        except Empty:
            status = "timeout"
            rendered = None
        elapsed = int((time.monotonic() - started) * 1000)
        return RenderAttempt(
            rendered,
            RenderDiagnostic(
                type(self.renderer).__name__, status, elapsed, detail
            ),
        )

    def validate_attempt(
        self,
        request: NarrativeRenderRequest,
        attempt: RenderAttempt,
    ) -> tuple[RenderedNarrative, tuple[RenderDiagnostic, ...]]:
        rendered = attempt.rendered
        diagnostic = attempt.diagnostic
        status = diagnostic.status
        detail = diagnostic.detail
        if rendered is not None and not validate_rendered_facts(
            rendered, request
        ):
            detail = ",".join(rendered_fact_issues(rendered, request))
            status, rendered = "fact_validation_failed", None
        elif rendered is not None and not validate_literary_quality(
            rendered, request
        ):
            status = "literary_quality_failed"
            detail = ",".join(literary_quality_issues(rendered, request))
            rendered = None
        diagnostic = RenderDiagnostic(
            diagnostic.renderer,
            status,
            diagnostic.elapsed_ms,
            detail,
        )
        if rendered is not None:
            return rendered, (diagnostic,)
        fallback = self.fallback_renderer.render(request)
        fallback_fact_issues = rendered_fact_issues(fallback, request)
        fallback_quality_issues = literary_quality_issues(
            fallback, request
        )
        if fallback_fact_issues or fallback_quality_issues:
            raise RuntimeError(
                "registered literary fallback failed validation: "
                + ",".join(
                    (*fallback_fact_issues, *fallback_quality_issues)
                )
            )
        return fallback, (
            diagnostic,
            RenderDiagnostic(
                "StructuredLiteraryRenderer",
                "fallback",
                0,
                status,
            ),
        )

    def _validate_cursor(self, events: tuple[object, ...]) -> None:
        if self.store.cursor_for(self.audience_id) > len(events):
            raise ValueError("presentation cursor is ahead of the event snapshot")

    def _visible_unseen(
        self, events: tuple[object, ...]
    ) -> tuple[object, ...]:
        unseen = adapt_source_events(
            events[self.store.cursor_for(self.audience_id) :]
        )
        if self.omniscient:
            return unseen
        visible: list[object] = []
        for source in unseen:
            if self.audience_id in source.observer_ids:
                visible.append(source)
        return tuple(visible)

    def _curated_windows(
        self, events: tuple[object, ...]
    ) -> tuple[CuratedEpisodeWindow, ...]:
        policy = replace(
            self.curation_policy,
            min_narrative_events=max(
                self.curation_policy.min_narrative_events,
                self.policy.unpresented_event_threshold,
            ),
        )
        if self.chapter_divider is not None:
            return divide_reader_windows(
                events,
                cursor=self.store.cursor_for(self.audience_id),
                audience_id=self.audience_id,
                omniscient=self.omniscient,
                policy=policy,
                minimum_events=self.policy.unpresented_event_threshold,
                divider=self.chapter_divider,
            )
        return curate_episode_windows(
            events,
            cursor=self.store.cursor_for(self.audience_id),
            audience_id=self.audience_id,
            omniscient=self.omniscient,
            policy=policy,
            release_tail=self.release_tail,
        )

