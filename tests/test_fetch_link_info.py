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
    article_to_text,
    extract_links,
    parse_article_url,
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
