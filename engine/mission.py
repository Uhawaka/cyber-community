"""Observation Missions — goals with consequences.

Missions are built from a character's living domains + current focus,
not a hardcoded mathematics/prime template table.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Mission:
    """A specific question the character is trying to answer about the literature / world."""

    id: str
    question: str
    domain: str
    progress: float = 0.0
    attempts: int = 0
    findings: list = field(default_factory=list)
    status: str = "active"  # active | completed | abandoned

    def record_finding(self, content: str, relevance: float):
        self.findings.append({"content": content[:200], "relevance": relevance})
        self.progress = min(1.0, self.progress + relevance * 0.3)
        self.attempts += 1
        if self.progress >= 0.8:
            self.status = "completed"

    def is_complete(self) -> bool:
        return self.status == "completed"

    def summary(self) -> str:
        return f"「{self.question[:50]}」进度 {self.progress:.0%}"


# Optional domain-keyed extras (English terms OK inside Chinese questions)
MISSION_TEMPLATES = {
    "computational_finance": [
        "人类最近在 Monte Carlo 方差缩减上有什么可检验的新结果？",
        "高频交易微观结构噪声，文献里现在常用哪些统计处理方法？",
        "Deep learning 期权定价相对经典数值方法，有没有扎实对比？",
    ],
    "stochastic_control": [
        "最优停时 / reflected BSDE 的数值方法，最近有什么突破？",
        "随机控制里处理 model uncertainty 的鲁棒方法有哪些新进展？",
    ],
    "statistical_finance": [
        "金融时间序列长程相关，最近有什么新的实证或理论？",
        "波动率聚集：微观结构解释 vs 宏观信息流，文献怎么站队？",
    ],
}


def _char_domains(char) -> list[str]:
    cfg = getattr(char, "config", {}) or {}
    domains = cfg.get("domains") or []
    if isinstance(domains, str):
        domains = [domains]
    if not domains and cfg.get("domain"):
        domains = [cfg.get("domain")]
    return [str(d) for d in domains if d]


def _char_focus(char) -> str:
    cfg = getattr(char, "config", {}) or {}
    research = cfg.get("research") or getattr(char, "research", None) or {}
    orient = cfg.get("orientation") or {}
    state_focus = ""
    if hasattr(char, "state") and getattr(char.state, "current_focus", None):
        state_focus = char.state.current_focus or ""
    return (
        state_focus
        or orient.get("current_focus")
        or research.get("project")
        or research.get("stuck_point")
        or ""
    ).strip()


def _generic_questions(domains: list[str], focus: str) -> list[str]:
    label = focus or (domains[0].replace("_", " ") if domains else "my current program")
    dom_bits = ", ".join(d.replace("_", " ") for d in domains[:3]) or label
    return [
        f"关于「{label}」，人类文献里最近有什么可检验的新进展（paper / survey）？",
        f"在 {dom_bits} 方向，有没有新的 journal / arXiv 结果能修正我现有假设？",
        f"哪些作者或课题组最近在推进与「{label}」相邻的问题？他们用了什么方法？",
        f"有没有反例、数值证据或负结果，动摇我对「{label}」的默认图景？",
    ]


def assign_mission(
    char_domain: str = "",
    existing_missions: list = None,
    domains: list = None,
    focus: str = "",
    char=None,
) -> Optional[Mission]:
    """Assign a new observation mission from domains/focus (character-aware)."""
    if char is not None:
        domains = _char_domains(char)
        focus = _char_focus(char)
        if not char_domain and domains:
            char_domain = domains[0]

    domains = list(domains or [])
    if not domains and char_domain:
        domains = [char_domain]

    templates: list[str] = []
    for d in domains:
        templates.extend(MISSION_TEMPLATES.get(d, []))
    # world-level coarse keys
    if char_domain in MISSION_TEMPLATES:
        templates.extend(MISSION_TEMPLATES[char_domain])
    templates.extend(_generic_questions(domains, focus))

    # Dedupe preserve order
    seen, uniq = set(), []
    for t in templates:
        if t not in seen:
            seen.add(t)
            uniq.append(t)

    existing_questions = [m.question for m in (existing_missions or [])]
    available = [t for t in uniq if t not in existing_questions] or uniq
    question = random.choice(available)
    mission_id = f"mission_{hash(question) % 10000:04d}"
    domain_label = char_domain or (domains[0] if domains else "general")
    return Mission(id=mission_id, question=question, domain=domain_label)


def evaluate_observation(observation: str, mission: Mission) -> float:
    """Keyword relevance 0–1 (lightweight; LLM matching can replace later)."""
    if not observation or not mission:
        return 0.0

    keywords = mission.question.lower().split()
    stop = {
        "的", "了", "是", "在", "有", "什么", "怎么", "吗", "呢", "？", "?",
        "人类", "有没有", "关于", "最近", "哪些", "他们", "我", "对",
        "a", "an", "the", "and", "or", "of", "in", "to", "for",
    }
    keywords = [w for w in keywords if w not in stop and len(w) > 1]
    if not keywords:
        return 0.15

    obs = observation.lower()
    matches = sum(1 for w in keywords if w in obs)
    if matches == 0:
        return 0.0
    return min(1.0, matches / max(len(keywords) * 0.3, 1))


class MissionBoard:
    """Manages all characters' observation missions."""

    def __init__(self, characters: dict):
        self.characters = characters
        self.missions: dict[str, list[Mission]] = {}
        self.completed: dict[str, list[Mission]] = {}

        for name, char in characters.items():
            mission = assign_mission(char=char)
            if mission:
                self.missions[name] = [mission]

    def get_active(self, char_name: str) -> Optional[Mission]:
        missions = self.missions.get(char_name, [])
        active = [m for m in missions if m.status == "active"]
        return active[0] if active else None

    def _assign_for(self, char_name: str) -> Optional[Mission]:
        char = self.characters.get(char_name)
        return assign_mission(char=char, existing_missions=self.missions.get(char_name, []))

    def process_observation(self, char_name: str, observation: str):
        mission = self.get_active(char_name)
        if mission is None:
            mission = self._assign_for(char_name)
            if mission:
                self.missions.setdefault(char_name, []).append(mission)

        if mission is None:
            return None

        relevance = evaluate_observation(observation, mission)
        if relevance > 0:
            mission.record_finding(observation, relevance)
            if mission.is_complete():
                self.missions[char_name].remove(mission)
                self.completed.setdefault(char_name, []).append(mission)
                new_mission = self._assign_for(char_name)
                if new_mission:
                    self.missions[char_name].append(new_mission)
        return mission

    def get_context(self, char_name: str) -> str:
        mission = self.get_active(char_name)
        if mission is None:
            return ""
        lines = ["## 你在追踪的问题", mission.summary()]
        if mission.findings:
            lines.append("最近的发现:")
            for f in mission.findings[-2:]:
                lines.append(f"  · {f['content'][:80]}")
        return "\n".join(lines)
