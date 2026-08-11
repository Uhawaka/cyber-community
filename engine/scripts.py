"""Motivation system: scripts, projects, and idle thoughts.

Characters are driven by:
1. Projects — long-term goals with progress tracking
2. Routines — time-of-day behavioral patterns
3. Personality scripts — permanent behavioral tendencies
4. Idle thoughts — low-frequency inner monologue (no energy cost)
"""

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Project:
    """A long-term goal the character is working toward."""
    goal: str
    progress: float = 0.0          # 0.0 — 1.0
    milestone: str = ""            # current sub-goal description
    started_day: int = 0
    breakthroughs: list = field(default_factory=list)

    def advance(self, amount: float = 0.05):
        """Advance project progress."""
        old_milestone = int(self.progress * 10)
        self.progress = min(1.0, self.progress + amount)
        new_milestone = int(self.progress * 10)
        if new_milestone > old_milestone:
            return True   # milestone reached
        return False

    def is_complete(self) -> bool:
        return self.progress >= 1.0

    def summary(self) -> str:
        pct = int(self.progress * 100)
        return f"「{self.goal}」进度 {pct}%"


@dataclass
class Routine:
    """Daily routine pattern that biases behavior at certain virtual hours."""
    name: str
    # start_hour, end_hour in virtual time (0-24)
    start_hour: float
    end_hour: float
    # bias: which actions get boosted
    bias: dict  # e.g., {"study": 1.5, "socialize": 0.3}

    def is_active(self, virtual_hour: float) -> bool:
        """Check if this routine is active at the given virtual hour."""
        hour = virtual_hour % 24
        if self.start_hour <= self.end_hour:
            return self.start_hour <= hour < self.end_hour
        else:
            # Overnight routine (e.g., 22:00-06:00)
            return hour >= self.start_hour or hour < self.end_hour


@dataclass
class PersonalityScript:
    """A permanent behavioral tendency triggered by state."""
    name: str
    description: str
    # Condition: when does this fire?
    condition_type: str   # "time_range", "energy_threshold", "project_milestone", "always"
    condition_params: dict = field(default_factory=dict)
    # Effect: what happens when condition is met
    effect: dict = field(default_factory=dict)

    def should_fire(self, virtual_hour: float, energy: int, progress: float) -> bool:
        ct = self.condition_type

        if ct == "time_range":
            h = virtual_hour % 24
            lo = self.condition_params.get("start", 0)
            hi = self.condition_params.get("end", 24)
            return lo <= h < hi

        if ct == "energy_threshold":
            threshold = self.condition_params.get("below", 30)
            return energy < threshold

        if ct == "project_milestone":
            milestone = self.condition_params.get("at", 0.5)
            return progress >= milestone

        if ct == "always":
            return True

        return False

    def get_bias(self) -> dict:
        """Return action weight multipliers."""
        return self.effect.get("bias", {})

    def get_triggered_action(self) -> Optional[str]:
        """If this script forces a specific action."""
        return self.effect.get("force_action")


class ScriptManager:
    """Manages all scripts for a character."""

    def __init__(self, config: dict):
        self.projects: list[Project] = []
        self.routines: list[Routine] = []
        self.personality_scripts: list[PersonalityScript] = []
        self.idle_thoughts: list[dict] = []   # recent idle thoughts
        self.idle_interval: float = 6.0       # virtual hours between idle thoughts
        self.last_idle_time: float = 0.0

        self._load_from_config(config)

    def _load_from_config(self, config: dict):
        scripts_cfg = config.get("scripts", {})

        # Projects
        for proj_cfg in scripts_cfg.get("projects", []):
            self.projects.append(Project(
                goal=proj_cfg.get("goal", ""),
                progress=proj_cfg.get("progress", 0.0),
                milestone=proj_cfg.get("milestone", ""),
                started_day=proj_cfg.get("started_day", 0),
            ))

        # Routines
        for r_cfg in scripts_cfg.get("routines", []):
            self.routines.append(Routine(
                name=r_cfg.get("name", ""),
                start_hour=r_cfg.get("start_hour", 8),
                end_hour=r_cfg.get("end_hour", 12),
                bias=r_cfg.get("bias", {}),
            ))

        # Personality scripts
        for p_cfg in scripts_cfg.get("personality", []):
            self.personality_scripts.append(PersonalityScript(
                name=p_cfg.get("name", ""),
                description=p_cfg.get("description", ""),
                condition_type=p_cfg.get("condition_type", "always"),
                condition_params=p_cfg.get("condition_params", {}),
                effect=p_cfg.get("effect", {}),
            ))

        # Idle thought config
        idle_cfg = scripts_cfg.get("idle_thoughts", {})
        self.idle_interval = idle_cfg.get("interval_hours", 6.0)

    # ─── Decision Bias ────────────────────────────────────────

    def get_decision_bias(self, virtual_hour: float, energy: int) -> dict:
        """Get action weight multipliers from all active scripts.

        Returns dict of action_name -> multiplier (>1 = boosted, <1 = suppressed).
        """
        bias = {}

        # 1. Project bias: if there's an active project, boost study
        for proj in self.projects:
            if not proj.is_complete():
                bias["study"] = bias.get("study", 1.0) * 1.5
                # Also favor tools if available
                bias["tool_run_code"] = bias.get("tool_run_code", 1.0) * 1.3
                bias["tool_write_paper"] = bias.get("tool_write_paper", 1.0) * 1.2
                break  # one active project is enough

        # 2. Routine bias
        for routine in self.routines:
            if routine.is_active(virtual_hour):
                for action, multiplier in routine.bias.items():
                    bias[action] = bias.get(action, 1.0) * multiplier

        # 3. Personality script bias
        active_project = self.projects[0] if self.projects else None
        progress = active_project.progress if active_project else 0.0

        for script in self.personality_scripts:
            if script.should_fire(virtual_hour, energy, progress):
                script_bias = script.get_bias()
                for action, multiplier in script_bias.items():
                    bias[action] = bias.get(action, 1.0) * multiplier

        return bias

    # ─── Active Project ────────────────────────────────────────

    def get_active_project(self) -> Optional[Project]:
        """Get the first non-complete project."""
        for proj in self.projects:
            if not proj.is_complete():
                return proj
        return None

    def advance_project(self, amount: float = 0.03) -> Optional[Project]:
        """Advance active project. Returns project if milestone reached."""
        proj = self.get_active_project()
        if proj is None:
            return None
        reached = proj.advance(amount)
        return proj if reached else None

    def add_breakthrough(self, description: str):
        proj = self.get_active_project()
        if proj:
            proj.breakthroughs.append(description)

    # ─── Idle Thoughts ─────────────────────────────────────────

    def should_idle_think(self, current_time: float) -> bool:
        """Check if it's time for an idle thought."""
        return current_time - self.last_idle_time >= self.idle_interval

    def record_idle_thought(self, thought: str, time: float):
        self.idle_thoughts.append({
            "time": time,
            "thought": thought,
        })
        self.last_idle_time = time
        # Keep only last 20
        if len(self.idle_thoughts) > 20:
            self.idle_thoughts = self.idle_thoughts[-20:]

    def get_idle_context(self, count: int = 5) -> str:
        """Get recent idle thoughts for context injection."""
        recent = self.idle_thoughts[-count:]
        if not recent:
            return ""
        return "\n".join(f"[t={t['time']:.1f}] {t['thought']}" for t in recent)

    # ─── Serialization ─────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "projects": [
                {
                    "goal": p.goal,
                    "progress": p.progress,
                    "milestone": p.milestone,
                    "started_day": p.started_day,
                    "breakthroughs": p.breakthroughs,
                }
                for p in self.projects
            ],
            "routines": [
                {
                    "name": r.name,
                    "start_hour": r.start_hour,
                    "end_hour": r.end_hour,
                    "bias": r.bias,
                }
                for r in self.routines
            ],
            "personality_scripts": [
                {
                    "name": ps.name,
                    "description": ps.description,
                    "condition_type": ps.condition_type,
                    "condition_params": ps.condition_params,
                    "effect": ps.effect,
                }
                for ps in self.personality_scripts
            ],
            "idle_thoughts": self.idle_thoughts,
        }
