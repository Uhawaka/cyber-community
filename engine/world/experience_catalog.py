"""Host-owned catalogs selectable by authored experience profiles."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from engine.contracts.experience import (
    EditorialBundleDefaults,
    RuntimeNarrativeContract,
)
from engine.contracts.literary import DEFAULT_EDITORIAL_PIPELINE


def _style(
    *,
    voice_id: str,
    narrative_distance: str,
    register: str,
    rhythm: str,
) -> tuple[tuple[str, object], ...]:
    return tuple(
        sorted(
            {
                "skill_id": "scene-craft-v2",
                "voice_id": voice_id,
                "language": "zh-CN",
                "point_of_view": "omniscient",
                "narrative_distance": narrative_distance,
                "register": register,
                "rhythm": rhythm,
                "dialogue_density": "balanced",
                "imagery_domains": (),
                "forbidden_phrases": (),
                "scene_shape": "turn-centered",
                "exposition": "implicit",
                "revision_level": "developmental-and-line",
            }.items()
        )
    )


_DEFAULT_EPISODE = tuple(
    sorted(
        {
            "max_events": 32,
            "max_world_time_span": 8,
            "min_narrative_events": 5,
            "max_repeated_action": 1,
            "min_arc_events": 1,
        }.items()
    )
)


RUNTIME_MODE_CATALOG: Mapping[str, RuntimeNarrativeContract] = (
    MappingProxyType(
        {
            "scene-pressure-v1": RuntimeNarrativeContract(
                "scene-pressure-v1",
                pressure_escalation_turns=3,
                max_pressure_level=3,
                decision_pressure_level=2,
                resolution_modes=(
                    "closure_signals",
                    "participant_decisions",
                ),
            )
        }
    )
)


EDITORIAL_BUNDLE_CATALOG: Mapping[str, EditorialBundleDefaults] = (
    MappingProxyType(
        {
            "neutral-observer-v1": EditorialBundleDefaults(
                "neutral-observer-v1",
                "neutral",
                "clear-observer-v1",
                DEFAULT_EDITORIAL_PIPELINE,
                _style(
                    voice_id="clear-observer-v1",
                    narrative_distance="medium",
                    register="literary",
                    rhythm="balanced",
                ),
                _DEFAULT_EPISODE,
            ),
            "restrained-mystery-v1": EditorialBundleDefaults(
                "restrained-mystery-v1",
                "mystery",
                "restrained-mystery-v1",
                DEFAULT_EDITORIAL_PIPELINE,
                _style(
                    voice_id="restrained-mystery-v1",
                    narrative_distance="close",
                    register="contemporary",
                    rhythm="restrained",
                ),
                _DEFAULT_EPISODE,
                narrative_functions=(
                    "anomaly",
                    "counterevidence",
                    "withheld_information",
                    "revelation",
                ),
                quality_dimensions=(
                    "clue_fairness",
                    "suspense",
                    "revelation_timing",
                ),
            ),
            "demythologized-dark-myth-v1": EditorialBundleDefaults(
                "demythologized-dark-myth-v1",
                "demythologized-dark-myth",
                "demythologized-dark-myth-v1",
                (
                    "mythic-intrigue-editor-v1",
                    *DEFAULT_EDITORIAL_PIPELINE[1:],
                ),
                _style(
                    voice_id="demythologized-dark-myth-v1",
                    narrative_distance="medium",
                    register="classical-vernacular",
                    rhythm="restrained",
                ),
                _DEFAULT_EPISODE,
                narrative_functions=(
                    "institutional_claim",
                    "extraction_cost",
                    "counterevidence",
                    "moral_ambiguity",
                    "resistance_choice",
                ),
                quality_dimensions=(
                    "institutional_coherence",
                    "moral_ambiguity",
                    "revelation_timing",
                    "human_cost",
                ),
            ),
        }
    )
)


REGISTERED_GENRE_IDS = frozenset(
    item.genre_id for item in EDITORIAL_BUNDLE_CATALOG.values()
)
