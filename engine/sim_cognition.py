"""Context injection, memory recording, deep think, soul study updates."""

from __future__ import annotations

from engine.memory import Episode
from engine.interactions import extract_soul_updates
from engine.needs import satisfy_needs


class CognitionMixin:
    """Memory, context, and deep-reflection machinery."""

    def _inject_context(self, char_name: str):
        """Inject memory, understanding, sociology, and location context into character."""
        char = self.characters.get(char_name)
        if char is None:
            return
        mem = self.memories.get(char_name)
        soul = self.souls.get(char_name)
        if mem:
            char._memory_context = mem.get_context()
        if soul:
            char._deep_understanding = soul.get_deep_understanding(3)
            char._soul_context = soul.get_context_summary()
            # Orientation focus from Soul v2 (not research essay dumps)
            orient = (soul.data.get("orientation") or {})
            if orient.get("current_focus"):
                char.state.current_focus = orient["current_focus"][:100]
            else:
                refs = soul.data.get("reflections") or []
                if refs and float(refs[-1].get("confidence") or 0) > 0.5:
                    char.state.current_focus = refs[-1].get("statement", "")[:100]
            # Sync living domains into character config for prompts
            live = list((soul.data.get("identity") or {}).get("domains") or [])
            if live:
                char.config["domains"] = live
                if not char.config.get("domain"):
                    char.config["domain"] = live[0]
        else:
            char._soul_context = ""
        # Inject location context
        loc = self.environment.get_location_context(char_name)
        if loc:
            char._memory_context = loc + "\n\n" + char._memory_context

        # Inject environmental stimuli
        stimuli = self.rich_env.get_stimuli(char_name)
        if stimuli:
            stim_lines = ["## 你感知到的事"]
            for s in stimuli[-4:]:
                prefix = {"high": "⚡", "medium": "🔔", "low": "·"}.get(s.urgency, "·")
                stim_lines.append(f"{prefix} [{s.source}] {s.content}")
            char._memory_context += "\n" + "\n".join(stim_lines)

        # Inject mission context
        mission_ctx = self.missions.get_context(char_name)
        if mission_ctx:
            char._memory_context = mission_ctx + "\n\n" + char._memory_context

        # Inject need state
        state = self.needs.get(char_name)
        if state:
            char._memory_context = "## 你的当前状态\n" + state.summary() + "\n\n" + char._memory_context

        # Inject worldview / observation window
        from engine.culture import format_world_context
        world_ctx = format_world_context(getattr(self, "world_frame", {}) or {})
        if world_ctx:
            char._memory_context = "## 你所在的世界\n" + world_ctx + "\n\n" + char._memory_context

        # Inject community culture (norms, stage, shared memory) — YAML-driven
        culture_ctx = self.society.get_culture_context()
        if culture_ctx:
            char._memory_context = "## 社区文化\n" + culture_ctx + "\n\n" + char._memory_context
            char._sociology_context = culture_ctx

        # Inject community public context (what everyone can see)
        social_ctx = self.society.get_social_context(char_name)
        if social_ctx:
            char._memory_context = "## 社区中的你\n" + social_ctx + "\n\n" + char._memory_context

        # Inject collaboration context
        self._inject_collab_context(char_name)
        if hasattr(char.state, 'collab_context') and char.state.collab_context:
            char._memory_context = char.state.collab_context + "\n\n" + char._memory_context

        # Inject anonymous / external events (never reveal user as source)
        anon_texts = self.anonymous.consume_for(char_name)
        if anon_texts:
            lines = ["## 你察觉到的异常"]
            for t in anon_texts:
                lines.append(f"· {t}")
            lines.append("（你不知道这些从何而来，可以自行猜测。）")
            char._memory_context = "\n".join(lines) + "\n\n" + char._memory_context

        # Drain pending thoughts into context
        if char.state.pending_thoughts:
            thoughts = char.state.pending_thoughts[:5]
            char.state.pending_thoughts = char.state.pending_thoughts[5:]
            char._memory_context = (
                "## 萦绕心头的念头\n"
                + "\n".join(f"· {t}" for t in thoughts)
                + "\n\n"
                + char._memory_context
            )


    def _record_memory(self, char_name: str, ep_type: str, summary: str, 
                        detail: str = "", participants: list = None,
                        valence: str = "neutral", importance: float = 0.5,
                        tags: list = None):
        """Record an episode in the character's memory and update event counts."""
        mem = self.memories.get(char_name)
        if mem is None:
            return

        ep = Episode(
            id=f"{char_name}_{self.clock:.1f}_{ep_type}",
            time=self.clock,
            day=self.day,
            type=ep_type,
            summary=summary[:200],
            detail=detail[:500],
            participants=participants or [],
            emotional_valence=valence,
            importance=importance,
            tags=tags or [],
        )
        mem.remember(ep)

        # Apply psychology-aware encoding
        char = self.characters.get(char_name)
        if char:
            soc_ctx = {"tension_zones": self.config.get("sociology", {}).get("hierarchy", {}).get("tension_zones", [])}
            ep = mem.encode_with_psychology(ep, char.personality, soc_ctx)
            # Re-save with adjusted importance
            mem.save()

        # Update working memory
        if ep_type == "study":
            mem.add_observation(summary)
        elif ep_type == "collision":
            mem.add_observation(f"与{', '.join(participants or ['某人'])}的对话: {summary[:80]}")
        elif ep_type == "tool_use":
            mem.add_observation(f"使用工具的结果: {summary[:80]}")

        # Increment event counter for deep think trigger
        counts = self._event_counts.get(char_name, {"study": 0, "collision": 0, "tool": 0})
        if ep_type in counts:
            counts[ep_type] += 1
        self._event_counts[char_name] = counts

        # Check if deep think should trigger
        self._check_deep_think(char_name)


    def _check_deep_think(self, char_name: str):
        """Check if character should do a deep thinking session."""
        counts = self._event_counts.get(char_name, {"study": 0, "collision": 0, "tool": 0})
        last = self._last_deep_think.get(char_name, 0.0)
        hours_since = self.clock - last

        if not self.deep_think.should_trigger(
            char_name, counts["study"], counts["collision"], 
            counts["tool"], hours_since
        ):
            return

        char = self.characters.get(char_name)
        if char is None:
            return

        # Gather recent events for this character
        recent = [e for e in self.event_log[-30:] 
                  if e.get("actor") == char_name or e.get("target") == char_name 
                  or e.get("initiator") == char_name]

        # Get soul context
        soul = self.souls.get(char_name)
        soul_ctx = soul.get_context_summary() if soul else ""

        # Run deep think
        self._log(f"\n  🧠 {char_name} 开始深度反思...")
        try:
            thought = self.deep_think.think_deep(char, recent, soul_ctx)
        except Exception as e:
            self._log(f"    ⚠ 深思失败: {e}")
            return

        self._log(f"    💡 洞见: {thought.understanding[:150]}...")
        self._log(f"    📊 把握: {thought.confidence:.0%}")

        # Reset counters
        self._event_counts[char_name] = {"study": 0, "collision": 0, "tool": 0}
        self._last_deep_think[char_name] = self.clock

        # Write to Soul
        if soul and not self.dry_run:
            soul.add_deep_thought(thought)

        # ── Production: record as insight artifact ──
        if not self.dry_run:
            self.production._current_day = self.day
            self.production.create_artifact(
                "insight", 
                f"洞见: {thought.understanding[:60]}...",
                thought.understanding[:500],
                [char_name],
                confidence=thought.confidence,
            )

        # ── Environment: notify rich env ──
        self.rich_env.record_event(f"{char_name} 有了一个深度洞见")

        # ── Need satisfaction ──
        state = self.needs.get(char_name)
        if state:
            satisfy_needs(state, "deep_think")

        # ── Environment: leave echo of deep insight ──
        loc = self.environment.get_location(char_name)
        if loc:
            self.environment.leave_echo(char_name, loc.id,
                f"深度反思 (Day{self.day}): {thought.understanding[:80]}")
        
        # Log event
        self.event_log.append({
            "time": self.clock,
            "type": "deep_think",
            "actor": char_name,
            "understanding": thought.understanding,
            "confidence": thought.confidence,
        })

        # ── Collaboration: deep insights may reveal shared interests ──
        self._check_solo_to_collab(char_name, thought)


    def _update_soul_from_study(self, char_name: str, topic: str, thought: str):
        """Extract soul changes from a study step."""
        soul = self.souls.get(char_name)
        if soul is None:
            return

        context = f"研究主题: {topic}\n思考:\n{thought[:1500]}"
        try:
            updates = extract_soul_updates(char_name, "study", context, self.llm)
        except Exception:
            return

        if not updates:
            return
        soul.apply_delta(updates, day=self.day)

