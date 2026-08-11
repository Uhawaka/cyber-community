"""Observation Pipeline: characters observe the human world.

The key missing piece that makes the community "observers of humanity."
Characters periodically look at what humans are publishing (arxiv),
get excited/curious/skeptical, and bring interesting findings back
to the community for discussion and synthesis.

This closes the loop:
  Human World → Observation → Internal Processing → Discussion → Production
"""


OBSERVATION_SOURCES = [
    {
        "name": "arxiv_recent",
        "description": "搜索 arXiv 上最新的数学论文",
        "trigger": "periodic",  # every N virtual hours
        "frequency_hours": 12,
        "query_templates": [
            "number theory recent",
            "prime gaps distribution",
            "Riemann zeta zeros",
            "random matrix theory number theory",
            "analytic number theory sieve methods",
        ],
    },
    {
        "name": "arxiv_specific",
        "description": "搜索与角色当前研究相关的论文",
        "trigger": "study_milestone",  # after N study steps
        "frequency_steps": 8,
    },
]


def get_observation_queries(char_research: dict, char_domain: str) -> list:
    """Generate search queries based on what a character is working on.
    Returns list of (query_type, query) tuples — 'arxiv' or 'web'."""
    queries = []
    project = char_research.get("project", "")
    
    # arXiv queries (academic)
    if "质数" in project or "prime" in project.lower():
        queries.append(("arxiv", "prime number distribution gaps"))
    if "筛法" in project or "sieve" in project.lower():
        queries.append(("arxiv", "sieve method recent advances"))
    if "湍流" in project or "Navier" in project:
        queries.append(("arxiv", "Navier-Stokes regularity statistical"))
    if "范畴" in char_domain or "category" in char_domain.lower():
        queries.append(("arxiv", "applied category theory recent"))
    
    # Web queries (broader: news, forums, Wikipedia)
    if "质数" in project or "prime" in project.lower():
        queries.append(("web", "质数 最新进展 数学"))
    if "金融" in project or "quant" in project.lower() or "trading" in project.lower():
        queries.append(("web", "量化交易 最新动态"))
    if "湍流" in project or "physics" in char_domain.lower():
        queries.append(("web", "流体力学 最新研究"))
    if "文学" in char_domain or "诗" in project:
        queries.append(("web", "现代诗歌 创作趋势"))
    
    # Default web query for general awareness
    if char_domain:
        queries.append(("web", f"{char_domain} 最新动态"))
    
    if not queries:
        queries.append(("arxiv", char_domain.replace("_", " ")))
    
    return queries[:6]  # max 6 queries (mix of arxiv + web)
