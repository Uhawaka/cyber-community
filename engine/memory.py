"""Memory System: episodic, semantic, and working memory.

          ┌──────────────┐
          │   Working    │ ← current focus, active thoughts (short-term)
          │   Memory     │
          └──────┬───────┘
                 │ attention + reflection
          ┌──────▼───────┐
          │  Episodic    │ ← specific events, conversations, discoveries
          │  Memory      │    with rich context and emotional valence
          └──────┬───────┘
                 │ abstraction + compression
          ┌──────▼───────┐
          │  Semantic    │ ← facts, concepts, patterns extracted from episodes
          │  Memory      │
          └──────┬───────┘
                 │ deep thinking
          ┌──────▼───────┐
          │    Soul      │ ← accumulated understanding, identity, beliefs
          └──────────────┘
"""

import json
import os
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Episode:
    """A single remembered event."""
    id: str
    time: float           # virtual time
    day: int
    type: str             # study | collision | tool_use | deep_think | idle
    summary: str          # one-line description
    detail: str           # richer detail (dialogue snippet, thought, result)
    participants: list = field(default_factory=list)
    emotional_valence: str = "neutral"  # exciting | frustrating | curious | neutral
    importance: float = 0.5  # 0-1, how significant was this?
    tags: list = field(default_factory=list)  # topic tags for retrieval


class Memory:
    """A character's memory system."""

    def __init__(self, path: str, max_episodes: int = 200):
        self.path = path
        self.max_episodes = max_episodes
        self.episodes: list[Episode] = []
        self.semantic_facts: list[dict] = []
        self.working: dict = {
            "current_focus": "",
            "active_hypotheses": [],
            "recent_observations": [],
            "pending_questions": [],
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._load()

    # ─── Episodic Memory ───────────────────────────────────────

    def remember(self, episode: Episode):
        """Store a new episodic memory."""
        self.episodes.append(episode)
        # Compress old memories
        if len(self.episodes) > self.max_episodes:
            self._compress_oldest()
        self.save()

    def recall_recent(self, count: int = 10) -> list[Episode]:
        """Get the most recent episodes."""
        return self.episodes[-count:]

    def recall_by_topic(self, topic: str, count: int = 5) -> list[Episode]:
        """Search episodic memory by topic tag."""
        matches = [e for e in self.episodes if topic in e.tags or topic in e.summary]
        return matches[-count:]

    def recall_important(self, count: int = 5) -> list[Episode]:
        """Get the most important episodes."""
        sorted_episodes = sorted(self.episodes, key=lambda e: e.importance, reverse=True)
        return sorted_episodes[:count]

    def recall_since(self, since_day: int) -> list[Episode]:
        """Get episodes since a given day."""
        return [e for e in self.episodes if e.day >= since_day]

    # ─── Semantic Memory ──────────────────────────────────────

    def learn_fact(self, fact: str, source: str = "", confidence: float = 0.5):
        """Store a semantic fact derived from experience."""
        self.semantic_facts.append({
            "fact": fact,
            "source": source,
            "confidence": confidence,
            "learned_at": datetime.now().isoformat(),
        })
        # Keep semantic memory bounded
        if len(self.semantic_facts) > 50:
            # Keep high-confidence facts, drop low-confidence
            self.semantic_facts.sort(key=lambda f: f["confidence"], reverse=True)
            self.semantic_facts = self.semantic_facts[:50]
        self.save()

    def get_facts(self, count: int = 10) -> list[str]:
        """Get most confident semantic facts."""
        sorted_facts = sorted(self.semantic_facts, key=lambda f: f["confidence"], reverse=True)
        return [f["fact"] for f in sorted_facts[:count]]

    # ─── Working Memory ───────────────────────────────────────

    def set_focus(self, focus: str):
        self.working["current_focus"] = focus

    def add_observation(self, observation: str):
        self.working["recent_observations"].append(observation)
        if len(self.working["recent_observations"]) > 10:
            self.working["recent_observations"] = self.working["recent_observations"][-10:]

    def add_hypothesis(self, hypothesis: str):
        self.working["active_hypotheses"].append(hypothesis)
        if len(self.working["active_hypotheses"]) > 5:
            self.working["active_hypotheses"] = self.working["active_hypotheses"][-5:]

    def add_question(self, question: str):
        self.working["pending_questions"].append(question)
        if len(self.working["pending_questions"]) > 5:
            self.working["pending_questions"] = self.working["pending_questions"][-5:]

    # ─── Context for Prompts ──────────────────────────────────

    def get_context(self, max_tokens: int = 500) -> str:
        """Build a memory context string for injection into prompts.

        This is what the character "remembers" when they think.
        """
        parts = []

        # Working memory
        if self.working["current_focus"]:
            parts.append(f"当前关注: {self.working['current_focus']}")
        if self.working["active_hypotheses"]:
            parts.append(f"活跃假设: {'; '.join(self.working['active_hypotheses'][-3:])}")
        if self.working["pending_questions"]:
            parts.append(f"待解疑问: {'; '.join(self.working['pending_questions'][-3:])}")

        # Key semantic facts
        facts = self.get_facts(5)
        if facts:
            parts.append(f"已知事实: {'; '.join(facts[:3])}")

        # Recent episodes (most recent 3, most important 2)
        recent = self.recall_recent(3)
        important = self.recall_important(2)
        all_refs = recent + [e for e in important if e not in recent]
        if all_refs:
            ep_lines = []
            for ep in all_refs[:5]:
                emoji = {"exciting": "🔥", "frustrating": "😤", "curious": "🤔", "neutral": "📝"}.get(ep.emotional_valence, "")
                ep_lines.append(f"[Day{ep.day}] {emoji} {ep.summary}")
            parts.append("记得的事:\n" + "\n".join(ep_lines))

        return "\n".join(parts)

    # ─── Internal ─────────────────────────────────────────────

    def _compress_oldest(self):
        """Compress the oldest 20 episodes into a single summary entry."""
        oldest = self.episodes[:20]
        self.episodes = self.episodes[20:]

        # Create a compressed summary
        types = set(e.type for e in oldest)
        days = set(e.day for e in oldest)
        avg_importance = sum(e.importance for e in oldest) / len(oldest)

        compressed = Episode(
            id=f"compressed_{oldest[0].id}",
            time=oldest[0].time,
            day=min(days),
            type="compressed",
            summary=f"早期记忆（{len(oldest)}个事件，Day{min(days)}-{max(days)}）",
            detail=f"涉及: {', '.join(types)}。平均重要性: {avg_importance:.2f}",
            importance=avg_importance * 0.3,  # compressed = less important
        )
        self.episodes.insert(0, compressed)

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    data = json.load(f)
                self.episodes = [Episode(**e) for e in data.get("episodes", [])]
                self.semantic_facts = data.get("semantic_facts", [])
                self.working = data.get("working", self.working)
            except (json.JSONDecodeError, TypeError):
                pass

    def save(self):
        with open(self.path, "w") as f:
            json.dump({
                "episodes": [{
                    "id": e.id, "time": e.time, "day": e.day,
                    "type": e.type, "summary": e.summary, "detail": e.detail,
                    "participants": e.participants, 
                    "emotional_valence": e.emotional_valence,
                    "importance": e.importance, "tags": e.tags,
                } for e in self.episodes],
                "semantic_facts": self.semantic_facts,
                "working": self.working,
            }, f, ensure_ascii=False, indent=2)

    # ─── Backstory Seeding ────────────────────────────────────

    def seed_backstory(self, char_config: dict):
        """Pre-populate memory with the character's backstory.

        A character without memories has no foundation. These seeds give them
        a past before the simulation begins — key relationships, formative
        experiences, the origin of their obsessions.
        """
        name = char_config.get("name", "")
        self_concept = char_config.get("self_concept", "")
        research = char_config.get("research", {})
        relationships = char_config.get("relationships", [])

        day_offset = -30  # Memories from "before" the simulation

        # ── Self-concept as foundational memory ──
        if self_concept:
            self.remember(Episode(
                id=f"{name}_backstory_identity",
                time=0.0, day=day_offset,
                type="backstory",
                summary="我之所以是我",
                detail=self_concept[:500],
                emotional_valence="neutral",
                importance=1.0,
                tags=["identity", "backstory"],
            ))

        # ── Research origin ──
        obsession = research.get("obsession", "")
        if obsession:
            self.remember(Episode(
                id=f"{name}_backstory_obsession",
                time=0.0, day=day_offset + 1,
                type="backstory",
                summary=f"最初让我着迷的事: {obsession[:80]}",
                detail=obsession[:300],
                emotional_valence="exciting",
                importance=0.9,
                tags=["research", "origin", "backstory"],
            ))

        stuck = research.get("stuck_point", "")
        if stuck:
            self.remember(Episode(
                id=f"{name}_backstory_stuck",
                time=0.0, day=day_offset + 2,
                type="backstory",
                summary=f"一直卡住的地方: {stuck[:80]}",
                detail=stuck[:300],
                emotional_valence="frustrating",
                importance=0.8,
                tags=["research", "struggle", "backstory"],
            ))

        # ── Key relationships ──
        for rel in relationships:
            target = rel.get("target", "")
            true_feel = rel.get("true_feeling", "")
            history = rel.get("history", "")
            if target:
                self.remember(Episode(
                    id=f"{name}_backstory_rel_{target}",
                    time=0.0, day=day_offset + 3,
                    type="backstory",
                    summary=f"我和{target}的关系: {true_feel[:60]}",
                    detail=f"表面: {rel.get('surface', '')}. 历史: {history[:200]}",
                    participants=[target],
                    emotional_valence="curious",
                    importance=0.85,
                    tags=["relationship", target, "backstory"],
                ))

        self.save()

    # ─── Psychology-Aware Encoding ────────────────────────────

    def encode_with_psychology(self, episode: Episode, personality: dict, 
                                 sociology_context: dict = None) -> Episode:
        """Adjust episode importance based on the character's psychology.

        Different personalities find different things memorable:
        - High neuroticism: frustration & conflict are amplified
        - High openness: surprising discoveries are amplified
        - Low agreeableness: status threats are amplified
        - Sociology: events involving status shifts or norm violations matter more
        """
        neuroticism = personality.get("neuroticism", 5)
        openness = personality.get("openness", 5)
        agreeableness = personality.get("agreeableness", 5)

        base_importance = episode.importance

        # Neuroticism amplifies negative experiences
        if neuroticism >= 7 and episode.emotional_valence in ("frustrating",):
            base_importance = min(1.0, base_importance * 1.5)

        # Openness amplifies novel/surprising experiences
        if openness >= 7 and episode.emotional_valence in ("exciting", "curious"):
            base_importance = min(1.0, base_importance * 1.3)

        # Low agreeableness amplifies conflict
        if agreeableness <= 3 and "不对" in episode.detail or "错了" in episode.detail:
            base_importance = min(1.0, base_importance * 1.4)

        # Sociology: status-relevant events are more memorable
        if sociology_context:
            tension = sociology_context.get("tension_zones", [])
            for t in tension:
                if any(word in episode.summary for word in t.split()[:3]):
                    base_importance = min(1.0, base_importance * 1.3)

        episode.importance = base_importance
        return episode
