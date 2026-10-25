# -*- coding: utf-8 -*-
"""agent_tools 的函数测试（简报 023：问答层三工具，只读本地不出网）

运行方式（项目根目录）：
    python tests/test_agent_tools.py
或：
    python -m pytest tests/test_agent_tools.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_tools import TOOL_SCHEMAS, ToolBox  # noqa: E402
from retriever import TfidfIndex  # noqa: E402

SKILL_DOC = {"id": "skill-0", "name": "镇山河",
             "text": "镇山河\n调息240秒\n产生4尺气场，队友免疫任何伤害。",
             "metadata": {"门派": "纯阳", "心法": "紫霞功", "类型": "技能"}}
PATCH_DOC = {"id": "patch-0", "name": "沁逸",
             "text": "第四重奇穴【沁逸】……调整为：持续3秒。",
             "metadata": {"门派": "万花", "心法": "花间游", "公告日期": "2026/09/24",
                          "is_changed": True, "类型": "技改"}}


def _make_box(jjc_dir: Path) -> ToolBox:
    return ToolBox(skill_index=TfidfIndex([SKILL_DOC]),
                   patch_index=TfidfIndex([PATCH_DOC]),
                   jjc_dir=jjc_dir)


def _write_snapshot(jjc_dir: Path, segment: str, day: str,
                    rows: list[dict] | None, unavailable_periods=()) -> Path:
    rankings = {}
    for period in ("node", "last7d", "last1d"):
        if rows is not None and period not in unavailable_periods:
            rankings[f"dps-{period}"] = {"kungfu_type": "dps",
                                         "period_type": period,
                                         "total": len(rows), "rows": rows}
        else:
            rankings[f"dps-{period}"] = {"kungfu_type": "dps",
                                         "period_type": period, "total": 0,
                                         "unavailable": "数据量过少",
                                         "rows": []}
    payload = {"snapshot_date": day, "segment": segment,
               "score_range": {"min": 2800, "max": 3100},
               "match_mode": "all", "periods": [], "rankings": rankings}
    jjc_dir.mkdir(parents=True, exist_ok=True)
    path = jjc_dir / f"jjc-{segment}-{day}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


_ROWS = [{"rank": 1, "kungfu_id": "1", "kungfu_name": "幽罗引",
          "appear_rate": 0.0242, "win_rate": 0.5331, "can_recommend": False},
         {"rank": 2, "kungfu_id": "2", "kungfu_name": "冰心诀",
          "appear_rate": 0.0617, "win_rate": 0.5041, "can_recommend": False}]


def _tmp_dir() -> Path:
    return Path(tempfile.mkdtemp())


# ---------------------------------------------------------------- 检索类工具

def test_query_skill_formats_source():
    box = _make_box(_tmp_dir())
    out = box.query_skill("镇山河")
    assert "技能｜纯阳/紫霞功" in out and "镇山河" in out


def test_query_patch_carries_announce_date():
    box = _make_box(_tmp_dir())
    out = box.query_patch("沁逸")
    assert "技改｜万花/花间游｜公告2026/09/24" in out


def test_query_empty_hits_says_so():
    box = _make_box(_tmp_dir())
    box.skill_index = TfidfIndex([])  # 空索引
    assert "未检索到相关资料" in box.query_skill("不存在的东西")


# ---------------------------------------------------------------- 强度榜工具

def test_meta_rank_fallback_and_format():
    """last7d 样本不足时回退 node 并注明；行格式含胜率/出场率。"""
    d = _tmp_dir()
    _write_snapshot(d, "2800-3100", "2026-10-25", _ROWS,
                    unavailable_periods=("last7d", "last1d"))
    out = _make_box(d).query_meta_rank()
    assert "数据日期 2026-10-25" in out
    assert "2800-3100" in out and "节点期" in out
    assert "已回退" in out and "数据量过少" in out
    assert "1. 幽罗引｜胜率 53.31%｜出场率 2.42%" in out


def test_meta_rank_picks_latest_snapshot():
    """同一分段多份快照取日期最新的一份。"""
    d = _tmp_dir()
    _write_snapshot(d, "all", "2026-10-24", _ROWS)
    newer = [dict(r, kungfu_name="藏剑", win_rate=0.5844) for r in _ROWS[:1]]
    _write_snapshot(d, "all", "2026-10-25", newer)
    out = _make_box(d).query_meta_rank(segment="all", period="node")
    assert "数据日期 2026-10-25" in out and "藏剑" in out


def test_meta_rank_missing_segment_lists_available():
    """分段快照整体缺失时列出可用分段，不编造。"""
    d = _tmp_dir()
    _write_snapshot(d, "all", "2026-10-25", _ROWS)
    out = _make_box(d).query_meta_rank(segment="2800-3100")
    assert "没有分段 2800-3100" in out and "all" in out


def test_meta_rank_all_periods_unavailable():
    """所有时间维度都无数据时如实说明。"""
    d = _tmp_dir()
    _write_snapshot(d, "2800-3100", "2026-10-25", None)
    out = _make_box(d).query_meta_rank()
    assert "所有时间维度均无数据" in out


def test_meta_rank_bad_kungfu_type():
    out = _make_box(_tmp_dir()).query_meta_rank(kungfu_type="坦克")
    assert "参数错误" in out


def test_meta_rank_force_view():
    """view=force：读 arena-rank 最新 3v3 快照，返回前 200 名门派分布。"""
    d = _tmp_dir()
    arena = d / "arena"
    arena.mkdir()
    payload = {"snapshot_date": "2026-10-20", "total": 1000, "top_n": 200,
               "force_stats": {"长歌": 33, "万花": 28}, "rows": []}
    (arena / "3v3-2026-10-20.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    box = _make_box(d)
    box.arena_dir = arena
    out = box.query_meta_rank(view="force")
    assert "前 200 名门派分布" in out and "数据日期 2026-10-20" in out
    assert "长歌：33 人" in out and "万花：28 人" in out


def test_meta_rank_force_view_missing_snapshot():
    box = _make_box(_tmp_dir())
    box.arena_dir = _tmp_dir()  # 空目录
    assert "没有 3v3 排行榜快照" in box.query_meta_rank(view="force")


def test_meta_rank_bad_view():
    assert "参数错误" in _make_box(_tmp_dir()).query_meta_rank(view="xx")


def test_available_segments_skips_legacy_filename():
    """旧版无分段文件（jjc-2026-10-24.json）不进分段列表。"""
    d = _tmp_dir()
    _write_snapshot(d, "all", "2026-10-25", _ROWS)
    (d / "jjc-2026-10-24.json").write_text("{}", encoding="utf-8")
    assert _make_box(d).available_segments() == ["all"]


# ---------------------------------------------------------------- 分发

def test_dispatch_routes_and_parses_string_args():
    box = _make_box(_tmp_dir())
    out = box.dispatch("query_skill", '{"question": "镇山河"}')
    assert "镇山河" in out


def test_dispatch_unknown_tool_returns_error_text():
    out = _make_box(_tmp_dir()).dispatch("hack_api", {})
    assert "未知工具" in out and "hack_api" in out


def test_dispatch_bad_json_returns_error_text():
    assert "不是合法 JSON" in _make_box(_tmp_dir()).dispatch("query_skill", "{oops")


def test_dispatch_bad_param_returns_error_text():
    out = _make_box(_tmp_dir()).dispatch("query_meta_rank", {"段位": "2800"})
    assert "参数错误" in out


def test_tool_schemas_shape():
    """schema 符合 OpenAI tools 格式，三工具齐备。"""
    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert names == ["query_skill", "query_patch", "query_meta_rank"]
    for t in TOOL_SCHEMAS:
        assert t["type"] == "function"
        assert t["function"]["parameters"]["type"] == "object"


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
