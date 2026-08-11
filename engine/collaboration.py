"""Collaboration engine — characters discover shared interests and work together.

No external intervention. Characters organically notice when their work overlaps,
propose collaboration, and form joint projects. Leadership emerges from who drives.
"""

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JointProject:
    """A collaborative project that characters discovered together."""
    id: str
    topic: str                    # what they're working on
    participants: list[str]       # character names
    proposer: str                 # who initiated
    progress: float = 0.0         # 0.0–1.0
    insight_log: list[dict] = field(default_factory=list)
    created_day: int = 1
    last_worked_day: int = 1
    status: str = "active"        # active | dormant | completed | abandoned
    join_requests: list[str] = field(default_factory=list)  # who wants to join

    def summary(self) -> str:
        emoji = {"active": "🔬", "dormant": "💤", "completed": "✅", "abandoned": "❌"}
        e = emoji.get(self.status, "📋")
        return f"{e} [{self.topic[:40]}] {', '.join(self.participants)} ({self.progress:.0%})"

    def advance(self, amount: float, insight: str = ""):
        self.progress = min(1.0, self.progress + amount)
        if insight:
            self.insight_log.append({
                "day": self.last_worked_day,
                "insight": insight[:300],
            })

    def add_participant(self, name: str):
        if name not in self.participants:
            self.participants.append(name)

    def remove_participant(self, name: str):
        if name in self.participants:
            self.participants.remove(name)
        if len(self.participants) < 2:
            self.status = "abandoned"


class CollaborationBoard:
    """Shared space where collaborative projects live.

    Characters don't need to be told to collaborate — they discover
    overlaps naturally through collisions and deep thinking.
    """

    def __init__(self):
        self.projects: list[JointProject] = []
        self._counter = 0

    # ─── Project Management ─────────────────────────────────

    def create(self, topic: str, proposer: str, participants: list[str],
               day: int = 1) -> JointProject:
        self._counter += 1
        p = JointProject(
            id=f"jp_{self._counter:03d}",
            topic=topic,
            proposer=proposer,
            participants=participants,
            created_day=day,
            last_worked_day=day,
        )
        self.projects.append(p)
        return p

    def get_active(self) -> list[JointProject]:
        return [p for p in self.projects if p.status == "active"]

    def get_by_participant(self, name: str) -> list[JointProject]:
        return [p for p in self.projects if name in p.participants]

    def get_recent(self, n: int = 5) -> list[JointProject]:
        return self.projects[-n:]

    # ─── Overlap Detection ──────────────────────────────────

    def detect_overlap(self, topic_a: str, topic_b: str) -> bool:
        """Simple overlap: shared keywords or character count."""
        if not topic_a or not topic_b:
            return False
        words_a = set(topic_a.lower().split())
        words_b = set(topic_b.lower().split())
        common = words_a & words_b
        # Need at least 2 shared content words (not stop words)
        stop = {"的", "了", "是", "在", "和", "the", "a", "an", "of", "in", "to", "is"}
        content_words = common - stop
        return len(content_words) >= 2

    def find_collaboration_candidates(self, char_name: str, char_topic: str,
                                       all_characters: dict) -> list[str]:
        """Which other characters are working on related things?"""
        candidates = []
        for name, char in all_characters.items():
            if name == char_name:
                continue
            their_topic = char.state.current_focus or ""
            if self.detect_overlap(char_topic, their_topic):
                candidates.append(name)
        return candidates

    # ─── Context for Prompts ────────────────────────────────

    def get_community_context(self) -> str:
        """What collaborative projects are active? For system prompts."""
        active = self.get_active()
        if not active:
            return ""
        lines = ["## 社区协作项目"]
        for p in active[-3:]:
            lines.append(f"  {p.summary()}")
        return "\n".join(lines)

    def get_my_projects(self, char_name: str) -> str:
        """What projects am I involved in?"""
        mine = self.get_by_participant(char_name)
        if not mine:
            return ""
        lines = ["## 你的协作项目"]
        for p in mine:
            others = [n for n in p.participants if n != char_name]
            partner_text = f"与 {', '.join(others)}"
            lines.append(f"  {p.summary()} — {partner_text}")
        return "\n".join(lines)

    def get_recent_insights(self, char_name: str, n: int = 3) -> str:
        """Recent collaborative insights for deep think."""
        insights = []
        for p in self.get_by_participant(char_name):
            for entry in p.insight_log[-2:]:
                insights.append(f"[{p.topic[:30]}] {entry['insight'][:120]}")
        if not insights:
            return ""
        return "协作洞见:\n" + "\n".join(f"  · {i}" for i in insights[-n:])
