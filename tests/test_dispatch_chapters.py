"""Demand-driven dialogue and chapters held for a reader arc."""

from dataclasses import replace
from pathlib import Path

from engine.adapters.literary_pipeline_renderer import LiteraryPipelineRenderer
from engine.contracts import AdjudicatedTurn, CharacterIntent, SceneTransition
from engine.runtime.autonomous_director import run_incident_scheduler
from engine.runtime.kernel.events import EventType
from engine.runtime.scene.dispatch import local_turn, resolve_dispatched_intent
from engine.runtime.scene.turns import commit_turn
from engine.narrative.curation import (
    CurationPolicy,
    curate_episode_windows,
    is_reader_visible_source,
)
from engine.narrative.digest import build_narrative_digest
from engine.narrative.exchange import _title, assemble_committed_exchange
from engine.narrative.planning import (
    NarrativeRenderRequest,
    NarrativeStyleProfile,
    build_narrative_plan,
)
from engine.narrative.source import SourceEventView
from engine.narrative.validation import (
    literary_quality_issues,
    rendered_fact_issues,
)
from engine.runtime.kernel.lifecycle import create_run
from engine.runtime.scene import (
    DeterministicSceneGenerator,
    ensure_scene,
    run_scene_turns,
)
from engine.runtime.scene.lifecycle import travel_to_scene
from engine.runtime.scene.npc import _response as npc_response
from engine.runtime.scene.perception import project_perception
from engine.world.package_compiler import compile_package

ROOT = Path(__file__).parents[1]


class _AddressPolicy:
    def decide(self, world, state, perception):
        del world, state
        if perception.actor_id == "bailing":
            return CharacterIntent(
                "bailing-address",
                "bailing",
                perception.scene_id,
                perception.scene_version,
                "把灰的去留说清楚",
                "我当面告诉悟空，灰不能交出去。",
                ("wukong",),
                "灰不能交给别人。",
                dispatch="address",
            )
        return CharacterIntent(
            "wukong-reply",
            perception.actor_id,
            perception.scene_id,
            perception.scene_version,
            "听完再决定",
            "我先把这句话接住。",
            ("bailing",),
            "我听见了，灰先留在你手里。",
            dispatch="think",
        )


class _ForbiddenAdjudicator:
    def adjudicate(self, world, state, intent):
        del world, state, intent
        raise AssertionError("dialogue must not load the environment")


def _source(
    source_id: str,
    *,
    progress: str = "advance",
    outcome: str | None = None,
    dispatch: str = "address",
    utterance: str | None = "我说完了。",
    decision: str | None = None,
    chain_id: str | None = None,
) -> SourceEventView:
    facts = {
        "status": "accepted",
        "dramatic_progress": progress,
        "dispatch": dispatch,
    }
    if outcome is not None:
        facts["scene_outcome"] = outcome
    if decision is not None:
        facts["decision"] = decision
    if chain_id is not None:
        facts["chain_id"] = chain_id
    spoken = utterance or "我说完了。"
    return SourceEventView(
        source_event_id=source_id,
        world_time=float(source_id.rsplit("-", 1)[-1]),
        kind="turn_resolved",
        actor_ids=("bailing",),
        observer_ids=("bailing",),
        location_id="back-door",
        target_id=None,
        goal="把话说完",
        summary=f"白灵说：“{spoken}”",
        utterance=utterance,
        causal_source_ids=(),
        changes=(),
        unresolved_points=(),
        facts=facts,
    )


def test_address_loads_the_listener_without_environment_adjudication():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    ensure_scene(
        run,
        "back-door",
        DeterministicSceneGenerator(),
        entering_actor_ids=("bailing", "wukong"),
    )
    run.intent_policy = _AddressPolicy()
    run.world_adjudicator = _ForbiddenAdjudicator()

    usage = run_scene_turns(
        run, ("bailing", "wukong"), turn_budget=1
    )

    spoken = [
        event.data.get("spoken_text")
        for event in run.events
        if event.data.get("spoken_text")
    ]
    assert usage.character_turns == 1
    assert spoken == ["灰不能交给别人。", "我听见了，灰先留在你手里。"]
    assert any(
        event.data.get("public_action") == "白灵说：“灰不能交给别人。”"
        for event in run.events
    )
    assert run.replay() == run.state


def test_thinking_about_an_object_does_not_call_the_environment():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    ensure_scene(
        run,
        "back-door",
        DeterministicSceneGenerator(),
        entering_actor_ids=("bailing",),
    )
    scene_id = run.state.entities["bailing"].components["presence"]["scene_id"]
    scene = run.state.entities[scene_id]
    anchor_id = scene.components["layout"]["anchor_ids"][0]
    run.world_adjudicator = _ForbiddenAdjudicator()

    resolve_dispatched_intent(
        run,
        CharacterIntent(
            "think-anchor",
            "bailing",
            scene_id,
            scene.version,
            "掂量眼前的东西",
            "我在心里看了看这处物件，还没有动手。",
            (anchor_id,),
            dispatch="think",
        ),
        intent_policy=object(),
        adjudicator=_ForbiddenAdjudicator(),
        generator=DeterministicSceneGenerator(),
        depth=0,
        spoken=set(),
    )

    turn = next(
        event
        for event in reversed(run.events)
        if event.event_type is EventType.TURN_RESOLVED
        and event.data.get("intent_id") == "think-anchor"
    )
    assert turn.data["dispatch"] == "think"
    assert not turn.data.get("spoken_text")
    assert turn.rule_basis == (
        "character dispatch committed without environment adjudication",
    )


def test_repeated_speech_builds_scene_pressure():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    ensure_scene(
        run,
        "back-door",
        DeterministicSceneGenerator(),
        entering_actor_ids=("bailing",),
    )
    scene_id = run.state.entities["bailing"].components["presence"]["scene_id"]
    line = "铃片上的粉和林间那层是同一种颜色，先别交出去。"
    for index in range(4):
        scene = run.state.entities[scene_id]
        intent = CharacterIntent(
            f"repeat-{index}",
            "bailing",
            scene_id,
            scene.version,
            "把同一句话再说一遍",
            "我换个说法，还是在问这层粉。",
            (scene_id,),
            line,
            dispatch="address",
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
                f"白灵说：“{line}”",
                "我说完了。",
                spoken_text=line,
                dramatic_progress="advance",
            ),
        )

    dramatic = run.state.entities[scene_id].components["dramatic"]
    assert dramatic["pressure_level"] >= 1
    assert dramatic["stagnant_turns"] >= 3
    assert run.events[-1].data["dramatic_progress"] == "none"


def test_reasking_the_same_person_is_not_progress():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    ensure_scene(
        run,
        "back-door",
        DeterministicSceneGenerator(),
        entering_actor_ids=("bailing", "wukong"),
    )
    scene_id = run.state.entities["bailing"].components["presence"]["scene_id"]
    lines = (
        "悟空，你看这印是登记号，还是追踪记？",
        "悟空，别换个说法拖着，给一句：号，还是记号？",
        "悟空，看完了就说，我们好定谁保管。",
        "悟空，雨要冲没了，你到底认不认这印？",
    )
    for index, line in enumerate(lines):
        scene = run.state.entities[scene_id]
        intent = CharacterIntent(
            f"ask-{index}",
            "bailing",
            scene_id,
            scene.version,
            "让悟空把判断说出来",
            "我换个说法，还是在等他的判断。",
            ("wukong",),
            line,
            dispatch="address",
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
                f"白灵说：“{line}”",
                "我说完了。",
                spoken_text=line,
                dramatic_progress="advance",
            ),
        )

    dramatic = run.state.entities[scene_id].components["dramatic"]
    assert dramatic["awaiting_actor_id"] == "wukong"
    assert dramatic["pressure_level"] >= 1
    assert run.events[-1].data["dramatic_progress"] == "none"


def test_open_question_blocks_leaving():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    ensure_scene(
        run,
        "back-door",
        DeterministicSceneGenerator(),
        entering_actor_ids=("bailing", "wukong"),
    )
    scene_id = run.state.entities["bailing"].components["presence"]["scene_id"]
    scene = run.state.entities[scene_id]
    ask = CharacterIntent(
        "ask-wukong",
        "bailing",
        scene_id,
        scene.version,
        "等悟空判断",
        "我先问清这印。",
        ("wukong",),
        "悟空，这印是号还是记号？",
        dispatch="address",
    )
    commit_turn(
        run,
        ask,
        AdjudicatedTurn(
            ask.intent_id,
            ask.actor_id,
            ask.scene_id,
            ask.expected_scene_version,
            "accepted",
            "白灵说：“悟空，这印是号还是记号？”",
            "我在等回答。",
            spoken_text=ask.speech,
            dramatic_progress="advance",
        ),
    )

    class _Leaving:
        def adjudicate(self, world, state, intent):
            del world, state
            return AdjudicatedTurn(
                intent.intent_id,
                intent.actor_id,
                intent.scene_id,
                intent.expected_scene_version,
                "accepted",
                "白灵走向林间。",
                "我想离开。",
                scene_transition=SceneTransition("forest-path", "default"),
                dramatic_progress="advance",
            )

    scene = run.state.entities[scene_id]
    resolve_dispatched_intent(
        run,
        CharacterIntent(
            "leave-early",
            "bailing",
            scene_id,
            scene.version,
            "先离开",
            "我走向林间。",
            (scene_id,),
            dispatch="act",
        ),
        intent_policy=object(),
        adjudicator=_Leaving(),
        generator=DeterministicSceneGenerator(),
        depth=0,
        spoken=set(),
    )

    assert run.state.characters["bailing"].location_id == "back-door"
    assert not any(
        event.event_type is EventType.MOVED for event in run.events
    )


def test_same_actor_restating_a_decision_stays_off_the_page():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run,
        "back-door",
        DeterministicSceneGenerator(),
        entering_actor_ids=("bailing", "traveler"),
    )
    speech = "铃片先由我收着，不离开众人视线，验完再定去向。"
    for index in (1, 2):
        view = project_perception(run.state, "bailing")
        intent = CharacterIntent(
            f"decision-{index}",
            "bailing",
            scene_id,
            view.scene_version,
            "约定保管",
            "我把保管说清楚。",
            (scene_id,),
            speech,
            decision="铃片由白灵在众人视线内保管。",
        )
        commit_turn(
            run,
            intent,
            AdjudicatedTurn(
                intent.intent_id,
                "bailing",
                scene_id,
                intent.expected_scene_version,
                "accepted",
                f"白灵说：“{speech}”",
                "我的决定已经公开。",
                spoken_text=speech,
                dramatic_progress="decision",
            ),
        )

    assert run.events[-1].data["restated"] is True
    assert run.events[-1].data["dramatic_progress"] == "none"


def test_chapter_title_stops_at_the_question():
    assert _title("婆婆，这排铃里哪一枚最先响？新绳结那枚是谁系的？") == (
        "婆婆，这排铃里哪一枚最先响"
    )


def test_npc_does_not_answer_from_a_grammatical_overlap():
    reply, disclosed = npc_response(
        {"known_facts": ("残火角落的松枝是前一个躲雨的人留下的。",)},
        "那两处空绳位，是铃自己掉的，还是被人取走的？",
    )

    assert disclosed is False
    assert "松枝" not in reply


def test_npc_does_not_invent_another_persons_history():
    reply, disclosed = npc_response(
        {
            "known_facts": (
                "搁在木托板上的断裂铜铃片是她今早从廊口积水里捡回来的。",
                "靠风隙那三枚最近被重新系过绳结。",
            )
        },
        "这铃片内侧的白粉，您见过没有？它是从哪处捡来的？",
        ("白灵", "沈砚", "孙悟空"),
    )

    assert disclosed is False
    assert "她" not in reply
    assert "捡回来" not in reply


def test_another_destination_waits_until_the_arrival_decides(monkeypatch):
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    scene_id = ensure_scene(
        run,
        "back-door",
        DeterministicSceneGenerator(),
        entering_actor_ids=("bailing", "traveler", "wukong"),
    )
    for actor_id in ("bailing", "traveler", "wukong"):
        view = project_perception(run.state, actor_id)
        intent = CharacterIntent(
            f"decision-{actor_id}",
            actor_id,
            scene_id,
            view.scene_version,
            "作出共同去向决定",
            "我公开承担自己的责任。",
            (scene_id,),
            decision=f"{actor_id}同意离开。",
        )
        commit_turn(
            run,
            intent,
            AdjudicatedTurn(
                intent.intent_id,
                actor_id,
                scene_id,
                intent.expected_scene_version,
                "accepted",
                f"{actor_id}公开决定离开。",
                "我的决定已经公开。",
                dramatic_progress="advance",
            ),
        )
    travel_to_scene(
        run, "wukong", "ruined-temple", DeterministicSceneGenerator()
    )
    monkeypatch.setattr(
        "engine.runtime.scene.executor.deterministic_egress",
        lambda run, actor_id, candidates: SceneTransition(
            "forest-path", "default"
        ),
    )

    run_scene_turns(
        run, ("bailing", "traveler", "wukong"), turn_budget=3
    )

    assert run.state.characters["bailing"].location_id == "back-door"
    assert run.state.characters["traveler"].location_id == "back-door"
    assert run.state.characters["wukong"].location_id == "ruined-temple"


def test_placed_incident_waits_for_someone_at_that_place():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=17)
    away = {
        actor_id: replace(character, location_id="forest-path")
        for actor_id, character in run.state.characters.items()
    }
    run.log._state = replace(run.state, tick=3, characters=away)
    assert run_incident_scheduler(run, 1) is None

    home = dict(away)
    home["bailing"] = replace(home["bailing"], location_id="back-door")
    run.log._state = replace(run.state, characters=home)
    event = run_incident_scheduler(run, 1)

    assert event is not None
    assert event.data["location_id"] == "scene:back-door"
    assert "逆风" in event.data["summary"]


def test_resolved_beat_does_not_close_a_short_chapter():
    events = [
        _source("world-0001", progress="resolved", outcome="当场约定"),
        _source("world-0002"),
        _source("world-0003"),
    ]

    windows = curate_episode_windows(
        events,
        cursor=0,
        audience_id="omniscient",
        omniscient=True,
        policy=CurationPolicy(min_arc_events=4, min_narrative_events=1),
    )

    assert windows == ()
    assert not is_reader_visible_source(
        _source(
            "world-0004",
            dispatch="think",
            utterance="我守在火边，等她说出结果。",
            progress="none",
        )
    )
    assert is_reader_visible_source(
        _source(
            "world-0006",
            dispatch="think",
            utterance="铃片先由我收着。",
            decision="铃片先由白灵收着",
        )
    )
    hidden = _source(
        "world-0007",
        dispatch="think",
        utterance="我站在夹廊入口，等蜡封落定。",
        progress="none",
    )
    hidden = replace(
        hidden, facts={**dict(hidden.facts), "decision": "None"}
    )
    assert not is_reader_visible_source(hidden)
    held = curate_episode_windows(
        [*events, _source("world-0004")],
        cursor=0,
        audience_id="omniscient",
        omniscient=True,
        policy=CurationPolicy(min_arc_events=4, min_narrative_events=1),
        release_tail=False,
    )
    assert held == ()
    capped = [
        _source(f"world-{index:04d}", chain_id="chain-a")
        for index in range(1, 5)
    ]
    capped.append(_source("world-0005", chain_id="chain-b"))
    closed = curate_episode_windows(
        capped,
        cursor=0,
        audience_id="omniscient",
        omniscient=True,
        policy=CurationPolicy(
            max_events=4, min_arc_events=4, min_narrative_events=1
        ),
        release_tail=False,
    )
    assert len(closed) == 1
    assert len(closed[0].sources) == 4
    linked = [
        _source("world-0001", chain_id="chain-a"),
        _source("world-0002", chain_id="chain-a"),
        _source("world-0003", chain_id="chain-b"),
    ]
    kept = curate_episode_windows(
        linked,
        cursor=0,
        audience_id="omniscient",
        omniscient=True,
        policy=CurationPolicy(max_events=1, min_narrative_events=1),
        release_tail=False,
    )
    assert len(kept) == 1
    assert [item.source_event_id for item in kept[0].sources] == [
        "world-0001",
        "world-0002",
    ]


def test_committed_exchange_is_the_chapter_without_a_second_draft():
    events = (
        _source("world-0001", utterance="灰不能交给别人。"),
        SourceEventView(
            source_event_id="world-0002",
            world_time=2.0,
            kind="turn_resolved",
            actor_ids=("wukong",),
            observer_ids=("wukong", "bailing"),
            location_id="back-door",
            target_id="bailing",
            goal="接住这句话",
            summary="悟空说：“我听见了，灰先留在你手里。”",
            utterance="我听见了，灰先留在你手里。",
            causal_source_ids=(),
            changes=(),
            unresolved_points=(),
            facts={"dispatch": "address", "status": "accepted"},
        ),
    )
    digest = build_narrative_digest(events)
    request = NarrativeRenderRequest(
        digest, build_narrative_plan(digest), NarrativeStyleProfile()
    )

    class _UnusedModel:
        def complete(self, prompt: str, timeout_seconds: float | None = None) -> str:
            del prompt, timeout_seconds
            raise AssertionError("committed exchange must not call the model")

    rendered = LiteraryPipelineRenderer(_UnusedModel()).render(request)

    assert "灰不能交给别人。" in rendered.body
    assert "我听见了，灰先留在你手里。" in rendered.body
    assert rendered_fact_issues(rendered, request) == ()
    assert literary_quality_issues(rendered, request) == ()
    assert assemble_committed_exchange(request) == rendered


def test_committed_exchange_prints_the_spoken_line():
    events = (
        _source("world-0001", utterance="灰不能交给别人。"),
        SourceEventView(
            source_event_id="world-0002",
            world_time=2.0,
            kind="turn_resolved",
            actor_ids=("sorter",),
            observer_ids=("sorter",),
            location_id="ash-kiln",
            target_id="wukong",
            goal="履行职责",
            summary="老分拣工回应了wukong。",
            utterance="石槽按灵性、骨重和来处编号。",
            causal_source_ids=(),
            changes=(),
            unresolved_points=(),
            facts={"dispatch": "address", "status": "accepted"},
        ),
        SourceEventView(
            source_event_id="world-0003",
            world_time=3.0,
            kind="scene_instantiated",
            actor_ids=(),
            observer_ids=(),
            location_id="ash-kiln",
            target_id=None,
            goal=None,
            summary="账目所指标号对应的废窑入口；窑火名义上已熄。",
            utterance=None,
            causal_source_ids=(),
            changes=(),
            unresolved_points=(),
            facts={},
        ),
    )
    digest = build_narrative_digest(events)
    request = NarrativeRenderRequest(
        digest, build_narrative_plan(digest), NarrativeStyleProfile()
    )

    rendered = assemble_committed_exchange(request)

    assert rendered is not None
    assert "石槽按灵性、骨重和来处编号。" in rendered.body
    assert "回应了wukong" not in rendered.body
    assert "窑火名义上已熄" not in rendered.body


class _StayAdjudicator:
    def adjudicate(self, world, state, intent):
        del world, state
        return AdjudicatedTurn(
            intent.intent_id,
            intent.actor_id,
            intent.scene_id,
            intent.expected_scene_version,
            "accepted",
            "孙悟空沿这一侧离开小路。",
            "路已经选定。",
            dramatic_progress="decision",
        )


def test_a_spent_layer_turns_leaving_into_the_next_place():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=83)
    generator = DeterministicSceneGenerator()
    ensure_scene(
        run,
        "back-door",
        generator,
        entering_actor_ids=("wukong", "traveler"),
    )
    scene_id = travel_to_scene(run, "wukong", "forest-path", generator)
    travel_to_scene(run, "traveler", "forest-path", generator)
    spoken = CharacterIntent(
        "forest-answer",
        "traveler",
        scene_id,
        run.state.entities[scene_id].version,
        "说出这一侧还看得见",
        "我告诉悟空粉靠界石这一侧还在。",
        ("wukong",),
        "粉靠界石这一侧还在。",
        dispatch="address",
    )
    commit_turn(run, spoken, local_turn(run, spoken))
    leaving = CharacterIntent(
        "forest-leave",
        "wukong",
        scene_id,
        run.state.entities[scene_id].version,
        "沿这一侧离开小路",
        "我不再比对，沿这一侧离开小路。",
        ("traveler",),
        decision="沿粉还在的一侧离开小路",
        dispatch="act",
    )

    resolve_dispatched_intent(
        run,
        leaving,
        intent_policy=_AddressPolicy(),
        adjudicator=_StayAdjudicator(),
        generator=generator,
        depth=0,
        spoken=set(),
    )

    assert run.state.characters["wukong"].location_id == "levy-outpost"


def test_leaving_before_anyone_answers_stays_in_place():
    result = compile_package(ROOT / "worlds" / "black-pine-ridge")
    assert result.compiled is not None
    run = create_run(result.compiled, seed=83)
    scene_id = ensure_scene(run, "back-door", DeterministicSceneGenerator())
    leaving = CharacterIntent(
        "door-leave",
        "wukong",
        scene_id,
        run.state.entities[scene_id].version,
        "离开后门",
        "我现在离开后门。",
        (),
        decision="我离开后门",
        dispatch="act",
    )

    resolve_dispatched_intent(
        run,
        leaving,
        intent_policy=_AddressPolicy(),
        adjudicator=_StayAdjudicator(),
        generator=DeterministicSceneGenerator(),
        depth=0,
        spoken=set(),
    )

    assert run.state.characters["wukong"].location_id == "back-door"
