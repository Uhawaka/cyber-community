"""Needs System v2 — principled need dynamics.

Key differences from RL:
  1. Short-term stable, long-term evolving (not a static reward function)
  2. Hierarchical — lower needs block higher ones
  3. Multiple competing drives — not a scalar to maximize
  4. Satiation is domain-specific — talking to Pavel ≠ presenting at seminar

Need structure:
  ENERGY (小时级)     — 生理需求, 快速衰减, 休息/发呆满足
  SAFETY (半天级)     — 环境安全感, 中速衰减, 整理空间/规律生活满足
  BELONGING (天级)    — 社交连接, 慢速衰减, 碰撞/集会/被邀请满足
  ESTEEM (周级)       — 认可, 很慢衰减, 论文被讨论/研讨会/洞见满足
  ACTUALIZATION (周级) — 成长, 变量衰减, 完成任务/发现新结构满足
"""

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NeedProfile:
    """One dimension of needs with its own decay and satisfaction dynamics."""

    name: str
    level: float = 30.0         # 0=fully satisfied, 100=desperate
    decay_per_hour: float = 2.0 # how fast it increases when unmet
    threshold_critical: float = 70  # above this, overrides all other needs
    threshold_high: float = 50      # above this, strongly biases behavior
    baseline: float = 20.0          # minimum level (can't go below this)
    
    def decay(self, hours: float):
        self.level = min(100.0, self.level + self.decay_per_hour * hours)

    def satisfy(self, amount: float):
        self.level = max(self.baseline, self.level - amount)

    def is_critical(self) -> bool:
        return self.level >= self.threshold_critical

    def is_elevated(self) -> bool:
        return self.level >= self.threshold_high


@dataclass  
class NeedsState:
    """Full need state for one character."""

    energy: NeedProfile = field(default_factory=lambda: NeedProfile(
        "energy", level=20.0, decay_per_hour=3.5, threshold_critical=80, threshold_high=55, baseline=10.0))
    safety: NeedProfile = field(default_factory=lambda: NeedProfile(
        "safety", level=30.0, decay_per_hour=1.5, threshold_critical=65, threshold_high=45, baseline=15.0))
    belonging: NeedProfile = field(default_factory=lambda: NeedProfile(
        "belonging", level=30.0, decay_per_hour=3.0, threshold_critical=55, threshold_high=35, baseline=15.0))
    esteem: NeedProfile = field(default_factory=lambda: NeedProfile(
        "esteem", level=40.0, decay_per_hour=1.0, threshold_critical=55, threshold_high=35, baseline=25.0))
    actualization: NeedProfile = field(default_factory=lambda: NeedProfile(
        "actualization", level=20.0, decay_per_hour=2.0, threshold_critical=45, threshold_high=28, baseline=12.0))

    def all_needs(self) -> list[NeedProfile]:
        return [self.energy, self.safety, self.belonging, self.esteem, self.actualization]

    def dominant_need(self) -> NeedProfile:
        """Find the most pressing need. Lower needs block higher ones."""
        # Critical energy → always dominant
        if self.energy.is_critical():
            return self.energy
        # Elevated energy → strong bias to rest
        if self.energy.is_elevated():
            return self.energy
        # Safety critical → dominant
        if self.safety.is_critical():
            return self.safety
        # Belonging critical → dominant  
        if self.belonging.is_critical():
            return self.belonging
        # Otherwise, highest relative to threshold
        needs = self.all_needs()
        needs.sort(key=lambda n: n.level / n.threshold_high, reverse=True)
        return needs[0]

    def decay_all(self, hours: float):
        for n in self.all_needs():
            n.decay(hours)

    def summary(self) -> str:
        dom = self.dominant_need()
        labels = {
            "energy": "需要休息",
            "safety": "需要安全感",
            "belonging": "需要社交",
            "esteem": "需要认可",
            "actualization": "需要创造",
        }
        parts = [
            f"当前驱动力: {labels.get(dom.name, '')}",
            f"精力{self.energy.level:.0f} 安全{self.safety.level:.0f} "
            f"归属{self.belonging.level:.0f} 认可{self.esteem.level:.0f} "
            f"创造{self.actualization.level:.0f}"
        ]
        return " | ".join(parts)


# ═══════════════════════════════════════════════════════════════
# Satisfaction amounts — domain-specific, not uniform
# ═══════════════════════════════════════════════════════════════

SATISFACTION = {
    # (event_type, intensity) → {need: amount}
    ("rest", "brief"):       {"energy": 15},
    ("rest", "proper"):      {"energy": 35, "safety": 5},
    ("collision", "casual"): {"belonging": 10},
    ("collision", "deep"):   {"belonging": 20, "esteem": 5, "actualization": 5},
    ("gathering", "any"):    {"belonging": 25, "esteem": 8},
    ("study", "any"):        {"actualization": 12, "esteem": 3},
    ("tool_use", "success"): {"actualization": 8, "esteem": 3},
    ("tool_use", "fail"):    {"actualization": 2},
    ("deep_think", "any"):   {"actualization": 20, "esteem": 8, "safety": 5},
    ("paper", "any"):        {"actualization": 30, "esteem": 20},
    ("mission_progress", "any"): {"actualization": 10, "esteem": 5},
    ("mission_complete", "any"): {"actualization": 35, "esteem": 25, "belonging": 10},
    ("seminar_present", "any"):  {"esteem": 30, "belonging": 15, "actualization": 10},
    ("seminar_attend", "any"):   {"belonging": 15, "actualization": 8},
    ("entertain", "any"):    {"energy": 8, "safety": 3},
    ("move_to_commons", "any"):  {"belonging": 5},
    ("modify_env", "any"):   {"safety": 15, "actualization": 3},
}


def determine_intensity(event_type: str, detail: dict = None) -> str:
    """Determine the intensity of an event for satisfaction lookup."""
    if event_type == "collision":
        if detail and detail.get("dialogue_length", 0) > 500:
            return "deep"
        return "casual"
    if event_type == "tool_use":
        if detail and detail.get("success", False):
            return "success"
        return "fail"
    if event_type == "rest":
        if detail and detail.get("duration", 0) > 2:
            return "proper"
        return "brief"
    return "any"


def satisfy_needs(state: NeedsState, event_type: str, detail: dict = None):
    """Apply need satisfaction from an event."""
    intensity = determine_intensity(event_type, detail)
    key = (event_type, intensity)
    alt_key = (event_type, "any")

    amounts = SATISFACTION.get(key) or SATISFACTION.get(alt_key) or {}
    for need_name, amount in amounts.items():
        need = getattr(state, need_name, None)
        if need:
            need.satisfy(amount)

    # Any non-rest activity slightly increases energy need
    if event_type not in ("rest", "entertain"):
        state.energy.decay(0.5)


# ═══════════════════════════════════════════════════════════════
# Behavior selection from needs
# ═══════════════════════════════════════════════════════════════

def need_driven_activity(state: NeedsState, phase_activity: dict) -> dict:
    """Override day rhythm based on current needs.

    Priority: critical needs override everything.
    Elevated needs bias toward satisfaction.
    """
    dom = state.dominant_need()

    # ── Critical overrides ──
    if state.energy.is_critical():
        return {"type": "rest", "label": "😴 急需休息"}
    if state.safety.is_critical():
        return {"type": "modify_env", "label": "🎨 整理空间"}

    # ── Elevated overrides ──
    if dom.name == "energy" and state.energy.is_elevated():
        if random.random() < 0.6:
            return {"type": "rest", "label": "☕ 休息一下"}

    if dom.name == "belonging" and state.belonging.is_elevated():
        return {"type": "socialize", "label": "💬 想找人联络"}

    # ── Mild bias: being in commons when belonging is moderate ──
    if state.belonging.level >= 40 and phase_activity.get("type") == "study":
        if random.random() < 0.3:
            return {"type": "move", "node": "commons", "label": "🚶 去大厅"}

    # ── Default: use day rhythm ──
    return phase_activity
