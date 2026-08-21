"""Context injection, memory recording, deep think, soul study updates."""

from __future__ import annotations

from engine.memory import Episode
from engine.interactions import extract_soul_updates
from engine.needs import satisfy_needs

# Soft cap for injected prompt context (world + culture + memory)
_MAX_INJECT_CHARS = 3600

# Actions that can meaningfully react to anonymous stimuli
_REACTIVE_ACTIONS = frozenset({
    "study", "socialize", "gather", "observe", "observe_world",
    "tool", "modify_env",
})


class CognitionMixin:
    """Memory, context, and deep-reflection machinery."""

    def _clip_inject(self, text: str, max_chars: int = _MAX_INJECT_CHARS) -> str:
        if not text or len(text) <= max_chars:
            return text or ""
        return text[: max_chars - 1] + "…"

    def _inject_context(self, char_name: str):
        """Inject memory, understanding, sociology, and location context into character.

        Anonymous events are peeked (not consumed) here — call
        `_consume_anon_if_reactive` after choosing a reactive action.
        """
        char = self.characters.get(char_name)
        if char is None:
            return
        mem = self.memories.get(char_name)
        soul = self.souls.get(char_name)
        blocks: list[str] = []

        if mem:
            char._memory_context = mem.get_context(max_tokens=400)
        else:
            char._memory_context = ""

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

        # High-signal blocks first (inbox / anon / needs), then culture, then memory
        from engine.inbox import build_inbox, format_inbox_briefing
        from engine.work_queue import format_work_briefing
        inbox = build_inbox(self, char_name)
        char._inbox = inbox
        work = format_work_briefing(char)
        if work:
            blocks.append(work)
        brief = format_inbox_briefing(inbox)
        if brief:
            blocks.append("## 待办收件箱（先处理别人找你的事）\n" + brief)

        anon_texts = self.anonymous.peek_for(char_name)
        if anon_texts:
            lines = ["## 你察觉到的异常"]
            for t in anon_texts[:3]:
                lines.append(f"· {t[:160]}")
            lines.append("（你不知道这些从何而来，可以自行猜测。）")
            blocks.append("\n".join(lines))

        if char.state.pending_thoughts:
            thoughts = char.state.pending_thoughts[:3]
            char.state.pending_thoughts = char.state.pending_thoughts[3:]
            blocks.append(
                "## 萦绕心头的念头\n" + "\n".join(f"· {t[:120]}" for t in thoughts)
            )

        state = self.needs.get(char_name)
        if state:
            blocks.append("## 你的当前状态\n" + state.summary())

        loc = self.environment.get_location_context(char_name)
        if loc:
            blocks.append(loc[:400])

        stimuli = self.rich_env.get_stimuli(char_name)
        if stimuli:
            stim_lines = ["## 你感知到的事"]
            for s in stimuli[-3:]:
                prefix = {"high": "⚡", "medium": "🔔", "low": "·"}.get(s.urgency, "·")
                stim_lines.append(f"{prefix} [{s.source}] {s.content[:120]}")
            blocks.append("\n".join(stim_lines))

        mission_ctx = self.missions.get_context(char_name)
        if mission_ctx:
            blocks.append(mission_ctx[:350])

        from engine.culture import format_world_context, format_practice_context
        from engine.research import research_prompt_block
        from engine.skills import bind_character_skills
        frame = getattr(self, "world_frame", {}) or {}
        char._world_practice = format_practice_context(frame)
        bind_character_skills(char, self.souls.get(char_name))
        char._research_protocol = research_prompt_block(frame)
        world_ctx = format_world_context(frame, max_chars=2800)
        if world_ctx:
            blocks.append("## 你所在的世界\n" + world_ctx)

        culture_ctx = self.society.get_culture_context()
        if culture_ctx:
            blocks.append("## 社区文化\n" + culture_ctx[:400])
            char._sociology_context = culture_ctx
        social_ctx = self.society.get_social_context(char_name)
        if social_ctx:
            blocks.append("## 社区中的你\n" + social_ctx[:300])

        self._inject_collab_context(char_name)
        if hasattr(char.state, "collab_context") and char.state.collab_context:
            blocks.append(str(char.state.collab_context)[:350])

        if char._memory_context:
            blocks.append(char._memory_context)

        char._memory_context = self._clip_inject("\n\n".join(blocks))

    def _consume_anon_if_reactive(self, char_name: str, action_type: str):
        """Mark anonymous events perceived only when the character can react."""
        if action_type in _REACTIVE_ACTIONS:
            self.anonymous.consume_for(char_name)

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
        if self.dry_run:
            return
        if not self._llm_budget_ok():
            return

        counts = self._event_counts.get(char_name, {"study": 0, "collision": 0, "tool": 0})
        last = self._last_deep_think.get(char_name, self.clock)
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

        # Write to Soul (identity may grow without a citable object)
        if soul:
            soul.add_deep_thought(thought)

        # Community production needs a source; musing stays on the Soul.
        from engine.work_queue import artifact_has_source

        blob = f"{thought.understanding}\n{getattr(thought, 'evidence', '') or ''}"
        if artifact_has_source(blob, char):
            self.production._current_day = self.day
            self.production.create_artifact(
                "insight",
                f"洞见: {thought.understanding[:60]}...",
                thought.understanding[:500],
                [char_name],
                confidence=thought.confidence,
            )
        else:
            self._log("    · 洞见留在灵魂里，未进社区产出（缺对象）")

        # ── Need satisfaction ──
        state = self.needs.get(char_name)
        if state:
            satisfy_needs(state, "deep_think")

        loc = self.environment.get_location(char_name)
        if loc and artifact_has_source(blob, char):
            self.rich_env.record_event(f"{char_name} 有了一个深度洞见")
            self.environment.leave_echo(
                char_name, loc.id,
                f"深度反思 (Day{self.day}): {thought.understanding[:80]}",
            )

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
        """Grow skills from practice; optionally extract identity-level soul changes."""
        soul = self.souls.get(char_name)
        if soul is None:
            return
        topic_s = " ".join((topic or "").split())[:40]
        soul.practice_skill("research", f"studied {topic_s}".strip(), day=self.day, amount=0.03)
        char = self.characters.get(char_name)
        if char is not None:
            from engine.skills import bind_character_skills

            bind_character_skills(char, soul)
        if self.dry_run or not self._llm_budget_ok():
            return

        context = f"研究主题: {topic}\n思考:\n{thought[:1500]}"
        try:
            updates = extract_soul_updates(char_name, "study", context, self.llm)
        except Exception:
            return

        if not updates:
            return
        soul.apply_delta(updates, day=self.day)
