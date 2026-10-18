from pathlib import Path

from engine.application import (
    create_run,
    publish_due_episode,
    rerender_episode,
    run_ticks,
)
from engine.narrative import (
    DeliveryPolicy,
    PresentationStore,
    RenderedNarrative,
)
from engine.world.package_compiler import compile_package


ROOT = Path(__file__).parents[1]


def _run():
    result = compile_package(ROOT / "worlds" / "echo-quay")
    assert result.ok and result.compiled is not None
    run = create_run(result.compiled, seed=17)
    run_ticks(run, 8)
    return run


def test_run_ticks_publish_rerender_preserves_autonomous_history():
    run = _run()
    events_before = run.events
    state_before = run.state
    history_before = run.history_hash()
    store = PresentationStore()

    published = publish_due_episode(
        run,
        store,
        DeliveryPolicy(unpresented_event_threshold=2),
    )

    assert published is not None
    assert published.source_event_ids == published.digest.source_event_ids
    assert published.world_time_start == published.digest.world_time_start
    assert published.world_time_end == published.digest.world_time_end
    assert published.render_version == 1
    episode = store.get_episode(published.episode_id)
    assert episode.source_event_ids == published.source_event_ids
    assert episode.render_version == 1
    assert "[world-" not in published.rendered.body
    assert "environment_decayed" not in published.rendered.body
    assert run.events == events_before
    assert run.state == state_before
    assert run.history_hash() == history_before

    cursor_before = store.cursor
    rerendered = rerender_episode(store, published.presentation_id)

    assert rerendered.render_version == 2
    assert rerendered.source_event_ids == published.source_event_ids
    assert store.get_episode(published.episode_id).render_version == 2
    assert store.cursor == cursor_before
    assert run.events == events_before
    assert run.state == state_before
    assert run.history_hash() == history_before


class _InventingRenderer:
    def render(self, digest):
        return RenderedNarrative(
            "伪造来源",
            '[world-999999] lin：“这句话从未发生。”',
        )


def test_invalid_quotes_and_source_ids_fall_back_deterministically():
    run = _run()
    store = PresentationStore()

    published = publish_due_episode(
        run,
        store,
        DeliveryPolicy(unpresented_event_threshold=2),
        renderer=_InventingRenderer(),
    )

    assert published is not None
    assert "world-999999" not in published.rendered.body
    assert "这句话从未发生。" not in published.rendered.body
    assert published.source_event_ids == published.digest.source_event_ids
    assert published.rendered.paragraphs
    assert {
        source_id
        for paragraph in published.rendered.paragraphs
        for source_id in paragraph.source_event_ids
    }.issubset(set(published.digest.source_event_ids))
