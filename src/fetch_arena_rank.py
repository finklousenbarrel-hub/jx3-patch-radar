# -*- coding: utf-8 -*-
"""推栏名剑大会排行榜快照抓取器（简报 020）

数据源：推栏直调 POST {host}/mine/arena/top200（无分页，一次返回全榜），
host 由 POST /conf/server-mapping 的 mine 映射决定（zone=电信区 + MatchType）。
实测 3v3 返回 rank 1~1000（跨区合并）；每行 personInfo 含 force/server/zone 等。
简报 020 验收口径：对前 200 名做门派统计。

鉴权（简报 019 逆向结论）：header token=ticket（deviceId 取 ticket 末段）、
ts（UTC 17 位毫秒时间戳）、sign: true、X-Sk（HMAC-SHA256，key/salt 从 .env 读，
绝不进仓库）；User-Agent 必须伪装 okhttp，否则 nginx 直接 403。

礼貌纪律：每日最多爬取一次——main 先查 state 再决定是否发请求，
当日已处理则输出“本次新增 0 条”且不发任何请求。

对外接口（可被其他模块 import）：
    load_credentials(env=None)       读 JX3_Ticket / JX3_XSK_KEY / JX3_XSK_SALT
    xsk_sign(raw, key, salt)         X-Sk 签名（纯函数）
    tuilan_post(url, params, creds)  签名 POST（requests 失败回退 curl 字节捕获）
    fetch_top200(creds, mode)        server-mapping 取 host → 拉全榜
    validate_top200(data)            校验 code/rankNum 连续/personInfo 键
    flatten_rows(data)               压平榜单行（空 force 归一为“未知”）
    force_statistics(rows, top_n)    前 top_n 名门派计数
    snapshot_uid(mode, today)        快照唯一标识（日频：3v3-2026-10-19）
    build_payload(mode, data, ...)   组装落盘快照（含 force_stats 与全量 rows）
    save_snapshot / process_snapshot 幂等落盘（state.json 同款，已处理不改动）
    main()                           命令行入口

状态文件沿用 data/state.json，以 snapshot_uid 为键：
    {"3v3-2026-10-19": {"url": "<接口url>", "processed_at": "2026-10-19"}}
增量运行时，已处理快照的文件不会被改动或重写。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
import time
from collections import Counter
from datetime import date as _date
from pathlib import Path

import requests
from dotenv import load_dotenv

from fetch_news import load_state, save_state

BASE_URL = "https://m.pvp.xoyo.com"
MAPPING_PATH = "/conf/server-mapping"
TOP200_PATH = "/mine/arena/top200"
SOURCE_DESC = "推栏 /mine/arena/top200"
# server-mapping 里 mine 映射按 zone + MatchType 查 host；3v3 电信= /3c，
# 实测该 host 返回的是跨区合并的全服榜（电信/双线/无界都在内）
MAPPING_ZONE = "电信区"
MODES = {"2v2": 2, "3v3": 3, "5v5": 5}
DEFAULT_MODE = "3v3"
TOP_N = 200
# 简报 019 实测：不带 okhttp UA 会被 nginx 直接 403
USER_AGENT = "okhttp/4.9.0"
UNKNOWN_FORCE = "未知"

DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "arena-rank"
STATE_FILE = DEFAULT_OUT_DIR.parent / "state.json"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

_CRED_KEYS = ("JX3_Ticket", "JX3_XSK_KEY", "JX3_XSK_SALT")


class FetchError(Exception):
    """凭证缺失、接口请求失败，或返回数据与侦察结论不符。"""


# ---------------------------------------------------------------- 凭证与签名

def load_credentials(env: dict | None = None) -> dict:
    """读取推栏调用凭证。默认先 load_dotenv 再读 os.environ；
    测试可注入 env dict。缺失任一项抛 FetchError 并指明缺哪项。
    """
    if env is None:
        load_dotenv(ENV_FILE)
        import os
        env = os.environ
    missing = [k for k in _CRED_KEYS if not env.get(k)]
    if missing:
        raise FetchError(f".env 缺少配置：{'、'.join(missing)}（见简报 020 交付说明）")
    ticket = env["JX3_Ticket"].strip()
    device_id = ticket.split(":")[-1]
    if not device_id:
        raise FetchError("JX3_Ticket 格式异常：无法从末段解析 deviceId")
    return {"ticket": ticket, "device_id": device_id,
            "xsk_key": env["JX3_XSK_KEY"].strip(),
            "xsk_salt": env["JX3_XSK_SALT"]}


def _ts17(now: float | None = None) -> str:
    """UTC 17 位毫秒时间戳（YYYYMMDDHHmmssSSS）。"""
    now = time.time() if now is None else now
    return time.strftime("%Y%m%d%H%M%S", time.gmtime(now)) + f"{int(now * 1000) % 1000:03d}"


def xsk_sign(raw_body: str, key: str, salt: str) -> str:
    """X-Sk 签名：HMAC-SHA256(key, 原始 body 字符串 + salt) 的小写 hex。"""
    return hmac.new(key.encode("utf-8"), (raw_body + salt).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _signed_request(url: str, params: dict | None, creds: dict) -> tuple[str, dict]:
    """组装签名请求的 body 与 headers（不含发送，便于测试）。"""
    body = dict(params or {})
    body["ts"] = _ts17()
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "deviceId": creds["device_id"],
        "platform": "android",
        "gameName": "jx3",
        "fromSys": "APP",
        "clientKey": "1",
        "apiVersion": "3",
        "Cache-Control": "no-cache",
        "sign": "true",
        "X-Sk": xsk_sign(raw, creds["xsk_key"], creds["xsk_salt"]),
        "token": creds["ticket"],
        "User-Agent": USER_AGENT,
    }
    return raw, headers


# ---------------------------------------------------------------- 抓取

def _post_via_curl(url: str, raw: str, headers: dict, timeout: float) -> dict:
    """requests 失败时的 curl 回退通道（字节捕获，防 Windows GBK 毁掉 UTF-8）。"""
    import subprocess

    cmd = ["curl", "-sS", "--max-time", str(int(timeout) or 30),
           "-X", "POST", url, "-d", raw]
    for name, value in headers.items():
        cmd += ["-H", f"{name}: {value}"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FetchError(f"curl 回退请求也失败：{exc}") from exc
    if out.returncode != 0:
        raise FetchError(f"curl 回退请求失败（退出码 {out.returncode}）："
                         f"{out.stderr.decode('utf-8', 'replace').strip()}")
    try:
        return json.loads(out.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise FetchError("curl 回退返回的不是合法 JSON") from exc


def tuilan_post(url: str, params: dict | None, creds: dict,
                timeout: float = 30) -> dict:
    """签名 POST 推栏接口，返回应用层 JSON；HTTP/应用层错误均抛 FetchError。"""
    raw, headers = _signed_request(url, params, creds)
    try:
        resp = requests.post(url, data=raw.encode("utf-8"), headers=headers,
                             timeout=timeout)
    except requests.RequestException:
        print("[提示] requests 请求失败，回退 curl 通道重试...")
        return _post_via_curl(url, raw, headers, timeout)

    if resp.status_code == 403:
        raise FetchError(f"HTTP 403（疑似缺少 okhttp User-Agent 或被 WAF 拦截）：{url}")
    if resp.status_code != 200:
        raise FetchError(f"接口返回 HTTP {resp.status_code}：{url}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise FetchError("接口返回的不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise FetchError(f"接口返回结构异常，顶层应为对象，实际为 {type(data).__name__}")
    if data.get("code") != 0:
        raise FetchError(f"推栏返回错误 code={data.get('code')}：{data.get('msg')}"
                         f"（url={url}；若为鉴权错误请更新 .env 的 JX3_Ticket）")
    return data


def resolve_mine_host(creds: dict, mode: str = DEFAULT_MODE,
                      timeout: float = 30) -> str:
    """POST /conf/server-mapping，按 zone + MatchType 查 mine 映射的 host。"""
    match_type = MODES[mode]
    data = tuilan_post(BASE_URL + MAPPING_PATH, {}, creds, timeout)
    entries = data.get("data", {}).get("mine")
    if not isinstance(entries, list):
        raise FetchError("server-mapping 返回缺少 mine 映射列表")
    for entry in entries:
        if entry.get("Name") == MAPPING_ZONE and entry.get("MatchType") == match_type:
            host = str(entry.get("Value") or "").rstrip("/")
            if host:
                return host
    raise FetchError(f"server-mapping 中找不到 {MAPPING_ZONE} MatchType={match_type} 的 host")


def fetch_top200(creds: dict, mode: str = DEFAULT_MODE,
                 timeout: float = 30) -> dict:
    """拉取名剑大会全榜（无分页，一次全量）。mode 取值见 MODES。"""
    if mode not in MODES:
        raise FetchError(f"未知比赛模式：{mode!r}（可选：{'、'.join(MODES)}）")
    host = resolve_mine_host(creds, mode, timeout)
    return tuilan_post(host + TOP200_PATH, {}, creds, timeout)


# ---------------------------------------------------------------- 校验与统计

def validate_top200(data: dict) -> dict:
    """校验榜单响应：data 为非空 list、rankNum 为 1..N 连续整数、
    每行 personInfo 含 force/server/zone 键（force 值允许为空）。
    任何一项不符即抛 FetchError，不做自行适配。校验通过返回原数据。
    """
    problems: list[str] = []
    rows = data.get("data")
    if not isinstance(rows, list) or not rows:
        raise FetchError(f"榜单 data 应为非空列表，实际为 {type(rows).__name__}")

    ranks: list[int] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"第 {i + 1} 行不是对象")
            continue
        try:
            ranks.append(int(row["rankNum"]))
        except (KeyError, TypeError, ValueError):
            problems.append(f"第 {i + 1} 行 rankNum 缺失或非整数：{row.get('rankNum')!r}")
        person = row.get("personInfo")
        if not isinstance(person, dict):
            problems.append(f"第 {i + 1} 行缺 personInfo")
            continue
        for key in ("force", "server", "zone"):
            if key not in person:
                problems.append(f"第 {i + 1} 行 personInfo 缺 {key} 键")

    if ranks and ranks != list(range(1, len(ranks) + 1)):
        problems.append(f"rankNum 应为 1..{len(rows)} 连续整数，实际异常"
                        f"（min={min(ranks)}, max={max(ranks)}, 共{len(ranks)}个）")

    if problems:
        report = "；".join(problems[:10])
        raise FetchError(f"榜单数据校验失败，停止执行：{report}")
    return data


def flatten_rows(data: dict) -> list[dict]:
    """把榜单压平成行列表；force 为空归一为「未知」（实测有空值）。"""
    rows = []
    for row in data["data"]:
        person = row.get("personInfo") or {}
        force = (person.get("force") or "").strip() or UNKNOWN_FORCE
        rows.append({
            "rank": int(row["rankNum"]),
            "role_name": person.get("roleName") or "",
            "server": person.get("server") or "",
            "zone": person.get("zone") or "",
            "force": force,
            "score": row.get("score") or "",
            "win_rate": row.get("winRate") or "",
            "game_role_id": person.get("gameRoleId") or "",
            "global_id": person.get("gameGlobalRoleId") or row.get("globalId") or "",
        })
    return rows


def force_statistics(rows: list[dict], top_n: int = TOP_N) -> dict:
    """前 top_n 名门派计数；按数量降序、同名按门派名排序，保证输出确定。"""
    counter = Counter(r["force"] for r in rows[:top_n])
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


# ---------------------------------------------------------------- 落盘

def snapshot_uid(mode: str = DEFAULT_MODE, today: _date | None = None) -> str:
    """快照唯一标识（日频）：如 3v3-2026-10-19。"""
    day = (today or _date.today()).isoformat()
    return f"{mode}-{day}"


def build_payload(mode: str, data: dict, top_n: int = TOP_N,
                  today: _date | None = None) -> dict:
    """组装落盘快照：统计口径前 top_n 名，rows 保留全量榜单。"""
    rows = flatten_rows(data)
    return {
        "mode": mode,
        "snapshot_date": (today or _date.today()).isoformat(),
        "source": SOURCE_DESC,
        "total": len(rows),
        "top_n": top_n,
        "force_stats": force_statistics(rows, top_n),
        "rows": rows,
    }


def save_snapshot(payload: dict, out_dir: Path | str = DEFAULT_OUT_DIR) -> Path:
    """快照落盘（UTF-8、中文不转义），文件名 = snapshot_uid。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{snapshot_uid(payload['mode'], _date.fromisoformat(payload['snapshot_date']))}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def process_snapshot(payload: dict,
                     out_dir: Path | str = DEFAULT_OUT_DIR,
                     state_path: Path | str = STATE_FILE) -> Path | None:
    """已处理（uid 已在 state 中）则原样跳过返回 None；新快照落盘并登记 state。"""
    uid = snapshot_uid(payload["mode"], _date.fromisoformat(payload["snapshot_date"]))
    state = load_state(state_path)
    if uid in state:
        return None
    path = save_snapshot(payload, out_dir)
    state[uid] = {"url": SOURCE_DESC, "processed_at": _date.today().isoformat()}
    save_state(state, state_path)
    return path


# ---------------------------------------------------------------- 入口

def main(mode: str = DEFAULT_MODE) -> int:
    uid = snapshot_uid(mode)
    state = load_state(STATE_FILE)
    if uid in state:
        print(f"快照 {uid} 已处理过，本次新增 0 条，已有文件与状态保持原样。")
        return 0

    print(f"[1/3] 读取凭证并请求 server-mapping + top200（mode={mode}）...")
    try:
        creds = load_credentials()
        data = fetch_top200(creds, mode)
        validate_top200(data)
    except FetchError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    total = len(data["data"])
    print(f"[2/3] 拉取成功，全榜 {total} 条，统计前 {TOP_N} 名门派分布...")
    payload = build_payload(mode, data)
    path = process_snapshot(payload)
    if path is None:
        print(f"[3/3] 快照 {uid} 已处理过，本次新增 0 条。")
        return 0
    stats = payload["force_stats"]
    print(f"[3/3] 新快照已落盘 -> {path}（state 已登记）")
    print(f"前 {TOP_N} 名门派统计（合计 {sum(stats.values())}）："
          + "、".join(f"{k} {v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODE))
