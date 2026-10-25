# -*- coding: utf-8 -*-
"""推栏名剑数据（心法强度榜）快照抓取器（简报 022）

数据源：推栏直调 POST /jjcrankstats/*（简报 021 探针结论）：
    aggregate-status/query  数据可用性开关（hasAggregate=false 时短路不抓）
    filter-options/query    筛选元数据（分段范围 minScore/maxScore、时间维度 periods）
    kungfu-rank/query       心法强度榜主表（strengthRank/appearRate/winRate）
host 固定 https://m.pvp.xoyo.com，不走 server-mapping，没有 /3c 前缀。
签名与鉴权沿用简报 019 方案，复用 fetch_arena_rank 的 tuilan_post。

快照口径（简报 023 升级为每日双快照）：分段 all（filter-options 全区间）
与 2800-3100（高分段），每个分段各自覆盖 kungfuType（dps/tps）× 全部可用
periodType（node/last7d/last1d，以 filter-options 下发为准，不写死），
matchMode 固定 all。排序在客户端做，服务端只按综合强度返回；rows 保留原始
强度名次。幂等 uid = 分段 + 日期，双快照互不顶替。

礼貌纪律：每日最多爬取一次——main 先查 state 再决定是否发请求，
当日全部分段已处理则输出“本次新增 0 条”且不发任何请求。

对外接口（可被其他模块 import）：
    fetch_aggregate_status(creds)      数据可用性开关
    fetch_filter_options(creds)        筛选元数据
    fetch_kungfu_rank(creds, ...)      拉单一维度组合的心法强度榜
    enabled_periods(filter_options)    可用时间维度列表（纯函数）
    flatten_rank_rows(data, ...)       压平榜单行（纯函数）
    validate_rank_rows(rows, context)  行字段校验（不符即抛 FetchError）
    resolve_score_range(...)           确定实际抓取区间（越界即抛 FetchError）
    pending_segments(state, today)     今日未处理的分段配置（纯函数）
    build_payload(rankings, ...)       组装落盘快照（含 segment 与实际区间）
    snapshot_uid(segment, today)       快照唯一标识：jjc-all-2026-10-24
    save_snapshot / process_snapshot   幂等落盘（state.json 同款，已处理不改动）
    main()                             命令行入口

状态文件沿用 data/state.json，以 snapshot_uid 为键：
    {"jjc-all-2026-10-24": {"url": "<接口url>", "processed_at": "2026-10-24"},
     "jjc-2800-3100-2026-10-24": {...}}
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

# 每日双快照（简报 023）：全分段 + 高分段 2800-3100。
# 显式区间为 None 表示取 filter-options 下发的全区间；
# 显式区间必须落在下发范围内，否则抛 FetchError，不自行适配。
SEGMENTS = (
    ("all", None, None),
    ("2800-3100", 2800, 3100),
)
DEFAULT_SEGMENT = SEGMENTS[0][0]

# 推栏对样本不足的筛选组合返回 code=-1「数据量过少」——这是正常数据
# （窄分段 × 短周期样本不足），快照中记为 unavailable，不算接口漂移。
NO_DATA_HINT = "数据量过少"

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

def snapshot_uid(segment: str = DEFAULT_SEGMENT, today: _date | None = None) -> str:
    """快照唯一标识（日频 + 分段）：如 jjc-all-2026-10-24、jjc-2800-3100-2026-10-24。
    双快照靠 segment 段互相区分，不会互顶。
    """
    return f"jjc-{segment}-{(today or _date.today()).isoformat()}"


def resolve_score_range(segment: str, score_start: int | None,
                        score_end: int | None,
                        filter_options: dict) -> tuple[int, int]:
    """确定实际抓取区间：None 取 filter-options 全区间；显式区间必须落在
    下发范围内（含边界），否则抛 FetchError，不自行适配。
    """
    lo, hi = filter_options["minScore"], filter_options["maxScore"]
    if score_start is None and score_end is None:
        return lo, hi
    if score_start is None or score_end is None or score_start >= score_end:
        raise FetchError(f"分段 {segment} 显式区间非法：{score_start}~{score_end}")
    if score_start < lo or score_end > hi:
        raise FetchError(f"分段 {segment} 区间 {score_start}~{score_end} 超出 "
                         f"filter-options 下发范围 {lo}~{hi}，停止执行")
    return score_start, score_end


def pending_segments(state: dict, today: _date | None = None) -> list[tuple]:
    """今日尚未处理的分段配置（uid 不在 state 中的），保持 SEGMENTS 顺序。"""
    return [cfg for cfg in SEGMENTS
            if snapshot_uid(cfg[0], today) not in state]


def build_payload(rankings: dict, filter_options: dict,
                  segment: str = DEFAULT_SEGMENT,
                  score_start: int | None = None,
                  score_end: int | None = None,
                  today: _date | None = None) -> dict:
    """组装落盘快照：rankings 键为 {kungfu_type}-{period_type}。"""
    start, end = resolve_score_range(segment, score_start, score_end,
                                     filter_options)
    return {
        "snapshot_date": (today or _date.today()).isoformat(),
        "source": SOURCE_DESC,
        "segment": segment,
        "score_range": {"min": start, "max": end},
        "match_mode": MATCH_MODE,
        "periods": [{"period_type": p["periodType"],
                     "period_name": p.get("periodName") or ""}
                    for p in enabled_periods(filter_options)],
        "rankings": rankings,
    }


def save_snapshot(payload: dict, out_dir: Path | str = DEFAULT_OUT_DIR) -> Path:
    """快照落盘（UTF-8、中文不转义），文件名 = snapshot_uid（含分段）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    uid = snapshot_uid(payload["segment"],
                       _date.fromisoformat(payload["snapshot_date"]))
    path = out_dir / f"{uid}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def process_snapshot(payload: dict,
                     out_dir: Path | str = DEFAULT_OUT_DIR,
                     state_path: Path | str = STATE_FILE) -> Path | None:
    """已处理（uid 已在 state 中）则原样跳过返回 None；新快照落盘并登记 state。"""
    uid = snapshot_uid(payload["segment"],
                       _date.fromisoformat(payload["snapshot_date"]))
    state = load_state(state_path)
    if uid in state:
        return None
    path = save_snapshot(payload, out_dir)
    state[uid] = {"url": SOURCE_DESC, "processed_at": _date.today().isoformat()}
    save_state(state, state_path)
    return path


# ---------------------------------------------------------------- 入口

def main() -> int:
    state = load_state(STATE_FILE)
    pending = pending_segments(state)
    if not pending:
        uids = "、".join(snapshot_uid(cfg[0]) for cfg in SEGMENTS)
        print(f"今日快照均已处理（{uids}），本次新增 0 条，"
              "已有文件与状态保持原样。")
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
        saved: list[str] = []
        for segment, score_start, score_end in pending:
            start, end = resolve_score_range(segment, score_start, score_end,
                                             options)
            print(f"[3/4] 分段 {segment}（{start}~{end}）：拉取心法强度榜，"
                  f"matchMode={MATCH_MODE}，共 {len(combos)} 个维度组合...")
            rankings: dict[str, dict] = {}
            for kungfu_type, period_type in combos:
                context = f"{segment}/{kungfu_type}/{period_type}"
                try:
                    data = fetch_kungfu_rank(creds, kungfu_type, period_type,
                                             start, end)
                except FetchError as exc:
                    # 窄分段官方口径的「数据量过少」是正常数据（样本不足），
                    # 记为 unavailable 继续其余组合；其余错误照常抛出。
                    if NO_DATA_HINT not in str(exc):
                        raise
                    rankings[f"{kungfu_type}-{period_type}"] = {
                        "kungfu_type": kungfu_type,
                        "period_type": period_type,
                        "total": 0,
                        "unavailable": NO_DATA_HINT,
                        "rows": [],
                    }
                    print(f"  - {context}：{NO_DATA_HINT}，记为不可用")
                    continue
                rows = validate_rank_rows(flatten_rank_rows(data), context)
                rankings[f"{kungfu_type}-{period_type}"] = {
                    "kungfu_type": kungfu_type,
                    "period_type": period_type,
                    "total": len(rows),
                    "rows": rows,
                }
                print(f"  - {context}：{len(rows)} 行，榜首 {rows[0]['kungfu_name']}"
                      f"（胜率 {rows[0]['win_rate']:.2%}）")
            if all(not r["rows"] for r in rankings.values()):
                raise FetchError(f"分段 {segment} 全部维度组合都无数据，停止执行")
            payload = build_payload(rankings, options, segment, start, end)
            path = process_snapshot(payload)
            if path is None:
                print(f"[4/4] 快照 {snapshot_uid(segment)} 已处理过，跳过落盘。")
            else:
                saved.append(str(path))
                print(f"[4/4] 新快照已落盘 -> {path}（state 已登记）")
    except FetchError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    print(f"本次新增 {len(saved)} 份快照。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
