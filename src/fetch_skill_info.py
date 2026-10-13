# -*- coding: utf-8 -*-
"""剑网3技能库快照抓取器（简报 013）

数据源：https://jx3.unua.top/api/schools/data （玩家自建站，单次请求即全量，
无鉴权；礼貌纪律：每天最多请求一次，本地缓存后一切查询只读本地文件）

对外接口（可被其他模块 import）：
    fetch_skill_data(timeout=30)         拉取技能库全量 JSON（requests 失败回退 curl）
    validate_skill_data(data)            按简报 013 侦察结论校验（门派数 / 乱天狼锚点 /
                                         generatedAt / source），不符即抛 FetchError
    validate_generated_at(value)         校验 generatedAt 为合法 ISO8601 且非未来时间
    snapshot_uid(data)                   快照唯一标识（generatedAt）
    snapshot_filename(generated_at)      由 generatedAt 生成安全的落盘文件名
    save_snapshot(data, out_dir)         快照原样落盘（保留 generatedAt 与 source 字段）
    process_snapshot(data, ...)          校验 -> 比对 state -> 仅处理新快照（幂等）
    main()                               命令行入口：拉取 -> 校验 -> 增量落盘 -> 更新 state

状态文件沿用 data/state.json，以 generatedAt 为键：
    {
      "<generatedAt>": {"url": "<接口url>", "generated_at": "<generatedAt>",
                        "processed_at": "2026-10-04"}
    }
增量运行时，已处理快照的文件不会被改动或重写。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import timedelta as _timedelta
from datetime import timezone as _timezone
from pathlib import Path

import requests

from fetch_news import load_state, save_state

API_URL = "https://jx3.unua.top/api/schools/data"
# 简报 013 侦察结论：验证锚点
EXPECTED_FORCE_COUNT = 22
ANCHOR_SKILL_NAME = "乱天狼"
ANCHOR_SKILL_OCCURRENCES = 15
# generatedAt 容忍的未来时钟偏差（防止服务端时间戳异常）
_FUTURE_TOLERANCE = _timedelta(hours=1)

# 快照落盘目录（相对于本文件：workspace/data/skill-info）
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "skill-info"
# 增量状态文件（与 fetch_news 共用 workspace/data/state.json）
STATE_FILE = DEFAULT_OUT_DIR.parent / "state.json"


class FetchError(Exception):
    """接口请求失败，或返回数据与简报 013 侦察结论不符。"""


# ---------------------------------------------------------------- 抓取

def _fetch_via_curl(timeout: float) -> dict:
    """requests 请求失败时，回退用 curl 拉取同一接口（字节捕获，防 GBK 误伤 UTF-8）。"""
    import subprocess

    try:
        out = subprocess.run(
            ["curl", "-sS", "--max-time", str(int(timeout) or 30), API_URL],
            capture_output=True, timeout=timeout + 5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FetchError(f"curl 回退请求也失败：{exc}") from exc
    if out.returncode != 0:
        raise FetchError(f"curl 回退请求失败（退出码 {out.returncode}）："
                         f"{out.stderr.decode('utf-8', 'replace').strip()}")
    try:
        return json.loads(out.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise FetchError("curl 回退返回的不是合法 JSON") from exc


def fetch_skill_data(timeout: float = 30) -> dict:
    """从 unua.top 拉取技能库全量快照（约 1.1MB JSON）。

    :param timeout: 请求超时秒数；超时抛出带明确说明的 FetchError
    :return: 接口返回的顶层字典
    """
    try:
        resp = requests.get(API_URL, timeout=timeout)
        if resp.status_code != 200:
            raise FetchError(f"接口返回 HTTP {resp.status_code}：{API_URL}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise FetchError("接口返回的不是合法 JSON") from exc
    except requests.Timeout as exc:
        raise FetchError(f"接口请求超时（>{timeout}s）：{API_URL}") from exc
    except requests.RequestException:
        # TLS/连接异常时回退 curl 通道
        print("[提示] requests 请求失败，回退 curl 通道重试...")
        data = _fetch_via_curl(timeout)

    if not isinstance(data, dict):
        raise FetchError(f"接口返回结构异常，顶层应为对象，实际为 {type(data).__name__}")
    return data


# ---------------------------------------------------------------- 校验（简报 013 侦察结论）

def validate_generated_at(value) -> str:
    """校验 generatedAt：非空字符串、合法 ISO8601、非未来时间（容忍 1 小时偏差）。

    校验通过返回原字符串，否则抛 FetchError。
    """
    if not isinstance(value, str) or not value.strip():
        raise FetchError(f"generatedAt 缺失或非字符串：{value!r}")
    try:
        parsed = _datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise FetchError(f"generatedAt 不是合法 ISO8601 时间戳：{value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_timezone.utc)
    if parsed > _datetime.now(_timezone.utc) + _FUTURE_TOLERANCE:
        raise FetchError(f"generatedAt 指向未来时间，疑似异常：{value!r}")
    return value


def validate_skill_data(data: dict) -> dict:
    """按简报 013 侦察结论校验快照；任何一项不符即抛 FetchError 并报告差异，
    不做自行适配。校验通过返回原数据。
    """
    problems: list[str] = []

    forces = data.get("forces")
    if not isinstance(forces, list) or len(forces) != EXPECTED_FORCE_COUNT:
        actual = len(forces) if isinstance(forces, list) else type(forces).__name__
        problems.append(f"门派数应为 {EXPECTED_FORCE_COUNT}，实际为 {actual}")

    source = data.get("source")
    if not source:
        problems.append(f"source 字段缺失或为空：{source!r}")

    try:
        validate_generated_at(data.get("generatedAt"))
    except FetchError as exc:
        problems.append(str(exc))

    text = json.dumps(data, ensure_ascii=False)
    occurrences = text.count(ANCHOR_SKILL_NAME)
    if occurrences != ANCHOR_SKILL_OCCURRENCES:
        problems.append(f"技能「{ANCHOR_SKILL_NAME}」全文应出现 {ANCHOR_SKILL_OCCURRENCES} 次，"
                        f"实际出现 {occurrences} 次")

    if problems:
        report = "；".join(problems)
        raise FetchError(f"返回数据与简报 013 侦察结论不符，停止执行：{report}")
    return data


# ---------------------------------------------------------------- 落盘

_FILENAME_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


def snapshot_uid(data: dict) -> str:
    """快照唯一标识：generatedAt（先经 validate_generated_at 校验）。"""
    return validate_generated_at(data.get("generatedAt")).strip()


def snapshot_filename(generated_at: str) -> str:
    """由 generatedAt 生成安全文件名：冒号转连字符，去掉 Windows 非法字符。"""
    safe = _FILENAME_ILLEGAL.sub("", generated_at.strip().replace(":", "-"))
    return f"{safe or '未命名快照'}.json"


def save_snapshot(data: dict, out_dir: Path | str = DEFAULT_OUT_DIR) -> Path:
    """将快照原样存入 out_dir（UTF-8、中文不转义，保留 generatedAt 与 source 字段）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / snapshot_filename(snapshot_uid(data))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- 增量处理

def process_snapshot(data: dict,
                     out_dir: Path | str = DEFAULT_OUT_DIR,
                     state_path: Path | str = STATE_FILE) -> Path | None:
    """校验并处理一份快照：已处理（generatedAt 已在 state 中）则原样跳过返回 None，
    不改动任何已有文件；新快照则落盘并登记 state，返回文件路径。
    """
    validate_skill_data(data)
    uid = snapshot_uid(data)

    state = load_state(state_path)
    if uid in state:
        return None

    path = save_snapshot(data, out_dir)
    state[uid] = {"url": API_URL, "generated_at": uid,
                  "processed_at": _date.today().isoformat()}
    save_state(state, state_path)
    return path


# ---------------------------------------------------------------- 入口

def main() -> int:
    print(f"[1/3] 正在请求 {API_URL} ...")
    try:
        data = fetch_skill_data()
    except FetchError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    uid = data.get("generatedAt")
    print(f"[2/3] 拉取成功，generatedAt = {uid}，开始校验...")
    try:
        path = process_snapshot(data)
    except FetchError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    if path is None:
        print(f"[3/3] 快照 {uid} 已处理过，本次新增 0 条，已有文件与状态保持原样。")
    else:
        print(f"[3/3] 新快照已落盘 -> {path}（state 已登记）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
