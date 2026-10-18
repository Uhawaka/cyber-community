"""The writing module closes a chapter from content, not from an episode quota."""

import json

from engine.narrative.division import ContentChapterDivider, divide_by_content
from engine.narrative.source import SourceEventView


def _source(
    source_id: str,
    *,
    actor: str,
    kind: str = "turn_resolved",
    utterance: str | None = None,
    chain_id: str | None = None,
    decision: str | None = None,
    location: str = "back-door",
) -> SourceEventView:
    facts = {"status": "accepted", "dramatic_progress": "advance"}
    if chain_id is not None:
        facts["chain_id"] = chain_id
    if decision is not None:
        facts["decision"] = decision
        facts["dramatic_progress"] = "decision"
    return SourceEventView(
        source_event_id=source_id,
        world_time=1.0,
        kind=kind,
        actor_ids=(actor,),
        observer_ids=(actor,),
        location_id=location,
        target_id=None,
        goal="把话说完",
        summary=utterance or decision or "现场有了变化",
        utterance=utterance,
        causal_source_ids=(),
        changes=(),
        unresolved_points=(),
        facts=facts,
    )


def _exchange() -> list[SourceEventView]:
    return [
        _source("world-0001", actor="bailing", utterance="灰先留在我手里。", chain_id="chain-a"),
        _source("world-0002", actor="wukong", utterance="我听见了。", chain_id="chain-a"),
    ]


def test_unfinished_exchange_stays_open():
    assert divide_by_content(_exchange()) is None


def test_content_closes_after_the_chain_that_carries_a_consequence():
    sources = [
        *_exchange(),
        _source(
            "world-0003",
            actor="bailing",
            utterance="那就由我保管。",
            chain_id="chain-a",
            decision="铃片由白灵保管",
        ),
        _source(
            "world-0004",
            actor="wukong",
            utterance="下一处去林间。",
            chain_id="chain-b",
        ),
    ]

    assert divide_by_content(sources) == 3


def test_writer_can_hold_or_choose_a_later_ending():
    sources = [
        *_exchange(),
        _source(
            "world-0003",
            actor="bailing",
            utterance="那就由我保管。",
            chain_id="chain-a",
            decision="铃片由白灵保管",
        ),
        _source("world-0004", actor="bailing", kind="moved"),
    ]

    class _Scripted:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def complete(self, prompt: str, timeout_seconds: float | None = None) -> str:
            del prompt, timeout_seconds
            return json.dumps(self.payload, ensure_ascii=False)

    assert (
        ContentChapterDivider(_Scripted({"decision": "hold"})).close_at(sources)
        is None
    )
    assert ContentChapterDivider(
        _Scripted(
            {"decision": "close", "end_source_event_id": "world-0004"}
        )
    ).close_at(sources) == 4


def test_finished_place_closes_before_the_next_one():
    sources = [
        *_exchange(),
        _source(
            "world-0003",
            actor="bailing",
            utterance="那就由我保管。",
            chain_id="chain-a",
            decision="铃片由白灵保管",
        ),
        _source(
            "world-0004",
            actor="bailing",
            kind="scene_instantiated",
            location="scene:forest-path",
        ),
        _source(
            "world-0005",
            actor="wukong",
            utterance="这边的粉更浓。",
            chain_id="chain-b",
            location="scene:forest-path",
        ),
    ]

    class _Scripted:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def complete(self, prompt: str, timeout_seconds: float | None = None) -> str:
            del prompt, timeout_seconds
            return json.dumps(self.payload, ensure_ascii=False)

    assert ContentChapterDivider().close_at(sources) == 3
    assert (
        ContentChapterDivider(_Scripted({"decision": "hold"})).close_at(sources)
        == 3
    )
    assert (
        ContentChapterDivider(
            _Scripted(
                {"decision": "close", "end_source_event_id": "world-0005"}
            )
        ).close_at(sources)
        == 3
    )
    assert (
        ContentChapterDivider(
            _Scripted(
                {"decision": "close", "end_source_event_id": "world-0003"}
            )
        ).close_at(sources)
        == 3
    )


def test_travel_alone_does_not_become_a_chapter():
    sources = [
        _source("world-0001", actor="wukong", kind="moved"),
        _source(
            "world-0002",
            actor="shenyan",
            kind="scene_entered",
            location="scene:ruined-temple:side-shrine",
        ),
    ]

    assert ContentChapterDivider().close_at(sources) is None


def test_a_subscene_stays_with_its_location():
    sources = [
        *_exchange(),
        _source(
            "world-0003",
            actor="bailing",
            utterance="那就由我保管。",
            chain_id="chain-a",
            decision="铃片由白灵保管",
            location="scene:back-door",
        ),
        _source(
            "world-0004",
            actor="wukong",
            utterance="哪一枚先响？",
            chain_id="chain-b",
            location="scene:back-door:bell-corridor",
        ),
    ]

    class _Hold:
        def complete(self, prompt: str, timeout_seconds: float | None = None) -> str:
            del prompt, timeout_seconds
            return json.dumps({"decision": "hold"})

    assert ContentChapterDivider(_Hold()).close_at(sources) is None


def test_a_turn_at_another_place_ends_the_chapter():
    sources = [
        *_exchange(),
        _source(
            "world-0003",
            actor="bailing",
            utterance="那就由我保管。",
            chain_id="chain-a",
            decision="铃片由白灵保管",
        ),
        _source(
            "world-0004",
            actor="wukong",
            utterance="洼地里的粉更浓。",
            chain_id="chain-b",
            location="scene:forest-path:pine-hollow",
        ),
    ]

    assert ContentChapterDivider().close_at(sources) == 3
