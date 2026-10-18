"""Model renderer backed by executable, versioned literary skills."""

from __future__ import annotations

from dataclasses import asdict

from engine.adapters.model_literary_stages import ModelLiteraryStageRunner
from engine.adapters.model_narrative_material import narrative_material
from engine.contracts import (
    DEFAULT_EDITORIAL_PIPELINE,
    EDITORIAL_STAGE_GRAPH,
    EditorialDiagnostic,
    TextModel,
)
from engine.narrative.digest import NarrativeDigest
from engine.narrative.exchange import assemble_committed_exchange
from engine.narrative.planning import (
    NarrativeRenderRequest,
    NarrativeStyleProfile,
    build_narrative_plan,
)
from engine.narrative.rendering import (
    RenderedNarrative,
    RenderedParagraph,
    compress_event_log_shape,
)
from engine.narrative.skills import get_literary_skill
from engine.narrative.validation import (
    literary_quality_issues,
    rendered_fact_issues,
    validate_literary_quality,
    validate_rendered_facts,
)


class LiteraryPipelineRenderer:
    """Execute editorial skills as isolated stages with bounded repair."""

    def __init__(
        self,
        model: TextModel,
        *,
        timeout_seconds: float = 8.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.labels = dict(labels or {})
        self.last_diagnostics: tuple[EditorialDiagnostic, ...] = ()
        self.last_artifacts: dict[str, object] = {}

    def render(
        self, value: NarrativeRenderRequest | NarrativeDigest
    ) -> RenderedNarrative:
        request = (
            value
            if isinstance(value, NarrativeRenderRequest)
            else NarrativeRenderRequest(
                value,
                build_narrative_plan(value),
                NarrativeStyleProfile(),
            )
        )
        assembled = assemble_committed_exchange(request)
        if assembled is not None:
            self.last_diagnostics = ()
            self.last_artifacts = {"renderer": "committed-exchange"}
            return assembled
        pipeline = (
            request.style.editorial_pipeline or DEFAULT_EDITORIAL_PIPELINE
        )
        skills_by_stage = self._skills_by_stage(pipeline)
        facts, plan, scene_lore = narrative_material(request)
        runner = ModelLiteraryStageRunner(
            self.model,
            timeout_seconds=self.timeout_seconds,
            labels=self.labels,
        )
        try:
            brief = runner.develop(
                skills_by_stage["developmental_edit"],
                request,
                facts,
                plan,
            )
            scene_draft = runner.draft(
                skills_by_stage["scene_draft"],
                request,
                brief,
                facts,
                scene_lore,
            )
            line_draft = runner.revise(
                skills_by_stage["line_edit"],
                request,
                scene_draft,
                brief,
                facts,
                scene_lore,
            )
            if line_draft == scene_draft:
                line_draft = runner.revise(
                    skills_by_stage["line_edit"],
                    request,
                    scene_draft,
                    brief,
                    facts,
                    scene_lore,
                    diagnostic=(
                        "line_edit_noop：逐句冷读后仍原样返回。必须实际删除"
                        "摘要腔、复述或同构句；若句子确无问题，至少改善段落"
                        "承重位置，同时保持来源不变"
                    ),
                )
            final_draft = runner.revise(
                skills_by_stage["fact_continuity"],
                request,
                line_draft,
                brief,
                facts,
                scene_lore,
            )
            rendered = _rendered(final_draft)
            for _ in range(2):
                if validate_rendered_facts(rendered, request):
                    break
                issues = ",".join(rendered_fact_issues(rendered, request))
                final_draft = runner.revise(
                    skills_by_stage["fact_continuity"],
                    request,
                    final_draft,
                    brief,
                    facts,
                    scene_lore,
                    diagnostic=issues or "fact_validation_failed",
                )
                rendered = _rendered(final_draft)
            if (
                validate_rendered_facts(rendered, request)
                and not validate_literary_quality(rendered, request)
            ):
                issues = ",".join(literary_quality_issues(rendered, request))
                line_draft = runner.revise(
                    skills_by_stage["line_edit"],
                    request,
                    final_draft,
                    brief,
                    facts,
                    scene_lore,
                    diagnostic=issues,
                )
                final_draft = runner.revise(
                    skills_by_stage["fact_continuity"],
                    request,
                    line_draft,
                    brief,
                    facts,
                    scene_lore,
                    diagnostic="post_line_edit_fact_check",
                )
                rendered = _rendered(final_draft)
            if literary_quality_issues(rendered, request) == (
                "event_log_paragraph_shape",
            ):
                rendered = compress_event_log_shape(rendered, request)
            return rendered
        finally:
            self.last_diagnostics = tuple(runner.diagnostics)
            self.last_artifacts = {
                **runner.artifacts,
                "pipeline": list(pipeline),
                "diagnostics": [
                    asdict(item) for item in runner.diagnostics
                ],
            }

    @staticmethod
    def _skills_by_stage(pipeline: tuple[str, ...]) -> dict[str, str]:
        expected = EDITORIAL_STAGE_GRAPH
        actual = tuple(get_literary_skill(item).stage for item in pipeline)
        if actual != expected:
            raise ValueError(
                "editorial pipeline stages must be "
                + " -> ".join(expected)
            )
        return dict(zip(actual, pipeline, strict=True))


def _rendered(value: object) -> RenderedNarrative:
    title = getattr(value, "title")
    paragraphs = tuple(
        RenderedParagraph(item.source_event_ids, item.text)
        for item in getattr(value, "paragraphs")
    )
    return RenderedNarrative(
        title=title,
        body="\n\n".join(item.text for item in paragraphs),
        paragraphs=paragraphs,
    )
