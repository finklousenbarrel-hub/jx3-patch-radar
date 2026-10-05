# -*- coding: utf-8 -*-
"""make_report 的验收测试（简报 008）

运行方式（项目根目录）：
    python tests/test_make_report.py
或：
    python -m pytest tests/test_make_report.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from make_report import generate_report, generate_report_file  # noqa: E402

JSON_0924 = ROOT / "data" / "patches" / "9月24日“苍生铸世”资料片第二轮武学调整.json"
JSON_0908 = ROOT / "data" / "patches" / "9月8日“苍生铸世”资料片首轮武学调整.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_ranking_sum_matches_counts():
    """验收：9/24 简报变化榜条目数合计 = 352，与 JSON 三数一致。"""
    data = _load(JSON_0924)
    md = generate_report(data)
    board = md.split("## 改动变化榜")[1].split("## 分门派详情")[0]
    nums = [int(m.group(1)) for line in board.splitlines()
            if (m := re.match(r"\|\s*\d+\s*\|[^|]+\|\s*(\d+)\s*\|", line))]
    assert sum(nums) == 352, sum(nums)
    assert len(nums) == len(data["sects"])


def _section(md: str, heading: str, level: int) -> str:
    """截取 heading 小节到下一个同级或更高级标题之间的文本。"""
    hashes = "#" * level
    m = re.search(rf"^{hashes} {re.escape(heading)}\s*$", md, re.M)
    assert m, f"找不到标题：{hashes} {heading}"
    rest = md[m.end():]
    nxt = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def test_qinyi_in_wanhua_huajianyou():
    """验收：『沁逸』条目出现在万花/花间游小节。"""
    md = generate_report(_load(JSON_0924))
    sect = _section(md, "万花", 3)
    xinfa = _section(sect, "花间游", 4)
    assert "沁逸" in xinfa


def test_header_counts():
    """标题头含标题 / 日期 / 三数统计。"""
    md = generate_report(_load(JSON_0924))
    assert md.startswith("# 9月24日“苍生铸世”资料片第二轮武学调整\n")
    assert "日期：2026/09/24" in md
    assert "门派数：21 ｜ 心法数：65 ｜ 条目数：352" in md


def test_shared_label():
    """is_shared 的门派/心法标注「（通用）」。"""
    md = generate_report(_load(JSON_0908))
    assert "### 旗舰通用（通用）" in md
    md24 = generate_report(_load(JSON_0924))
    assert "#### 旗舰通用（通用）" in md24  # 少林等门派下的共享心法
    assert "#### 易筋经（通用）" not in md24


def test_notes_before_entries():
    """notes 叙述文保留在心法开头、条目之前（9/8 调整思路）。"""
    md = generate_report(_load(JSON_0908))
    sect = _section(md, "万花", 3)
    xinfa = _section(sect, "花间游", 4)
    assert "调整思路" in xinfa
    if "- " in xinfa:
        assert xinfa.index("调整思路") < xinfa.index("- ")


def test_deterministic_regeneration():
    """验收：连续生成两次，产出逐字节一致（git status 无变化的前提）。"""
    data = _load(JSON_0924)
    assert generate_report(data) == generate_report(data)
    out_dir = Path(tempfile.mkdtemp())
    p1 = generate_report_file(JSON_0924, out_dir)
    first = p1.read_bytes()
    p2 = generate_report_file(JSON_0924, out_dir)
    assert p1 == p2 and p2.read_bytes() == first


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
