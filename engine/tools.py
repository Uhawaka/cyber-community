"""Tool system for character communities.

Characters use tools as natural extensions of their abilities:
- run_code: Write and execute Python to test conjectures
- write_paper: Produce research notes/papers
- search_arxiv: Observe what humans are publishing

Tools are defined per-world in community.yaml. The ToolRegistry loads
available tools and provides execution with artifact saving.
"""

import os
import json
import subprocess
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from typing import Optional


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

    def __init__(self, tool_configs: list[dict], output_dir: Path, llm=None):
        self.tools = {}
        self.output_dir = output_dir
        self.llm = llm  # for tools that need LLM-generated content

        for cfg in tool_configs:
            name = cfg["name"]
            if name == "run_code":
                self.tools[name] = self._make_run_code(cfg)
            elif name == "write_paper":
                self.tools[name] = self._make_write_paper(cfg)
            elif name == "search_arxiv":
                self.tools[name] = self._make_search_arxiv(cfg)

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

        def run(char_name: str, params: dict) -> ToolResult:
            code = params.get("code", "")
            language = params.get("language", "python")
            topic = params.get("topic", "")

            if not code.strip():
                return ToolResult(False, "没有提供代码")

            # Write code to temp file
            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = char_name.replace(" ", "_")
            code_dir = self.output_dir / "code"
            code_dir.mkdir(parents=True, exist_ok=True)
            code_path = code_dir / f"{safe_name}_{now}.py"

            with open(code_path, "w") as f:
                f.write(code)

            try:
                result = subprocess.run(
                    ["python3", str(code_path)],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                stdout = result.stdout[:3000] if result.stdout else ""
                stderr = result.stderr[:1000] if result.stderr else ""

                if result.returncode == 0:
                    output = f"代码运行成功。\n输出:\n{stdout}" if stdout else "代码运行成功（无输出）。"
                    success = True
                else:
                    output = f"代码运行出错。\n错误:\n{stderr}" if stderr else f"代码运行出错（退出码: {result.returncode}）"
                    success = False

                # Save metadata
                meta_path = code_dir / f"{safe_name}_{now}_meta.json"
                with open(meta_path, "w") as f:
                    json.dump({
                        "character": char_name,
                        "topic": topic,
                        "timestamp": datetime.now().isoformat(),
                        "exit_code": result.returncode,
                        "success": success,
                    }, f, ensure_ascii=False, indent=2)

                return ToolResult(
                    success=success,
                    output=output,
                    artifact_path=str(code_path),
                    metadata={"topic": topic, "language": language},
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
        desc = cfg.get("description", "在arXiv上搜索人类发表的论文，了解某个领域的最新进展")
        max_results = cfg.get("max_results", 5)

        def run(char_name: str, params: dict) -> ToolResult:
            query = params.get("query", "")
            topic = params.get("topic", query)

            if not query.strip():
                return ToolResult(False, "没有提供搜索关键词")

            now = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = char_name.replace(" ", "_")
            search_dir = self.output_dir / "searches"
            search_dir.mkdir(parents=True, exist_ok=True)

            # Query arxiv API
            try:
                encoded_query = urllib.parse.quote(query)
                url = f"http://export.arxiv.org/api/query?search_query=all:{encoded_query}&start=0&max_results={max_results}&sortBy=relevance"
                
                req = urllib.request.Request(url, headers={"User-Agent": "CyberCommunity/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    xml_data = resp.read().decode("utf-8")

                # Parse results
                root = ET.fromstring(xml_data)
                ns = {"atom": "http://www.w3.org/2005/Atom"}

                papers = []
                for entry in root.findall("atom:entry", ns):
                    title_elem = entry.find("atom:title", ns)
                    summary_elem = entry.find("atom:summary", ns)

                    title_text = title_elem.text.strip() if title_elem is not None and title_elem.text else "无标题"
                    summary_text = summary_elem.text.strip()[:300] if summary_elem is not None and summary_elem.text else ""

                    authors = []
                    for author in entry.findall("atom:author", ns):
                        name_elem = author.find("atom:name", ns)
                        if name_elem is not None and name_elem.text:
                            authors.append(name_elem.text.strip())

                    papers.append({
                        "title": title_text,
                        "authors": authors,
                        "summary": summary_text,
                    })

                # Save search results
                search_path = search_dir / f"{safe_name}_{now}_{query[:30]}.json"
                with open(search_path, "w") as f:
                    json.dump({
                        "character": char_name,
                        "query": query,
                        "timestamp": datetime.now().isoformat(),
                        "results": papers,
                    }, f, ensure_ascii=False, indent=2)

                if not papers:
                    output = f"arXiv搜索「{query}」: 未找到相关论文。"
                else:
                    lines = [f"arXiv搜索「{query}」: 找到 {len(papers)} 篇论文\n"]
                    for i, p in enumerate(papers, 1):
                        authors_str = ", ".join(p["authors"][:3])
                        if len(p["authors"]) > 3:
                            authors_str += " et al."
                        lines.append(f"{i}. {p['title']}")
                        lines.append(f"   作者: {authors_str}")
                        lines.append(f"   摘要: {p['summary'][:150]}...")
                        lines.append("")
                    output = "\n".join(lines)

                return ToolResult(
                    success=True,
                    output=output,
                    artifact_path=str(search_path),
                    metadata={"query": query, "result_count": len(papers)},
                )
            except Exception as e:
                return ToolResult(False, f"arXiv搜索失败: {e}")

        return desc, run
