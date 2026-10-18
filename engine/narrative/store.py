"""Durable presentation-owned state and record codecs."""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from engine.narrative.digest import NarrativeDigest, NarrativeDigestEntry
from engine.narrative.persistence import next_id, persist_snapshot
from engine.narrative.rendering import RenderDiagnostic, RenderedNarrative, RenderedParagraph
from engine.narrative.source import NarrativeChange
from engine.narrative.validation import validate_rendered_facts
@dataclass(frozen=True)
class Episode:
    episode_id: str
    digest: NarrativeDigest
    source_event_ids: tuple[str, ...]
    world_time_start: float
    world_time_end: float
    render_version: int = 1
    audience_id: str = "omniscient"
@dataclass(frozen=True)
class Presentation:
    presentation_id: str
    digest: NarrativeDigest
    rendered: RenderedNarrative
    render_version: int = 1
    episode_id: str = ""
    source_event_ids: tuple[str, ...] = ()
    world_time_start: float = 0.0
    world_time_end: float = 0.0
    audience_id: str = "omniscient"
    render_diagnostics: tuple[RenderDiagnostic, ...] = ()
PRESENTATION_SCHEMA_VERSION = "presentation-store.v1"
class PresentationPersistenceError(ValueError):
    """Raised when presentation data cannot be trusted or persisted."""


class PresentationStore:
    """Presentation-owned durable state, independent from runtime services."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._cursors: dict[str, int] = {}
        self._presentations: dict[str, Presentation] = {}
        self._episodes: dict[str, Episode] = {}

    @property
    def cursor(self) -> int:
        return self.cursor_for("omniscient")

    @property
    def path(self) -> Path | None:
        return self._path

    def cursor_for(self, audience_id: str) -> int:
        return self._cursors.get(audience_id, 0)

    @property
    def presentations(self) -> tuple[Presentation, ...]:
        return tuple(self._presentations.values())

    @property
    def episodes(self) -> tuple[Episode, ...]:
        return tuple(self._episodes.values())

    def get(self, presentation_id: str) -> Presentation:
        try:
            return self._presentations[presentation_id]
        except KeyError as exc:
            raise ValueError(
                f"unknown presentation: {presentation_id}"
            ) from exc

    def get_episode(self, episode_id: str) -> Episode:
        try:
            return self._episodes[episode_id]
        except KeyError as exc:
            raise ValueError(f"unknown episode: {episode_id}") from exc

    def publish(
        self,
        digest: NarrativeDigest,
        rendered: RenderedNarrative,
        *,
        cursor_after: int,
        audience_id: str = "omniscient",
        diagnostics: tuple[RenderDiagnostic, ...] = (),
    ) -> Presentation:
        if cursor_after <= self.cursor_for(audience_id):
            raise ValueError("publication must advance the presentation cursor")
        presentation_id = next_id("presentation", self._presentations)
        episode_id = next_id("episode", self._episodes)
        episode = Episode(
            episode_id,
            digest,
            digest.source_event_ids,
            digest.world_time_start,
            digest.world_time_end,
            1,
            audience_id,
        )
        presentation = Presentation(
            presentation_id,
            digest,
            rendered,
            1,
            episode_id,
            digest.source_event_ids,
            digest.world_time_start,
            digest.world_time_end,
            audience_id,
            tuple(diagnostics),
        )
        episodes = {**self._episodes, episode_id: episode}
        presentations = {
            **self._presentations,
            presentation_id: presentation,
        }
        cursors = {**self._cursors, audience_id: cursor_after}
        self._commit(cursors, presentations, episodes)
        return presentation

    def rerender(
        self,
        presentation_id: str,
        rendered: RenderedNarrative,
        *,
        diagnostics: tuple[RenderDiagnostic, ...] = (),
    ) -> Presentation:
        current = self.get(presentation_id)
        updated = replace(
            current,
            rendered=rendered,
            render_version=current.render_version + 1,
            render_diagnostics=(
                *current.render_diagnostics,
                *diagnostics,
            ),
        )
        episode = self.get_episode(current.episode_id)
        episodes = {
            **self._episodes,
            current.episode_id: replace(
                episode,
                render_version=updated.render_version,
            ),
        }
        presentations = {
            **self._presentations,
            presentation_id: updated,
        }
        self._commit(dict(self._cursors), presentations, episodes)
        return updated

    def clear(self, audience_id: str | None = None) -> None:
        if audience_id is None:
            cursors: dict[str, int] = {}
            presentations: dict[str, Presentation] = {}
            episodes: dict[str, Episode] = {}
        else:
            cursors = {
                key: value
                for key, value in self._cursors.items()
                if key != audience_id
            }
            presentations = {
                key: value
                for key, value in self._presentations.items()
                if value.audience_id != audience_id
            }
            retained_episode_ids = {
                value.episode_id for value in presentations.values()
            }
            episodes = {
                key: value
                for key, value in self._episodes.items()
                if key in retained_episode_ids
            }
        self._commit(cursors, presentations, episodes)

    def _commit(
        self,
        cursors: dict[str, int],
        presentations: dict[str, Presentation],
        episodes: dict[str, Episode],
    ) -> None:
        self._persist(cursors, presentations, episodes)
        self._cursors = cursors
        self._presentations = presentations
        self._episodes = episodes

    @classmethod
    def load(cls, path: str | Path) -> "PresentationStore":
        store = cls(path)
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if raw.get("schema_version") != PRESENTATION_SCHEMA_VERSION:
                raise PresentationPersistenceError(
                    "unsupported presentation schema version"
                )
            if (
                isinstance(raw.get("render_version"), bool)
                or not isinstance(raw.get("render_version"), int)
                or raw["render_version"] < 1
            ):
                raise PresentationPersistenceError(
                    "invalid presentation render version"
                )
            store._cursors = {
                str(key): int(value)
                for key, value in _required_mapping(raw, "cursors").items()
            }
            for value in _required_list(raw, "presentations"):
                item = _presentation_from_record(value)
                if item.presentation_id in store._presentations:
                    raise PresentationPersistenceError(
                        "duplicate presentation id"
                    )
                store._presentations[item.presentation_id] = item
            for value in _required_list(raw, "episodes"):
                item = _episode_from_record(value)
                if item.episode_id in store._episodes:
                    raise PresentationPersistenceError("duplicate episode id")
                store._episodes[item.episode_id] = item
            store._validate_loaded()
            return store
        except PresentationPersistenceError:
            raise
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise PresentationPersistenceError(
                "invalid presentation store"
            ) from exc

    def _validate_loaded(self) -> None:
        if any(cursor < 0 for cursor in self._cursors.values()):
            raise PresentationPersistenceError("negative presentation cursor")
        for item in self._presentations.values():
            episode = self._episodes.get(item.episode_id)
            if episode is None:
                raise PresentationPersistenceError(
                    "presentation references missing episode"
                )
            if (
                item.source_event_ids != item.digest.source_event_ids
                or episode.source_event_ids != item.source_event_ids
                or item.render_version < 1
                or episode.render_version != item.render_version
                or episode.audience_id != item.audience_id
                or not validate_rendered_facts(item.rendered, item.digest)
            ):
                raise PresentationPersistenceError(
                    "inconsistent presentation provenance"
                )

    def _persist(
        self,
        cursors: dict[str, int] | None = None,
        presentations: dict[str, Presentation] | None = None,
        episodes: dict[str, Episode] | None = None,
    ) -> None:
        selected_cursors = self._cursors if cursors is None else cursors
        selected_presentations = (
            self._presentations if presentations is None else presentations
        )
        selected_episodes = self._episodes if episodes is None else episodes
        if self._path is None:
            return
        try:
            persist_snapshot(
                self._path,
                schema_version=PRESENTATION_SCHEMA_VERSION,
                cursors=selected_cursors,
                presentations=selected_presentations,
                episodes=selected_episodes,
                presentation_record=_presentation_record,
                episode_record=_episode_record,
            )
        except OSError as exc:
            raise PresentationPersistenceError(
                "failed to persist presentation store"
            ) from exc


def _required_mapping(value: object, key: str) -> dict[str, object]:
    if not isinstance(value, dict) or not isinstance(value.get(key), dict):
        raise PresentationPersistenceError(f"missing mapping: {key}")
    return value[key]


def _required_list(value: object, key: str) -> list[object]:
    if not isinstance(value, dict) or not isinstance(value.get(key), list):
        raise PresentationPersistenceError(f"missing list: {key}")
    return value[key]


def _change_record(value: NarrativeChange) -> dict[str, object]:
    return {
        "category": value.category,
        "subject_id": value.subject_id,
        "target_id": value.target_id,
        "value": value.value,
        "is_cost": value.is_cost,
    }


def _entry_record(value: NarrativeDigestEntry) -> dict[str, object]:
    return {
        "source_event_id": value.source_event_id,
        "world_time": value.world_time,
        "actor_id": value.actor_id,
        "kind": value.kind,
        "summary": value.summary,
        "dialogue": value.dialogue,
        "actor_ids": list(value.actor_ids),
        "observer_ids": list(value.observer_ids),
        "location_id": value.location_id,
        "target_id": value.target_id,
        "goal": value.goal,
        "causal_source_ids": list(value.causal_source_ids),
        "changes": [_change_record(item) for item in value.changes],
        "unresolved_points": list(value.unresolved_points),
        "facts": dict(value.facts),
    }


def _digest_record(value: NarrativeDigest) -> dict[str, object]:
    return {
        "source_event_ids": list(value.source_event_ids),
        "world_time_start": value.world_time_start,
        "world_time_end": value.world_time_end,
        "entries": [_entry_record(item) for item in value.entries],
        "causal_event_ids": list(value.causal_event_ids),
        "character_ids": list(value.character_ids),
        "location_ids": list(value.location_ids),
        "target_ids": list(value.target_ids),
        "utterances": list(value.utterances),
        "changes": [_change_record(item) for item in value.changes],
        "unresolved_points": list(value.unresolved_points),
    }


def _diagnostic_record(value: RenderDiagnostic) -> dict[str, object]:
    return {
        "renderer": value.renderer,
        "status": value.status,
        "elapsed_ms": value.elapsed_ms,
        "detail": value.detail,
    }


def _presentation_record(value: Presentation) -> dict[str, object]:
    return {
        "presentation_id": value.presentation_id,
        "digest": _digest_record(value.digest),
        "rendered": {
            "title": value.rendered.title,
            "body": value.rendered.body,
            "non_factual_atmosphere": value.rendered.non_factual_atmosphere,
            "paragraphs": [
                {"source_event_ids": list(item.source_event_ids), "text": item.text}
                for item in value.rendered.paragraphs
            ],
        },
        "render_version": value.render_version,
        "episode_id": value.episode_id,
        "source_event_ids": list(value.source_event_ids),
        "world_time_start": value.world_time_start,
        "world_time_end": value.world_time_end,
        "audience_id": value.audience_id,
        "render_diagnostics": [
            _diagnostic_record(item) for item in value.render_diagnostics
        ],
    }


def _episode_record(value: Episode) -> dict[str, object]:
    return {
        "episode_id": value.episode_id,
        "digest": _digest_record(value.digest),
        "source_event_ids": list(value.source_event_ids),
        "world_time_start": value.world_time_start,
        "world_time_end": value.world_time_end,
        "render_version": value.render_version,
        "audience_id": value.audience_id,
    }


def _change_from_record(value: object) -> NarrativeChange:
    if not isinstance(value, dict):
        raise PresentationPersistenceError("invalid narrative change")
    return NarrativeChange(
        str(value["category"]),
        str(value["subject_id"]),
        None if value.get("target_id") is None else str(value["target_id"]),
        str(value["value"]),
        bool(value.get("is_cost", False)),
    )


def _entry_from_record(value: object) -> NarrativeDigestEntry:
    if not isinstance(value, dict):
        raise PresentationPersistenceError("invalid digest entry")
    return NarrativeDigestEntry(
        source_event_id=str(value["source_event_id"]),
        world_time=float(value["world_time"]),
        actor_id=str(value["actor_id"]),
        kind=str(value["kind"]),
        summary=str(value["summary"]),
        dialogue=None if value.get("dialogue") is None else str(value["dialogue"]),
        actor_ids=tuple(str(item) for item in value.get("actor_ids", ())),
        observer_ids=tuple(str(item) for item in value.get("observer_ids", ())),
        location_id=None if value.get("location_id") is None else str(value["location_id"]),
        target_id=None if value.get("target_id") is None else str(value["target_id"]),
        goal=None if value.get("goal") is None else str(value["goal"]),
        causal_source_ids=tuple(
            str(item) for item in value.get("causal_source_ids", ())
        ),
        changes=tuple(
            _change_from_record(item) for item in value.get("changes", ())
        ),
        unresolved_points=tuple(
            str(item) for item in value.get("unresolved_points", ())
        ),
        facts={
            str(key): str(item)
            for key, item in dict(value.get("facts", {})).items()
        },
    )


def _digest_from_record(value: object) -> NarrativeDigest:
    if not isinstance(value, dict):
        raise PresentationPersistenceError("invalid digest")
    return NarrativeDigest(
        source_event_ids=tuple(str(item) for item in value["source_event_ids"]),
        world_time_start=float(value["world_time_start"]),
        world_time_end=float(value["world_time_end"]),
        entries=tuple(_entry_from_record(item) for item in value["entries"]),
        causal_event_ids=tuple(str(item) for item in value.get("causal_event_ids", ())),
        character_ids=tuple(str(item) for item in value.get("character_ids", ())),
        location_ids=tuple(str(item) for item in value.get("location_ids", ())),
        target_ids=tuple(str(item) for item in value.get("target_ids", ())),
        utterances=tuple(str(item) for item in value.get("utterances", ())),
        changes=tuple(_change_from_record(item) for item in value.get("changes", ())),
        unresolved_points=tuple(
            str(item) for item in value.get("unresolved_points", ())
        ),
    )


def _presentation_from_record(value: object) -> Presentation:
    if not isinstance(value, dict) or not isinstance(value.get("rendered"), dict):
        raise PresentationPersistenceError("invalid presentation")
    rendered = value["rendered"]
    return Presentation(
        presentation_id=str(value["presentation_id"]),
        digest=_digest_from_record(value["digest"]),
        rendered=RenderedNarrative(
            str(rendered["title"]),
            str(rendered["body"]),
            rendered.get("non_factual_atmosphere"),
            tuple(
                RenderedParagraph(
                    tuple(str(value) for value in item["source_event_ids"]),
                    str(item["text"]),
                )
                for item in rendered.get("paragraphs", ())
            ),
        ),
        render_version=int(value["render_version"]),
        episode_id=str(value["episode_id"]),
        source_event_ids=tuple(str(item) for item in value["source_event_ids"]),
        world_time_start=float(value["world_time_start"]),
        world_time_end=float(value["world_time_end"]),
        audience_id=str(value["audience_id"]),
        render_diagnostics=tuple(
            RenderDiagnostic(
                str(item["renderer"]),
                str(item["status"]),
                int(item["elapsed_ms"]),
                str(item.get("detail", "")),
            )
            for item in value.get("render_diagnostics", ())
        ),
    )


def _episode_from_record(value: object) -> Episode:
    if not isinstance(value, dict):
        raise PresentationPersistenceError("invalid episode")
    return Episode(
        str(value["episode_id"]), _digest_from_record(value["digest"]),
        tuple(str(item) for item in value["source_event_ids"]),
        float(value["world_time_start"]), float(value["world_time_end"]),
        int(value["render_version"]), str(value["audience_id"]),
    )

