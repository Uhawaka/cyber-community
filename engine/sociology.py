"""Sociology Engine v2 — community as a social system.

Not just individuals + interactions. A community is:
  1. Roles — not jobs, but social positions that shift
  2. Exchanges — gifts, debts, favors that create bonds
  3. Information flow — rumors, gossip, informal awareness
  4. Rituals — shared experiences that generate emotional energy
  5. Status games — subtle competition for recognition
  6. Front/back stage — different selves in different contexts

This engine tracks the invisible web that makes a community feel alive.
"""

import random
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# 1. Social Roles
# ═══════════════════════════════════════════════════════════════

SOCIAL_ROLES = {
    "elder":       "被默认尊重的长者——不一定是年龄，是积累的信任",
    "newcomer":    "新加入的——还在被观察，需要证明自己",
    "bridge":      "连接者——唯一能和所有人有效沟通的人",
    "challenger":  "质疑者——任何新想法必须先过ta这关",
    "nurturer":    "照顾者——注意谁情绪低落，谁需要被拉一把",
    "innovator":   "创新者——不断抛出疯狂想法，其中10%是真的",
    "stabilizer":  "稳定者——在混乱中保持冷静，被依赖的人",
    "outsider":    "局外人——视角不同，不参与内部竞争",
}


# ═══════════════════════════════════════════════════════════════
# 2. Gift Economy
# ═══════════════════════════════════════════════════════════════

@dataclass
class SocialLedger:
    """Tracks gifts, debts, and favors between community members."""

    debts: dict = field(default_factory=dict)     # who → {owes_whom: amount}
    gifts_given: dict = field(default_factory=dict)  # who → [{to, what, when}]
    trust_scores: dict = field(default_factory=dict)  # who → {whom: 0-1}

    def record_gift(self, giver: str, receiver: str, what: str, value: float = 1.0):
        """Someone did something for someone else."""
        # Track the gift
        self.gifts_given.setdefault(giver, []).append(
            {"to": receiver, "what": what, "value": value})

        # Create a soft debt (not enforced, but felt)
        self.debts.setdefault(receiver, {})
        self.debts[receiver][giver] = self.debts[receiver].get(giver, 0) + value

        # Increase trust
        self.trust_scores.setdefault(receiver, {})
        self.trust_scores[receiver][giver] = min(1.0,
            self.trust_scores[receiver].get(giver, 0.3) + value * 0.15)

    def get_balance(self, name: str) -> dict:
        """Who owes whom?"""
        return self.debts.get(name, {})

    def get_most_trusted(self, name: str) -> list:
        """Who does this person trust most?"""
        scores = self.trust_scores.get(name, {})
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ═══════════════════════════════════════════════════════════════
# 3. Information Flow (Rumors, Gossip, Informal Awareness)
# ═══════════════════════════════════════════════════════════════

@dataclass
class Rumor:
    """Informal information flowing through the community."""

    content: str
    source: str          # who started it (or "observed")
    spread_to: list = field(default_factory=list)
    accuracy: float = 0.8  # how true is it?
    day: int = 1


class Grapevine:
    """Informal information network."""

    def __init__(self):
        self.rumors: list[Rumor] = []

    def spread(self, content: str, source: str, day: int,
               characters: list, accuracy: float = 0.8):
        """A piece of information starts spreading."""
        rumor = Rumor(content=content, source=source, accuracy=accuracy, day=day)

        # Spreads to 1-3 random characters
        targets = [c for c in characters if c != source]
        spread_count = random.randint(1, min(3, len(targets)))
        rumor.spread_to = random.sample(targets, spread_count)

        self.rumors.append(rumor)
        if len(self.rumors) > 20:
            self.rumors = self.rumors[-20:]

    def what_does_X_know_about_Y(self, listener: str, subject: str) -> str:
        """What informal information does X have about Y?"""
        relevant = [r for r in self.rumors
                    if listener in r.spread_to and
                    (subject in r.content or r.source == subject)]
        if not relevant:
            return ""
        latest = relevant[-1]
        confidence = "听说" if latest.accuracy < 0.9 else "知道"
        return f"{confidence}: {latest.content[:80]}"

    def get_buzz(self, listener: str) -> list:
        """What's the latest buzz this person has heard?"""
        heard = [r for r in self.rumors[-5:] if listener in r.spread_to]
        return [f"{r.content[:60]}" for r in heard]


# ═══════════════════════════════════════════════════════════════
# 4. Front Stage / Back Stage (Dramaturgy)
# ═══════════════════════════════════════════════════════════════

@dataclass
class StagePresence:
    """How a character presents themselves in different contexts."""

    name: str
    in_public: str       # how they act when others are watching
    in_private: str       # how they act when alone or with trusted others
    tells: list = field(default_factory=list)  # behaviors that reveal the private self

    def current_presentation(self, context: str) -> str:
        """Which self is showing right now?"""
        if context in ("commons", "gathering", "seminar"):
            return self.in_public
        return self.in_private


# ═══════════════════════════════════════════════════════════════
# 5. Community Rituals
# ═══════════════════════════════════════════════════════════════

@dataclass
class Ritual:
    """A recurring community practice that generates emotional energy."""

    name: str
    description: str
    frequency: str       # daily | weekly | spontaneous
    participants: list = field(default_factory=list)
    emotional_charge: float = 0.3  # how much it bonds participants
    last_performed: int = 0


# ═══════════════════════════════════════════════════════════════
# Unified Community Engine
# ═══════════════════════════════════════════════════════════════

class CommunityEngine:
    """The full social system — roles, exchanges, information, rituals."""

    def __init__(self, characters: dict):
        self.characters = characters
        self.names = list(characters.keys())

        # Roles
        self.roles: dict[str, str] = {}           # name → primary role
        self.role_history: dict[str, list] = {}    # name → [(role, day), ...]

        # Gift economy
        self.ledger = SocialLedger()

        # Information flow
        self.grapevine = Grapevine()

        # Stage presence
        self.stage: dict[str, StagePresence] = {}

        # Rituals
        self.rituals: list[Ritual] = []

        # Status (simple tracking)
        self.status: dict[str, float] = {n: 50.0 for n in self.names}

        # Activity tracking
        self.recent_activity: dict[str, list] = {n: [] for n in self.names}

        self._init_roles()
        self._init_stage()
        self._init_rituals()

    def _init_roles(self):
        """Assign initial social roles based on character traits."""
        # Default roles — can shift over time
        defaults = {
            "Elias": "challenger",   # questions everything
            "Yuki": "elder",          # respected for depth
            "Pavel": "bridge",        # connects everyone
            "Hayashi": "nurturer",    # cares about people
        }
        for name, role in defaults.items():
            if name in self.names:
                self.roles[name] = role
                self.role_history[name] = [(role, 0)]

        # Newcomers get "newcomer" if not in defaults
        for name in self.names:
            if name not in self.roles:
                self.roles[name] = "newcomer"

    def _init_stage(self):
        """Define how characters present themselves."""
        presences = {
            "Elias": StagePresence("Elias",
                in_public="严肃、精确、不耐烦——用数据和公式说话，不闲聊",
                in_private="焦虑、自我怀疑——反复检查计算结果，会在草稿纸上写'我是不是在浪费时间'",
                tells=["独自一人时会自言自语", "深夜时会盯着同一个数字看很久"]),
            "Yuki": StagePresence("Yuki",
                in_public="优雅、抽象、偶尔刻薄——用最少的词表达最深的洞察",
                in_private="比表面更孤独——偶尔会画一些没有数学意义的箭头，只是觉得好看",
                tells=["在没人注意时会在纸上画重复的几何图案"]),
            "Pavel": StagePresence("Pavel",
                in_public="热情、幽默、自嘲——让所有人放松的人",
                in_private="比表面更焦虑——担心自己的工作永远不够严格，偶尔检查邮件希望得到认可",
                tells=["独自时会盯着同一个方程看很久，不写任何东西"]),
            "Hayashi": StagePresence("Hayashi",
                in_public="温暖、好奇、连接者——让每个人觉得自己被看见",
                in_private="偶尔感到不被理解——她的工作不被认为是'真正的数学'。偷偷把观察笔记藏起来",
                tells=["笔记本从不离身", "在别人争论时会安静地做笔记"]),
        }
        for name in self.names:
            if name in presences:
                self.stage[name] = presences[name]

    def _init_rituals(self):
        """Define community rituals."""
        self.rituals = [
            Ritual("每周研讨会", "轮流主讲，其他人提问和质疑", "weekly", emotional_charge=0.6),
            Ritual("走廊偶遇", "在大厅或花园随机碰到，闲聊几句", "spontaneous", emotional_charge=0.2),
            Ritual("沉默的认可", "当某人展示了一个真正漂亮的证明，其他人会沉默片刻——这是最高赞誉",
                   "spontaneous", emotional_charge=0.5),
        ]

    # ─── Actions ──────────────────────────────────────────────

    def record_gift(self, giver: str, receiver: str, what: str, value: float = 1.0):
        """Record a social gift."""
        self.ledger.record_gift(giver, receiver, what, value)
        self._log_activity(giver, f"帮助了{receiver}: {what}")
        self._log_activity(receiver, f"接受了{giver}的帮助: {what}")

    def spread_rumor(self, content: str, source: str, day: int, accuracy: float = 0.8):
        """Information starts circulating."""
        self.grapevine.spread(content, source, day, self.names, accuracy)

    def shift_role(self, name: str, new_role: str, day: int):
        """A character's social role changes."""
        old = self.roles.get(name, "")
        self.roles[name] = new_role
        self.role_history.setdefault(name, []).append((new_role, day))
        if old != new_role:
            self.spread_rumor(f"{name}的角色似乎开始转变——从{old}变得更像{new_role}了",
                              "observed", day, accuracy=0.5)

    def boost_status(self, name: str, amount: float):
        self.status[name] = min(100, self.status.get(name, 50) + amount)
        for other in self.names:
            if other != name:
                self.status[other] = max(10, self.status.get(other, 50) - amount * 0.1)

    def _log_activity(self, name: str, what: str):
        self.recent_activity.setdefault(name, []).append(what)
        if len(self.recent_activity[name]) > 10:
            self.recent_activity[name] = self.recent_activity[name][-10:]

    # ─── Context Generation ────────────────────────────────────

    def get_social_context(self, char_name: str) -> str:
        """Rich social context for this character's prompt."""

        parts = []

        # 1. Role awareness
        role = self.roles.get(char_name, "")
        role_desc = SOCIAL_ROLES.get(role, "")
        if role:
            parts.append(f"你在社区中的角色: {role}（{role_desc}）")

        # 2. Status awareness
        ranking = sorted(self.status.items(), key=lambda x: x[1], reverse=True)
        pos = next((i+1 for i, (n, _) in enumerate(ranking) if n == char_name), 0)
        parts.append(f"你在社区中的位置: 第{pos}/{len(self.names)}位")

        # 3. Trust network
        trusted = self.ledger.get_most_trusted(char_name)
        if trusted:
            top = trusted[:2]
            parts.append("你最信任的人: " + ", ".join(f"{n}({s:.0%})" for n, s in top))

        # 4. Debts
        debts = self.ledger.get_balance(char_name)
        if debts:
            debt_strs = [f"欠{n}一个人情" for n, v in debts.items() if v > 0.5]
            if debt_strs:
                parts.append("社会债务: " + "; ".join(debt_strs[:2]))

        # 5. What you've heard
        buzz = self.grapevine.get_buzz(char_name)
        if buzz:
            parts.append("你最近听到的: " + "; ".join(buzz[:2]))

        # 6. Front/back stage
        # (implicit — the character just IS their stage-appropriate self)

        return "\n".join(parts)
