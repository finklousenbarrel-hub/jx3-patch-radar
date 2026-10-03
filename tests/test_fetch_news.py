# -*- coding: utf-8 -*-
"""fetch_news 的函数测试（简报 006 目标2：<a> 链接保留）

运行方式（项目根目录）：
    python tests/test_fetch_news.py
或：
    python -m pytest tests/test_fetch_news.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fetch_news import html_to_text  # noqa: E402


def test_link_kept_as_text_with_url():
    """<a href>文字</a> → 「文字 (URL)」。"""
    html = '<p>前往查看<a href="https://jx3.xoyo.com/a?id=1">万花武学调整详情</a>。</p>'
    assert html_to_text(html) == "前往查看万花武学调整详情 (https://jx3.xoyo.com/a?id=1)。"


def test_link_without_href_keeps_text_only():
    """无 href 的 <a> 仅保留链接文字，不追加括号。"""
    assert html_to_text("<p><a>纯文字</a></p>") == "纯文字"


def test_multiple_links_in_one_line():
    """同行多个链接各自保留。"""
    html = '<p><a href="https://a.com/1">甲</a>和<a href="https://b.com/2">乙</a></p>'
    assert html_to_text(html) == "甲 (https://a.com/1)和乙 (https://b.com/2)"


def test_block_tags_still_newline():
    """块级标签仍转换为换行，空行被折叠。"""
    html = "<p>第一段</p><p>第二段</p>"
    assert html_to_text(html) == "第一段\n\n第二段"


def test_html_entities_unescaped():
    """HTML 实体仍被解码。"""
    assert html_to_text("<p>A&amp;B</p>") == "A&B"


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[通过] {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"[失败] {t.__name__}: {exc!r}", file=sys.stderr)
    print(f"\n{len(tests) - failed}/{len(tests)} 项通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
