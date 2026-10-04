# -*- coding: utf-8 -*-
"""剑网3技改公告抓取器 v2（简报 005 抓取 + 简报 006 链接保留 + 简报 007 增量去重）

数据源：https://www.jx3api.com/news/records

对外接口（可被其他模块 import）：
    fetch_records(limit=50, timeout=15)  拉取公告列表
    filter_patch_records(records)        筛出技改（武学调整）条目
    record_to_text(record)               提取单条公告的纯文本正文（去除 HTML，
                                         <a> 保留为「链接文字 (URL)」）
    save_patch_txt(record, out_dir)      将技改条目存为 txt，返回文件路径
    record_uid(record)                   公告唯一标识（url，缺失时回退标题）
    load_state(path) / save_state(state, path)   读写增量状态文件
    filter_new_records(records, state)   筛出 state 中尚未处理的新公告
    main()                               命令行入口：拉列表 -> 比对 state ->
                                         只处理新增（存 txt + 解析存 json）->
                                         更新 state -> 打印本次新增 N 条

状态文件 data/state.json 结构（以公告 url 为键）：
    {
      "<公告url>": {"url": "<公告url>", "processed_at": "2026-10-04"}
    }
增量运行时，已处理公告的 txt/json 不会被改动或重写。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date as _date
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import requests

import parse_patch

API_URL = "https://www.jx3api.com/news/records"
MAX_LIMIT = 50
# 技改条目标题关键词
PATCH_KEYWORDS = ("武学调整", "技改")
# txt 落盘目录（相对于本文件：workspace/data/patches）
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "patches"
# 增量状态文件（workspace/data/state.json）
STATE_FILE = DEFAULT_OUT_DIR.parent / "state.json"


class FetchError(Exception):
    """接口请求或返回数据异常。"""


# ---------------------------------------------------------------- 抓取

def _fetch_via_curl(limit: int, timeout: float) -> dict:
    """requests 的 TLS 握手被数据源拒绝时，回退用 curl 拉取同一接口。"""
    import subprocess

    try:
        out = subprocess.run(
            ["curl", "-sS", "--max-time", str(int(timeout) or 15),
             f"{API_URL}?limit={limit}"],
            capture_output=True, timeout=timeout + 5,  # 字节捕获，避免 GBK 控制台编码误伤 UTF-8
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


def fetch_records(limit: int = MAX_LIMIT, timeout: float = 15) -> list[dict]:
    """从 JX3API 拉取最新公告列表。

    :param limit: 返回条数，必须 1 <= limit <= 50，否则接口报错
    :param timeout: 请求超时秒数；超时抛出带明确说明的 FetchError
    :return: 公告记录列表（字典）
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit 必须在 1~{MAX_LIMIT} 之间，收到: {limit}")

    try:
        resp = requests.get(API_URL, params={"limit": limit}, timeout=timeout)
        try:
            data = resp.json()
        except ValueError as exc:
            raise FetchError(f"接口返回的不是合法 JSON（HTTP {resp.status_code}）") from exc
    except requests.Timeout as exc:
        raise FetchError(f"接口请求超时（>{timeout}s）：{API_URL}") from exc
    except requests.RequestException:
        # TLS 握手被数据源拒绝（SSLEOFError 等）时回退 curl 通道
        print("[提示] requests 请求失败，回退 curl 通道重试...")
        data = _fetch_via_curl(limit, timeout)

    records = data.get("data")
    if not isinstance(records, list):
        raise FetchError(f"接口返回结构异常，data 字段缺失或非列表：{data.get('msg')!r}")
    return records


# ---------------------------------------------------------------- 筛选

def filter_patch_records(records: list[dict],
                         keywords: tuple[str, ...] = PATCH_KEYWORDS) -> list[dict]:
    """从公告列表中筛出技改条目（标题含武学调整/技改）。"""
    return [r for r in records
            if any(k in str(r.get("title", "")) for k in keywords)]


# ---------------------------------------------------------------- HTML -> 纯文本

class _TextExtractor(HTMLParser):
    """仅保留文本内容：丢弃所有标签，<br>/<p> 等块级标签转换为换行；
    <a> 标签保留为「链接文字 (URL)」的纯文本形式（无 href 时仅保留文字）。"""

    BLOCK_TAGS = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._link_stack: list[str | None] = []  # 嵌套 <a> 的 href 栈

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")
        elif tag == "a":
            self._link_stack.append(dict(attrs).get("href"))

    def handle_endtag(self, tag):
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")
        elif tag == "a" and self._link_stack:
            href = self._link_stack.pop()
            if href:
                self._parts.append(f" ({href})")

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """把 HTML 转为纯文本：去标签、解压实体、折叠多余空白，仅保留文本内容。"""
    parser = _TextExtractor()
    parser.feed(html)
    text = unescape(parser.get_text())
    # 行内空白折叠，去掉行首行尾空白，连续空行折叠为一个
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def record_to_text(record: dict) -> str:
    """提取单条公告的纯文本正文。desc 可能是 dict（含 content）或字符串。"""
    desc = record.get("desc")
    if isinstance(desc, dict):
        html = str(desc.get("content", ""))
    else:
        html = str(desc or "")
    return html_to_text(html)


# ---------------------------------------------------------------- 落盘

_FILENAME_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _safe_filename(title: str) -> str:
    """标题转合法文件名：去掉 Windows 非法字符，压缩空白。"""
    name = _FILENAME_ILLEGAL.sub("", title)
    return re.sub(r"\s+", " ", name).strip() or "未命名公告"


def save_patch_txt(record: dict, out_dir: Path | str = DEFAULT_OUT_DIR) -> Path:
    """将一条技改公告存入 out_dir，文件名为公告标题，内容为纯文本正文。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_safe_filename(str(record.get('title', '')))}.txt"
    path.write_text(record_to_text(record), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 增量状态

def record_uid(record: dict) -> str:
    """公告唯一标识：优先 url，缺失时回退标题（并打印警告）。"""
    url = str(record.get("url") or "").strip()
    if url:
        return url
    title = str(record.get("title", "")).strip()
    print(f"[警告] 公告缺少 url，回退用标题作唯一标识：{title}", file=sys.stderr)
    return title


def load_state(path: Path | str = STATE_FILE) -> dict:
    """读取状态文件；文件缺失或损坏时返回空状态（视为全部未处理）。"""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        print(f"[警告] 状态文件损坏，按空状态处理：{exc}", file=sys.stderr)
        return {}
    return state if isinstance(state, dict) else {}


def save_state(state: dict, path: Path | str = STATE_FILE) -> Path:
    """写入状态文件（UTF-8、中文不转义、键排序保证确定性）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8")
    return path


def filter_new_records(records: list[dict], state: dict) -> list[dict]:
    """筛出 state 中尚未处理的公告（按 record_uid 比对）。"""
    return [r for r in records if record_uid(r) not in state]


def process_record(record: dict, out_dir: Path | str = DEFAULT_OUT_DIR) -> Path:
    """处理一条新公告：存 txt 并解析为 json，返回 txt 路径。"""
    txt_path = save_patch_txt(record, out_dir)
    parse_patch.save_patch_json(txt_path)
    return txt_path


# ---------------------------------------------------------------- 入口

def main(limit: int = MAX_LIMIT) -> int:
    print(f"[1/4] 正在请求 {API_URL}（limit={limit}）...")
    try:
        records = fetch_records(limit=limit)
    except (FetchError, ValueError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    if not records:
        print("[警告] 接口返回 0 条公告，无可处理数据。", file=sys.stderr)
        return 1

    patches = filter_patch_records(records)
    print(f"[2/4] 共 {len(records)} 条公告，筛出 {len(patches)} 条技改条目。")

    state = load_state()
    new_records = filter_new_records(patches, state)
    print(f"[3/4] 其中已处理 {len(patches) - len(new_records)} 条，本次新增 {len(new_records)} 条。")

    if new_records:
        today = _date.today().isoformat()
        for r in new_records:
            txt_path = process_record(r)
            state[record_uid(r)] = {"url": record_uid(r), "processed_at": today}
            print(f"  已处理 -> {txt_path.name}（txt + json）")
        save_state(state)
        print(f"[4/4] 状态文件已更新：{STATE_FILE}")
    else:
        print("[4/4] 无新增条目，已有 txt/json 与状态文件保持原样。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
