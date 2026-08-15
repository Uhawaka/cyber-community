"""Language policy for LLM I/O.

Config (world/soul/research) stays English for technical accuracy.
Character dialogue may be Chinese, but technical terms must stay English.

Why:
  - Forced Chinese translations of math terms are often wrong or opaque
  - Chinese idioms translate poorly into English academic talk
  - Digital researchers should speak the literature's native nouns
"""

from __future__ import annotations

from typing import Optional


def speech_language(config: Optional[dict] = None, default: str = "zh") -> str:
    cfg = config or {}
    lang = (cfg.get("speech_language") or default or "zh").lower()
    if lang.startswith("en"):
        return "en"
    return "zh"


def term_policy_block(lang: str = "zh") -> str:
    """Short rule block injected into system / user prompts."""
    if lang.startswith("en"):
        return (
            "## Language\n"
            "Write in clear English. Prefer standard technical nouns from the literature. "
            "Do not invent awkward translations of Chinese idioms; say the plain meaning.\n"
        )
    return (
        "## 语言约定（重要）\n"
        "叙述与对话用中文；专业术语、定理名、人名、期刊名、软件/库名保留英文原文。\n"
        "例：写 L-function / sieve / random matrix / Annals，不要硬译成生僻中文。\n"
        "少用成语与网文腔；说清楚推理即可。中英可以同句混用，术语侧以英文为准。\n"
    )


def reply_rule(lang: str = "zh") -> str:
    if lang.startswith("en"):
        return (
            "Reply in English. Keep technical terms in their standard English form. "
            "Length follows the thought — one sentence or a careful paragraph."
        )
    return (
        "回复用中文写叙述；专业术语/定理/期刊/人名保留英文原文，不要硬译。"
        "少用成语。长度取决于内容——可以是一句话，也可以是一段深入推理。"
    )


def think_system(character_name: str, lang: str = "zh") -> str:
    base = f"You are {character_name}."
    if lang.startswith("en"):
        return f"{base} Respond in character, in English. Keep technical terms standard."
    return (
        f"{base} 用角色身份回答。"
        "叙述用中文，专业术语保留英文原文，不要硬译成生僻中文。"
    )


def academic_query_hint(
    domains: list | None = None,
    focus: str = "",
    *,
    channel: str = "arxiv",
    lit_cfg: dict | None = None,
) -> str:
    """Hint for building literature search queries (delegates to literature policy)."""
    from engine.literature import literature_query_hint

    return literature_query_hint(domains, focus, channel=channel, lit_cfg=lit_cfg)


def looks_like_cjk_query(query: str) -> bool:
    from engine.literature import looks_like_cjk

    return looks_like_cjk(query)


def sanitize_academic_query(
    query: str,
    focus: str = "",
    fallback: str = "research open problems",
    *,
    extra_lexicon: list | None = None,
) -> str:
    """Force an English frontier query when the model emits Chinese slogans.

    Thin wrapper over engine.literature — never returns a CJK-heavy string.
    Default fallback is domain-agnostic; worlds set literature.fallback_query.
    """
    from engine.literature import to_frontier_english

    eng, _ = to_frontier_english(
        query, focus=focus, fallback=fallback, extra_lexicon=extra_lexicon
    )
    return eng


def format_domains_for_query(domains: list | None, focus: str = "", fallback: str = "") -> list[str]:
    """Build English observation/search query strings from living domains + focus."""
    queries: list[str] = []
    focus = " ".join((focus or "").split())
    fb = fallback or "research open problems"
    if focus:
        queries.append(sanitize_academic_query(focus, focus=focus, fallback=fb))
    for d in domains or []:
        q = str(d).replace("_", " ").strip()
        if q and not looks_like_cjk_query(q):
            queries.append(q)
    if not queries and fallback:
        queries.append(str(fallback).replace("_", " "))
    out, seen = [], set()
    for q in queries:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out[:6]
