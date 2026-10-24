# -*- coding: utf-8 -*-
"""fetch_jjc_stats 的函数测试（简报 022：推栏心法强度榜快照抓取器）

运行方式（项目根目录）：
    python tests/test_fetch_jjc_stats.py
或：
    python -m pytest tests/test_fetch_jjc_stats.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import fetch_jjc_stats  # noqa: E402
from fetch_jjc_stats import (  # noqa: E402
    FetchError,
    build_payload,
    enabled_periods,
    flatten_rank_rows,
    process_snapshot,
    save_snapshot,
    snapshot_uid,
    validate_rank_rows,
)

_TODAY = date(2020, 1, 1)


def _fake_options() -> dict:
    return {
        "minScore": 1000,
        "maxScore": 3300,
        "periods": [
            {"periodType": "node", "periodName": "7月13日-今天", "disabled": False},
            {"periodType": "last7d", "periodName": "近7日", "disabled": False},
            {"periodType": "last1d", "periodName": "近1日", "disabled": True},
        ],
    }


def _fake_rank_response(names: list[str]) -> dict:
    rows = []
    for i, name in enumerate(names, start=1):
        rows.append({
            "strengthRank": i,
            "kungfuId": 10000 + i,
            "kungfuName": name,
            "kungfuIcon": f"icon/{i}.png",
            "appearRate": round(0.5 - i * 0.01, 4),
            "winRate": round(0.6 - i * 0.01, 4),
            "canRecommend": False,
        })
    return {"code": 0, "msg": "success", "data": {"cursor": 0, "data": rows}}


def _expect_fetch_error(fn, hint: str = "") -> str:
    """断言调用抛出 FetchError，返回异常消息。"""
    try:
        fn()
    except FetchError as exc:
        return str(exc)
    raise AssertionError(f"应抛出 FetchError（{hint}）")


def _tmp(name: str) -> Path:
    return Path(tempfile.mkdtemp()) / name


# ---------------------------------------------------------------- 时间维度筛选

def test_enabled_periods_filters_disabled():
    """disabled 的时间维度被剔除，保留下发顺序与标签。"""
    periods = enabled_periods(_fake_options())
    assert [p["periodType"] for p in periods] == ["node", "last7d"]
    assert periods[0]["periodName"] == "7月13日-今天"


def test_enabled_periods_all_disabled_raises():
    """全部 disabled 时抛 FetchError，不静默产出空快照。"""
    options = _fake_options()
    for p in options["periods"]:
        p["disabled"] = True
    msg = _expect_fetch_error(lambda: enabled_periods(options), "全部 disabled")
    assert "没有可用的时间维度" in msg


# ---------------------------------------------------------------- 压平与校验

def test_flatten_and_validate_ok():
    """结构正常的响应压平后通过校验，字段齐全。"""
    rows = validate_rank_rows(
        flatten_rank_rows(_fake_rank_response(["幽罗引", "分山劲"])), "dps/node")
    assert rows[0] == {"rank": 1, "kungfu_id": 10001, "kungfu_name": "幽罗引",
                       "appear_rate": 0.49, "win_rate": 0.59,
                       "can_recommend": False}


def test_flatten_rejects_bad_envelope():
    """缺 data.data 列表的响应直接抛 FetchError。"""
    msg = _expect_fetch_error(lambda: flatten_rank_rows({"code": 0, "data": {}}),
                              "坏信封")
    assert "data.data" in msg


def test_validate_empty_rows_raises():
    """空榜单抛 FetchError（tps 榜行数少但不应为空）。"""
    msg = _expect_fetch_error(lambda: validate_rank_rows([], "tps/node"), "空榜")
    assert "榜单为空" in msg


def test_validate_noncontiguous_ranks_raises():
    """strengthRank 不连续时抛 FetchError，不自行适配。"""
    data = _fake_rank_response(["幽罗引", "分山劲"])
    data["data"]["data"][1]["strengthRank"] = 5
    rows = flatten_rank_rows(data)
    msg = _expect_fetch_error(lambda: validate_rank_rows(rows, "dps/node"), "跳号")
    assert "连续整数" in msg


def test_validate_rate_out_of_range_raises():
    """胜率超出 0~1 时抛 FetchError（防单位口径漂移，如变成百分数）。"""
    data = _fake_rank_response(["幽罗引"])
    data["data"]["data"][0]["winRate"] = 53.29
    rows = flatten_rank_rows(data)
    msg = _expect_fetch_error(lambda: validate_rank_rows(rows, "dps/node"), "胜率口径")
    assert "0~1" in msg


def test_validate_blank_name_raises():
    """kungfuName 为空时抛 FetchError。"""
    data = _fake_rank_response(["幽罗引"])
    data["data"]["data"][0]["kungfuName"] = ""
    rows = flatten_rank_rows(data)
    msg = _expect_fetch_error(lambda: validate_rank_rows(rows, "dps/node"), "空名")
    assert "kungfuName" in msg


# ---------------------------------------------------------------- 组装与落盘

def test_snapshot_uid_daily():
    """快照 uid 为日频：jjc-<日期>。"""
    assert snapshot_uid(_TODAY) == "jjc-2020-01-01"


def test_build_payload_structure():
    """快照含分段区间、match_mode、可用时间维度与 rankings。"""
    rankings = {"dps-node": {"kungfu_type": "dps", "period_type": "node",
                             "total": 2,
                             "rows": flatten_rank_rows(
                                 _fake_rank_response(["幽罗引", "分山劲"]))}}
    payload = build_payload(rankings, _fake_options(), _TODAY)
    assert payload["snapshot_date"] == "2020-01-01"
    assert payload["score_range"] == {"min": 1000, "max": 3300}
    assert payload["match_mode"] == "all"
    assert [p["period_type"] for p in payload["periods"]] == ["node", "last7d"]
    assert payload["rankings"]["dps-node"]["rows"][0]["kungfu_name"] == "幽罗引"


def test_save_snapshot_filename_and_encoding():
    """落盘文件名 = uid，UTF-8 中文不转义。"""
    payload = build_payload({}, _fake_options(), _TODAY)
    path = save_snapshot(payload, _tmp("out"))
    assert path.name == "jjc-2020-01-01.json"
    raw = path.read_bytes().decode("utf-8")
    assert "近7日" in raw and "\\u" not in raw


def test_process_snapshot_idempotent():
    """首次落盘并登记 state；重复处理返回 None 且文件逐字节不变。"""
    payload = build_payload({}, _fake_options(), _TODAY)
    out_dir, state_path = _tmp("out"), _tmp("state.json")
    path = process_snapshot(payload, out_dir, state_path)
    assert path is not None and path.exists()
    before = path.read_bytes()
    assert process_snapshot(payload, out_dir, state_path) is None
    assert path.read_bytes() == before
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "jjc-2020-01-01" in state


# ---------------------------------------------------------------- 日频守卫（main 不发请求）

def test_main_daily_guard_no_request():
    """state 已有今日 uid 时 main 直接返回 0，不发起任何抓取。"""
    state_path = _tmp("state.json")
    state_path.write_text(json.dumps(
        {snapshot_uid(): {"url": "x", "processed_at": "2020-01-01"}},
        ensure_ascii=False), encoding="utf-8")

    calls = {"fetch": 0}
    orig_state_file = fetch_jjc_stats.STATE_FILE
    orig_status = fetch_jjc_stats.fetch_aggregate_status

    def _forbidden_fetch(*a, **kw):
        calls["fetch"] += 1
        raise AssertionError("日频守卫失效：已处理当日快照仍发起了抓取")

    fetch_jjc_stats.STATE_FILE = state_path
    fetch_jjc_stats.fetch_aggregate_status = _forbidden_fetch
    try:
        assert fetch_jjc_stats.main() == 0
    finally:
        fetch_jjc_stats.STATE_FILE = orig_state_file
        fetch_jjc_stats.fetch_aggregate_status = orig_status
    assert calls["fetch"] == 0


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
