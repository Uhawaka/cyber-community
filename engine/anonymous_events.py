"""Anonymous event injection.

Users intervene without revealing themselves as creators.
Events appear as letters, coincidences, environment shifts, or rumors —
characters never learn the true source (DESIGN §2.1.3 / §3.8).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional


FRAMINGS = {
    "letter": [
        "一封来历不明的信出现在{place}，内容大致是：{content}",
        "{place}的桌上多了一封匿名信，字迹陌生：{content}",
    ],
    "coincidence": [
        "有人在{place}偶然发现了一条笔记：{content}",
        "路过{place}时，视线扫到一行不知谁留下的字：{content}",
    ],
    "environment": [
        "{place}起了细微变化——{content}",
        "空气里多了一丝异常：{place}似乎在提示「{content}」",
    ],
    "rumor": [
        "社区里开始流传一则消息：{content}",
        "有人低声说起一件事：{content}",
    ],
    "discovery": [
        "在{place}的角落里，有人注意到：{content}",
        "{place}里多了一份来历不明的材料：{content}",
    ],
}

PLACES = ["公共区", "书房门口", "知识库旁", "白板边", "休息园", "档案架旁"]


@dataclass
class AnonymousEvent:
    """A user-injected event, framed as a natural occurrence."""

    raw: str
    framed: str
    framing_type: str
    target: Optional[str] = None  # None = whole community
    day_injected: int = 1
    time_injected: float = 0.0
    perceived_by: set = field(default_factory=set)

    def for_character(self, name: str) -> Optional[str]:
        """Return framed text if this character should perceive it."""
        if self.target and self.target != name:
            return None
        if name in self.perceived_by:
            return None
        return self.framed

    def mark_perceived(self, name: str):
        self.perceived_by.add(name)


def frame_message(
    content: str,
    framing: Optional[str] = None,
    place: Optional[str] = None,
) -> tuple[str, str]:
    """Wrap raw user content in a natural framing.

    Returns (framing_type, framed_text).
    """
    content = (content or "").strip()
    if not content:
        raise ValueError("匿名事件内容不能为空")

    framing_type = framing if framing in FRAMINGS else random.choice(list(FRAMINGS))
    template = random.choice(FRAMINGS[framing_type])
    place = place or random.choice(PLACES)
    framed = template.format(place=place, content=content)
    return framing_type, framed


class AnonymousEventBoard:
    """Queue of pending anonymous events waiting to be perceived."""

    def __init__(self):
        self.events: list[AnonymousEvent] = []

    def inject(
        self,
        content: str,
        day: int = 1,
        time: float = 0.0,
        target: Optional[str] = None,
        framing: Optional[str] = None,
    ) -> AnonymousEvent:
        framing_type, framed = frame_message(content, framing=framing)
        event = AnonymousEvent(
            raw=content,
            framed=framed,
            framing_type=framing_type,
            target=target,
            day_injected=day,
            time_injected=time,
        )
        self.events.append(event)
        return event

    def pending_for(self, char_name: str) -> list[AnonymousEvent]:
        return [e for e in self.events if e.for_character(char_name)]

    def consume_for(self, char_name: str) -> list[str]:
        """Return framed texts and mark them perceived."""
        texts = []
        for event in self.pending_for(char_name):
            texts.append(event.framed)
            event.mark_perceived(char_name)
        return texts

    def recent(self, count: int = 5) -> list[AnonymousEvent]:
        return self.events[-count:]
