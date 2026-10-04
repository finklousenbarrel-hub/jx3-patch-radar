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

from fetch_news import (  # noqa: E402
    filter_new_records,
    html_to_text,
    load_state,
    process_record,
    record_uid,
    save_state,
)


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


# ---------------------------------------------------------------- 增量状态（简报 007）

import tempfile as _tempfile  # noqa: E402


def _tmp(name: str) -> Path:
    return Path(_tempfile.mkdtemp()) / name


def _fake_record(url: str, title: str = "测试武学调整") -> dict:
    return {"url": url, "title": title, "date": "2026/10/01",
            "desc": "<p>◎测试门派</p><p>#测试心法#</p><p>·条目甲</p>"}


def test_record_uid_prefers_url():
    """唯一标识取 url。"""
    assert record_uid(_fake_record("https://a.com/1")) == "https://a.com/1"


def test_record_uid_fallback_title():
    """url 缺失时回退标题。"""
    r = _fake_record("")
    assert record_uid(r) == "测试武学调整"


def test_state_save_load_roundtrip():
    """state 写入后可原样读回，且每条记录含 url + 处理日期。"""
    path = _tmp("state.json")
    state = {"https://a.com/1": {"url": "https://a.com/1", "processed_at": "2026-10-04"}}
    save_state(state, path)
    loaded = load_state(path)
    assert loaded == state
    rec = loaded["https://a.com/1"]
    assert rec["url"] and rec["processed_at"]


def test_load_state_missing_file():
    """状态文件不存在时返回空状态。"""
    assert load_state(_tmp("不存在.json")) == {}


def test_load_state_corrupt_file():
    """状态文件损坏时按空状态处理，不抛异常。"""
    path = _tmp("state.json")
    path.write_text("这不是合法JSON", encoding="utf-8")
    assert load_state(path) == {}


def test_filter_new_records_skips_processed():
    """已在 state 中的公告被跳过，只返回新公告。"""
    records = [_fake_record("https://a.com/1"), _fake_record("https://a.com/2")]
    state = {"https://a.com/1": {"url": "https://a.com/1", "processed_at": "2026-10-04"}}
    new = filter_new_records(records, state)
    assert [record_uid(r) for r in new] == ["https://a.com/2"]


def test_processed_files_not_rewritten():
    """增量流程：已处理公告的 txt/json 不被改动（第二轮筛出 0 条新增）。"""
    out_dir = Path(_tempfile.mkdtemp())
    record = _fake_record("https://a.com/1")

    # 第一轮：处理新公告，产出 txt + json
    txt_path = process_record(record, out_dir)
    json_path = txt_path.with_suffix(".json")
    first_txt = txt_path.read_bytes()
    first_json = json_path.read_bytes()

    # 第二轮：同一公告已在 state 中 -> 筛出 0 条，不调用 process_record
    state = {record_uid(record): {"url": record_uid(record), "processed_at": "2026-10-04"}}
    assert filter_new_records([record], state) == []

    # 文件内容保持原样
    assert txt_path.read_bytes() == first_txt
    assert json_path.read_bytes() == first_json

    # 重建一致性：重新处理同一条公告，产出内容逐字节相同
    txt_path2 = process_record(record, out_dir)
    assert txt_path2.read_bytes() == first_txt
    assert json_path.read_bytes() == first_json


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
