"""Day Rhythm — a character's natural daily flow.

Replaces random Poisson activation with a structured day:
  天亮了 → 到工位 → 看环境 → 看arxiv → 有意思就深挖 → 复现 → 找人聊 → 反思 → 休息

Each character has their own rhythm based on config.routines.
"""

import random
from dataclasses import dataclass, field
from enum import Enum


class DayPhase(Enum):
    WAKE = "wake"              # 0-2h: wake up, check environment
    MORNING_DEEP = "morning"   # 2-6h: deep focused work
    LATE_MORNING = "late_am"   # 6-8h: check observations, lighter work
    MIDDAY = "midday"          # 8-12h: social window
    AFTERNOON = "afternoon"    # 12-16h: work or rest
    EVENING = "evening"        # 16-20h: reflection, writing
    NIGHT = "night"            # 20-24h: wind down, idle thoughts, rest


# Default phase → activities mapping
PHASE_ACTIVITIES = {
    DayPhase.WAKE: [
        {"type": "move", "node": "study_chamber", "weight": 0.5},
        {"type": "rest", "weight": 0.3},
        {"type": "entertain", "weight": 0.2},
    ],
    DayPhase.MORNING_DEEP: [
        {"type": "study", "weight": 0.6},
        {"type": "tool_run_code", "weight": 0.2},
        {"type": "tool_write_paper", "weight": 0.1},
        {"type": "rest", "weight": 0.1},
    ],
    DayPhase.LATE_MORNING: [
        {"type": "observe_world", "weight": 0.4},
        {"type": "study", "weight": 0.3},
        {"type": "tool_search_arxiv", "weight": 0.15},
        {"type": "move", "node": "commons", "weight": 0.15},
    ],
    DayPhase.MIDDAY: [
        {"type": "socialize", "weight": 0.4},
        {"type": "gather", "weight": 0.2},
        {"type": "move", "node": "commons", "weight": 0.2},
        {"type": "rest", "weight": 0.2},
    ],
    DayPhase.AFTERNOON: [
        {"type": "study", "weight": 0.3},
        {"type": "tool_run_code", "weight": 0.2},
        {"type": "rest", "weight": 0.2},
        {"type": "entertain", "weight": 0.15},
        {"type": "socialize", "weight": 0.15},
    ],
    DayPhase.EVENING: [
        {"type": "tool_write_paper", "weight": 0.3},
        {"type": "rest", "weight": 0.25},
        {"type": "modify_env", "weight": 0.15},
        {"type": "socialize", "weight": 0.15},
        {"type": "entertain", "weight": 0.15},
    ],
    DayPhase.NIGHT: [
        {"type": "rest", "weight": 0.4},
        {"type": "entertain", "weight": 0.3},
        {"type": "idle_thought", "weight": 0.2},
        {"type": "move", "node": "garden", "weight": 0.1},
    ],
}


def get_phase(hour: float) -> DayPhase:
    """Map virtual hour to day phase."""
    h = hour % 24
    if h < 2:
        return DayPhase.WAKE
    elif h < 6:
        return DayPhase.MORNING_DEEP
    elif h < 8:
        return DayPhase.LATE_MORNING
    elif h < 12:
        return DayPhase.MIDDAY
    elif h < 16:
        return DayPhase.AFTERNOON
    elif h < 20:
        return DayPhase.EVENING
    else:
        return DayPhase.NIGHT


def get_phase_activity(phase: DayPhase, character_routines: list = None) -> dict:
    """Get a weighted-random activity appropriate for this day phase.

    Character routines can override the default weights.
    """
    activities = PHASE_ACTIVITIES.get(phase, [{"type": "rest", "weight": 1.0}])

    # Apply routine overrides
    if character_routines:
        for routine in character_routines:
            if routine.is_active(getattr(routine, '_current_hour', 12)):
                for act in activities:
                    act_type = act["type"]
                    if act_type in routine.bias:
                        act["weight"] *= routine.bias[act_type]

    choices = [a["type"] for a in activities]
    weights = [a["weight"] for a in activities]

    # Normalize
    total = sum(weights)
    if total == 0:
        return {"type": "rest"}

    weights = [w / total for w in weights]
    chosen = random.choices(choices, weights=weights, k=1)[0]

    # One-line activity → decision mapping
    map_activity = {
        "tool_run_code":     {"type": "tool", "tool": "run_code", "label": "🔧 写代码验证"},
        "tool_write_paper":  {"type": "tool", "tool": "write_paper", "label": "📝 写笔记"},
        "tool_search_arxiv": {"type": "tool", "tool": "search_arxiv", "label": "🔍 搜论文"},
        "socialize":  {"type": "socialize", "label": "💬 想找人聊聊"},
        "gather":     {"type": "gather", "label": "📢 想召集讨论"},
        "study":      {"type": "study", "label": "📖 研究"},
        "rest":       {"type": "rest", "label": "☕ 休息"},
        "entertain":  {"type": "entertain", "label": "🎵 放松"},
        "modify_env": {"type": "modify_env", "label": "🎨 整理空间"},
        "observe_world": {"type": "observe_world", "label": "🔭 看看外面"},
        "idle_thought":  {"type": "entertain", "label": "💭 发呆"},
        "move": {"type": "move", "node": next((a["node"] for a in activities if a["type"] == "move" and "node" in a), "commons"), "label": "🚶 换个地方"},
    }
    return map_activity.get(chosen, {"type": chosen, "label": f"📋 {chosen}"})
