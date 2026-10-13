# -*- coding: utf-8 -*-
"""fetch_skill_info 的函数测试（简报 013：技能库快照抓取器）

运行方式（项目根目录）：
    python tests/test_fetch_skill_info.py
或：
    python -m pytest tests/test_fetch_skill_info.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fetch_skill_info import (  # noqa: E402
    ANCHOR_SKILL_NAME,
    FetchError,
    process_snapshot,
    save_snapshot,
    snapshot_filename,
    snapshot_uid,
    validate_generated_at,
    validate_skill_data,
)

_FAKE_GENERATED_AT = "2020-01-01T04:00:00Z"


def _fake_payload(force_count: int = 22, skill_occurrences: int = 15) -> dict:
    """构造满足简报 013 侦察结论的假快照：22 门派 + 乱天狼恰好出现 N 次。"""
    forces = [{"name": f"测试门派{i:02d}", "forceId": i} for i in range(force_count)]
    forces[0]["skillData"] = [{"skillName": ANCHOR_SKILL_NAME}
                              for _ in range(skill_occurrences)]
    return {
        "forces": forces,
        "source": {"name": "推栏", "url": "https://m.pvp.xoyo.com"},
        "generatedAt": _FAKE_GENERATED_AT,
    }


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
    """满足侦察结论的快照校验通过，返回原数据。"""
    payload = _fake_payload()
    assert validate_skill_data(payload) is payload


def test_validate_force_count_mismatch():
    """门派数不是 22 时报差异并停止。"""
    msg = _expect_fetch_error(lambda: validate_skill_data(_fake_payload(force_count=21)))
    assert "22" in msg and "21" in msg


def test_validate_source_missing():
    """source 缺失或为空时报差异。"""
    payload = _fake_payload()
    payload["source"] = None
    _expect_fetch_error(lambda: validate_skill_data(payload), "source 为空")


def test_validate_generated_at_not_iso():
    """generatedAt 不是合法 ISO8601 时报差异。"""
    payload = _fake_payload()
    payload["generatedAt"] = "不是日期"
    _expect_fetch_error(lambda: validate_skill_data(payload), "generatedAt 非法")


def test_validate_generated_at_future():
    """generatedAt 指向未来时间（超过容忍偏差）时报差异。"""
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    _expect_fetch_error(lambda: validate_generated_at(future), "未来时间")


def test_validate_generated_at_accepts_z_suffix():
    """带 Z 后缀的 ISO8601 校验通过并返回原值。"""
    assert validate_generated_at(_FAKE_GENERATED_AT) == _FAKE_GENERATED_AT


def test_validate_anchor_mismatch():
    """乱天狼出现次数不是 15 时报差异（含实际次数）。"""
    msg = _expect_fetch_error(
        lambda: validate_skill_data(_fake_payload(skill_occurrences=14)))
    assert "15" in msg and "14" in msg


# ---------------------------------------------------------------- 落盘

def test_snapshot_uid_is_generated_at():
    """快照唯一标识取 generatedAt。"""
    assert snapshot_uid(_fake_payload()) == _FAKE_GENERATED_AT


def test_snapshot_filename_safe():
    """文件名不含 Windows 非法字符（冒号转连字符）。"""
    name = snapshot_filename(_FAKE_GENERATED_AT)
    assert name.endswith(".json")
    for ch in '\\/:*?"<>|':
        assert ch not in name


def test_save_snapshot_preserves_generated_at_and_source():
    """落盘 JSON 原样保留 generatedAt 与 source，且中文不转义。"""
    payload = _fake_payload()
    path = save_snapshot(payload, _tmp("skill-info"))
    raw = path.read_text(encoding="utf-8")
    assert "测试门派" in raw  # ensure_ascii=False
    saved = json.loads(raw)
    assert saved["generatedAt"] == payload["generatedAt"]
    assert saved["source"] == payload["source"]
    assert len(saved["forces"]) == 22


# ---------------------------------------------------------------- 增量幂等

def test_process_snapshot_idempotent(tmp_path=None):
    """同一快照重复处理：首次落盘并登记 state，再次处理跳过且不改动任何文件。"""
    out_dir = _tmp("skill-info")
    state_path = _tmp("state.json")
    payload = _fake_payload()

    path = process_snapshot(payload, out_dir, state_path)
    assert path is not None and path.exists()
    first_bytes = path.read_bytes()

    state = json.loads(state_path.read_text(encoding="utf-8"))
    entry = state[_FAKE_GENERATED_AT]
    assert entry["generated_at"] == _FAKE_GENERATED_AT
    assert entry["processed_at"]

    # 再次处理：返回 None，已有文件与 state 逐字节不变
    state_bytes = state_path.read_bytes()
    assert process_snapshot(payload, out_dir, state_path) is None
    assert path.read_bytes() == first_bytes
    assert state_path.read_bytes() == state_bytes


def test_process_snapshot_invalid_writes_nothing():
    """校验失败时抛 FetchError，不落盘、不写 state。"""
    out_dir = _tmp("skill-info")
    state_path = _tmp("state.json")
    _expect_fetch_error(
        lambda: process_snapshot(_fake_payload(force_count=1), out_dir, state_path))
    assert not out_dir.exists() or not list(out_dir.iterdir())
    assert not state_path.exists()


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
