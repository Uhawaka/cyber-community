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


def academic_query_hint(domains: list | None = None, focus: str = "") -> str:
    """Hint for building English search queries."""
    bits = []
    if domains:
        bits.append("domains: " + ", ".join(str(d) for d in domains[:5]))
    if focus:
        bits.append("focus: " + focus[:120])
    extra = (" (" + "; ".join(bits) + ")") if bits else ""
    return (
        "Generate a precise English academic search query (3–8 words)"
        f"{extra}. Prefer literature nouns (L-functions, random matrices, Galois, …). "
        "Do not use Chinese in the query."
    )


def format_domains_for_query(domains: list | None, focus: str = "", fallback: str = "") -> list[str]:
    """Build English observation/search query strings from living domains + focus."""
    queries: list[str] = []
    focus = " ".join((focus or "").split())
    if focus:
        # Prefer English-looking focus; strip obvious Chinese-only noise lightly
        queries.append(focus[:80])
    for d in domains or []:
        q = str(d).replace("_", " ").strip()
        if q:
            queries.append(q)
    if not queries and fallback:
        queries.append(str(fallback).replace("_", " "))
    # dedupe
    out, seen = [], set()
    for q in queries:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
    return out[:6]
