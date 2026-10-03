# -*- coding: utf-8 -*-
"""parse_patch 的验收测试（简报 006）

运行方式（项目根目录）：
    python tests/test_parse_patch.py
或：
    python -m pytest tests/test_parse_patch.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from parse_patch import parse_patch_file, parse_patch_text  # noqa: E402

PATCH_0924 = ROOT / "data" / "patches" / "9月24日“苍生铸世”资料片第二轮武学调整.txt"


def _counts(data: dict) -> tuple[int, int, int]:
    n_sect = len(data["sects"])
    n_xinfa = sum(len(s["xinfas"]) for s in data["sects"])
    n_entry = sum(len(x["entries"]) for s in data["sects"] for x in s["xinfas"])
    return n_sect, n_xinfa, n_entry


def test_0924_counts():
    """验收：9/24 公告 → 门派 21、心法 65、条目 352。"""
    data = parse_patch_file(PATCH_0924)
    assert _counts(data) == (21, 65, 352), _counts(data)


def test_0924_title_date_preamble():
    """标题取自文件名；日期为 2026/09/24；前言为第一个◎之前的文本。"""
    data = parse_patch_file(PATCH_0924)
    assert data["title"] == "9月24日“苍生铸世”资料片第二轮武学调整"
    assert data["date"] == "2026/09/24"
    assert data["preamble"].startswith("各位侠士好")
    assert "◎" not in data["preamble"]


def test_qinyi_entry_complete():
    """抽查『沁逸』条目：必须同时包含原效果和『调整为』后的文本。"""
    data = parse_patch_file(PATCH_0924)
    entry = next(
        e for s in data["sects"] for x in s["xinfas"] for e in x["entries"]
        if "沁逸" in e
    )
    assert "持续2.5秒" in entry          # 原效果
    assert "调整为：" in entry
    assert "持续3秒" in entry            # 调整后
    assert "造成的伤害降低20%" in entry  # 同条目后续段落


def test_sect_and_xinfa_names():
    """门派/心法名称解析正确（◎ 后空白被去除）。"""
    data = parse_patch_file(PATCH_0924)
    assert data["sects"][0]["name"] == "万花"
    assert [x["name"] for x in data["sects"][0]["xinfas"]] == [
        "花间游", "离经易道", "花间游·悟", "离经易道·悟",
    ]


def test_sect_marker_with_space():
    """兼容「◎ 万花」这类标记后带空白的写法。"""
    data = parse_patch_text("◎ 万花\n\n#花间游#\n\n·条目甲")
    assert data["sects"][0]["name"] == "万花"
    assert data["sects"][0]["xinfas"][0]["entries"] == ["条目甲"]


def test_sect_without_xinfa():
    """门派下直接出现条目（无 # 心法标题）时归入隐式心法（name 为空）。"""
    data = parse_patch_text("前言。\n\n◎旗舰通用\n\n·条目甲\n\n·条目乙")
    assert data["preamble"] == "前言。"
    xinfas = data["sects"][0]["xinfas"]
    assert len(xinfas) == 1 and xinfas[0]["name"] == ""
    assert xinfas[0]["entries"] == ["条目甲", "条目乙"]


def test_is_shared_flag():
    """name 含「通用」的门派/心法 is_shared = true，其余为 false。"""
    text = "◎旗舰通用\n\n·条目甲\n\n◎少林\n\n#旗舰通用#\n\n·条目乙\n\n#易筋经#\n\n·条目丙"
    data = parse_patch_text(text)
    assert data["sects"][0]["is_shared"] is True          # 门派级「旗舰通用」
    assert data["sects"][1]["is_shared"] is False
    xinfas = {x["name"]: x for x in data["sects"][1]["xinfas"]}
    assert xinfas["旗舰通用"]["is_shared"] is True        # 心法级「旗舰通用」
    assert xinfas["易筋经"]["is_shared"] is False


def test_0924_shaolin_qijian_shared():
    """验收：9/24 公告中少林门派下的旗舰通用 is_shared = true。"""
    data = parse_patch_file(PATCH_0924)
    shaolin = next(s for s in data["sects"] if s["name"] == "少林")
    qijian = next(x for x in shaolin["xinfas"] if x["name"] == "旗舰通用")
    assert qijian["is_shared"] is True


def test_notes_capture_narrative():
    """心法下不以 · 开头且未跟随条目的叙述段收入 notes。"""
    text = "◎万花\n\n#花间游#\n\n调整思路：\n\n本赛季计划改造丹鼎流派。\n\n·条目甲"
    data = parse_patch_text(text)
    xinfa = data["sects"][0]["xinfas"][0]
    assert xinfa["notes"] == "调整思路：\n\n本赛季计划改造丹鼎流派。"
    assert xinfa["entries"] == ["条目甲"]


def test_0908_coverage_no_silent_loss():
    """验收：9/8 公告 JSON 全部文本字数 ≥ 原 txt 字数 95%（防静默丢数据）。"""
    import re as _re

    def _texts(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from _texts(x)
        elif isinstance(v, list):
            for x in v:
                yield from _texts(x)

    txt_path = PATCH_0924.with_name("9月8日“苍生铸世”资料片首轮武学调整.txt")
    data = parse_patch_file(txt_path)
    strip = lambda s: _re.sub(r"\s+", "", s)
    json_chars = sum(len(strip(t)) for t in _texts(data))
    txt_chars = len(strip(txt_path.read_text(encoding="utf-8")))
    assert json_chars >= txt_chars * 0.95, f"{json_chars}/{txt_chars}"


def test_entry_continuation_paragraphs():
    """条目的续段（调整为/伤害变化等）并入同一条目，段落间以空行连接。"""
    text = "◎万花\n\n#花间游#\n\n·条目甲（原效果）\n\n调整为：新效果\n\n伤害降低10%。\n\n·条目乙"
    data = parse_patch_text(text)
    entries = data["sects"][0]["xinfas"][0]["entries"]
    assert entries == ["条目甲（原效果）\n\n调整为：新效果\n\n伤害降低10%。", "条目乙"]


def test_json_chinese_unescaped():
    """落盘 JSON：UTF-8 且中文不转义。"""
    out = ROOT / "data" / "patches" / "9月24日“苍生铸世”资料片第二轮武学调整.json"
    raw = out.read_text(encoding="utf-8")
    assert "万花" in raw
    assert "\\u4e07" not in raw
    json.loads(raw)  # 合法 JSON


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
