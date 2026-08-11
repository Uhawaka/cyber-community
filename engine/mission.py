"""Observation Missions — goals with consequences.

Characters observe humanity not randomly, but to answer specific questions.
Success → reward (energy, excitement, social recognition)
Failure → frustration, strategy change
Progress → visible, drives behavior

This simple feedback loop is what makes behavior feel "alive."
"""

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Mission:
    """A specific question the character is trying to answer about humanity."""

    id: str
    question: str                        # what they want to know
    domain: str                          # what field
    progress: float = 0.0                # 0.0 — 1.0
    attempts: int = 0
    findings: list = field(default_factory=list)   # what they've discovered
    status: str = "active"               # active | completed | abandoned

    def record_finding(self, content: str, relevance: float):
        """Record something found that's relevant to the mission."""
        self.findings.append({"content": content[:200], "relevance": relevance})
        self.progress = min(1.0, self.progress + relevance * 0.3)
        self.attempts += 1

        if self.progress >= 0.8:
            self.status = "completed"

    def is_complete(self) -> bool:
        return self.status == "completed"

    def summary(self) -> str:
        return f"「{self.question[:50]}」进度 {self.progress:.0%}"


# ═══════════════════════════════════════════════════════════════
# Mission Templates — domain-specific observation goals
# ═══════════════════════════════════════════════════════════════

MISSION_TEMPLATES = {
    "computational_finance": [
        "人类最近在蒙特卡洛方法上有什么突破？有没有新的方差缩减技术？",
        "人类在做高频交易时用什么统计方法来处理市场微观结构噪声？",
        "深度学习在期权定价上真的比传统数值方法好吗？证据是什么？",
        "人类有没有发现新的波动率模型可以更好地拟合肥尾？",
    ],
    "stochastic_control": [
        "人类在最优停时问题上有什么新进展？反射BSDE的数值方法有什么突破？",
        "人类在随机控制中怎么处理模型不确定性？有没有新的鲁棒方法？",
        "深度学习求解高维PDE的进展如何？Deep BSDE方法现在能做到什么程度？",
    ],
    "statistical_finance": [
        "人类在金融时间序列的长程相关性上有什么新发现？",
        "人类有没有找到波动率聚集的根本原因——是微观结构还是宏观信息流？",
        "统计力学方法在金融风险管理中有什么新应用？",
    ],
    "mathematics": [
        "人类在随机矩阵理论上有什么新结果？有没有新的普适性类被发现了？",
        "人类对黎曼ζ函数零点的数值计算推进到了什么高度？",
        "人类有没有发现新的筛法可以处理短区间的质数分布？",
    ],
}


def assign_mission(char_domain: str, existing_missions: list = None) -> Mission:
    """Assign a new observation mission based on character's domain."""
    templates = MISSION_TEMPLATES.get(char_domain, MISSION_TEMPLATES.get("mathematics", []))
    if not templates:
        return None

    # Avoid duplicates
    existing_questions = [m.question for m in (existing_missions or [])]
    available = [t for t in templates if t not in existing_questions]
    if not available:
        available = templates

    question = random.choice(available)
    mission_id = f"mission_{hash(question) % 10000:04d}"

    return Mission(id=mission_id, question=question, domain=char_domain)


def evaluate_observation(observation: str, mission: Mission) -> float:
    """How relevant is this observation to the mission? 0-1.

    Simple keyword-based relevance for now — could use LLM for better matching.
    """
    if not observation or not mission:
        return 0.0

    keywords = mission.question.lower().split()
    # Remove stop words
    stop = {"的", "了", "是", "在", "有", "什么", "怎么", "吗", "呢", "？", "？", "人类", "有没有"}
    keywords = [w for w in keywords if w not in stop and len(w) > 1]

    matches = sum(1 for w in keywords if w in observation.lower())
    if matches == 0:
        return 0.0
    return min(1.0, matches / max(len(keywords) * 0.3, 1))


class MissionBoard:
    """Manages all characters' observation missions."""

    def __init__(self, characters: dict):
        self.missions: dict[str, list[Mission]] = {}  # char_name → active missions
        self.completed: dict[str, list[Mission]] = {}

        # Assign initial missions
        for name, char in characters.items():
            domain = char.config.get("domain", "mathematics")
            mission = assign_mission(domain)
            if mission:
                self.missions[name] = [mission]

    def get_active(self, char_name: str) -> Optional[Mission]:
        """Get the character's current active mission."""
        missions = self.missions.get(char_name, [])
        active = [m for m in missions if m.status == "active"]
        return active[0] if active else None

    def process_observation(self, char_name: str, observation: str):
        """Process an observation against the character's active mission."""
        mission = self.get_active(char_name)
        if mission is None:
            # Assign a new one
            char_domain = "mathematics"
            mission = assign_mission(char_domain, self.missions.get(char_name, []))
            if mission:
                self.missions.setdefault(char_name, []).append(mission)

        if mission is None:
            return None

        relevance = evaluate_observation(observation, mission)
        if relevance > 0:
            mission.record_finding(observation, relevance)

            if mission.is_complete():
                # Move to completed
                self.missions[char_name].remove(mission)
                self.completed.setdefault(char_name, []).append(mission)
                # Assign new mission
                domain = "mathematics"
                new_mission = assign_mission(domain, self.missions.get(char_name, []))
                if new_mission:
                    self.missions[char_name].append(new_mission)

        return mission

    def get_context(self, char_name: str) -> str:
        """Mission context for system prompt injection."""
        mission = self.get_active(char_name)
        if mission is None:
            return ""

        lines = [f"## 你在追踪的问题", mission.summary()]
        if mission.findings:
            recent = mission.findings[-2:]
            lines.append("最近的发现:")
            for f in recent:
                lines.append(f"  · {f['content'][:80]}")
        return "\n".join(lines)
