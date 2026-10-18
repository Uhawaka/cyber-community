import json
from dataclasses import replace
from pathlib import Path

from engine.adapters.model_renderer import ModelNarrativeRenderer
from engine.application import rerender_frozen_presentations
from engine.contracts import DEFAULT_EDITORIAL_PIPELINE
from engine.narrative import (
    DeliveryPolicy,
    NarrativeChange,
    NarrativeDelivery,
    NarrativeStyleProfile,
    PresentationStore,
    SourceEventView,
    StructuredLiteraryRenderer,
)
from engine.narrative.skills import get_literary_skill


class ScriptedModel:
    def __init__(self, replies: list[dict[str, object]]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(
        self, prompt: str, timeout_seconds: float | None = None
    ) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.replies.pop(0), ensure_ascii=False)


def _event() -> SourceEventView:
    return SourceEventView(
        source_event_id="world-000001",
        world_time=1.0,
        kind="observed",
        actor_ids=("lin",),
        observer_ids=("lin",),
        location_id="quay",
        target_id=None,
        goal="查看码头",
        summary="lin observed quay",
        utterance=None,
        causal_source_ids=(),
        changes=(NarrativeChange("relationship", "lin", None, "+1"),),
        unresolved_points=(),
        facts={},
    )


def test_registered_skills_are_real_versioned_resources():
    stages = tuple(
        get_literary_skill(skill_id).stage
        for skill_id in DEFAULT_EDITORIAL_PIPELINE
    )

    assert stages == (
        "developmental_edit",
        "scene_draft",
        "line_edit",
        "fact_continuity",
    )
    assert all(
        "# " in get_literary_skill(skill_id).instruction
        for skill_id in DEFAULT_EDITORIAL_PIPELINE
    )


def test_model_renderer_executes_each_skill_and_keeps_artifacts():
    brief = {
        "focus": "lin",
        "goal": "查看码头",
        "conflict": "码头情况不明",
        "stakes": "无法判断去路",
        "turn_source_id": "world-000001",
        "selected_source_ids": ["world-000001"],
        "direct_quote_source_ids": [],
        "ending_source_id": "world-000001",
        "ending_fact_relation": "观察已经发生",
    }
    draft = {
        "title": "码头",
        "paragraphs": [
            {
                "source_event_ids": ["world-000001"],
                "text": "lin observed quay",
            }
        ],
    }
    edited = {
        "title": "码头",
        "paragraphs": [
            {
                "source_event_ids": ["world-000001"],
                "text": "lin observed quay.",
            }
        ],
    }
    model = ScriptedModel([brief, draft, edited, edited])
    renderer = ModelNarrativeRenderer(model)
    delivery = NarrativeDelivery(
        PresentationStore(),
        DeliveryPolicy(unpresented_event_threshold=1),
        renderer,
    )

    presentation = delivery.publish((_event(),))

    assert presentation.render_diagnostics[0].status == "ok"
    assert len(model.prompts) == 4
    assert tuple(
        item.stage for item in renderer.last_diagnostics
    ) == (
        "developmental_edit",
        "scene_draft",
        "line_edit",
        "fact_continuity",
    )
    assert set(renderer.last_artifacts) >= {
        "developmental_edit",
        "scene_draft",
        "line_edit",
        "fact_continuity",
    }


def test_revision_stages_only_receive_authorized_quote_excerpt():
    brief = {
        "focus": "lin",
        "goal": "查看码头",
        "conflict": "码头情况不明",
        "stakes": "无法判断去路",
        "turn_source_id": "world-000001",
        "selected_source_ids": ["world-000001"],
        "direct_quote_source_ids": ["world-000001"],
        "ending_source_id": "world-000001",
        "ending_fact_relation": "观察已经发生",
    }
    draft = {
        "title": "码头",
        "paragraphs": [{
            "source_event_ids": ["world-000001"],
            "text": "lin observed quay.",
        }],
    }
    edited = {
        "title": "码头",
        "paragraphs": [{
            "source_event_ids": ["world-000001"],
            "text": "lin observed quay!",
        }],
    }
    model = ScriptedModel([brief, draft, edited, edited])
    renderer = ModelNarrativeRenderer(model)
    hidden_tail = "这是一段超过引用上限而且绝不能泄漏给后续编辑阶段的解释性长尾内容"
    event = replace(
        _event(),
        utterance=f"灯还亮着。{hidden_tail}{hidden_tail}",
    )

    NarrativeDelivery(
        PresentationStore(),
        DeliveryPolicy(unpresented_event_threshold=1),
        renderer,
    ).publish((event,))

    assert hidden_tail in model.prompts[0]
    assert all(hidden_tail not in prompt for prompt in model.prompts[1:])
    assert all('"spoken_text"' not in prompt for prompt in model.prompts[1:])


def test_frozen_rerender_copies_material_without_touching_source(tmp_path):
    source = tmp_path / "source.json"
    source_store = PresentationStore(source)
    NarrativeDelivery(
        source_store,
        DeliveryPolicy(unpresented_event_threshold=1),
    ).publish((_event(),))
    before = source.read_bytes()

    report = rerender_frozen_presentations(
        source,
        tmp_path / "iteration",
        renderer=StructuredLiteraryRenderer(),
        style_profile=NarrativeStyleProfile(),
        package_id="probe",
        world_title="Probe",
        seed=17,
    )

    assert source.read_bytes() == before
    assert report["world_advanced"] is False
    assert report["results"][0]["status"] == "ok"
    assert Path(report["results"][0]["story"]).is_file()
