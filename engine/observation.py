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
    """Generate search queries based on what a character is working on."""
    queries = []
    project = char_research.get("project", "")
    stuck = char_research.get("stuck_point", "")
    
    if "质数" in project or "prime" in project.lower():
        queries.append("prime number distribution gaps")
    if "筛法" in project or "sieve" in project.lower():
        queries.append("sieve method recent advances")
    if "湍流" in project or "Navier" in project:
        queries.append("Navier-Stokes regularity statistical")
    if "范畴" in char_domain or "category" in char_domain.lower():
        queries.append("applied category theory recent")
    if "zeta" in project.lower() or "黎曼" in project:
        queries.append("Riemann zeta function zeros distribution")
    
    if not queries:
        queries.append(char_domain.replace("_", " "))
    
    return queries[:3]  # max 3 queries
