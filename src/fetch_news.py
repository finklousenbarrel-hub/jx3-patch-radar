# -*- coding: utf-8 -*-
"""剑网3技改公告抓取器 v1（简报 005）

数据源：https://www.jx3api.com/news/records

对外接口（可被其他模块 import）：
    fetch_records(limit=50, timeout=15)  拉取公告列表
    filter_patch_records(records)        筛出技改（武学调整）条目
    record_to_text(record)               提取单条公告的纯文本正文（去除 HTML）
    save_patch_txt(record, out_dir)      将技改条目存为 txt，返回文件路径
    main()                               命令行入口：抓取 -> 筛选 -> 打印 -> 落盘
"""

from __future__ import annotations

import re
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import requests

API_URL = "https://www.jx3api.com/news/records"
MAX_LIMIT = 50
# 技改条目标题关键词
PATCH_KEYWORDS = ("武学调整", "技改")
# txt 落盘目录（相对于本文件：workspace/docs/Jx3_Info_Datased）
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "patches"


class FetchError(Exception):
    """接口请求或返回数据异常。"""


# ---------------------------------------------------------------- 抓取

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
    except requests.Timeout as exc:
        raise FetchError(f"接口请求超时（>{timeout}s）：{API_URL}") from exc
    except requests.RequestException as exc:
        raise FetchError(f"接口请求失败：{exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise FetchError(f"接口返回的不是合法 JSON（HTTP {resp.status_code}）") from exc

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
    """仅保留文本内容：丢弃所有标签，<br>/<p> 等块级标签转换为换行。"""

    BLOCK_TAGS = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

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


# ---------------------------------------------------------------- 入口

def main(limit: int = MAX_LIMIT) -> int:
    print(f"[1/3] 正在请求 {API_URL}（limit={limit}）...")
    try:
        records = fetch_records(limit=limit)
    except (FetchError, ValueError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    if not records:
        print("[警告] 接口返回 0 条公告，无可处理数据。", file=sys.stderr)
        return 1

    patches = filter_patch_records(records)
    print(f"[2/3] 共 {len(records)} 条公告，筛出 {len(patches)} 条技改条目：")
    for r in patches:
        print(f"  {r.get('date')} | {r.get('title')}")
    if not patches:
        print("[警告] 未找到任何技改条目。", file=sys.stderr)
        return 1

    print(f"[3/3] 写入目录：{DEFAULT_OUT_DIR}")
    for r in patches:
        path = save_patch_txt(r)
        print(f"  已保存 -> {path.name}")

    # 验收输出：目标条目 + 技改信息前 500 个字符（纯文本）
    target = next((r for r in patches if "第二轮武学调整" in str(r.get("title", ""))),
                  patches[0])
    print("\n===== 验收输出 =====")
    print(f"标题：{target.get('title')}")
    print(f"日期：{target.get('date')}")
    print("正文前 500 字符：")
    print(record_to_text(target)[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
