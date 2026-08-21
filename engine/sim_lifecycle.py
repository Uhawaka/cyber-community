"""Simulation lifecycle: bootstrap, run loop, day boundary."""

from __future__ import annotations

import random

from engine.events import Event
from engine.character import Character


class LifecycleMixin:
    """DES main loop and day-boundary housekeeping."""

    # Dense day beats (virtual hours). Rhythm owns activate; spontaneous is separate.
    RHYTHM_OFFSETS = (2.0, 4.0, 7.0, 10.0, 12.0, 14.0, 16.0, 18.0, 21.0)

    def _schedule_day_activities(self, day_start: float):
        """Push one virtual day's activates + spontaneous for every character."""
        for char in self.characters.values():
            for offset in self.RHYTHM_OFFSETS:
                self.queue.push(Event(
                    time=day_start + offset, type="activate", actor=char.name,
                ))
            # Spontaneous sparks between beats (density lever; not post-activate chain)
            for _ in range(random.randint(3, 4)):
                self.queue.push(Event(
                    time=day_start + random.uniform(1.0, 23.0),
                    type="spontaneous",
                    actor=char.name,
                ))
            if not self.dry_run:
                self.queue.push(Event(
                    time=day_start + random.uniform(3.0, 6.0),
                    type="idle_thought",
                    actor=char.name,
                ))
                # Second idle later in the day — more Soul texture
                self.queue.push(Event(
                    time=day_start + random.uniform(14.0, 20.0),
                    type="idle_thought",
                    actor=char.name,
                ))

    def bootstrap(self):
        """Schedule day rhythm + spontaneous for the current day; gather at commons."""
        env = getattr(self, "environment", None)
        if env and "commons" in env.nodes:
            for name in list(getattr(self, "characters", {}) or {}):
                env.move_character(name, "commons")
            try:
                env.save()
            except Exception:
                pass
        day_start = (max(int(self.day), 1) - 1) * 24.0
        self._schedule_day_activities(day_start=day_start)
        boundary = day_start + 24.0
        if boundary <= self.clock:
            boundary = (int(self.clock // 24) + 1) * 24.0
        self.queue.push(Event(time=boundary, type="day_boundary"))
        seminar = 72.0
        if seminar > self.clock:
            self.queue.push(Event(time=seminar, type="weekly_seminar"))
        # Restore-only: drop leftover beats from before the saved clock.
        # Fresh start is clock==0; dropping then would eat same-tick injects.
        drop = getattr(self.queue, "drop_at_or_before", None)
        if callable(drop) and self.clock > 0:
            drop(self.clock)


    def run(self, max_days: int = 1, verbose: bool = True):
        """Run simulation for max_days virtual days (batch / experiment)."""
        self.running = True
        if not getattr(self, "_bootstrapped", False):
            self.bootstrap()
            self._bootstrapped = True

        # From the current clock, so a founded community can add days.
        max_time = self.clock + max_days * 24.0
        self.run_slice(until_time=max_time, max_events=10_000_000, verbose=verbose)

        self.running = False
        if hasattr(self, "save_sim_state"):
            self.save_sim_state(founded=self.day > 1 or bool(self.event_log))
        if verbose:
            self._log(f"模拟结束: Day {self.day}, t={self.clock:.1f}")

    def run_slice(
        self,
        until_time: float | None = None,
        max_events: int = 40,
        max_llm_calls: int | None = None,
        verbose: bool = False,
    ) -> dict:
        """Process a bounded DES slice (used by live hang windows).

        Dispatches events with time <= until_time (if set), up to max_events.
        Soft-caps LLM calls via max_llm_calls (expensive paths skip when over).
        Does not call bootstrap; caller must bootstrap once for live mode.
        """
        if not getattr(self, "_bootstrapped", False):
            self.bootstrap()
            self._bootstrapped = True
            self.running = True

        self._llm_calls_slice_start = getattr(self.llm, "call_count", 0)
        self._max_llm_calls_slice = max_llm_calls

        processed = 0
        while self.running and self.queue and processed < max_events:
            peek = self.queue.peek_time()
            if peek is None:
                break
            if until_time is not None and peek > until_time:
                break
            event = self.queue.pop()
            if event is None:
                break
            # Guard for batch: pop may return event past until after race; skip
            if until_time is not None and event.time > until_time:
                self.queue.push(event)
                break
            self.clock = event.time
            self._dispatch(event, verbose)
            processed += 1

        used = self._llm_calls_used()
        self._max_llm_calls_slice = None
        return {
            "processed": processed,
            "clock": self.clock,
            "day": self.day,
            "queue": len(self.queue),
            "llm_calls": used,
        }


    def _dispatch(self, event: Event, verbose: bool):
        handler = getattr(self, f"_handle_{event.type}", None)
        if handler:
            handler(event, verbose)
        else:
            if verbose:
                self._log(f"⚠ 未知事件类型: {event.type}")


    def _log(self, msg: str):
        print(msg, flush=True)


    def _handle_day_boundary(self, event: Event, verbose: bool):
        completed_day = self.day
        self.day += 1
        if verbose:
            self._log(f"\n{'='*50}")
            self._log(f"🌅 Day {self.day} 开始 (Day {completed_day} 结束)")
            self._log(f"{'='*50}")

        # Generate daily summaries for each character
        today_events = [e for e in self.event_log 
                       if self.clock - 24 <= e["time"] <= self.clock]
        
        for name, char in self.characters.items():
            char_events = [e for e in today_events if e.get("actor") == name]
            summary = ""
            if char_events:
                summary = self._generate_day_summary(name, char, char_events)
                self.archives[name].add_day_summary(completed_day, summary, char_events)
                if verbose:
                    self._log(f"  📝 {name}: {summary[:80]}...")

            # Memory consolidation — promote facts, compress stale episodes
            mem = self.memories.get(name)
            if mem:
                stats = mem.consolidate_day(completed_day)
                if verbose and (stats.get("facts_added") or stats.get("compressed")):
                    self._log(
                        f"  🧠 {name} 记忆整理: +{stats['facts_added']}事实, "
                        f"压缩{stats['compressed']}条, 剩余{stats['remaining']}"
                    )

            # Soul calibration every 7 days — fight personality flattening
            if completed_day > 0 and completed_day % 7 == 0:
                soul = self.souls.get(name)
                if soul:
                    recent = []
                    if summary:
                        recent.append(summary)
                    archive_ctx = self.archives[name].get_recent_context(3)
                    if archive_ctx:
                        recent.append(archive_ctx)
                    note = soul.calibrate(completed_day, recent)
                    if note:
                        char.state.pending_thoughts.append(f"[内心提醒] {note}")
                        if verbose:
                            self._log(f"  ⚓ {name} 人格校准")

            # Reset energy
            char.reset_energy()
            char._day = self.day

        # Schedule next day boundary
        self.queue.push(Event(time=self.clock + 24.0, type="day_boundary"))

        # Save environment
        self.environment.save()
        if hasattr(self, "save_sim_state"):
            self.save_sim_state(founded=True)

        # Schedule denser rhythm + spontaneous for the new day
        self._schedule_day_activities(day_start=self.clock)


    def _generate_day_summary(self, name: str, char: Character, events: list) -> str:
        """Generate a daily summary for a character using LLM."""
        study_steps = [e for e in events if e["type"] == "study_step"]
        collisions = [e for e in events if e["type"] == "collision" and 
                     (e.get("actor") == name or e.get("target") == name or e.get("initiator") == name)]
        tool_uses = [e for e in events if e["type"] == "tool_use" and e.get("actor") == name]
        
        if not study_steps and not collisions and not tool_uses:
            return "休息和思考"
        
        # Build context
        context_parts = []
        for s in study_steps[-3:]:
            thought = s.get("thought", "")[:150]
            if thought:
                context_parts.append(f"研究思考: {thought}")
        
        for c in collisions[-3:]:
            dialogue = c.get("dialogue", "")[:200]
            if dialogue:
                context_parts.append(f"对话: {dialogue}")
        
        if not context_parts:
            parts = []
            if study_steps:
                parts.append("做了一些研究")
            if collisions:
                others = set()
                for c in collisions:
                    for key in ["actor", "target", "initiator"]:
                        if c.get(key) and c[key] != name:
                            others.add(c[key])
                if others:
                    parts.append(f"与 {', '.join(others)} 进行了交流")
            if tool_uses:
                tool_names = set(e.get("tool", "") for e in tool_uses)
                parts.append(f"使用工具: {', '.join(tool_names)}")
            return "；".join(parts) if parts else "休息和思考"
        
        fallback = "；".join(
            p for p in [
                f"研究了{len(study_steps)}次" if study_steps else "",
                f"交流了{len(collisions)}次" if collisions else "",
                f"用了{len(tool_uses)}次工具" if tool_uses else "",
            ] if p
        ) or "休息和思考"

        if not self._llm_budget_ok():
            return fallback

        context = "\n".join(context_parts)
        system = f"你是 {name} 的日记助手。用一句话（20字以内）总结 {name} 今天做了什么、想了什么。用第一人称。"
        prompt = f"今天的事件:\n{context}\n\n用一句话总结今天（第一人称，20字以内）:"

        try:
            summary = self.llm.chat([{"role": "user", "content": prompt}], system=system, temperature=0.5)
            return summary.strip()[:60]
        except Exception:
            return fallback

