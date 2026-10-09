# -*- coding: utf-8 -*-
"""门派子文章抓取器（简报 009）

读取 data/patches/*.json 中 notes 里的网页链接（形如
「前往查看万花武学调整详情 (https://jx3.xoyo.com/index/#/article-details?catid=2466&id=7477)」），
抓取对应文章全文，以 txt 存入 data/extra-info/。

背景：链接是 SPA 前端路由（#/article-details），页面 HTML 不含正文。
真实数据接口（逆向自官网 page-main chunk）：
    GET https://jx3.xoyo.com/api.php?op=search_api&action=get_article_detail&catid={catid}&id={id}
返回 JSON，data[0].content 为全文 HTML，data[0].title 为文章标题
（已含「-门派」后缀，如「9月8日“苍生铸世”资料片首轮武学调整-万花」）。

对外接口（可被其他模块 import）：
    extract_links(data)            从单个公告 JSON 的 notes 提取链接列表
    parse_article_url(url)         从 SPA 链接解析 catid / id
    fetch_article(catid, article_id, timeout)  调接口取文章（dict）
    article_to_text(article)       content HTML -> 纯文本
    save_article_txt(article, out_dir)         存为 txt，返回路径
    main()                         命令行入口：扫 json -> 抓文章 -> 落盘
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from fetch_news import html_to_text

# json 输入目录 / txt 输出目录（相对于本文件：workspace/...）
DEFAULT_JSON_DIR = Path(__file__).resolve().parent.parent / "data" / "patches"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "extra-info"

ARTICLE_API = "https://jx3.xoyo.com/api.php"
# 抓取间隔（秒），避免对官网造成压力
REQUEST_INTERVAL = 0.5

# notes 中「链接文字 (URL)」的 URL（与 fetch_news 的 <a> 保留格式对应）
_LINK_RE = re.compile(r"\((https?://[^)\s]+)\)")
_FILENAME_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t]')


class LinkFetchError(Exception):
    """子文章接口请求或返回数据异常。"""


# ---------------------------------------------------------------- 链接提取

def parse_article_url(url: str) -> tuple[str, str]:
    """从 SPA 链接解析 (catid, id)。查询参数在 # fragment 里，需特殊处理。

    >>> parse_article_url("https://jx3.xoyo.com/index/#/article-details?catid=2466&id=7477")
    ('2466', '7477')
    """
    frag = urlparse(url).fragment  # 如 /article-details?catid=2466&id=7477
    qs = parse_qs(urlparse(frag).query if "?" in frag else "")
    # fragment 不是标准路径时兜底：直接按 query 解析 ? 之后的部分
    if not qs and "?" in url:
        qs = parse_qs(url.split("?", 1)[1])
    catid = (qs.get("catid") or [""])[0]
    article_id = (qs.get("id") or [""])[0]
    if not catid or not article_id:
        raise ValueError(f"链接缺少 catid/id 参数：{url}")
    return catid, article_id


def extract_links(data: dict) -> list[dict]:
    """从单个公告 JSON 的所有 notes 提取链接。

    :return: [{"sect": 门派名, "url": ..., "catid": ..., "id": ...}, ...]（按出现顺序）
    """
    out = []
    for sect in data.get("sects", []):
        for xinfa in sect.get("xinfas", []):
            for m in _LINK_RE.finditer(xinfa.get("notes") or ""):
                url = m.group(1)
                try:
                    catid, article_id = parse_article_url(url)
                except ValueError as exc:
                    print(f"[警告] 跳过无法解析的链接：{exc}", file=sys.stderr)
                    continue
                out.append({"sect": sect["name"], "url": url,
                            "catid": catid, "id": article_id})
    return out


# ---------------------------------------------------------------- 抓取

def _get_json_via_curl(url: str, timeout: float) -> dict:
    """requests 的 TLS 握手被拒时，回退 curl（字节捕获，避免 GBK 误伤 UTF-8）。"""
    import subprocess

    try:
        out = subprocess.run(
            ["curl", "-sS", "--max-time", str(int(timeout) or 15),
             "-H", "Referer: https://jx3.xoyo.com/index/", url],
            capture_output=True, timeout=timeout + 5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LinkFetchError(f"curl 回退请求也失败：{exc}") from exc
    if out.returncode != 0:
        raise LinkFetchError(f"curl 回退请求失败（退出码 {out.returncode}）："
                             f"{out.stderr.decode('utf-8', 'replace').strip()}")
    try:
        return json.loads(out.stdout.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LinkFetchError(f"接口返回的不是合法 JSON：{url}") from exc


def fetch_article(catid: str, article_id: str, timeout: float = 20) -> dict:
    """调官网文章详情接口，返回 data[0]（含 title/content 等字段）。"""
    params = {"op": "search_api", "action": "get_article_detail",
              "catid": catid, "id": article_id}
    try:
        resp = requests.get(ARTICLE_API, params=params, timeout=timeout,
                            headers={"Referer": "https://jx3.xoyo.com/index/"})
        data = resp.json()
    except requests.RequestException:
        print("[提示] requests 请求失败，回退 curl 通道重试...")
        query = "&".join(f"{k}={v}" for k, v in params.items())
        data = _get_json_via_curl(f"{ARTICLE_API}?{query}", timeout)
    except ValueError as exc:
        raise LinkFetchError(f"接口返回的不是合法 JSON（catid={catid}, id={article_id}）") from exc

    articles = data.get("data")
    if not isinstance(articles, list) or not articles:
        raise LinkFetchError(f"接口未返回文章内容（catid={catid}, id={article_id}）："
                             f"{data.get('msg')!r}")
    return articles[0]


def article_to_text(article: dict) -> str:
    """文章 content HTML 转纯文本（复用 fetch_news 的清洗逻辑，保留链接）。"""
    return html_to_text(str(article.get("content", "")))


def _safe_filename(title: str) -> str:
    """标题转合法文件名：去掉 Windows 非法字符，压缩空白。"""
    name = _FILENAME_ILLEGAL.sub("", title)
    return re.sub(r"\s+", " ", name).strip() or "未命名文章"


def save_article_txt(article: dict, out_dir: Path | str = DEFAULT_OUT_DIR) -> Path:
    """文章存为 txt：文件名为文章标题，内容为标题行 + 纯文本正文。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    title = str(article.get("title", "")).strip()
    path = out_dir / f"{_safe_filename(title)}.txt"
    path.write_text(f"{title}\n\n{article_to_text(article)}\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------- 入口

def main(json_dir: Path = DEFAULT_JSON_DIR,
         out_dir: Path = DEFAULT_OUT_DIR) -> int:
    jsons = sorted(json_dir.glob("*.json"))
    if not jsons:
        print(f"[警告] {json_dir} 下没有 json 文件。", file=sys.stderr)
        return 1

    links = []
    for jp in jsons:
        links.extend(extract_links(json.loads(jp.read_text(encoding="utf-8"))))
    print(f"[1/2] 从 {len(jsons)} 个 JSON 中提取到 {len(links)} 条文章链接。")
    if not links:
        print("[警告] 未发现任何链接。", file=sys.stderr)
        return 1

    print(f"[2/2] 开始抓取，输出目录：{out_dir}")
    ok = 0
    for i, link in enumerate(links):
        if i:
            time.sleep(REQUEST_INTERVAL)
        try:
            article = fetch_article(link["catid"], link["id"])
            path = save_article_txt(article, out_dir)
            ok += 1
            print(f"  [{ok}/{len(links)}] {link['sect']} -> {path.name}")
        except (LinkFetchError, ValueError) as exc:
            print(f"  [失败] {link['sect']} {link['url']}：{exc}", file=sys.stderr)

    print(f"完成：成功 {ok}/{len(links)} 篇。")
    return 0 if ok == len(links) else 1


if __name__ == "__main__":
    sys.exit(main())
