# -*- coding: utf-8 -*-
"""fetch_link_info 的函数测试（简报 009）

只测纯函数与落盘逻辑，不碰网络（接口逆向结论见 src/fetch_link_info.py docstring）。

运行方式（项目根目录）：
    python tests/test_fetch_link_info.py
或：
    python -m pytest tests/test_fetch_link_info.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fetch_link_info import (  # noqa: E402
    article_to_markdown,
    article_to_text,
    extract_links,
    parse_article_url,
    save_article_md,
    save_article_txt,
)

JSON_0908 = ROOT / "data" / "patches" / "9月8日“苍生铸世”资料片首轮武学调整.json"


def test_parse_article_url_fragment():
    """SPA 链接的查询参数在 # fragment 里。"""
    url = "https://jx3.xoyo.com/index/#/article-details?catid=2466&id=7477"
    assert parse_article_url(url) == ("2466", "7477")


def test_parse_article_url_plain_query():
    """普通 query 形式也能解析（兜底）。"""
    assert parse_article_url("https://jx3.xoyo.com/api?catid=1&id=2") == ("1", "2")


def test_parse_article_url_missing_params():
    """缺 catid/id 时抛 ValueError。"""
    for bad in ("https://jx3.xoyo.com/index/#/article-details?catid=2466",
                "https://jx3.xoyo.com/index/#/article-details"):
        try:
            parse_article_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"应抛 ValueError：{bad}")


def test_extract_links_from_real_json():
    """验收前置：9/8 JSON 的 notes 中可提取 21 条门派链接。"""
    data = json.loads(JSON_0908.read_text(encoding="utf-8"))
    links = extract_links(data)
    assert len(links) == 21, len(links)
    sects = {l["sect"] for l in links}
    assert "万花" in sects and "流派·无相楼" in sects
    for l in links:
        assert l["catid"] == "2466" and l["id"].isdigit()


def test_extract_links_ignores_entries():
    """只扫 notes，不扫 entries。"""
    data = {"sects": [{"name": "甲", "xinfas": [{
        "name": "乙", "notes": "详情 (https://a.com/i#/?catid=1&id=2)",
        "entries": ["条目里的链接 (https://a.com/i#/?catid=9&id=9) 不应被提取"]}]}]}
    links = extract_links(data)
    assert len(links) == 1 and links[0]["id"] == "2"


def test_save_article_txt(tmp_path=None):
    """文章落盘：文件名=标题（非法字符去除），内容含标题行+纯文本。"""
    import tempfile as _tf

    out_dir = Path(_tf.mkdtemp())
    article = {"title": "9月8日“苍生铸世”资料片首轮武学调整-万花",
               "content": "<p>◎ 万花</p><p>#花间游#</p>"
                          "<p>·条目甲</p><p><a href=\"https://a.com/1\">详情</a></p>"}
    path = save_article_txt(article, out_dir)
    assert path.name == "9月8日“苍生铸世”资料片首轮武学调整-万花.txt"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("9月8日“苍生铸世”资料片首轮武学调整-万花\n")
    assert "·条目甲" in text
    assert "详情 (https://a.com/1)" in text  # 链接保留


def test_article_to_text_strips_html():
    assert article_to_text({"content": "<p>甲</p><p>乙</p>"}) == "甲\n\n乙"


# ---------------------------------------------------------------- Markdown plus（简报 010）

def test_md_table_basic():
    """表格转 Markdown 管道表格：首行为表头，含分隔行。"""
    html = ('<table><tbody>'
            '<tr><td>奇穴重数</td><td>奇穴名称</td></tr>'
            '<tr><td>第一重</td><td>踏莲</td></tr>'
            '</tbody></table>')
    md = article_to_markdown({"content": html})
    assert "| 奇穴重数 | 奇穴名称 |" in md
    assert "| --- | --- |" in md
    assert "| 第一重 | 踏莲 |" in md


def test_md_table_rowspan_expanded():
    """rowspan 合并单元格在后续行重复展开，保持语义归属。"""
    html = ('<table><tbody>'
            '<tr><td>重数</td><td>名称</td></tr>'
            '<tr><td rowspan="2">第一重</td><td>甲</td></tr>'
            '<tr><td>乙</td></tr>'
            '</tbody></table>')
    md = article_to_markdown({"content": html})
    assert "| 第一重 | 甲 |" in md
    assert "| 第一重 | 乙 |" in md


def test_md_table_cell_pipe_and_br():
    """单元格内 | 转义、<br> 保留为 <br>（不换行破坏表形）。"""
    html = ('<table><tbody><tr><td>甲</td></tr>'
            '<tr><td>效果a<br/>效果b|c</td></tr></tbody></table>')
    md = article_to_markdown({"content": html})
    assert "效果a<br>效果b\\|c" in md


def test_md_red_bold():
    """标红（rgb/#ff0000/red 三种写法）转 **加粗**，普通文本不加粗。"""
    for style in ("color: rgb(255, 0, 0);", "color:#ff0000", "color: red;"):
        html = f'<p>原文<span style="{style}">改动内容</span>尾巴</p>'
        md = article_to_markdown({"content": html})
        assert "**改动内容**" in md, style
        assert "**原文" not in md
    # 蓝色不算标红
    md = article_to_markdown({"content": '<p><span style="color: rgb(0, 0, 255);">蓝字</span></p>'})
    assert "**蓝字**" not in md


def test_md_red_bold_not_broken_by_newline():
    """红色数据段以内换行开头时，** 不跨行断裂（每行 ** 成对）。"""
    html = ('<p><span style="color: rgb(255, 0, 0);">\n调息时间25秒。</span></p>')
    md = article_to_markdown({"content": html})
    for line in md.splitlines():
        assert line.count("**") % 2 == 0, line
    assert "**调息时间25秒。**" in md


def test_md_red_bold_in_table_cell():
    """表格单元格内的标红同样加粗，且不泄漏到下一格。"""
    html = ('<table><tbody><tr><td>甲</td><td>乙</td></tr>'
            '<tr><td><span style="color: rgb(255, 0, 0);">新增</span></td><td>普通</td></tr>'
            '</tbody></table>')
    md = article_to_markdown({"content": html})
    assert "| **新增** | 普通 |" in md


def test_md_link_markdown_form():
    """<a> 转 [文字](URL)。"""
    html = '<p><a href="https://a.com/1">详情</a></p>'
    assert "[详情](https://a.com/1)" in article_to_markdown({"content": html})


def test_save_article_md():
    """plus 版落盘：.md 后缀、一级标题 + Markdown 正文。"""
    out_dir = Path(tempfile.mkdtemp())
    article = {"title": "9月8日“苍生铸世”资料片首轮武学调整-万花",
               "content": '<table><tbody><tr><td>甲</td></tr></tbody></table>'}
    path = save_article_md(article, out_dir)
    assert path.suffix == ".md" and "万花" in path.name
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 9月8日“苍生铸世”资料片首轮武学调整-万花\n")
    assert "| 甲 |" in text


def test_plus_files_on_disk():
    """验收：data/extra-info/plus 下 21 篇 md，表格与加粗成对存在。"""
    plus_dir = ROOT / "data" / "extra-info" / "plus"
    files = sorted(plus_dir.glob("*.md"))
    assert len(files) == 21, len(files)
    n_tbl = n_bold = 0
    for f in files:
        md = f.read_text(encoding="utf-8")
        n_tbl += md.count("| ---")
        n_bold += md.count("**") // 2
        for line in md.splitlines():
            assert line.count("**") % 2 == 0, (f.name, line[:60])
    assert n_tbl > 0 and n_bold > 0


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
            print(f"[失败] {t.__name__}: {exc}", file=sys.stderr)
    print(f"\n{len(tests) - failed}/{len(tests)} 项通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
