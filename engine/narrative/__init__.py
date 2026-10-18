"""Independent narrative presentation over committed runtime events."""

from engine.narrative.artifacts import STORY_DOCUMENT_SCHEMA_VERSION, render_story_markdown, story_document_name, write_story_markdown
from engine.narrative.curation import CurationPolicy, CuratedEpisodeWindow, curate_episode_windows, is_reader_visible_source
from engine.narrative.delivery import DeliveryDecision, DeliveryNotDue, DeliveryPolicy, NarrativeDelivery
from engine.narrative.digest import NarrativeDigest, NarrativeDigestEntry, build_narrative_digest
from engine.narrative.planning import NarrativeBeat, NarrativePlan, NarrativeRenderRequest, NarrativeStyleProfile, build_narrative_plan, style_profile_from_contract, validate_narrative_plan
from engine.narrative.rendering import (AudienceMode, DeterministicNarrativeRenderer, NarrativeRenderer, RenderDiagnostic, RenderedNarrative, RenderedParagraph, StructuredLiteraryRenderer)
from engine.narrative.skills import get_literary_skill, get_world_voice, literary_skill_ids, world_voice_ids
from engine.narrative.source import NarrativeChange, SourceEvent, SourceEventView, adapt_source_event, adapt_source_events
from engine.narrative.store import Episode, PRESENTATION_SCHEMA_VERSION, Presentation, PresentationPersistenceError, PresentationStore
from engine.narrative.validation import validate_literary_quality, validate_rendered_facts

__all__ = [
    "AudienceMode", "DeliveryDecision", "DeliveryNotDue", "DeliveryPolicy",
    "CurationPolicy", "CuratedEpisodeWindow",
    "DeterministicNarrativeRenderer", "Episode", "NarrativeDelivery",
    "NarrativeDigest", "NarrativeDigestEntry", "NarrativeRenderer", "Presentation",
    "PresentationPersistenceError", "PresentationStore", "PRESENTATION_SCHEMA_VERSION",
    "RenderDiagnostic", "RenderedNarrative", "StructuredLiteraryRenderer",
    "RenderedParagraph", "NarrativeBeat", "NarrativePlan",
    "NarrativeRenderRequest", "NarrativeStyleProfile",
    "STORY_DOCUMENT_SCHEMA_VERSION", "render_story_markdown", "story_document_name",
    "write_story_markdown",
    "NarrativeChange", "SourceEvent", "SourceEventView", "adapt_source_event",
    "adapt_source_events", "build_narrative_digest", "validate_rendered_facts",
    "validate_literary_quality",
    "build_narrative_plan", "curate_episode_windows",
    "style_profile_from_contract",
    "validate_narrative_plan",
    "get_literary_skill", "get_world_voice", "is_reader_visible_source",
    "literary_skill_ids", "world_voice_ids",
]
