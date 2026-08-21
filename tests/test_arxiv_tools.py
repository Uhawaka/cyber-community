#!/usr/bin/env python3
"""arXiv search/read tools — legal preprint deep-read path."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.tools import (
    ToolRegistry,
    normalize_arxiv_id,
    parse_arxiv_atom,
    _html_to_readable,
    _tex_math_excerpts,
)


SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>On the zeros of zeta and a test formula</title>
    <published>2023-01-01T00:00:00Z</published>
    <summary>
      We study non-trivial zeros of ζ(s). Under RH one has
      |ψ(x)-x| ≪ x^{1/2} log^2 x. We prove a conditional lemma.
    </summary>
    <author><name>A. Tester</name></author>
    <category term="math.NT" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:primary_category term="math.NT"/>
  </entry>
</feed>
"""

MIXED_SHELF_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.00001v1</id>
    <title>On Hodge classes</title>
    <published>2023-01-01T00:00:00Z</published>
    <summary>A fourfold Hodge class and a checkable cycle class map.</summary>
    <author><name>A. Tester</name></author>
    <category term="math.AG" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:primary_category term="math.AG"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/hep-ex/9901001</id>
    <title>A collider measurement of something</title>
    <published>1999-01-01T00:00:00Z</published>
    <summary>We measure a cross section at the LHC.</summary>
    <author><name>B. Collider</name></author>
    <category term="hep-ex" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:primary_category term="hep-ex"/>
  </entry>
</feed>
"""


def test_normalize_arxiv_id():
    assert normalize_arxiv_id("2301.12345") == "2301.12345"
    assert normalize_arxiv_id("https://arxiv.org/abs/2301.12345v2") == "2301.12345v2"
    assert normalize_arxiv_id("https://ar5iv.labs.arxiv.org/html/2301.12345") == "2301.12345"


def test_parse_atom_full_abstract_and_links():
    papers = parse_arxiv_atom(SAMPLE_ATOM)
    assert len(papers) == 1
    p = papers[0]
    assert p["arxiv_id"].startswith("2301.00001")
    assert "ζ(s)" in p["summary"] or "zeta" in p["summary"].lower()
    assert "arxiv.org/abs/" in p["abs_url"]
    assert p.get("primary_category") == "math.NT"
    assert "math.NT" in (p.get("categories") or [])
    assert len(p["summary"]) > 50  # not the old 150-char trunc habit


def test_search_arxiv_drops_off_shelf_hits():
    with tempfile.TemporaryDirectory() as tmp:
        reg = ToolRegistry(
            [{"name": "search_arxiv", "max_results": 5}],
            Path(tmp),
            world_frame={
                "literature": {
                    "enabled": True,
                    "frontier_language": "en",
                    "allow_vernacular": True,
                    "fallback_query": "open problems mathematics",
                    "arxiv_categories": ["math.*", "hep-th"],
                }
            },
        )
        with patch("engine.tools._http_get", return_value=MIXED_SHELF_ATOM.encode()):
            result = reg.execute("search_arxiv", "Yuki", {"query": "Hodge class"})
        assert result.success
        assert "2301.00001" in result.output
        assert "hep-ex" in result.output or "货架外" in result.output
        assert "9901001" not in (result.metadata or {}).get("arxiv_ids", [])
        ids = [h["arxiv_id"] for h in (result.metadata or {}).get("hits") or []]
        assert any("2301.00001" in i for i in ids)
        assert not any("9901001" in i for i in ids)
        assert "cat:" in ((result.metadata or {}).get("api_query") or "")


def test_html_and_tex_math_extractors():
    html = "<html><body><h1>Title</h1><p>Let $$\\zeta(s)=0$$ on the critical line.</p><script>x</script></body></html>"
    text = _html_to_readable(html, max_chars=2000)
    assert "zeta" in text.lower() or "ζ" in text or "critical" in text
    assert "<script>" not in text
    tex = r"""
\section{Intro}
Hello world without math.
\begin{theorem}
If $\mathrm{Re}(s)=\tfrac12$ then $|\zeta(s)|\ll t^{\varepsilon}$.
\end{theorem}
More text.
"""
    ex = _tex_math_excerpts(tex, max_chars=2000)
    assert "theorem" in ex.lower() or "zeta" in ex.lower() or "tfrac" in ex


def test_search_arxiv_output_includes_full_abstract():
    with tempfile.TemporaryDirectory() as tmp:
        reg = ToolRegistry(
            [{"name": "search_arxiv", "max_results": 1}],
            Path(tmp),
        )
        with patch("engine.tools._http_get", return_value=SAMPLE_ATOM.encode()):
            result = reg.execute("search_arxiv", "Elias", {"query": "riemann hypothesis"})
        assert result.success
        assert "摘要:" in result.output
        assert "ψ(x)" in result.output or "zeta" in result.output.lower()
        assert "read_arxiv" in result.output


def test_read_arxiv_falls_back_to_abstract():
    with tempfile.TemporaryDirectory() as tmp:
        reg = ToolRegistry(
            [{"name": "read_arxiv", "max_chars": 2000}],
            Path(tmp),
        )

        def fake_get(url, timeout=20):
            if "export.arxiv.org" in url:
                return SAMPLE_ATOM.encode()
            raise RuntimeError("no html")

        with patch("engine.tools._http_get", side_effect=fake_get):
            with patch("engine.tools.fetch_arxiv_html_body", return_value=("", "")):
                with patch("engine.tools.fetch_arxiv_tex_excerpts", return_value=""):
                    result = reg.execute(
                        "read_arxiv", "Nora", {"arxiv_id": "2301.00001"}
                    )
        assert result.success
        assert "Abstract" in result.output
        assert "2301.00001" in result.output
        assert result.metadata.get("body_kind") == "abstract_only"


def test_math_commune_registers_read_arxiv():
    import yaml
    from engine.world_builder import expand_world

    raw = yaml.safe_load((ROOT / "worlds/math-commune/community.yaml").read_text())
    cfg = expand_world(raw)
    names = [t["name"] for t in cfg.get("tools") or []]
    assert "read_arxiv" in names
    assert "search_arxiv" in names
    assert cfg["world"].get("seed_readings")


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("OK", name)
            except Exception:
                failed += 1
                traceback.print_exc()
    raise SystemExit(failed)
