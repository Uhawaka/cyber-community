"""Work obligations — SOP gates, not prompt sermons.

Borrowed from MetaGPT (`Code = SOP(Team)`) and ChatDev phase exits:
talk is cheap; the next action is forced by unfinished work, not by mood.

Gates
-----
1. Search hits go on an unread shelf. Memory must not say「读了」. Next
   action (or an immediate follow-up event) is read_arxiv on a real id.
2. Production artifacts need a citable object: arXiv id, a named curve /
   LMFDB label, or the character's working_object.
3. After COLLISION_FORCE_AFTER social collisions with no tool, return to study.
4. Public traces (collision-as-work, board, echo) must name an object.
   Otherwise the character may only ask a question or go back to work.
"""

from __future__ import annotations

import re
from typing import Optional

COLLISION_FORCE_AFTER = 3
UNREAD_CAP = 6
READ_CAP = 12

ARXIV_ID_RE = re.compile(
    r"(?:arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+/\d{7}(?:v\d+)?)",
    re.I,
)
# Cremona / LMFDB-style labels and explicit Weierstrass equations
CURVE_RE = re.compile(
    r"\b(?:LMFDB|Cremona)\b|"
    r"\b\d{1,3}[a-z]\d{1,2}\b|"
    r"y\s*\^\s*2\s*=|y²\s*=",
    re.I,
)
QUESTION_RE = re.compile(r"[?？]|吗[。？]?|呢[。？]?|哪一步|缺什么|卡在哪")
META_OBJECT_RE = re.compile(
    r"从.{0,16}转向|作为检验|核心问题仍是|先验证搜索|检验统计量|"
    r"which seed|种子货架|工作规范|open problems",
    re.I,
)
_OBJECT_STOP = frozenset({
    "theorem", "series", "working", "unit", "problem", "class", "function",
    "the", "and", "for", "with", "from", "this", "that", "reduction",
    "hypothesis", "conjecture", "object", "today", "still", "keep",
    "board", "week", "only", "analysis", "focus", "claim",
})
_SHORT_MARKS = frozenset({"sat", "np", "hjb", "bkm", "ym", "rh", "ns"})

MISSION_QUERY_RE = re.compile(
    r"open problems mathematics|"
    r"Get one member|Deliver one|Cite one seed|Make the seed|"
    r"Write and stress|shelf-cited|Open a Clay|"
    r"Attach a killable|someone cites Clay",
    re.I,
)


def extract_arxiv_ids(text: str) -> list[str]:
    seen, out = set(), []
    for m in ARXIV_ID_RE.finditer(text or ""):
        aid = m.group(1)
        if aid not in seen:
            seen.add(aid)
            out.append(aid)
    return out


def looks_like_mission_query(text: str) -> bool:
    return bool(MISSION_QUERY_RE.search(text or ""))


def agent_search_query(text: str) -> str:
    """Query the character actually wrote. Empty if slogan / engine-unusable."""
    q = " ".join((text or "").split())
    if not q or looks_like_mission_query(q):
        return ""
    if re.search(r"[\u4e00-\u9fff]", q):
        latin = re.sub(r"[\u4e00-\u9fff]+", " ", q)
        latin = re.sub(r"\s+", " ", latin).strip(" .,;:|-")
        if len(latin) < 4:
            return ""
        return latin[:160]
    return q[:160]


def salvage_search_query(query: str, focus: str = "", domains=None) -> str:
    """Drop mission-card / slogan queries; fall back to living domains."""
    q = (query or "").strip()
    if q and not looks_like_mission_query(q):
        return q
    foc = (focus or "").strip()
    if foc and not looks_like_mission_query(foc) and not re.search(r"[\u4e00-\u9fff]", foc):
        return foc
    bits = []
    for d in domains or []:
        s = str(d).replace("_", " ").strip()
        if s and s.lower() not in {b.lower() for b in bits}:
            bits.append(s)
    return " ".join(bits[:4])


def artifact_has_source(text: str, char=None) -> bool:
    """True if the note cites an arXiv id, a known read, a curve, or a named object."""
    blob = text or ""
    if extract_arxiv_ids(blob):
        return True
    if CURVE_RE.search(blob):
        return True
    if char is not None:
        known = list(getattr(char.state, "read_arxiv_ids", None) or [])
        for aid in known:
            if aid and aid in blob:
                return True
        unread = getattr(char.state, "unread_arxiv", None) or []
        for hit in unread:
            aid = (hit.get("arxiv_id") or hit.get("id") or "")
            if aid and aid in blob:
                return True
        if speech_mentions_object(blob, named_objects_for(char)):
            return True
    return False


def note_search_hits(char, hits: list) -> list[dict]:
    """Put search hits on the unread shelf. Returns normalized hits kept."""
    shelf = list(getattr(char.state, "unread_arxiv", None) or [])
    known = {h.get("arxiv_id") for h in shelf}
    known.update(getattr(char.state, "read_arxiv_ids", None) or [])
    added = []
    for raw in hits or []:
        if isinstance(raw, str):
            aid, title, cat = raw, "", ""
        else:
            aid = str(raw.get("arxiv_id") or raw.get("id") or "").strip()
            title = str(raw.get("title") or "")[:80]
            cat = str(raw.get("primary_category") or raw.get("category") or "")[:32]
        if not aid or aid in known:
            continue
        rec = {"arxiv_id": aid, "title": title}
        if cat:
            rec["category"] = cat
        shelf.append(rec)
        known.add(aid)
        added.append(rec)
    char.state.unread_arxiv = shelf[-UNREAD_CAP:]
    return added


def note_read(char, arxiv_id: str) -> None:
    aid = (arxiv_id or "").strip()
    if not aid:
        return
    shelf = [
        h for h in (getattr(char.state, "unread_arxiv", None) or [])
        if h.get("arxiv_id") != aid
    ]
    char.state.unread_arxiv = shelf
    seen = list(getattr(char.state, "read_arxiv_ids", None) or [])
    if aid not in seen:
        seen.append(aid)
    char.state.read_arxiv_ids = seen[-READ_CAP:]
    char.state.collision_streak = 0


def note_collision(char) -> None:
    char.state.collision_streak = int(getattr(char.state, "collision_streak", 0) or 0) + 1


def note_tool(char) -> None:
    char.state.collision_streak = 0


def _fold_object(text: str) -> str:
    """Lowercase and drop punctuation so 's=1/2.' still matches 's=1/2'."""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", (text or "").lower()).strip()


def distinctive_tokens(obj: str) -> list[str]:
    """Proper-name-ish tokens an utterance can point at."""
    raw = obj or ""
    out, seen = [], set()

    def _add(tok: str) -> None:
        t = (tok or "").strip()
        if not t or t in seen or t in _OBJECT_STOP:
            return
        seen.add(t)
        out.append(t)

    for m in re.findall(r"[A-Za-z][A-Za-z0-9]+(?:[-–—][A-Za-z0-9]+)+", raw):
        _add(_fold_object(m))
    for w in _fold_object(raw).split():
        if w in _SHORT_MARKS or (len(w) >= 5 and w not in _OBJECT_STOP):
            _add(w)
    return out


def _object_rank(text: str) -> int:
    t = " ".join((text or "").split())
    if not t or looks_like_mission_query(t) or META_OBJECT_RE.search(t):
        return 0
    return len(distinctive_tokens(t))


def adopt_working_object(char, text: str) -> None:
    """Remember the named object this character is actually on.

    Refuse slogans / 「从验证转向」meta. Do not overwrite a sharper name
    with a worse one.
    """
    t = " ".join((text or "").split())[:80].rstrip(".;,。；：:")
    if _object_rank(t) == 0:
        return
    cur = (getattr(char.state, "working_object", None) or "").strip()
    if cur and _object_rank(t) < _object_rank(cur):
        return
    char.state.working_object = t


def named_objects_for(char) -> list[str]:
    """Objects this character may legally point at in public."""
    if char is None:
        return []
    out, seen = [], set()
    state = getattr(char, "state", None)
    for raw in (
        getattr(state, "working_object", None),
        getattr(state, "current_focus", None),
    ):
        t = " ".join((raw or "").split())[:80]
        if not t or looks_like_mission_query(t) or META_OBJECT_RE.search(t):
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    for aid in getattr(state, "read_arxiv_ids", None) or []:
        if aid and aid not in seen:
            seen.add(aid)
            out.append(str(aid))
    return out


def objects_among(*chars) -> list[str]:
    seen, out = set(), []
    for char in chars:
        for obj in named_objects_for(char):
            key = obj.lower()
            if key not in seen:
                seen.add(key)
                out.append(obj)
    return out


def public_topic(char, fallback: str = "") -> str:
    """Topic that may go on a collision / gathering. Empty = no object."""
    objs = named_objects_for(char)
    if objs:
        return objs[0]
    t = " ".join((fallback or "").split())[:80]
    if t and not looks_like_mission_query(t):
        return t
    return ""


def speech_mentions_object(text: str, objects: list[str]) -> bool:
    blob = text or ""
    if extract_arxiv_ids(blob) or CURVE_RE.search(blob):
        return True
    folded_blob = _fold_object(blob)
    for obj in objects or []:
        raw = (obj or "").strip().rstrip(".;,。；：:")
        if not raw:
            continue
        if len(raw) >= 4 and raw.lower() in blob.lower():
            return True
        if 0 < len(raw) < 4 and raw in blob:
            return True
        folded = _fold_object(raw)
        if len(folded) >= 8 and folded in folded_blob:
            return True
        marks = distinctive_tokens(raw)
        if any(m in folded_blob for m in marks if " " in m or len(m) >= 5):
            return True
        shorts = [m for m in marks if m in _SHORT_MARKS]
        if shorts and any(s in folded_blob for s in shorts) and any(
            m in folded_blob for m in marks if m not in _SHORT_MARKS
        ):
            return True
    return False


def looks_like_question(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and len(t) < 220 and bool(QUESTION_RE.search(t))


def public_speech_ok(text: str, *chars) -> bool:
    """True if this text may go on the board / echo / production."""
    if speech_mentions_object(text, objects_among(*chars)):
        return True
    for char in chars:
        if char is not None and artifact_has_source(text, char):
            return True
    return False


def format_object_reminder(*chars) -> str:
    objs = objects_among(*chars)
    if not objs:
        return (
            "你现在没有正在对付的具体对象。"
            "对外只能问一个具体问题，或回去对着一个点得名的对象干活。"
            "不要发表见解。"
        )
    return "对外发言必须点名对象，或只问一个问题。对象: " + "; ".join(objs[:4])


def forced_decision(char) -> Optional[dict]:
    """SOP next action, or None if the character is free to inbox / rhythm."""
    unread = list(getattr(char.state, "unread_arxiv", None) or [])
    if unread:
        hit = unread[0]
        aid = hit.get("arxiv_id") or ""
        return {
            "type": "tool",
            "tool": "read_arxiv",
            "arxiv_id": aid,
            "topic": (getattr(char.state, "current_focus", None) or hit.get("title") or ""),
            "label": f"📖 深读未读 {aid}",
            "forced": "unread",
        }
    if int(getattr(char.state, "collision_streak", 0) or 0) >= COLLISION_FORCE_AFTER:
        topic = (
            getattr(char.state, "working_object", None)
            or getattr(char.state, "current_focus", None)
            or ""
        )
        return {
            "type": "study",
            "topic": topic,
            "label": "📖 连聊后回到自己的问题",
            "forced": "collision_streak",
        }
    return None


def format_work_briefing(char) -> str:
    unread = list(getattr(char.state, "unread_arxiv", None) or [])
    reads = list(getattr(char.state, "read_arxiv_ids", None) or [])
    streak = int(getattr(char.state, "collision_streak", 0) or 0)
    obj = (getattr(char.state, "working_object", None) or "").strip()
    if not unread and not reads and streak < 2 and not obj:
        return ""
    lines = ["## 未完成的工作义务（先于闲聊）"]
    if obj:
        lines.append("正在对付的对象: " + obj)
    if unread:
        bits = [f"{h.get('arxiv_id')} {h.get('title', '')[:40]}".strip() for h in unread[:4]]
        lines.append("未深读（检索命中，还不算读过）: " + "; ".join(bits))
    if reads:
        lines.append("已深读: " + ", ".join(reads[-4:]))
    if streak:
        lines.append(f"连续对话未对着对象干活: {streak}（≥{COLLISION_FORCE_AFTER} 则回到问题）")
    return "\n".join(lines)
