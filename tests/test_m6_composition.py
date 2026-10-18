import json
from pathlib import Path

from engine.adapters.model_actor import ModelActorPolicy
from engine.adapters.model_adjudicator import ModelWorldAdjudicator
from engine.adapters.model_intent import ModelIntentPolicy
from engine.adapters.model_scene_generator import ModelSceneGenerator
from engine.adapters.model_json import decode_json_object
from engine.adapters.model_renderer import ModelNarrativeRenderer
from engine.bootstrap import build_application
from engine.narrative import (
    DeliveryPolicy,
    NarrativeChange,
    NarrativeDelivery,
    NarrativeStyleProfile,
    PresentationStore,
    SourceEventView,
)
from engine.runtime.character.policy import ModelDialogueActorPolicy
from engine.runtime.scene import (
    DeterministicIntentPolicy,
    DeterministicSceneGenerator,
    DeterministicWorldAdjudicator,
)
from engine.world import compile_package


PACKAGE = Path(__file__).parents[1] / "worlds" / "echo-quay"


class FakeTextModel:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0
        self.prompts = []

    def complete(
        self, prompt: str, timeout_seconds: float | None = None
    ) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        return self.reply


def test_model_renderer_decodes_fenced_or_prefaced_json():
    value = {"title": "片段", "paragraphs": []}

    assert decode_json_object(
        "```json\n" + json.dumps(value, ensure_ascii=False) + "\n```"
    ) == value
    assert decode_json_object(
        "终稿如下：\n" + json.dumps(value, ensure_ascii=False)
    ) == value


def _compiled():
    result = compile_package(PACKAGE)
    assert result.ok and result.compiled is not None
    return result.compiled


def test_composition_is_deterministic_unless_model_is_explicitly_injected():
    deterministic = build_application(_compiled())
    fake = FakeTextModel(
        json.dumps(
            {
                "title": "片段",
                "paragraphs": [
                    {
                        "source_event_ids": ["world-000001"],
                        "text": "片段",
                    }
                ],
            }
        )
    )
    modeled = build_application(_compiled(), text_model=fake)

    assert deterministic.text_model is None
    assert isinstance(
        deterministic.scene_generator, DeterministicSceneGenerator
    )
    assert isinstance(
        deterministic.intent_policy, DeterministicIntentPolicy
    )
    assert isinstance(
        deterministic.world_adjudicator,
        DeterministicWorldAdjudicator,
    )
    assert isinstance(modeled.actor_policy, ModelActorPolicy)
    assert isinstance(modeled.renderer, ModelNarrativeRenderer)
    assert isinstance(modeled.scene_generator, ModelSceneGenerator)
    assert isinstance(modeled.intent_policy, ModelIntentPolicy)
    assert isinstance(
        modeled.world_adjudicator, ModelWorldAdjudicator
    )
    dialogue_only = build_application(
        _compiled(),
        text_model=fake,
        model_config={"actor_model": "dialogue_only"},
    )
    assert isinstance(
        dialogue_only.actor_policy, ModelDialogueActorPolicy
    )


def test_model_renderer_still_uses_fact_validator_and_fallback():
    fake = FakeTextModel(
        json.dumps(
            {
                "title": "invented-entity",
                "paragraphs": [
                    {
                        "source_event_ids": ["world-000001"],
                        "text": "新增事实",
                    }
                ],
            }
        )
    )
    event = SourceEventView(
        source_event_id="world-000001",
        world_time=1.0,
        kind="observed",
        actor_ids=("lin",),
        observer_ids=("lin",),
        location_id="quay",
        target_id=None,
        goal=None,
        summary="lin observed quay",
        utterance=None,
        causal_source_ids=(),
        changes=(NarrativeChange("relationship", "lin", None, "+1"),),
        unresolved_points=(),
        facts={},
    )
    delivery = NarrativeDelivery(
        PresentationStore(),
        DeliveryPolicy(unpresented_event_threshold=1),
        ModelNarrativeRenderer(fake),
    )

    presentation = delivery.publish((event,))

    assert fake.calls == 7
    assert presentation.render_diagnostics[0].status == "fact_validation_failed"
    assert presentation.render_diagnostics[1].status == "fallback"
    assert "lin" in presentation.rendered.body


def test_model_renderer_receives_registered_style_and_sourced_plan():
    fake = FakeTextModel(
        json.dumps(
            {
                "title": "lin quay",
                "paragraphs": [
                    {
                        "source_event_ids": ["world-000001"],
                        "text": "lin observed quay",
                    }
                ],
            }
        )
    )
    event = SourceEventView(
        source_event_id="world-000001",
        world_time=1.0,
        kind="observed",
        actor_ids=("lin",),
        observer_ids=("lin",),
        location_id="quay",
        target_id=None,
        goal=None,
        summary="lin observed quay",
        utterance=None,
        causal_source_ids=(),
        changes=(),
        unresolved_points=(),
        facts={},
    )
    delivery = NarrativeDelivery(
        PresentationStore(),
        DeliveryPolicy(unpresented_event_threshold=1),
        ModelNarrativeRenderer(fake),
        style_profile=NarrativeStyleProfile(
                voice_id="restrained-mystery-v1",
            imagery_domains=("潮声",),
        ),
    )

    presentation = delivery.publish((event,))

    assert presentation.render_diagnostics[0].status == "ok"
    assert presentation.rendered.paragraphs[0].source_event_ids == (
        "world-000001",
    )
    assert "developmental-editor-v1" in fake.prompts[0]
    assert "scene-writer-v1" in fake.prompts[1]
    assert "line-editor-v1" in fake.prompts[2]
    assert "line_edit_noop" in fake.prompts[3]
    assert "fact-continuity-editor-v1" in fake.prompts[4]
    assert "克制的当代悬疑声音" in fake.prompts[1]
    assert "潮声" in fake.prompts[1]
