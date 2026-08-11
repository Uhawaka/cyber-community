"""Request Board — a community marketplace for needs and offers.

Not scripted interactions. Organic: someone posts a need, someone else
browses, finds it interesting, responds. Like a bulletin board or Slack.

Types:
  HELP: "Can anyone verify this inequality for parameters X,Y?"
  REVIEW: "I wrote a draft — anyone willing to read it?"
  DISCUSS: "I'm thinking about X — anyone want to explore this together?"
  OFFER: "I found an interesting arxiv paper on X — sharing in case useful"
  SOCIAL: "Anyone free for a coffee break?"
"""

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Request:
    """A posted request/offer in the community."""

    id: str
    author: str
    type: str          # help | review | discuss | offer | social
    content: str       # what they need/offer
    urgency: str = "normal"  # low | normal | high
    day: int = 1
    respondents: list = field(default_factory=list)
    status: str = "open"  # open | fulfilled | expired
    ttl_days: int = 2     # expires after N days

    def respond(self, responder: str, response: str = ""):
        self.respondents.append({"name": responder, "response": response})
        if len(self.respondents) >= 1:
            self.status = "fulfilled"

    def summary(self) -> str:
        emoji = {"help": "🆘", "review": "📄", "discuss": "💡", "offer": "📢", "social": "☕"}
        e = emoji.get(self.type, "📋")
        return f"{e} [{self.author}] {self.content[:60]}"


# ═══════════════════════════════════════════════════════════════
# Request generation — based on character state
# ═══════════════════════════════════════════════════════════════

REQUEST_TEMPLATES = {
    "help": [
        "帮我验证一个不等式——参数 {param} 时它是否成立？",
        "我写了一段代码验证 {topic}，但结果和预期差了一个量级——谁能帮我看一下？",
        "需要有人帮我算一下 {topic} 在 {param} 参数下的渐近行为",
    ],
    "review": [
        "刚写完一个关于 {topic} 的笔记——有人愿意读一下吗？",
        "我有个猜想需要被挑战——谁有空来质疑我十分钟？",
    ],
    "discuss": [
        "我最近在想 {topic}——有人想一起推一下吗？",
        "有个想法还不成熟——{topic} 和另一个领域可能有联系，想找人聊聊",
    ],
    "offer": [
        "刚在 arXiv 上看到一篇论文讲 {topic}——可能对大家有用",
        "我发现一个有趣的数据模式——{topic} 的分布在某参数下出现异常",
    ],
    "social": [
        "有人想去花园坐一会儿吗？我需要离开屏幕一下",
        "谁在大厅？我去泡杯茶——虚拟的那种",
    ],
}


def generate_request(char_name: str, char_state: dict, topics: list) -> Request:
    """Generate a request based on character's current state and research."""

    # Choose type based on state
    if char_state.get("stuck", False):
        req_type = random.choice(["help", "discuss"])
    elif char_state.get("excited", False):
        req_type = random.choice(["offer", "discuss"])
    elif char_state.get("lonely", False) or random.random() < 0.2:
        req_type = "social"
    else:
        req_type = random.choice(["help", "review", "discuss", "offer"])

    # Pick template
    templates = REQUEST_TEMPLATES.get(req_type, REQUEST_TEMPLATES["social"])
    template = random.choice(templates)

    # Fill template
    topic = random.choice(topics) if topics else "最近的研究"
    param = random.choice(["ξ=1.8", "N=10^6", "α=0.5", "T=100", "κ=1.2"])
    content = template.format(topic=topic, param=param)

    rid = f"req_{random.randint(1000, 9999)}"
    return Request(id=rid, author=char_name, type=req_type, content=content)


class RequestBoard:
    """Shared space where community members post and browse requests."""

    def __init__(self, characters: dict):
        self.characters = characters
        self.requests: list[Request] = []
        self.fulfilled: list[Request] = []

    def post(self, request: Request):
        """Post a new request."""
        self.requests.append(request)

    def browse(self, char_name: str) -> Optional[Request]:
        """A character browses the board — what catches their eye?"""
        open_requests = [r for r in self.requests
                         if r.status == "open" and r.author != char_name]

        if not open_requests:
            return None

        # Weight by: same topics, urgency, recency
        weights = []
        for r in open_requests:
            w = 1.0
            if r.urgency == "high":
                w *= 2.0
            if r.type in ("discuss", "help"):
                w *= 1.5  # more engaging
            weights.append(w)

        total = sum(weights)
        if total == 0:
            return None
        probs = [w / total for w in weights]
        return random.choices(open_requests, weights=probs, k=1)[0]

    def fulfill(self, request_id: str, responder: str, response: str = ""):
        """Someone responds to a request."""
        for r in self.requests:
            if r.id == request_id:
                r.respond(responder, response)
                if r.status == "fulfilled":
                    self.requests.remove(r)
                    self.fulfilled.append(r)
                return r
        return None

    def expire_old(self, current_day: int):
        """Remove expired requests."""
        self.requests = [r for r in self.requests
                         if current_day - r.day < r.ttl_days]

    def get_context(self) -> str:
        """Board context for prompts."""
        open_reqs = self.requests[-6:] if self.requests else []
        if not open_reqs:
            return ""

        lines = ["## 社区请求板"]
        for r in open_reqs[-4:]:
            lines.append(f"  {r.summary()}")
        return "\n".join(lines)

    def generate_and_post(self, char_name: str, char_state: dict, topics: list):
        """Generate a contextual request and post it."""
        if random.random() < 0.3:  # 30% chance per call
            req = generate_request(char_name, char_state, topics)
            self.post(req)
            return req
        return None
