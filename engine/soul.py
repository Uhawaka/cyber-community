"""Memory system: Soul files + daily archive + fuzzy compression."""

import json
import os
import yaml
from datetime import datetime
from typing import Optional


class SoulFile:
    """A character's essence — personality anchor that evolves slowly."""

    def __init__(self, path: str):
        self.path = path
        self.data = {}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._load_or_init()

    def _load_or_init(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.data = yaml.safe_load(f) or {}
        else:
            self.data = {
                "name": "",
                "essence": {
                    "core_belief": "",
                    "intellectual_style": "",
                    "emotional_pattern": "",
                },
                "relationships_deep": {},
                "knowledge_evolved": {
                    "gained": [],
                    "questions": [],
                    "abandoned": [],
                },
                "witnessed_moments": [],
                "projects": {},   # project_goal -> {progress, breakthroughs}
                "idle_thoughts": [],  # recent inner monologue
            }

    def init_from_config(self, name: str, config: dict):
        """Initialize soul from character config. Preserves existing soul data."""
        self.data["name"] = name
        seed = config.get("seed", "")
        
        # Only set core_belief if it's empty (first init); don't overwrite evolved souls
        if seed and not self.data.get("essence", {}).get("core_belief", ""):
            self.data.setdefault("essence", {})["core_belief"] = seed

        self.save()

    def add_witnessed_moment(self, moment: str):
        """Add a user-witnessed moment that will never be compressed away."""
        entry = {
            "time": datetime.now().isoformat(),
            "content": moment,
        }
        self.data.setdefault("witnessed_moments", []).append(entry)
        self.save()

    def add_knowledge(self, category: str, item: str):
        """Add gained knowledge, open question, or abandoned idea."""
        key = {
            "gained": "gained",
            "question": "questions",
            "abandoned": "abandoned",
        }.get(category, category)
        self.data.setdefault("knowledge_evolved", {})
        self.data["knowledge_evolved"].setdefault(key, []).append(item)
        self.save()

    def update_relationship(self, target_name: str, bond: str, history_note: str = ""):
        """Update relationship with another character."""
        rels = self.data.setdefault("relationships_deep", {})
        if target_name not in rels:
            rels[target_name] = {"bond": bond, "history": []}
        else:
            rels[target_name]["bond"] = bond
        if history_note:
            rels[target_name].setdefault("history", []).append(history_note)
        self.save()

    def get_context_summary(self) -> str:
        """Get a ~200 token summary for injection into activate context."""
        e = self.data.get("essence", {})
        name = self.data.get("name", "")
        belief = e.get("core_belief", "")[:80]

        rels = self.data.get("relationships_deep", {})
        rel_text = ""
        for target, rel in list(rels.items())[:3]:
            rel_text += f"对 {target}: {rel.get('bond', '')}. "

        questions = self.data.get("knowledge_evolved", {}).get("questions", [])[-3:]
        q_text = " ".join(questions) if questions else ""
        
        # Project info
        projects = self.data.get("projects", {})
        proj_text = ""
        for goal, info in list(projects.items())[:2]:
            pct = int(info.get("progress", 0) * 100)
            proj_text += f"项目「{goal[:30]}」进度{pct}%. "

        return f"你是 {name}。核心信念: {belief}。{rel_text}{proj_text}当前探索的问题: {q_text}"

    def update_project(self, goal: str, progress: float, breakthrough: str = ""):
        """Record project progress."""
        projects = self.data.setdefault("projects", {})
        if goal not in projects:
            projects[goal] = {"progress": 0.0, "breakthroughs": []}
        projects[goal]["progress"] = max(projects[goal]["progress"], progress)
        if breakthrough:
            projects[goal].setdefault("breakthroughs", []).append(breakthrough)
        self.save()

    def add_deep_thought(self, thought) -> None:
        """Record a deep thinking result in Soul.

        Deep thoughts are different from idle thoughts — they represent
        genuine understanding formed through reflection, not passing ideas.
        """
        from engine.deep_think import DeepThought
        understanding = self.data.setdefault("understanding", [])
        understanding.append({
            "day": thought.day,
            "insight": thought.understanding[:500],
            "confidence": thought.confidence,
            "observations": thought.observations[:200],
            "connections": thought.connections[:200],
            "implications": thought.implications,
            "open_questions": thought.open_questions,
            "timestamp": datetime.now().isoformat(),
        })
        # Keep last 20 deep thoughts
        if len(understanding) > 20:
            self.data["understanding"] = understanding[-20:]
        self.save()

    def get_deep_understanding(self, count: int = 3) -> str:
        """Get recent deep understanding for context injection."""
        understanding = self.data.get("understanding", [])[-count:]
        if not understanding:
            return ""
        parts = []
        for u in understanding:
            parts.append(
                f"[Day {u['day']}] 洞见 (把握{u['confidence']:.0%}): {u['insight'][:200]}"
            )
        return "\n".join(parts)

    def add_idle_thought(self, thought: str):
        """Record an idle thought."""
        thoughts = self.data.setdefault("idle_thoughts", [])
        thoughts.append({
            "time": datetime.now().isoformat(),
            "content": thought,
        })
        if len(thoughts) > 30:
            self.data["idle_thoughts"] = thoughts[-30:]
        self.save()

    def get_recent_idle_thoughts(self, count: int = 5) -> str:
        """Get recent idle thoughts for context."""
        thoughts = self.data.get("idle_thoughts", [])[-count:]
        if not thoughts:
            return ""
        return "\n".join(f"· {t['content']}" for t in thoughts)

    def save(self):
        with open(self.path, "w") as f:
            yaml.dump(self.data, f, allow_unicode=True, default_flow_style=False)


class DailyArchive:
    """Daily compressed summaries for a character."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._ensure_file()

    def _read(self) -> list:
        if not os.path.exists(self.path):
            return []
        with open(self.path) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []

    def _write(self, data: list):
        with open(self.path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _ensure_file(self):
        if not os.path.exists(self.path):
            self._write([])

    def add_day_summary(self, day: int, summary: str, events: list):
        """Add a day's summary."""
        data = self._read()
        data.append({
            "day": day,
            "summary": summary,
            "event_count": len([e for e in events if e.get("actor")]),
            "timestamp": datetime.now().isoformat(),
        })
        self._write(data)

    def get_recent_context(self, days: int = 3) -> str:
        """Get recent day summaries for context injection (~500 tokens)."""
        data = self._read()
        recent = data[-days:]
        lines = []
        for entry in recent:
            lines.append(f"[Day {entry['day']}] {entry['summary']}")
        return "\n".join(lines)

    def compress_weekly(self, week_num: int, weekly_summary: str):
        """Compress 7 daily archives into a weekly summary."""
        data = self._read()
        # Mark the last 7 entries as compressed
        cutoff = len(data) - 7
        if cutoff < 0:
            cutoff = 0
        compressed = data[cutoff:]
        # Replace with weekly summary
        data = data[:cutoff]
        data.append({
            "week": week_num,
            "summary": weekly_summary,
            "compressed_days": len(compressed),
            "timestamp": datetime.now().isoformat(),
        })
        self._write(data)
