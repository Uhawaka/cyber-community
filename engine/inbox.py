"""Inbox-first briefing — Moltbook-style /home for community characters.

Priority: reply to people who reached out > continue collab > broadcast new work.
"""

from __future__ import annotations

from typing import Any, Optional


def peek_pending_messages(char) -> list[dict]:
    return list(char.state.pending_messages or [])


def consume_messages_from(char, sender: str) -> list[dict]:
    """Remove and return pending messages from one sender."""
    kept, consumed = [], []
    for msg in char.state.pending_messages or []:
        if msg.get("from") == sender:
            consumed.append(msg)
        else:
            kept.append(msg)
    char.state.pending_messages = kept
    return consumed


def build_inbox(engine, char_name: str) -> dict[str, Any]:
    """Structured check-in payload for one character (observer-safe fields only)."""
    char = engine.characters.get(char_name)
    if char is None:
        return {"messages": [], "mentions": [], "collabs": [], "has_priority": False}

    messages = peek_pending_messages(char)

    mentions: list[dict] = []
    for e in reversed(engine.event_log[-50:]):
        if e.get("type") != "collision":
            continue
        if e.get("target") == char_name or e.get("initiator") == char_name:
            other = e.get("initiator") if e.get("target") == char_name else e.get("target")
            if other == char_name:
                continue
            mentions.append({
                "with": other,
                "topic": str(e.get("data", {}).get("topic") or e.get("topic") or "")[:60],
                "time": e.get("time"),
            })
            if len(mentions) >= 3:
                break

    collabs: list[dict] = []
    collab = getattr(engine, "collab", None)
    if collab is not None:
        for p in collab.get_by_participant(char_name):
            if getattr(p, "status", "active") not in ("active", ""):
                continue
            partners = [n for n in (p.participants or []) if n != char_name]
            collabs.append({
                "topic": (p.topic or "")[:60],
                "partners": partners,
                "progress": getattr(p, "progress", 0),
            })
            if len(collabs) >= 3:
                break

    return {
        "messages": messages,
        "mentions": mentions,
        "collabs": collabs,
        "has_priority": bool(messages) or bool(collabs),
    }


def format_inbox_briefing(inbox: dict) -> str:
    """Human/LLM readable inbox block."""
    if not inbox:
        return ""
    lines: list[str] = []
    msgs = inbox.get("messages") or []
    if msgs:
        lines.append("未读留言（优先处理）:")
        for m in msgs[:5]:
            lines.append(f"  · {m.get('from', '?')}: {str(m.get('message', ''))[:80]}")
    collabs = inbox.get("collabs") or []
    if collabs:
        lines.append("进行中的协作:")
        for c in collabs[:3]:
            partners = ", ".join(c.get("partners") or []) or "?"
            lines.append(f"  · 与 {partners}: {c.get('topic', '')}")
    mentions = inbox.get("mentions") or []
    if mentions:
        lines.append("近期相关对话:")
        for m in mentions[:3]:
            lines.append(f"  · 与 {m.get('with', '?')}: {m.get('topic', '')}")
    if not lines:
        return ""
    lines.append("原则: 先回应找你的人，再主动开新话题或写长文。")
    return "\n".join(lines)


def suggest_inbox_action(engine, char_name: str, inbox: Optional[dict] = None) -> Optional[dict]:
    """If inbox demands a reply, return an override decision; else None."""
    inbox = inbox if inbox is not None else build_inbox(engine, char_name)
    messages = inbox.get("messages") or []
    if messages:
        # Prefer an Available sender; otherwise still target the first
        chosen = None
        for msg in messages:
            sender = msg.get("from") or ""
            other = engine.characters.get(sender)
            if other and other.can_be_interrupted("normal"):
                chosen = msg
                break
        if chosen is None:
            chosen = messages[0]
        sender = chosen.get("from") or ""
        if sender and sender in engine.characters:
            return {
                "type": "socialize",
                "target": sender,
                "topic": str(chosen.get("message") or "")[:100],
                "label": f"💬 回复 {sender} 的留言",
                "inbox_reply": True,
            }

    collabs = inbox.get("collabs") or []
    if collabs:
        c0 = collabs[0]
        partners = [p for p in (c0.get("partners") or []) if p in engine.characters]
        if partners:
            # Prefer available partner
            target = partners[0]
            for p in partners:
                other = engine.characters.get(p)
                if other and other.can_be_interrupted("normal"):
                    target = p
                    break
            return {
                "type": "socialize",
                "target": target,
                "topic": c0.get("topic") or "",
                "label": f"💬 推进与 {target} 的协作",
                "inbox_reply": False,
            }
    return None


def inbox_weight_bias(inbox: dict) -> dict[str, float]:
    """Nudge phase weights when inbox has unfinished social obligations."""
    if not inbox or not inbox.get("has_priority"):
        return {}
    return {
        "socialize": 2.2,
        "gather": 1.3,
        "tool_write_paper": 0.55,
        "study": 0.85,
        "entertain": 0.7,
    }


def community_inbox_snapshot(engine) -> str:
    """Compact multi-character inbox for the observer guide."""
    lines = []
    for name in engine.characters:
        inbox = build_inbox(engine, name)
        n_msg = len(inbox.get("messages") or [])
        n_col = len(inbox.get("collabs") or [])
        if n_msg or n_col:
            lines.append(f"- {name}: {n_msg} 条未读留言, {n_col} 个活跃协作")
    return "\n".join(lines) if lines else "- （无人积压留言）"
