from pathlib import Path
import json

from engine.adapters.model_scene_generator import ModelSceneGenerator
from engine.adapters.model_adjudicator import ModelWorldAdjudicator
from engine.adapters.model_intent import ModelIntentPolicy
from engine.contracts import (
    AdjudicatedTurn,
    BuiltinComponent,
    CharacterIntent,
    ComponentPatch,
    ComponentValue,
    EntityKind,
    EntitySpec,
    InteractionRequest,
    PatchOperation,
    SceneBlueprint,
)
from engine.runtime.kernel import Delta, EventLog, EventType, WorldEvent, WorldState
from engine.runtime.kernel.events import event_from_record, event_record
from engine.runtime.kernel.lifecycle import create_run
from engine.narrative.source import adapt_source_event
from engine.runtime.scene import (
    DeterministicSceneGenerator,
    commit_turn,
    capabilities_for_intent,
    enter_scene,
    ensure_scene,
    evolve_scene_time,
    project_perception,
    resolve_ambient_npc_requests,
    run_scene_turns,
    travel_to_scene,
)
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).resolve().parents[1]


class _FakeSceneModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self, prompt: str, timeout_seconds: float | None = None
    ) -> str:
        del prompt, timeout_seconds
        self.calls += 1
        return json.dumps(
            {
                "entry_anchor_id": "scene:back-door:threshold",
                "local_rules": ["庙门内可以避雨"],
                "anchors": [
                    {
                        "id": "scene:back-door:threshold",
                        "name": "门槛",
                        "description": "雨水打湿了半边门槛。",
                    }
                ],
                "items": [
                    {
                        "id": "scene:back-door:bell",
                        "name": "断铃",
                        "description": "一片断裂铜铃。",
                        "anchor_id": "scene:back-door:threshold",
                        "interaction_hints": ["查看残留痕迹"],
                    }
                ],
                "npcs": [
                    {
                        "id": "scene:back-door:keeper",
                        "name": "守庙人",
                        "description": "只管照看门口的老人。",
                        "anchor_id": "scene:back-door:threshold",
                        "routines": ["照看庙门"],
                        "response_style": "简短",
                        "known_facts": [
                            "这道细铃声只在风从庙内向外吹时响起"
                        ],
                        "interaction_hints": ["询问庙里的旧事"],
                    }
                ],
            },
            ensure_ascii=False,
        )


class _JsonModel:
    def __init__(self, *values: dict[str, object]) -> None:
        self.values = list(values)

    def complete(
        self, prompt: str, timeout_seconds: float | None = None
    ) -> str:
        del prompt, timeout_seconds
        return json.dumps(self.values.pop(0), ensure_ascii=False)


def _state() -> WorldState:
    return WorldState(
        world_id="test-world",
        world_hash="world-hash",
        seed=17,
        tick=0,
        world_time=0,
        characters={},
        resources={},
        inventories={},
        relationships={},
    )


def _blueprint() -> SceneBlueprint:
    return SceneBlueprint(
        "scene:inn",
        "inn",
        "anchor:door",
        (
            EntitySpec(
                "scene:inn",
                EntityKind.SCENE,
                (
                    ComponentValue(
                        BuiltinComponent.IDENTITY.value,
                        {
                            "name": "南门客栈",
                            "description": "雨幕把客栈檐灯映成一团暖黄。",
                        },
                    ),
                    ComponentValue(
                        BuiltinComponent.LAYOUT.value,
                        {"anchor_ids": ["anchor:door", "anchor:table"]},
                    ),
                ),
            ),
            EntitySpec(
                "anchor:door",
                EntityKind.ANCHOR,
                (
                    ComponentValue(
                        BuiltinComponent.IDENTITY.value,
                        {"name": "门口"},
                    ),
                ),
            ),
            EntitySpec(
                "anchor:table",
                EntityKind.ANCHOR,
                (
                    ComponentValue(
                        BuiltinComponent.IDENTITY.value,
                        {"name": "靠窗餐桌"},
                    ),
                ),
            ),
        ),
    )


def test_scene_blueprint_is_committed_and_replayed_losslessly():
    state = _state()
    blueprint = _blueprint()
    patches = tuple(
        ComponentPatch(
            PatchOperation.CREATE_ENTITY,
            entity.entity_id,
            entity=entity,
        )
        for entity in blueprint.entities
    )
    event = WorldEvent(
        sequence=0,
        tick=0,
        event_type=EventType.SCENE_INSTANTIATED,
        actor_id=None,
        observers=(),
        delta=Delta(entity_patches=patches),
        data={"scene_id": blueprint.scene_id},
        pre_state_hash=state.state_hash(),
        world_hash=state.world_hash,
    )

    log = EventLog(state)
    log.append(event)
    decoded = event_from_record(
        event_record(log.events[0]), world_hash=state.world_hash
    )
    replayed = EventLog.replay(state, log.events).state

    assert decoded == log.events[0]
    assert replayed == log.state
    assert replayed.entities["scene:inn"].kind is EntityKind.SCENE
    assert replayed.entities["scene:inn"].version == 0
    source = adapt_source_event(log.events[0])
    assert source.kind == "scene_instantiated"
    assert source.summary == "雨幕把客栈檐灯映成一团暖黄。"
    assert source.facts["scene_description"] == source.summary
    assert "门口" in source.facts["scene_elements"]
    assert "component:scene:inn:layout" in source.facts


def test_component_patch_uses_optimistic_entity_version():
    state = _state()
    blueprint = _blueprint()
    created = state.apply(
        Delta(
            entity_patches=tuple(
                ComponentPatch(
                    PatchOperation.CREATE_ENTITY,
                    entity.entity_id,
                    entity=entity,
                )
                for entity in blueprint.entities
            )
        )
    )
    updated = created.apply(
        Delta(
            entity_patches=(
                ComponentPatch(
                    PatchOperation.UPSERT_COMPONENT,
                    "scene:inn",
                    expected_entity_version=0,
                    component=ComponentValue(
                        BuiltinComponent.ATTRIBUTES.value,
                        {"turn_count": 1},
                    ),
                ),
            )
        )
    )

    assert updated.entities["scene:inn"].version == 1
    assert updated.entities["scene:inn"].components["attributes"]["turn_count"] == 1


def test_scene_presence_drives_first_person_perception_and_turns():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run, "back-door", DeterministicSceneGenerator()
    )
    view = project_perception(run.state, "wukong")
    focus_id = f"{scene_id}:focus"
    intent = CharacterIntent(
        "intent-1",
        "wukong",
        scene_id,
        view.scene_version,
        "靠近主要活动处",
        "我从入口走向主要活动处。",
        (focus_id,),
    )
    turn = AdjudicatedTurn(
        intent.intent_id,
        intent.actor_id,
        intent.scene_id,
        intent.expected_scene_version,
        "accepted",
        "孙悟空从入口来到主要活动处。",
        "我已经来到主要活动处。",
        (
            ComponentPatch(
                PatchOperation.UPSERT_COMPONENT,
                "wukong",
                component=ComponentValue(
                    BuiltinComponent.PRESENCE.value,
                    {
                        "scene_id": scene_id,
                        "anchor_id": focus_id,
                        "location_id": "back-door",
                    },
                ),
            ),
        ),
        rule_basis=("the target anchor exists in the current scene",),
    )

    event = commit_turn(run, intent, turn)
    updated = project_perception(run.state, "wukong")

    assert event.event_type is EventType.TURN_RESOLVED
    source = adapt_source_event(event)
    assert source.summary == "孙悟空从入口来到主要活动处。"
    assert source.goal == "靠近主要活动处"
    assert source.location_id == scene_id
    assert "主要活动处" in updated.first_person_context
    assert run.replay() == run.state
    assert run.state.entities[scene_id].version == 2


def test_scene_pressure_escalates_and_committed_outcome_closes_stage():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run, "back-door", DeterministicSceneGenerator()
    )
    opening = project_perception(run.state, "bailing")
    assert "这一处只能看清这一层" in opening.first_person_context
    assert "我的当前承诺" in opening.first_person_context

    for index in range(3):
        view = project_perception(run.state, "bailing")
        intent = CharacterIntent(
            f"stagnant-{index}",
            "bailing",
            scene_id,
            view.scene_version,
            "继续查验",
            "我再次查看同一处粉痕。",
            (scene_id,),
        )
        commit_turn(
            run,
            intent,
            AdjudicatedTurn(
                intent.intent_id,
                intent.actor_id,
                scene_id,
                intent.expected_scene_version,
                "accepted",
                "白灵再次查看同一处粉痕。",
                "没有得到足以改变决定的新结果。",
            ),
        )

    dramatic = run.state.entities[scene_id].components["dramatic"]
    assert dramatic["pressure_level"] == 1
    assert "场景压力已升至1级" in project_perception(
        run.state, "bailing"
    ).first_person_context

    view = project_perception(run.state, "bailing")
    intent = CharacterIntent(
        "resolve-stage",
        "bailing",
        scene_id,
        view.scene_version,
        "明确保管责任",
        "我与同行者约定暂由我保管铃片并共同前往夹廊。",
        (scene_id,),
    )
    event = commit_turn(
        run,
        intent,
        AdjudicatedTurn(
            intent.intent_id,
            intent.actor_id,
            scene_id,
            intent.expected_scene_version,
            "accepted",
            "白灵与同行者明确了铃片保管责任和共同去向。",
            "保管责任和下一步去向已经成为公开决定。",
            dramatic_progress="resolved",
            scene_outcome="白灵暂时保管铃片，众人共同前往悬铃夹廊。",
        ),
    )

    dramatic = run.state.entities[scene_id].components["dramatic"]
    assert dramatic["status"] == "resolved"
    assert dramatic["outcome"].startswith("白灵暂时保管")
    assert event.data["dramatic_progress"] == "resolved"
    assert "阶段结果" in adapt_source_event(event).summary
    assert run.replay() == run.state


def test_all_present_characters_deciding_closes_scene_collectively():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run, "back-door", DeterministicSceneGenerator()
    )
    final_event = None
    for actor_id in ("bailing", "traveler", "wukong"):
        view = project_perception(run.state, actor_id)
        intent = CharacterIntent(
            f"decision-{actor_id}",
            actor_id,
            scene_id,
            view.scene_version,
            "作出共同去向决定",
            "我公开承担自己的责任并同意共同前往夹廊。",
            (scene_id,),
            decision=f"{actor_id}承担责任并同意共同前往夹廊。",
        )
        final_event = commit_turn(
            run,
            intent,
            AdjudicatedTurn(
                intent.intent_id,
                actor_id,
                scene_id,
                intent.expected_scene_version,
                "accepted",
                f"{actor_id}公开承担责任并同意共同前往夹廊。",
                "我的决定已经公开。",
                dramatic_progress="advance",
            ),
        )

    assert final_event is not None
    assert final_event.data["dramatic_progress"] == "resolved"
    dramatic = run.state.entities[scene_id].components["dramatic"]
    assert dramatic["status"] == "resolved"
    assert set(dramatic["decisions"]) == {
        "bailing",
        "traveler",
        "wukong",
    }
    before = len(run.events)
    usage = run_scene_turns(
        run,
        ("bailing", "traveler", "wukong"),
        turn_budget=3,
    )
    first_destinations = {
        event.data.get("destination_id")
        for event in run.events[before:]
        if event.event_type is EventType.MOVED
    }
    assert len(first_destinations) <= 1
    if usage.character_turns < 3:
        usage = run_scene_turns(
            run,
            ("bailing", "traveler", "wukong"),
            turn_budget=3,
        )
        assert usage.character_turns >= 1
    assert any(
        event.event_type is EventType.MOVED
        for event in run.events
    )
    for actor_id in ("bailing", "traveler", "wukong"):
        assert run.state.characters[actor_id].location_id == (
            run.state.entities[actor_id]
            .components["presence"]["location_id"]
        )
    assert run.replay() == run.state


def test_model_scene_is_generated_once_then_reused_from_state():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    model = _FakeSceneModel()
    generator = ModelSceneGenerator(model)

    first = ensure_scene(run, "back-door", generator)
    second = ensure_scene(run, "back-door", generator)

    assert first == second == "scene:back-door"
    assert model.calls == 1
    assert "scene:back-door:bell" in run.state.entities
    authored_bell = run.state.entities[
        "scene:back-door:resource-bell-fragment"
    ]
    assert authored_bell.components["attributes"]["authored"] is True
    assert authored_bell.components["attributes"]["resource_id"] == (
        "bell-fragment"
    )
    assert "“入供”二字" in authored_bell.components["identity"][
        "description"
    ]
    assert sum(
        event.event_type is EventType.SCENE_INSTANTIATED
        for event in run.events
    ) == 1


def test_location_hosts_multiple_lazy_persistent_scenes_with_local_time():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    generator = DeterministicSceneGenerator()
    default_id = ensure_scene(run, "back-door", generator)
    inner_id = ensure_scene(
        run,
        "back-door",
        generator,
        scene_key="bell-corridor",
    )

    location = run.state.entities["location:back-door"]
    assert location.kind is EntityKind.LOCATION
    assert location.components["layout"]["scene_ids"] == (
        default_id,
        inner_id,
    )
    assert "哪一枚铃先响" in run.state.entities[
        inner_id
    ].components["identity"]["description"]
    assert run.state.entities["wukong"].components["presence"][
        "scene_id"
    ] == default_id

    enter_scene(
        run,
        "wukong",
        "back-door",
        generator,
        scene_key="bell-corridor",
    )
    run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=run.state.tick,
            event_type=EventType.INCIDENT_OCCURRED,
            actor_id=None,
            observers=(),
            delta=Delta(advance_tick=1, advance_time=3),
            data={
                "elapsed": 3,
                "summary": "夹廊深处传来一次逆风铃响。",
            },
            pre_state_hash=run.state.state_hash(),
            world_hash=run.state.world_hash,
        )
    )
    evolved = evolve_scene_time(run, inner_id)
    assert "逆风铃响" in project_perception(
        run.state, "wukong"
    ).first_person_context
    enter_scene(run, "wukong", "back-door", generator)

    assert evolved is not None
    assert evolved.event_type is EventType.SCENE_EVOLVED
    assert run.state.entities[inner_id].components["attributes"][
        "temporal_revision"
    ] == 1
    assert sum(
        event.event_type is EventType.SCENE_INSTANTIATED
        for event in run.events
    ) == 2
    assert run.replay() == run.state


def test_scene_travel_commits_map_and_presence_together():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    generator = DeterministicSceneGenerator()
    ensure_scene(run, "back-door", generator)

    destination_scene = travel_to_scene(
        run,
        "wukong",
        "ruined-temple",
        generator,
        egress_reason="查验庙内铃声",
    )

    assert destination_scene == "scene:ruined-temple"
    assert run.state.characters["wukong"].location_id == "ruined-temple"
    presence = run.state.entities["wukong"].components["presence"]
    assert presence["location_id"] == "ruined-temple"
    assert presence["scene_id"] == destination_scene
    moved = run.events[-1]
    assert moved.event_type is EventType.MOVED
    assert moved.data["passage_id"] == "door-to-temple"
    assert moved.data["egress_reason"] == "查验庙内铃声"
    assert "scene:" not in moved.data["summary"]
    assert "孙悟空" in moved.data["summary"]
    assert run.replay() == run.state


def test_first_person_intent_creates_request_and_ambient_npc_responds():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    ensure_scene(
        run, "back-door", ModelSceneGenerator(_FakeSceneModel())
    )
    intent_model = _JsonModel(
        {
            "goal": "询问铃声来历",
            "description": "我走到守庙人面前，询问这里的铃声。",
            "referenced_entity_ids": ["scene:back-door:keeper"],
            "speech": "老人家，这铃声从前也这样响吗？",
            "private_reasoning": "他可能知道庙里的旧事。",
            "reply_to_interaction_id": None,
        }
    )
    intent_policy = ModelIntentPolicy(intent_model)
    view = project_perception(run.state, "wukong")
    intent = intent_policy.decide(
        result.compiled.world, run.state, view
    )
    adjudicator = ModelWorldAdjudicator(
        _JsonModel(
            {
                "status": "accepted",
                "public_action": "孙悟空走到守庙人面前询问铃声。",
                "actor_feedback": "守庙人听见了我的问题。",
                "observer_feedback": {},
                "patches": [],
                "scene_boundary": "stay",
                "scene_transition": None,
                "item_custody_updates": [],
                "interaction_requests": [
                    {
                        "recipient_id": "scene:back-door:keeper",
                        "public_prompt": "老人家，这铃声从前也这样响吗？",
                        "private_context": "",
                    }
                ],
            }
        )
    )
    turn = adjudicator.adjudicate(
        result.compiled.world, run.state, intent
    )

    commit_turn(run, intent, turn)
    npc_events = resolve_ambient_npc_requests(run)

    assert len(npc_events) == 1
    assert npc_events[0].actor_id == "scene:back-door:keeper"
    assert "风从庙内向外吹" in npc_events[0].data["spoken_text"]
    assert npc_events[0].data["dramatic_progress"] == "advance"
    behavior = run.state.entities[
        "scene:back-door:keeper"
    ].components[BuiltinComponent.AMBIENT_BEHAVIOR.value]
    assert not behavior["pending_interactions"]
    assert run.replay() == run.state


def test_workflow_capabilities_are_component_driven_not_action_enums():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run, "back-door", DeterministicSceneGenerator()
    )
    intent = CharacterIntent(
        "intent-capabilities",
        "wukong",
        scene_id,
        run.state.entities[scene_id].version,
        "试探同行者",
        "我向白灵提出交换线索，也准备在冲突时自保。",
        ("bailing",),
    )

    capability_ids = {
        item.capability_id
        for item in capabilities_for_intent(run.state, intent)
    }

    assert {"social", "trade", "conflict"}.issubset(capability_ids)


def test_adjudicator_can_request_lazy_transition_from_location_outline():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run, "back-door", DeterministicSceneGenerator()
    )
    intent = CharacterIntent(
        "intent-transition",
        "wukong",
        scene_id,
        run.state.entities[scene_id].version,
        "循铃声深入",
        "我离开门槛，循着庙内铃声进入夹廊。",
        (scene_id,),
    )
    adjudicator = ModelWorldAdjudicator(
        _JsonModel(
            {
                "status": "accepted",
                "public_action": "孙悟空循铃声离开门槛，往庙内深入。",
                "actor_feedback": "我走到了通往夹廊的入口。",
                "observer_feedback": {},
                "patches": [],
                "interaction_requests": [],
                "scene_boundary": "transition",
                "item_custody_updates": [],
                "scene_transition": {
                    "location_id": "back-door",
                    "scene_key": "bell-corridor",
                },
            }
        )
    )

    turn = adjudicator.adjudicate(
        result.compiled.world, run.state, intent
    )

    assert turn.scene_transition is not None
    assert turn.scene_transition.scene_key == "bell-corridor"


def test_full_character_receives_first_person_request_and_reply_clears_it():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run, "back-door", DeterministicSceneGenerator()
    )
    intent = CharacterIntent(
        "intent-request",
        "wukong",
        scene_id,
        run.state.entities[scene_id].version,
        "向白灵求证",
        "我询问白灵是否见过白色粉末。",
        ("bailing",),
        "你见过这种白色粉末吗？",
    )
    request = InteractionRequest(
        "interaction-request",
        "wukong",
        "bailing",
        scene_id,
        "你见过这种白色粉末吗？",
    )
    commit_turn(
        run,
        intent,
        AdjudicatedTurn(
            intent.intent_id,
            intent.actor_id,
            intent.scene_id,
            intent.expected_scene_version,
            "accepted",
            "孙悟空向白灵询问白色粉末。",
            "白灵听见了我的问题。",
            spoken_text=intent.speech,
            interaction_requests=(request,),
        ),
    )

    view = project_perception(run.state, "bailing")

    assert view.pending_interaction_ids == ("interaction-request",)
    assert "你见过这种白色粉末吗" in view.first_person_context
    assert "interaction-request" in view.first_person_context
    assert "刚刚已经发生" in view.first_person_context

    reply = CharacterIntent(
        "intent-reply",
        "bailing",
        scene_id,
        run.state.entities[scene_id].version,
        "回应求证",
        "我回应孙悟空的问题。",
        ("wukong",),
        "见过，但我还不能断定来路。",
        reply_to_interaction_id="interaction-request",
    )
    commit_turn(
        run,
        reply,
        AdjudicatedTurn(
            reply.intent_id,
            reply.actor_id,
            reply.scene_id,
            reply.expected_scene_version,
            "accepted",
            "白灵回应了孙悟空。",
            "我的回应已经说出口。",
            spoken_text=reply.speech,
        ),
    )

    assert not project_perception(
        run.state, "bailing"
    ).pending_interaction_ids


class _RecordingModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self.prompts: list[str] = []
        self.payload = payload

    def complete(
        self, prompt: str, timeout_seconds: float | None = None
    ) -> str:
        del timeout_seconds
        self.prompts.append(prompt)
        return json.dumps(self.payload)


def test_character_turn_prompt_separates_ambition_conduct_and_the_hand():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    ensure_scene(
        run,
        "back-door",
        DeterministicSceneGenerator(),
        entering_actor_ids=("bailing",),
    )
    model = _RecordingModel(
        {
            "goal": "带着听到的离开",
            "description": "我不再追问，离开这里。",
            "dispatch": "act",
            "address_target_id": None,
            "referenced_entity_ids": [],
            "speech": None,
            "private_reasoning": "这一层已经有了。",
            "reply_to_interaction_id": None,
            "decision": "我离开这里。",
        }
    )

    ModelIntentPolicy(model).decide(
        result.compiled.world,
        run.state,
        project_perception(run.state, "bailing"),
    )

    prompt = model.prompts[0]
    assert "志向是整段路的方向" in prompt
    assert "行事方式决定你怎么看" in prompt
    assert "眼前这一手从现场推出来" in prompt
    assert "用离开保住自己" in prompt
    assert "success_conditions" not in prompt
    assert "这一处只能看清这一层" in prompt


def test_a_local_voice_tells_the_character_not_to_ask_again():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run,
        "back-door",
        DeterministicSceneGenerator(),
        entering_actor_ids=("bailing",),
    )
    anchor_id = str(
        run.state.entities[scene_id].components["layout"]["anchor_ids"][0]
    )
    npc_id = "scene:back-door:voice"
    run.log.append(
        WorldEvent(
            sequence=len(run.events),
            tick=run.state.tick,
            event_type=EventType.SCENE_ENTERED,
            actor_id=None,
            observers=(),
            delta=Delta(
                entity_patches=(
                    ComponentPatch(
                        PatchOperation.CREATE_ENTITY,
                        npc_id,
                        entity=EntitySpec(
                            npc_id,
                            EntityKind.NPC,
                            (
                                ComponentValue(
                                    BuiltinComponent.IDENTITY.value,
                                    {"name": "扫庙老人"},
                                ),
                                ComponentValue(
                                    BuiltinComponent.PRESENCE.value,
                                    {
                                        "scene_id": scene_id,
                                        "anchor_id": anchor_id,
                                        "location_id": "back-door",
                                    },
                                ),
                            ),
                        ),
                    ),
                )
            ),
            data={},
            pre_state_hash=run.state.state_hash(),
            world_hash=run.state.world_hash,
        )
    )
    scene = run.state.entities[scene_id]
    spoken = CharacterIntent(
        "local-voice",
        npc_id,
        scene_id,
        scene.version,
        "说出亲眼见到的",
        "我告诉来客门外的泥留不住脚印。",
        ("bailing",),
        "门外泥地一下雨就留不住脚印。",
        dispatch="address",
    )
    commit_turn(
        run,
        spoken,
        AdjudicatedTurn(
            spoken.intent_id,
            npc_id,
            scene_id,
            spoken.expected_scene_version,
            "accepted",
            "扫庙老人说：“门外泥地一下雨就留不住脚印。”",
            "我说完了。",
            spoken_text=spoken.speech,
            dramatic_progress="advance",
        ),
    )

    context = project_perception(run.state, "bailing").first_person_context

    assert "不要再问第二遍" in context
    assert "扫庙老人" in context
    assert f"{npc_id}：" not in context


def test_adjudicator_is_shown_the_next_place_when_leaving():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run, "back-door", DeterministicSceneGenerator()
    )
    model = _RecordingModel({})
    ModelWorldAdjudicator(model).adjudicate(
        result.compiled.world,
        run.state,
        CharacterIntent(
            "leave-door",
            "bailing",
            scene_id,
            run.state.entities[scene_id].version,
            "离开后门",
            "我离开后门。",
            (),
            decision="我离开这里",
            dispatch="act",
        ),
    )

    prompt = model.prompts[0]
    assert "不能把离开写成仍在原地向前迈步" in prompt
    assert "where_i_can_go" in prompt
    assert "forest-path" in prompt
    assert "inner_scenes" in prompt


def test_leaving_can_step_onto_the_next_authored_place():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run, "back-door", DeterministicSceneGenerator()
    )
    intent = CharacterIntent(
        "leave-door",
        "bailing",
        scene_id,
        run.state.entities[scene_id].version,
        "离开后门",
        "我离开后门。",
        (),
        decision="我离开这里",
        dispatch="act",
    )
    accepted = {
        "status": "accepted",
        "public_action": "白灵跨出后门，走向林间。",
        "actor_feedback": "我离开了后门。",
        "observer_feedback": {},
        "patches": [],
        "interaction_requests": [],
        "scene_boundary": "transition",
        "scene_transition": {
            "location_id": "forest-path",
            "scene_key": "default",
        },
        "item_custody_updates": [],
        "dramatic_progress": "decision",
        "scene_outcome": None,
    }

    turn = ModelWorldAdjudicator(_JsonModel(accepted)).adjudicate(
        result.compiled.world, run.state, intent
    )

    assert turn.status == "accepted"
    assert turn.scene_transition is not None
    assert turn.scene_transition.location_id == "forest-path"

    skipped = {
        **accepted,
        "scene_transition": {
            "location_id": "ash-kiln",
            "scene_key": "default",
        },
    }
    rejected = ModelWorldAdjudicator(
        _JsonModel(skipped, skipped)
    ).adjudicate(result.compiled.world, run.state, intent)
    assert rejected.status == "rejected"
