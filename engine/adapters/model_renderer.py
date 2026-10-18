"""Compatibility export for the executable literary skill renderer."""

from engine.adapters.literary_pipeline_renderer import (
    LiteraryPipelineRenderer as ModelNarrativeRenderer,
)

__all__ = ["ModelNarrativeRenderer"]
