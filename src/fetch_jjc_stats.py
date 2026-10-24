# -*- coding: utf-8 -*-
"""推栏名剑数据（心法强度榜）快照抓取器（简报 022）

数据源：推栏直调 POST /jjcrankstats/*（简报 021 探针结论）：
    aggregate-status/query  数据可用性开关（hasAggregate=false 时短路不抓）
    filter-options/query    筛选元数据（分段范围 minScore/maxScore、时间维度 periods）
    kungfu-rank/query       心法强度榜主表（strengthRank/appearRate/winRate）
host 固定 https://m.pvp.xoyo.com，不走 server-mapping，没有 /3c 前缀。
签名与鉴权沿用简报 019 方案，复用 fetch_arena_rank 的 tuilan_post。

快照口径：kungfuType（dps/tps）× 全部可用 periodType（node/last7d/last1d，
以 filter-options 下发为准，不写死），matchMode 固定 all，分段取全区间。
排序在客户端做，服务端只按综合强度返回；rows 保留原始强度名次。

礼貌纪律：每日最多爬取一次——main 先查 state 再决定是否发请求，
当日已处理则输出“本次新增 0 条”且不发任何请求。

对外接口（可被其他模块 import）：
    fetch_aggregate_status(creds)      数据可用性开关
    fetch_filter_options(creds)        筛选元数据
    fetch_kungfu_rank(creds, ...)      拉单一维度组合的心法强度榜
    enabled_periods(filter_options)    可用时间维度列表（纯函数）
    flatten_rank_rows(data, ...)       压平榜单行（纯函数）
    validate_rank_rows(rows, context)  行字段校验（不符即抛 FetchError）
    build_payload(rankings, ...)       组装落盘快照
    snapshot_uid(today)                快照唯一标识（日频：jjc-2026-10-20）
    save_snapshot / process_snapshot   幂等落盘（state.json 同款，已处理不改动）
    main()                             命令行入口

状态文件沿用 data/state.json，以 snapshot_uid 为键：
    {"jjc-2026-10-20": {"url": "<接口url>", "processed_at": "2026-10-20"}}
增量运行时，已处理快照的文件不会被改动或重写。
"""

from __future__ import annotations

import json
import sys
from datetime import date as _date
from pathlib import Path

from fetch_arena_rank import FetchError, load_credentials, tuilan_post
from fetch_news import load_state, save_state

BASE_URL = "https://m.pvp.xoyo.com"
AGGREGATE_STATUS_PATH = "/jjcrankstats/aggregate-status/query"
FILTER_OPTIONS_PATH = "/jjcrankstats/filter-options/query"
KUNGFU_RANK_PATH = "/jjcrankstats/kungfu-rank/query"
SOURCE_DESC = "推栏 /jjcrankstats/kungfu-rank/query"

KUNGFU_TYPES = ("dps", "tps")
MATCH_MODE = "all"
PAGE_CURSOR = 0
PAGE_SIZE = 100

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "jjc-stats"
STATE_FILE = DEFAULT_OUT_DIR.parent / "state.json"


# ---------------------------------------------------------------- 抓取

def fetch_aggregate_status(creds: dict, timeout: float = 30) -> bool:
    """数据可用性开关；hasAggregate=false 表示「功能升级维护中」，调用方应短路。"""
    data = tuilan_post(BASE_URL + AGGREGATE_STATUS_PATH, {}, creds, timeout)
    status = data.get("data")
    if not isinstance(status, dict) or "hasAggregate" not in status:
        raise FetchError("aggregate-status 返回缺少 hasAggregate 字段")
    return bool(status["hasAggregate"])


def fetch_filter_options(creds: dict, timeout: float = 30) -> dict:
    """筛选元数据：{minScore, maxScore, periods: [{periodType, periodName, disabled}]}。"""
    data = tuilan_post(BASE_URL + FILTER_OPTIONS_PATH, {}, creds, timeout)
    options = data.get("data")
    if not isinstance(options, dict):
        raise FetchError("filter-options 返回缺少 data 对象")
    for key in ("minScore", "maxScore"):
        if not isinstance(options.get(key), int):
            raise FetchError(f"filter-options 返回 {key} 缺失或非整数：{options.get(key)!r}")
    periods = options.get("periods")
    if not isinstance(periods, list) or not periods:
        raise FetchError("filter-options 返回缺少 periods 列表")
    return options


def fetch_kungfu_rank(creds: dict, kungfu_type: str, period_type: str,
                      score_start: int, score_end: int,
                      match_mode: str = MATCH_MODE,
                      cursor: int = PAGE_CURSOR, size: int = PAGE_SIZE,
                      timeout: float = 30) -> dict:
    """拉单一维度组合的心法强度榜，返回应用层 JSON（data: {cursor, data: [...]}）。"""
    if kungfu_type not in KUNGFU_TYPES:
        raise FetchError(f"未知心法类型：{kungfu_type!r}（可选：{'、'.join(KUNGFU_TYPES)}）")
    params = {
        "scoreStart": score_start,
        "scoreEnd": score_end,
        "matchMode": match_mode,
        "kungfuType": kungfu_type,
        "periodType": period_type,
        "cursor": cursor,
        "size": size,
    }
    return tuilan_post(BASE_URL + KUNGFU_RANK_PATH, params, creds, timeout)


# ---------------------------------------------------------------- 校验与压平

def enabled_periods(filter_options: dict) -> list[dict]:
    """可用时间维度（disabled 的剔除）；标签 periodName 随版本下发，不写死。"""
    periods = [p for p in filter_options["periods"]
               if isinstance(p, dict) and p.get("periodType") and not p.get("disabled")]
    if not periods:
        raise FetchError("filter-options 中没有可用的时间维度（全部 disabled）")
    return periods


def flatten_rank_rows(data: dict) -> list[dict]:
    """把 kungfu-rank 响应压平成行列表。"""
    body = data.get("data")
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise FetchError("kungfu-rank 返回缺少 data.data 列表")
    rows = []
    for row in body["data"]:
        rows.append({
            "rank": row.get("strengthRank"),
            "kungfu_id": row.get("kungfuId"),
            "kungfu_name": row.get("kungfuName") or "",
            "appear_rate": row.get("appearRate"),
            "win_rate": row.get("winRate"),
            "can_recommend": bool(row.get("canRecommend")),
        })
    return rows


def validate_rank_rows(rows: list[dict], context: str) -> list[dict]:
    """校验榜单行：非空；rank 为 1..N 连续整数；kungfu_name 非空；
    appear_rate / win_rate 为 0~1 小数。任何一项不符即抛 FetchError，
    不做自行适配。校验通过返回原列表。tps 榜仅数行属正常，不设下限。
    """
    if not rows:
        raise FetchError(f"{context}：榜单为空")
    problems: list[str] = []
    ranks: list[int] = []
    for i, row in enumerate(rows):
        rank = row.get("rank")
        if not isinstance(rank, int):
            problems.append(f"第 {i + 1} 行 strengthRank 缺失或非整数：{rank!r}")
        else:
            ranks.append(rank)
        if not row.get("kungfu_name"):
            problems.append(f"第 {i + 1} 行 kungfuName 为空")
        for key in ("appear_rate", "win_rate"):
            value = row.get(key)
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                problems.append(f"第 {i + 1} 行 {key} 应为 0~1 小数，实际为 {value!r}")
    if ranks and ranks != list(range(1, len(ranks) + 1)):
        problems.append(f"strengthRank 应为 1..{len(rows)} 连续整数，实际异常"
                        f"（min={min(ranks)}, max={max(ranks)}）")
    if problems:
        report = "；".join(problems[:10])
        raise FetchError(f"{context}：榜单数据校验失败，停止执行：{report}")
    return rows


# ---------------------------------------------------------------- 落盘

def snapshot_uid(today: _date | None = None) -> str:
    """快照唯一标识（日频）：如 jjc-2026-10-20。"""
    return f"jjc-{(today or _date.today()).isoformat()}"


def build_payload(rankings: dict, filter_options: dict,
                  today: _date | None = None) -> dict:
    """组装落盘快照：rankings 键为 {kungfu_type}-{period_type}。"""
    return {
        "snapshot_date": (today or _date.today()).isoformat(),
        "source": SOURCE_DESC,
        "score_range": {"min": filter_options["minScore"],
                        "max": filter_options["maxScore"]},
        "match_mode": MATCH_MODE,
        "periods": [{"period_type": p["periodType"],
                     "period_name": p.get("periodName") or ""}
                    for p in enabled_periods(filter_options)],
        "rankings": rankings,
    }


def save_snapshot(payload: dict, out_dir: Path | str = DEFAULT_OUT_DIR) -> Path:
    """快照落盘（UTF-8、中文不转义），文件名 = snapshot_uid。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{snapshot_uid(_date.fromisoformat(payload['snapshot_date']))}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def process_snapshot(payload: dict,
                     out_dir: Path | str = DEFAULT_OUT_DIR,
                     state_path: Path | str = STATE_FILE) -> Path | None:
    """已处理（uid 已在 state 中）则原样跳过返回 None；新快照落盘并登记 state。"""
    uid = snapshot_uid(_date.fromisoformat(payload["snapshot_date"]))
    state = load_state(state_path)
    if uid in state:
        return None
    path = save_snapshot(payload, out_dir)
    state[uid] = {"url": SOURCE_DESC, "processed_at": _date.today().isoformat()}
    save_state(state, state_path)
    return path


# ---------------------------------------------------------------- 入口

def main() -> int:
    uid = snapshot_uid()
    state = load_state(STATE_FILE)
    if uid in state:
        print(f"快照 {uid} 已处理过，本次新增 0 条，已有文件与状态保持原样。")
        return 0

    print("[1/4] 读取凭证并检查数据可用性（aggregate-status）...")
    try:
        creds = load_credentials()
        if not fetch_aggregate_status(creds):
            print("[提示] hasAggregate=false（功能升级维护中），本次不抓取，"
                  "state 不登记，明日再试。")
            return 0
        print("[2/4] 拉取筛选元数据（filter-options）...")
        options = fetch_filter_options(creds)
        periods = enabled_periods(options)
        combos = [(kt, p["periodType"]) for kt in KUNGFU_TYPES for p in periods]
        print(f"[3/4] 拉取心法强度榜：分段 {options['minScore']}~{options['maxScore']}，"
              f"matchMode={MATCH_MODE}，共 {len(combos)} 个维度组合...")
        rankings: dict[str, dict] = {}
        for kungfu_type, period_type in combos:
            context = f"{kungfu_type}/{period_type}"
            data = fetch_kungfu_rank(creds, kungfu_type, period_type,
                                     options["minScore"], options["maxScore"])
            rows = validate_rank_rows(flatten_rank_rows(data), context)
            rankings[f"{kungfu_type}-{period_type}"] = {
                "kungfu_type": kungfu_type,
                "period_type": period_type,
                "total": len(rows),
                "rows": rows,
            }
            print(f"  - {context}：{len(rows)} 行，榜首 {rows[0]['kungfu_name']}"
                  f"（胜率 {rows[0]['win_rate']:.2%}）")
    except FetchError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    payload = build_payload(rankings, options)
    path = process_snapshot(payload)
    if path is None:
        print(f"[4/4] 快照 {uid} 已处理过，本次新增 0 条。")
        return 0
    print(f"[4/4] 新快照已落盘 -> {path}（state 已登记）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
