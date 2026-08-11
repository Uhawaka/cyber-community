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

    def __init__(self, characters: dict, sociology_config: dict | None = None):
        self.characters = characters
        self.names = list(characters.keys())
        self.sociology_config = sociology_config or {}

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
        """Assign roles from personality/drives — no name hardcoding."""
        for name in self.names:
            char = self.characters.get(name)
            role = self._role_from_traits(char)
            self.roles[name] = role
            self.role_history[name] = [(role, 0)]

    @staticmethod
    def _role_from_traits(char) -> str:
        if char is None:
            return "newcomer"
        cfg = getattr(char, "config", {}) or {}
        p = getattr(char, "personality", None) or cfg.get("personality") or {}
        d = getattr(char, "drives", None) or cfg.get("drives") or {}
        ex = float(p.get("extraversion", 5) or 5)
        ag = float(p.get("agreeableness", 5) or 5)
        co = float(p.get("conscientiousness", 5) or 5)
        op = float(p.get("openness", 5) or 5)
        rel = float(d.get("relatedness", 5) or 5)
        comp = float(d.get("competence", 5) or 5)

        if ex >= 7 and (ag >= 6 or rel >= 7):
            return "bridge"
        if co >= 7 and ag <= 4:
            return "challenger"
        if op >= 8 and co <= 5:
            return "elder"  # depth / taste authority
        if ag >= 7 and rel >= 7:
            return "nurturer"
        if comp >= 8 and ex <= 4:
            return "challenger"
        return "newcomer"

    def _init_stage(self):
        """Stage presence derived from voice / cognitive / community_role."""
        for name in self.names:
            char = self.characters.get(name)
            self.stage[name] = self._presence_from_traits(name, char)

    @staticmethod
    def _presence_from_traits(name: str, char) -> "StagePresence":
        cfg = getattr(char, "config", {}) or {} if char else {}
        voice = getattr(char, "voice", None) or cfg.get("voice") or []
        if not voice:
            voice = (cfg.get("soul") or {}).get("voice") or []
        role = (cfg.get("community_role") or "").strip()
        mode = (cfg.get("cognitive") or getattr(char, "cognitive", {}) or {}).get("primary_mode", "")
        defense = (cfg.get("defense") or getattr(char, "defense", {}) or {}).get("primary", "")

        public_bits = []
        if role:
            public_bits.append(role[:40])
        if mode:
            public_bits.append(f"思维偏 {mode}")
        if voice:
            public_bits.append(str(voice[0])[:50])
        in_public = "；".join(public_bits) if public_bits else "在公共场合克制、就事论事"

        private = "独处时更诚实——会复查自己是否在自欺"
        if defense == "humor":
            private = "独处时比表面更焦虑；幽默是外壳"
        elif defense == "intellectualization":
            private = "独处时把不安转成技术细节反复推敲"

        tells = [str(v)[:40] for v in voice[:2]] if voice else ["工作时会自言自语"]
        return StagePresence(name, in_public=in_public, in_private=private, tells=tells)

    def _init_rituals(self):
        """Define community rituals."""
        self.rituals = [
            Ritual("每周研讨会", "轮流主讲，其他人提问和质疑", "weekly", emotional_charge=0.6),
            Ritual("走廊偶遇", "在大厅或花园随机碰到，闲聊几句", "spontaneous", emotional_charge=0.2),
            Ritual("沉默的认可", "当某人展示了一个真正漂亮的结果，其他人会沉默片刻——这是最高赞誉",
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

    def get_culture_context(self) -> str:
        """Community-wide norms / stage / collective memory from YAML."""
        from engine.culture import format_culture_context
        return format_culture_context(self.sociology_config)

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

    def get_community_snapshot(self) -> str:
        """Observer-facing snapshot for digests (not injected into character prompts)."""
        parts = []

        ranking = sorted(self.status.items(), key=lambda x: x[1], reverse=True)
        if ranking:
            parts.append(
                "地位排序: "
                + ", ".join(f"{n}({s:.0f})" for n, s in ranking)
            )

        role_bits = [f"{n}:{r}" for n, r in self.roles.items() if r]
        if role_bits:
            parts.append("角色: " + ", ".join(role_bits))

        buzz_all = []
        for name in self.names:
            buzz_all.extend(self.grapevine.get_buzz(name)[:1])
        # de-dupe while preserving order
        seen = set()
        unique_buzz = []
        for b in buzz_all:
            if b not in seen:
                seen.add(b)
                unique_buzz.append(b)
        if unique_buzz:
            parts.append("近期流言: " + "; ".join(unique_buzz[:3]))

        return "\n".join(parts) if parts else "社区氛围平静。"
