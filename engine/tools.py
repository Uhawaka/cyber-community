"""Tool system for character communities.

Characters use tools as natural extensions of their abilities:
- run_code: Write and execute Python to test conjectures
- write_paper: Produce research notes/papers
- search_arxiv: Observe what humans are publishing
- read_arxiv: Deep-read an arXiv paper (full abstract + HTML/TeX math body)
- search_web: Search the broader web (LLM-synthesized; pluggable real backends)

Tools are defined per-world in community.yaml. The ToolRegistry loads
available tools and provides execution with artifact saving.
"""

import ast
import html as html_lib
import io
import os
import json
import re
import subprocess
import tarfile
import tempfile
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import Optional


# Modules allowed inside sandboxed run_code (scientific / stdlib safe subset)
_ALLOWED_MODULES = frozenset({
    "math", "cmath", "random", "statistics", "decimal", "fractions",
    "itertools", "functools", "operator", "collections", "heapq",
    "bisect", "array", "copy", "dataclasses", "typing", "abc",
    "string", "re", "json", "csv", "time", "datetime", "calendar",
    "numpy", "np", "scipy", "sympy", "pandas", "matplotlib",
    "mpl_toolkits", "sklearn", "networkx",
})

_FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input",
    "breakpoint", "exit", "quit", "help", "memoryview",
})

_FORBIDDEN_ATTRS = frozenset({
    "__subclasses__", "__bases__", "__globals__", "__code__",
    "__builtins__", "__loader__", "__import__", "system",
    "popen", "walk", "remove", "unlink", "rmtree",
})


def validate_sandboxed_code(code: str) -> Optional[str]:
    """Static check for dangerous patterns. Returns error message or None if OK."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"语法错误: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in _ALLOWED_MODULES:
                    return f"沙箱不允许导入模块: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                return "沙箱不允许相对导入"
            root = node.module.split(".")[0]
            if root not in _ALLOWED_MODULES:
                return f"沙箱不允许导入模块: {node.module}"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_NAMES:
                return f"沙箱禁止调用: {func.id}()"
            if isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_ATTRS:
                return f"沙箱禁止属性调用: .{func.attr}"
        elif isinstance(node, ast.Attribute):
            if node.attr in _FORBIDDEN_ATTRS:
                return f"沙箱禁止访问: .{node.attr}"
        elif isinstance(node, ast.Name) and node.id in ("__builtins__", "__loader__"):
            return f"沙箱禁止访问: {node.id}"

    return None


_ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html)/|ar5iv\.labs\.arxiv\.org/html/)?"
    r"(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)",
    re.I,
)
_MATH_LINE_RE = re.compile(
    r"(\\begin\{(?:equation|align|thm|theorem|lemma|proof|proposition|corollary)"
    r"|\\\[|\$\$|\\mathbb|\\mathcal|Theorem|Lemma|Proposition|Corollary|"
    r"Conjecture|Proof\.|Claim\.)",
    re.I,
)


def normalize_arxiv_id(raw: str) -> str:
    """Extract a bare arXiv id from a URL or id string."""
    s = (raw or "").strip()
    if not s:
        return ""
    m = _ARXIV_ID_RE.search(s.replace(" ", ""))
    if m:
        return m.group("id")
    # already bare?
    if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", s):
        return s
    return ""


def _http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CyberCommunity/1.0 (research; +https://github.com/)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _html_to_readable(raw_html: str, max_chars: int = 7000) -> str:
    """Strip tags; keep enough body that formulas/definitions survive."""
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)</(div|h[1-6]|li|tr)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if len(text) > max_chars:
        # Prefer a window denser in math markers
        best, best_score = text[:max_chars], -1
        step = max(400, max_chars // 4)
        for start in range(0, max(1, len(text) - max_chars), step):
            chunk = text[start : start + max_chars]
            score = len(_MATH_LINE_RE.findall(chunk))
            if score > best_score:
                best, best_score = chunk, score
        text = best + "\n…[truncated]"
    return text


def _tex_math_excerpts(tex: str, max_chars: int = 5000) -> str:
    lines = tex.splitlines()
    picked: list[str] = []
    i = 0
    while i < len(lines) and sum(len(x) + 1 for x in picked) < max_chars:
        line = lines[i]
        if _MATH_LINE_RE.search(line) or (line.strip().startswith("%") is False and "$" in line):
            block = [line]
            # take a few neighbors for context
            for j in range(i + 1, min(i + 8, len(lines))):
                block.append(lines[j])
                if re.search(r"\\end\{(?:equation|align|thm|theorem|lemma|proof)", lines[j], re.I):
                    break
            picked.extend(block)
            picked.append("")
            i += max(1, len(block))
        else:
            i += 1
    body = "\n".join(picked).strip()
    if not body:
        # fallback: head of file without comments
        body = "\n".join(
            ln for ln in lines[:120]
            if ln.strip() and not ln.strip().startswith("%")
        )
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return body


def fetch_arxiv_html_body(arxiv_id: str, max_chars: int = 7000) -> tuple[str, str]:
    """Return (source_label, readable_text) from ar5iv / arxiv HTML."""
    aid = normalize_arxiv_id(arxiv_id)
    if not aid:
        return "", ""
    bare = re.sub(r"v\d+$", "", aid)
    candidates = [
        ("ar5iv", f"https://ar5iv.labs.arxiv.org/html/{bare}"),
        ("arxiv_html", f"https://arxiv.org/html/{bare}"),
    ]
    for label, url in candidates:
        try:
            raw = _http_get(url, timeout=25).decode("utf-8", errors="replace")
            if "404" in raw[:200].lower() and "not found" in raw[:800].lower():
                continue
            text = _html_to_readable(raw, max_chars=max_chars)
            if len(text) > 400:
                return label, text
        except Exception:
            continue
    return "", ""


def fetch_arxiv_tex_excerpts(arxiv_id: str, max_chars: int = 5000) -> str:
    """Download arXiv e-print source and extract math-heavy TeX excerpts."""
    aid = normalize_arxiv_id(arxiv_id)
    if not aid:
        return ""
    bare = re.sub(r"v\d+$", "", aid)
    url = f"https://arxiv.org/e-print/{bare}"
    try:
        data = _http_get(url, timeout=30)
    except Exception:
        return ""
    # Single .gz tex
    if data[:2] == b"\x1f\x8b":
        import gzip
        try:
            tex = gzip.decompress(data).decode("utf-8", errors="replace")
            if "\\documentclass" in tex or "\\begin{document}" in tex or "$" in tex:
                return _tex_math_excerpts(tex, max_chars=max_chars)
        except Exception:
            pass
    # tar archive
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            tex_members = [
                m for m in tar.getmembers()
                if m.isfile()
                and m.name.lower().endswith((".tex", ".ltx"))
                and not m.name.lower().endswith((".cls", ".sty"))
                and "/." not in m.name
                and not any(
                    skip in m.name.lower()
                    for skip in ("compositio.cls", "smfthm", "/cls/", "standalone")
                )
            ]
            # Prefer paper-like names over package junk
            def _rank(m):
                n = m.name.lower()
                score = 0
                if n.endswith(".tex"):
                    score -= 10
                if any(k in n for k in ("main", "paper", "ms", "article", "bsd", "rh")):
                    score -= 20
                if n.count("/") > 2:
                    score += 5
                score += min(m.size // 5000, 20)  # prefer larger content files slightly
                # but penalize huge class dumps
                if m.size > 200_000:
                    score += 50
                return (score, -m.size)

            tex_members.sort(key=_rank)
            chunks = []
            for m in tex_members[:4]:
                f = tar.extractfile(m)
                if not f:
                    continue
                tex = f.read().decode("utf-8", errors="replace")
                # Skip if this looks like a class/package, not a paper
                head = tex[:800].lower()
                if "\\providespackage" in head or "\\ProvidesClass" in tex[:800] or (
                    "\\loadclass" in head and "\\title" not in tex[:3000].lower()
                ):
                    if "\\begin{document}" not in tex.lower() and "\\title" not in tex[:5000].lower():
                        continue
                chunks.append(_tex_math_excerpts(tex, max_chars=max_chars // 2))
            body = "\n\n".join(c for c in chunks if c)
            return body[:max_chars]
    except Exception:
        return ""


def parse_arxiv_atom(xml_data: str) -> list[dict]:
    """Parse arXiv Atom API XML into paper dicts with full abstracts."""
    root = ET.fromstring(xml_data)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    papers = []
    for entry in root.findall("atom:entry", ns):
        title_elem = entry.find("atom:title", ns)
        summary_elem = entry.find("atom:summary", ns)
        id_elem = entry.find("atom:id", ns)
        title_text = (title_elem.text or "无标题").strip()
        title_text = re.sub(r"\s+", " ", title_text)
        summary_text = (summary_elem.text or "").strip()
        summary_text = re.sub(r"\s+", " ", summary_text)
        raw_id = (id_elem.text or "").strip() if id_elem is not None else ""
        aid = normalize_arxiv_id(raw_id) or normalize_arxiv_id(title_text)
        authors = []
        for author in entry.findall("atom:author", ns):
            name_elem = author.find("atom:name", ns)
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())
        published = entry.find("atom:published", ns)
        papers.append({
            "arxiv_id": aid,
            "title": title_text,
            "authors": authors,
            "summary": summary_text,
            "published": (published.text or "")[:10] if published is not None else "",
            "abs_url": f"https://arxiv.org/abs/{aid}" if aid else "",
            "pdf_url": f"https://arxiv.org/pdf/{aid}.pdf" if aid else "",
            "html_url": (
                f"https://ar5iv.labs.arxiv.org/html/{re.sub(r'v\d+$', '', aid)}"
                if aid else ""
            ),
        })
    return papers


class ToolResult:
    """Result of a tool execution."""

    def __init__(self, success: bool, output: str, artifact_path: Optional[str] = None,
                 metadata: Optional[dict] = None):
        self.success = success
        self.output = output
        self.artifact_path = artifact_path
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "artifact_path": self.artifact_path,
            "metadata": self.metadata,
        }


class ToolRegistry:
    """Manages available tools for a community world."""

    def __init__(
        self,
        tool_configs: list[dict],
        output_dir: Path,
        llm=None,
        *,
        world_frame: dict | None = None,
        config: dict | None = None,
    ):
        self.tools = {}
        self.output_dir = output_dir
        self.llm = llm  # for tools that need LLM-generated content
        self.world_frame = world_frame or {}
        self.config = config or {}

        for cfg in tool_configs:
            name = cfg["name"]
            if name == "run_code":
                self.tools[name] = self._make_run_code(cfg)
            elif name == "write_paper":
                self.tools[name] = self._make_write_paper(cfg)
            elif name == "search_arxiv":
                self.tools[name] = self._make_search_arxiv(cfg)
            elif name == "read_arxiv":
                self.tools[name] = self._make_read_arxiv(cfg)
            elif name == "search_web":
                self.tools[name] = self._make_search_web(cfg)

    def get_tool(self, name: str):
        return self.tools.get(name)

    def list_tools(self) -> list[dict]:
        """Return tool descriptions for LLM prompts."""
        descriptions = []
        for name, (desc, _) in self.tools.items():
            descriptions.append({"name": name, "description": desc})
        return descriptions

    def execute(self, tool_name: str, char_name: str, params: dict) -> ToolResult:
        """Execute a tool by name."""
        tool = self.tools.get(tool_name)
        if tool is None:
            return ToolResult(False, f"未知工具: {tool_name}")
        _, executor = tool
        return executor(char_name, params)

    # ─── Tool Implementations ─────────────────────────────────

    def _make_run_code(self, cfg: dict):
        desc = cfg.get("description", "编写并运行Python代码来验证数学猜想或进行数值实验")
        timeout = cfg.get("timeout_seconds", 30)
        enabled = cfg.get("enabled", True)
        # Default ON: AST allowlist + isolated subprocess. Set sandbox: false to opt out.
        sandbox = cfg.get("sandbox", True)

        def run(char_name: str, params: dict) -> ToolResult:
            code = params.get("code", "")
            language = params.get("language", "python")
            topic = params.get("topic", "")

            if not enabled:
                return ToolResult(False, "run_code 已在世界配置中禁用")

            if not code.strip():
                return ToolResult(False, "没有提供代码")

            if language and language.lower() not in ("python", "py", ""):
                return ToolResult(False, f"仅支持 Python，收到: {language}")

            if sandbox:
                err = validate_sandboxed_code(code)
                if err:
                    return ToolResult(False, err)

            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = char_name.replace(" ", "_")
            code_dir = self.output_dir / "code"
            code_dir.mkdir(parents=True, exist_ok=True)
            code_path = code_dir / f"{safe_name}_{now}.py"

            with open(code_path, "w") as f:
                f.write(code)

            try:
                with tempfile.TemporaryDirectory(prefix="cc_code_") as tmp:
                    run_env = {
                        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "HOME": tmp,
                        "TMPDIR": tmp,
                        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
                    }
                    # -I: isolated mode (ignore user site / PYTHONPATH)
                    cmd = ["python3", "-I", str(code_path)] if sandbox else ["python3", str(code_path)]
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        cwd=tmp,
                        env=run_env,
                    )
                stdout = result.stdout[:3000] if result.stdout else ""
                stderr = result.stderr[:1000] if result.stderr else ""

                if result.returncode == 0:
                    output = f"代码运行成功。\n输出:\n{stdout}" if stdout else "代码运行成功（无输出）。"
                    success = True
                else:
                    output = f"代码运行出错。\n错误:\n{stderr}" if stderr else f"代码运行出错（退出码: {result.returncode}）"
                    success = False

                meta_path = code_dir / f"{safe_name}_{now}_meta.json"
                with open(meta_path, "w") as f:
                    json.dump({
                        "character": char_name,
                        "topic": topic,
                        "timestamp": datetime.now().isoformat(),
                        "exit_code": result.returncode,
                        "success": success,
                        "sandbox": sandbox,
                    }, f, ensure_ascii=False, indent=2)

                return ToolResult(
                    success=success,
                    output=output,
                    artifact_path=str(code_path),
                    metadata={"topic": topic, "language": language, "sandbox": sandbox},
                )
            except subprocess.TimeoutExpired:
                return ToolResult(False, f"代码运行超时（>{timeout}秒）")
            except Exception as e:
                return ToolResult(False, f"代码执行异常: {e}")

        return desc, run

    def _make_write_paper(self, cfg: dict):
        desc = cfg.get("description", "撰写研究论文或笔记，记录自己的发现和思考")

        def run(char_name: str, params: dict) -> ToolResult:
            title = params.get("title", "未命名")
            content = params.get("content", "")
            topic = params.get("topic", "")

            if not content.strip():
                return ToolResult(False, "没有提供论文内容")

            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = char_name.replace(" ", "_")
            paper_dir = self.output_dir / "papers"
            paper_dir.mkdir(parents=True, exist_ok=True)

            safe_title = "".join(c if c.isalnum() or c in "_- " else "_" for c in title)[:50]
            paper_path = paper_dir / f"{safe_name}_{now}_{safe_title}.md"

            paper_text = f"""# {title}

**作者**: {char_name}
**日期**: {datetime.now().strftime("%Y年%m月%d日 %H:%M")}
**主题**: {topic}

---

{content}
"""
            with open(paper_path, "w") as f:
                f.write(paper_text)

            return ToolResult(
                success=True,
                output=f"论文已保存: {paper_path.name}\n标题: {title}\n字数: {len(content)}",
                artifact_path=str(paper_path),
                metadata={"title": title, "topic": topic, "word_count": len(content)},
            )

        return desc, run

    def _make_search_arxiv(self, cfg: dict):
        desc = cfg.get(
            "description",
            "在 arXiv 搜索论文：返回完整摘要 + arXiv id / abs / pdf / HTML 链接（供 read_arxiv 深读）",
        )
        max_results = cfg.get("max_results", 5)

        def run(char_name: str, params: dict) -> ToolResult:
            from engine.literature import (
                looks_like_cjk,
                plan_literature_search,
                primary_query,
                resolve_literature_config,
            )

            raw_query = params.get("query", "")
            topic = params.get("topic", raw_query)
            lit = resolve_literature_config(self.world_frame, self.config)
            plan = plan_literature_search(
                intent="frontier",
                channel="arxiv",
                query=str(raw_query or ""),
                focus=str(topic or ""),
                world_or_frame=self.world_frame,
                config=self.config,
            )
            query = primary_query(plan, "arxiv")
            if not query.strip():
                return ToolResult(False, "没有提供搜索关键词")

            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = char_name.replace(" ", "_")
            search_dir = self.output_dir / "searches"
            search_dir.mkdir(parents=True, exist_ok=True)

            try:
                url = (
                    f"http://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(query)}"
                    f"&start=0&max_results={max_results}&sortBy=relevance"
                )
                xml_data = _http_get(url, timeout=15).decode("utf-8")
                papers = parse_arxiv_atom(xml_data)

                if not papers:
                    retry_plan = plan_literature_search(
                        intent="frontier",
                        channel="arxiv",
                        query=str(topic or query),
                        focus=str(topic or query),
                        world_or_frame=self.world_frame,
                        config=self.config,
                    )
                    retry_q = primary_query(retry_plan, "arxiv")
                    if retry_q and retry_q != query:
                        xml_data = _http_get(
                            f"http://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(retry_q)}"
                            f"&start=0&max_results={max_results}&sortBy=relevance",
                            timeout=15,
                        ).decode("utf-8")
                        papers = parse_arxiv_atom(xml_data)
                        if papers:
                            query = retry_q

                search_path = search_dir / f"{safe_name}_{now}_search.json"
                with open(search_path, "w") as f:
                    json.dump({
                        "character": char_name,
                        "query": query,
                        "raw_query": raw_query,
                        "cjk_rewritten": looks_like_cjk(raw_query),
                        "literature_policy": lit.get("frontier_language"),
                        "timestamp": datetime.now().isoformat(),
                        "results": papers,
                    }, f, ensure_ascii=False, indent=2)

                note = ""
                if looks_like_cjk(raw_query) and raw_query.strip() != query:
                    note = f"（文献策略: 前沿检索改写为英文 → {query}）\n"

                if not papers:
                    output = (
                        f"arXiv搜索「{query}」: 未找到相关论文。{note}"
                        "换用定理/对象英文名再试，或 read_arxiv 指定 id。"
                    )
                else:
                    lines = [
                        f"arXiv搜索「{query}」: 找到 {len(papers)} 篇。",
                        note.strip(),
                        "只看标题会空转名词——挑一篇用 read_arxiv 读正文/公式。",
                        "",
                    ]
                    for i, p in enumerate(papers, 1):
                        authors_str = ", ".join(p["authors"][:3])
                        if len(p["authors"]) > 3:
                            authors_str += " et al."
                        abs_full = p.get("summary") or ""
                        lines.append(f"{i}. [{p.get('arxiv_id') or '?'}] {p['title']}")
                        lines.append(f"   作者: {authors_str}")
                        if p.get("published"):
                            lines.append(f"   日期: {p['published']}")
                        lines.append(f"   abs: {p.get('abs_url')}")
                        lines.append(f"   html: {p.get('html_url')}")
                        lines.append(f"   摘要:\n   {abs_full}")
                        lines.append("")
                    output = "\n".join(x for x in lines if x is not None)
                    if len(output) > 12000:
                        output = output[:11999] + "…"

                return ToolResult(
                    success=True,
                    output=output,
                    artifact_path=str(search_path),
                    metadata={"query": query, "result_count": len(papers), "raw_query": raw_query},
                )
            except Exception as e:
                return ToolResult(False, f"arXiv搜索失败: {e}")

        return desc, run

    def _make_read_arxiv(self, cfg: dict):
        desc = cfg.get(
            "description",
            "深读一篇 arXiv 论文：完整摘要 + ar5iv/HTML 正文或 TeX 公式摘录（合法开放预印本）",
        )
        max_chars = int(cfg.get("max_chars", 7000))

        def run(char_name: str, params: dict) -> ToolResult:
            arxiv_id = normalize_arxiv_id(
                params.get("arxiv_id")
                or params.get("id")
                or params.get("url")
                or params.get("query")
                or ""
            )
            query = (params.get("query") or params.get("topic") or "").strip()

            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = char_name.replace(" ", "_")
            read_dir = self.output_dir / "readings"
            read_dir.mkdir(parents=True, exist_ok=True)

            try:
                paper = None
                if arxiv_id:
                    xml = _http_get(
                        f"http://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}",
                        timeout=15,
                    ).decode("utf-8")
                    papers = parse_arxiv_atom(xml)
                    paper = papers[0] if papers else None
                elif query:
                    xml = _http_get(
                        "http://export.arxiv.org/api/query?"
                        + urllib.parse.urlencode({
                            "search_query": f"all:{query}",
                            "start": 0,
                            "max_results": 1,
                            "sortBy": "relevance",
                        }),
                        timeout=15,
                    ).decode("utf-8")
                    papers = parse_arxiv_atom(xml)
                    paper = papers[0] if papers else None
                    if paper:
                        arxiv_id = paper.get("arxiv_id") or ""

                if not paper or not arxiv_id:
                    return ToolResult(
                        False,
                        "read_arxiv 需要 arxiv_id（如 2301.12345）或能命中一篇论文的 query",
                    )

                abstract = paper.get("summary") or ""
                src_label, body = fetch_arxiv_html_body(arxiv_id, max_chars=max_chars)
                body_kind = src_label or ""
                if not body:
                    tex = fetch_arxiv_tex_excerpts(arxiv_id, max_chars=max_chars)
                    if tex:
                        body, body_kind = tex, "tex_source"
                if not body:
                    body = abstract
                    body_kind = "abstract_only"

                authors_str = ", ".join((paper.get("authors") or [])[:8])
                lines = [
                    f"深读 arXiv:{arxiv_id}",
                    f"标题: {paper.get('title')}",
                    f"作者: {authors_str}",
                    f"链接: {paper.get('abs_url')}",
                    f"HTML: {paper.get('html_url')}",
                    f"正文来源: {body_kind}",
                    "",
                    "## Abstract",
                    abstract,
                    "",
                    "## Body / math excerpts",
                    body,
                    "",
                    "阅读要求: 从正文摘出至少一条带公式的 Claim/Lemma/定义，再谈下一步；"
                    "禁止只复述标题关键词。",
                ]
                output = "\n".join(lines)
                if len(output) > 14000:
                    output = output[:13999] + "…"

                out_path = read_dir / f"{safe_name}_{now}_{arxiv_id.replace('/', '_')}.json"
                with open(out_path, "w") as f:
                    json.dump({
                        "character": char_name,
                        "arxiv_id": arxiv_id,
                        "title": paper.get("title"),
                        "body_kind": body_kind,
                        "abstract": abstract,
                        "body": body,
                        "timestamp": datetime.now().isoformat(),
                    }, f, ensure_ascii=False, indent=2)

                return ToolResult(
                    success=True,
                    output=output,
                    artifact_path=str(out_path),
                    metadata={
                        "arxiv_id": arxiv_id,
                        "body_kind": body_kind,
                        "title": paper.get("title"),
                    },
                )
            except Exception as e:
                return ToolResult(False, f"read_arxiv 失败: {e}")

        return desc, run

    def _make_search_web(self, cfg: dict):
        """Web search — Bing primary, LLM fallback.

        Literature policy: English frontier track first; optional Chinese
        vernacular track when world.literature.bilingual_web is on.
        """
        desc = cfg.get(
            "description",
            "搜索互联网（默认英文前沿资料；可选中文解读轨道）",
        )
        backend = cfg.get("backend", "bing")
        max_results = cfg.get("max_results", 5)

        def _bing_search(q: str, accept_lang: str) -> list[dict]:
            bing_url = "https://www.bing.com/search?" + urllib.parse.urlencode({
                "q": q, "count": max_results,
            })
            req = urllib.request.Request(bing_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept-Language": accept_lang,
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            blocks = re.findall(
                r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>(.*?)</li>',
                html, re.DOTALL,
            )
            out = []
            for block in blocks[:max_results]:
                title_m = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL)
                snippet_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
                cite_m = re.search(r'<cite[^>]*>(.*?)</cite>', block, re.DOTALL)
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else ""
                snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else ""
                url = re.sub(r'<[^>]+>', '', cite_m.group(1)).strip() if cite_m else ""
                if title:
                    out.append({
                        "title": title[:120], "snippet": snippet[:200], "url": url,
                    })
            return out

        def run(char_name: str, params: dict) -> ToolResult:
            from engine.literature import (
                looks_like_cjk,
                plan_literature_search,
                primary_query,
                resolve_literature_config,
            )

            raw_query = params.get("query", "")
            topic = params.get("topic", raw_query)
            vernacular_zh = (params.get("vernacular_zh") or params.get("zh_query") or "").strip()
            lit = resolve_literature_config(self.world_frame, self.config)
            plan = plan_literature_search(
                intent="mixed" if lit.get("bilingual_web") else "frontier",
                channel="web",
                query=str(raw_query or ""),
                focus=str(topic or ""),
                world_or_frame=self.world_frame,
                config=self.config,
            )
            query = primary_query(plan, "web")
            zh_query = vernacular_zh
            if not zh_query:
                for sq in plan.queries:
                    if sq.channel == "web_zh":
                        zh_query = sq.text
                        break

            if not query.strip():
                return ToolResult(False, "没有提供搜索关键词")

            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = char_name.replace(" ", "_")
            search_dir = self.output_dir / "searches"
            search_dir.mkdir(parents=True, exist_ok=True)

            search_backend = backend
            results: list[dict] = []
            zh_results: list[dict] = []

            if search_backend == "bing":
                try:
                    results = _bing_search(query, "en-US,en;q=0.9,zh-CN;q=0.4")
                    if (
                        zh_query
                        and lit.get("allow_vernacular")
                        and lit.get("bilingual_web")
                        and zh_query.strip() != query.strip()
                    ):
                        try:
                            zh_results = _bing_search(zh_query, "zh-CN,zh;q=0.9,en;q=0.4")
                        except Exception:
                            zh_results = []
                    if not results and not zh_results:
                        search_backend = "llm"
                except Exception:
                    search_backend = "llm"

            if search_backend == "llm" and self.llm:
                try:
                    system = (
                        "你是搜索引擎。用户查询，你基于训练数据返回搜索结果摘要。\n"
                        "每条: 标题 | 来源 | 1-2句摘要。不编造。不确定标[不确定]。"
                        "优先返回英文前沿文献线索；若有中文解读可另列。"
                    )
                    prompt = f'搜索(英文前沿): "{query}"\n'
                    if zh_query:
                        prompt += f'可选中文解读轨: "{zh_query}"\n'
                    prompt += f"返回{max_results}条。"
                    response = self.llm.chat(
                        [{"role": "user", "content": prompt}],
                        system=system, temperature=0.3,
                    )
                    results = [{"title": "LLM综合结果", "snippet": response[:500], "url": ""}]
                except Exception:
                    results = [{"title": "搜索不可用", "snippet": "无法连接。", "url": ""}]

            if not results and not zh_results:
                output = f"🌐 网页搜索「{query}」: 无结果。"
            else:
                lines = [f"🌐 网页搜索「{query}」({search_backend}) [EN frontier]:"]
                for i, r in enumerate(results, 1):
                    lines.append(f"\n{i}. {r['title']}")
                    if r.get("snippet"):
                        lines.append(f"   {r['snippet'][:180]}")
                    if r.get("url"):
                        lines.append(f"   {r['url'][:80]}")
                if zh_results:
                    lines.append(f"\n--- ZH vernacular track「{zh_query}」---")
                    for i, r in enumerate(zh_results, 1):
                        lines.append(f"\n{i}. {r['title']}")
                        if r.get("snippet"):
                            lines.append(f"   {r['snippet'][:180]}")
                        if r.get("url"):
                            lines.append(f"   {r['url'][:80]}")
                output = "\n".join(lines)

            search_path = search_dir / f"{safe_name}_{now}_web_{query[:40].replace('/', '_')}.json"
            with open(search_path, "w") as f:
                json.dump({
                    "character": char_name,
                    "query": query,
                    "zh_query": zh_query,
                    "raw_query": raw_query,
                    "cjk_rewritten": looks_like_cjk(raw_query),
                    "backend": search_backend,
                    "literature_policy": lit.get("frontier_language"),
                    "timestamp": datetime.now().isoformat(),
                    "results": results,
                    "zh_results": zh_results,
                }, f, ensure_ascii=False, indent=2)

            return ToolResult(
                success=True, output=output,
                artifact_path=str(search_path),
                metadata={
                    "query": query,
                    "zh_query": zh_query,
                    "backend": search_backend,
                    "result_count": len(results) + len(zh_results),
                },
            )

        return desc, run
