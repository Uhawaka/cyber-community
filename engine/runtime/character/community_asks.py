"""别人亲口对你提的请求，以及你回没回。

模型一直在说"你帮我去问一句"（speech_act=request），但这些话在事实层没有落成一个能答复的东西，
所以谁也没法拒绝——拒绝需要一个对象。这里把"最近有人求过你什么"作为可查询的事实交给角色：
只读已提交的对白事件，看到的是原话，不是意图推断。

被拒绝或答应之后，那条请求就从"待回应"里消失（同一件事不再反复问）。
"""

from __future__ import annotations

REQUEST_HORIZON = 24
REQUESTS_LIMIT = 4
REPLY_ACTS = frozenset({"refuse", "promise"})


def _dialogue(event):
    return event.event_type.value == "dialogue"


def requests_to_me(run, actor_id, *, horizon=REQUEST_HORIZON, limit=REQUESTS_LIMIT):
    """(对白事件来源, 对方名字, 对方原话) — 近 horizon Tick 内、还没有被我回过的。"""
    names = {character.id: character.name for character in run.compiled.world.characters}
    answered = set()
    for event in run.events:
        if not _dialogue(event) or event.actor_id != actor_id:
            continue
        replies = event.data.get("replies_to")
        if replies:
            answered.add(str(replies))
    open_asks = []
    for event in reversed(run.events):
        if len(open_asks) >= limit or run.state.tick - event.tick > horizon:
            break
        if not _dialogue(event) or event.actor_id == actor_id:
            continue
        if event.data.get("speech_act") != "request":
            continue
        if event.data.get("listener_id") != actor_id:
            continue
        ref = f"event:{event.sequence}"
        if ref in answered:
            continue
        utterance = str(event.data.get("utterance") or "").strip()
        if not utterance:
            continue
        open_asks.append((ref, names.get(event.actor_id, event.actor_id), utterance[:80]))
    return tuple(open_asks)


def open_request_refs(run, actor_id, *, horizon=REQUEST_HORIZON):
    """可用于 reply_to 的请求来源集合。"""
    return frozenset(ref for ref, _, _ in requests_to_me(run, actor_id, horizon=horizon, limit=REQUESTS_LIMIT))


def request_by_ref(run, ref, actor_id):
    """按来源取回"对方求你的那句话"；不属于本人的请求返回 None。"""
    sequence = ref.split(":", 1)[-1]
    if not sequence.isdigit():
        return None
    for event in run.events:
        if event.sequence != int(sequence) or not _dialogue(event):
            continue
        if event.data.get("speech_act") != "request" or event.data.get("listener_id") != actor_id:
            return None
        if run.state.tick - event.tick > REQUEST_HORIZON:
            return None
        names = {character.id: character.name for character in run.compiled.world.characters}
        return (event.actor_id, names.get(event.actor_id, event.actor_id),
                str(event.data.get("utterance") or "")[:80])
    return None
