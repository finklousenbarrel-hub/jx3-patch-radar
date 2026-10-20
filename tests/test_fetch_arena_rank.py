# -*- coding: utf-8 -*-
"""fetch_arena_rank 的函数测试（简报 020：推栏名剑榜快照抓取器）

运行方式（项目根目录）：
    python tests/test_fetch_arena_rank.py
或：
    python -m pytest tests/test_fetch_arena_rank.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import fetch_arena_rank  # noqa: E402
from fetch_arena_rank import (  # noqa: E402
    FetchError,
    TOP_N,
    UNKNOWN_FORCE,
    _signed_request,
    build_payload,
    flatten_rows,
    force_statistics,
    load_credentials,
    process_snapshot,
    snapshot_uid,
    validate_top200,
    xsk_sign,
)

_TODAY = date(2020, 1, 1)


def _fake_row(rank: int, force: str = "万花") -> dict:
    return {
        "rankNum": str(rank),
        "score": str(4000 - rank),
        "winRate": "60%",
        "upNum": "",
        "personInfo": {
            "roleName": f"测试角色{rank:04d}",
            "server": "梦江南",
            "zone": "电信区",
            "force": force,
            "gameRoleId": str(30000000 + rank),
            "gameGlobalRoleId": f"SK01-TEST-{rank:04d}",
        },
    }


def _fake_board(n: int = 1000, force: str = "万花") -> dict:
    return {"code": 0, "msg": "success",
            "data": [_fake_row(i, force) for i in range(1, n + 1)]}


def _expect_fetch_error(fn, hint: str = "") -> str:
    """断言调用抛出 FetchError，返回异常消息。"""
    try:
        fn()
    except FetchError as exc:
        return str(exc)
    raise AssertionError(f"应抛出 FetchError（{hint}）")


def _tmp(name: str) -> Path:
    return Path(tempfile.mkdtemp()) / name


# ---------------------------------------------------------------- 校验

def test_validate_ok():
    """结构正常的榜单校验通过，返回原数据。"""
    board = _fake_board()
    assert validate_top200(board) is board


def test_validate_empty_data():
    """data 为空列表或不是列表时报错。"""
    _expect_fetch_error(lambda: validate_top200({"code": 0, "data": []}), "空列表")
    _expect_fetch_error(lambda: validate_top200({"code": 0, "data": "x"}), "非列表")


def test_validate_rank_gap():
    """rankNum 断号时报错并指出 rankNum 异常。"""
    board = _fake_board(10)
    del board["data"][4]  # 去掉第 5 名，1..10 断号
    msg = _expect_fetch_error(lambda: validate_top200(board))
    assert "rankNum" in msg


def test_validate_rank_not_int():
    """rankNum 不是整数时报错。"""
    board = _fake_board(3)
    board["data"][1]["rankNum"] = "第二名"
    _expect_fetch_error(lambda: validate_top200(board), "rankNum 非整数")


def test_validate_missing_personinfo_key():
    """personInfo 缺 force/server/zone 键时报错。"""
    board = _fake_board(3)
    del board["data"][0]["personInfo"]["force"]
    msg = _expect_fetch_error(lambda: validate_top200(board))
    assert "force" in msg


def test_validate_empty_force_ok():
    """force 值为空字符串是线上实况（简报 020 侦查），校验应放行。"""
    board = _fake_board(5)
    board["data"][2]["personInfo"]["force"] = ""
    assert validate_top200(board) is board


# ---------------------------------------------------------------- 压平与统计

def test_flatten_rows_mapping():
    """字段压平映射正确，空 force 归一为「未知」。"""
    board = _fake_board(3)
    board["data"][1]["personInfo"]["force"] = ""
    rows = flatten_rows(board)
    assert len(rows) == 3
    first = rows[0]
    assert first["rank"] == 1 and first["force"] == "万花"
    assert first["server"] == "梦江南" and first["zone"] == "电信区"
    assert first["win_rate"] == "60%" and first["score"] == str(4000 - 1)
    assert first["game_role_id"] == str(30000001)
    assert first["global_id"] == "SK01-TEST-0001"
    assert rows[1]["force"] == UNKNOWN_FORCE


def test_force_statistics_top_n_only():
    """只统计前 top_n 名，且合计等于 top_n。"""
    rows = flatten_rows(_fake_board(250))
    for r in rows[TOP_N:]:
        r["force"] = "七秀"
    stats = force_statistics(rows, TOP_N)
    assert stats == {"万花": TOP_N}
    assert sum(stats.values()) == TOP_N


def test_force_statistics_sorted():
    """统计结果按数量降序、同量按门派名升序，输出确定。"""
    rows = flatten_rows(_fake_board(10))
    for i, force in enumerate(["七秀", "七秀", "七秀", "五毒", "五毒"]):
        rows[i]["force"] = force
    stats = force_statistics(rows, 10)
    assert list(stats.items()) == [("万花", 5), ("七秀", 3), ("五毒", 2)]


# ---------------------------------------------------------------- 签名与请求组装

def test_xsk_sign_vector():
    """X-Sk 签名与独立实现的 HMAC-SHA256 一致（小写 hex）。"""
    raw = '{"a":1,"ts":"20200101000000000"}'
    expected = hmac.new(b"k", (raw + "s").encode("utf-8"), hashlib.sha256).hexdigest()
    assert xsk_sign(raw, "k", "s") == expected


def test_signed_request_headers():
    """签名请求带齐推栏 headers：token/deviceId/UA/sign/X-Sk，body 含 17 位 ts。"""
    creds = {"ticket": "aa:bb:ccdd", "device_id": "ccdd",
             "xsk_key": "k", "xsk_salt": "s"}
    raw, headers = _signed_request("https://m.pvp.xoyo.com/x", {"m": 1}, creds)
    assert headers["token"] == "aa:bb:ccdd"
    assert headers["deviceId"] == "ccdd"
    assert headers["User-Agent"].startswith("okhttp")
    assert headers["sign"] == "true"
    body = json.loads(raw)
    assert body["m"] == 1 and len(body["ts"]) == 17
    assert headers["X-Sk"] == xsk_sign(raw, "k", "s")


def test_load_credentials_ok():
    """凭证齐全时解析出 deviceId（ticket 末段）。"""
    env = {"JX3_Ticket": "h1:UID_X:qq:acct:dev01",
           "JX3_XSK_KEY": "k", "JX3_XSK_SALT": "s"}
    creds = load_credentials(env)
    assert creds["device_id"] == "dev01"
    assert creds["xsk_key"] == "k" and creds["xsk_salt"] == "s"


def test_load_credentials_missing():
    """缺配置时报错并指明缺哪几项。"""
    msg = _expect_fetch_error(lambda: load_credentials({}))
    assert "JX3_Ticket" in msg and "JX3_XSK_KEY" in msg and "JX3_XSK_SALT" in msg
    msg = _expect_fetch_error(
        lambda: load_credentials({"JX3_Ticket": "a:b:c"}))
    assert "JX3_XSK_KEY" in msg and "JX3_Ticket" not in msg


# ---------------------------------------------------------------- 落盘与幂等

def test_snapshot_uid():
    """快照 uid 为 mode-日期。"""
    assert snapshot_uid("3v3", _TODAY) == "3v3-2020-01-01"


def test_build_payload():
    """落盘快照结构：统计口径前 top_n 名，rows 保留全量。"""
    payload = build_payload("3v3", _fake_board(250), today=_TODAY)
    assert payload["mode"] == "3v3"
    assert payload["snapshot_date"] == "2020-01-01"
    assert payload["total"] == 250 and payload["top_n"] == TOP_N
    assert len(payload["rows"]) == 250
    assert sum(payload["force_stats"].values()) == TOP_N


def test_process_snapshot_idempotent():
    """首次落盘并登记 state；再次处理返回 None，文件与 state 逐字节不变。"""
    out_dir = _tmp("arena-rank")
    state_path = _tmp("state.json")
    payload = build_payload("3v3", _fake_board(250), today=_TODAY)

    path = process_snapshot(payload, out_dir, state_path)
    assert path is not None and path.exists()
    assert path.name == "3v3-2020-01-01.json"
    first_bytes = path.read_bytes()
    state_bytes = state_path.read_bytes()

    assert process_snapshot(payload, out_dir, state_path) is None
    assert path.read_bytes() == first_bytes
    assert state_path.read_bytes() == state_bytes


def test_snapshot_file_encoding():
    """落盘 JSON 为 UTF-8 且中文不转义。"""
    out_dir = _tmp("arena-rank")
    state_path = _tmp("state.json")
    payload = build_payload("3v3", _fake_board(3), today=_TODAY)
    path = process_snapshot(payload, out_dir, state_path)
    text = path.read_text(encoding="utf-8")
    assert "万花" in text and "\\u" not in text


# ---------------------------------------------------------------- 日频守卫（main 不发请求）

def test_main_daily_guard_no_request():
    """state 已有今日 uid 时 main 直接返回 0，不发起任何抓取。"""
    state_path = _tmp("state.json")
    state_path.write_text(json.dumps(
        {snapshot_uid("3v3"): {"url": "x", "processed_at": "2020-01-01"}},
        ensure_ascii=False), encoding="utf-8")

    calls = {"fetch": 0}
    orig_state_file = fetch_arena_rank.STATE_FILE
    orig_fetch = fetch_arena_rank.fetch_top200

    def _forbidden_fetch(*a, **kw):
        calls["fetch"] += 1
        raise AssertionError("日频守卫失效：已处理当日快照仍发起了抓取")

    fetch_arena_rank.STATE_FILE = state_path
    fetch_arena_rank.fetch_top200 = _forbidden_fetch
    try:
        assert fetch_arena_rank.main("3v3") == 0
    finally:
        fetch_arena_rank.STATE_FILE = orig_state_file
        fetch_arena_rank.fetch_top200 = orig_fetch
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
