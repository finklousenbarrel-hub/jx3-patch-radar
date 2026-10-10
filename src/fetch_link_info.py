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
    article_to_markdown(article)   content HTML -> Markdown（简报 010：
                                   表格转 Markdown 表格，标红文本转加粗）
    save_article_md(article, out_dir)          存为 .md（data/extra-info/plus）
    main()                         命令行入口：扫 json -> 抓文章 -> txt + plus md 落盘

标红判定：元素 style 中 color 为 rgb(255, 0, 0) / #ff0000 / red（官网用红色标注改动内容）。
表格 rowspan/colspan 合并单元格在 Markdown 中展开为重复内容（保持语义归属）。
"""

from __future__ import annotations

import json
import re
import sys
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from fetch_news import html_to_text

# json 输入目录 / txt 输出目录（相对于本文件：workspace/...）
DEFAULT_JSON_DIR = Path(__file__).resolve().parent.parent / "data" / "patches"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "extra-info"
# Markdown plus 版输出目录（表格 + 标红加粗）
DEFAULT_PLUS_DIR = DEFAULT_OUT_DIR / "plus"

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


# ---------------------------------------------------------------- Markdown plus（简报 010）

# 标红判定：style 中 color 为 rgb(255, 0, 0) / #f00 / #ff0000 / red
_RED_RE = re.compile(
    r"color\s*:\s*(?:rgb\(\s*255\s*,\s*0\s*,\s*0\s*\)|#f00\b|#ff0000\b|red\b)",
    re.IGNORECASE)
_BLOCK_TAGS = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}


def _is_red(attrs: dict) -> bool:
    return bool(_RED_RE.search(attrs.get("style", "")))


class _MarkdownExtractor(HTMLParser):
    """HTML -> Markdown：
    - <table> 转 Markdown 管道表格（rowspan/colspan 展开为重复内容，| 转义，换行转 <br>）
    - 标红文本（元素 style 里红色）转 **加粗**
    - <a> 转 [文字](URL)（无 href 仅留文字）
    - 块级标签转换为段落空行
    """

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []          # 正文输出
        self._style_stack: list[bool] = []   # 每层元素是否标红（endtag 配对弹出）
        self._bold_open = False              # 当前 ** 是否打开
        self._link_stack: list[str | None] = []
        # 表格状态
        self._in_table = False
        self._grid: dict[tuple[int, int], str] = {}
        self._row_idx = -1
        self._in_cell = False
        self._cell_buf: list[str] = []
        self._cell_span = (1, 1)
        self._n_cols = 0

    # ------------------------------------------------------------ 基础输出

    def _emit(self, s: str) -> None:
        if not s:
            return
        (self._cell_buf if self._in_cell else self._parts).append(s)

    def _set_bold(self, on: bool) -> None:
        if on != self._bold_open:
            self._emit("**")
            self._bold_open = on

    def _is_red_now(self) -> bool:
        return any(self._style_stack)

    # ------------------------------------------------------------ 标签处理

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            self._set_bold(False)
            self._style_stack.append(False)
            self._in_table = True
            self._grid, self._row_idx, self._n_cols = {}, -1, 0
            return
        self._style_stack.append(_is_red(attrs))
        if self._in_table:
            if tag == "tr":
                self._row_idx += 1
            elif tag in ("td", "th"):
                self._in_cell = True
                self._cell_buf = []
                rs = int(attrs.get("rowspan") or 1)
                cs = int(attrs.get("colspan") or 1)
                self._cell_span = (max(rs, 1), max(cs, 1))
            elif tag == "br":
                self._set_bold(False)  # 单元格内换行前收尾加粗
                self._emit("\n")
            return
        if tag in _BLOCK_TAGS:
            self._set_bold(False)
            self._parts.append("\n")
        elif tag == "a":
            href = attrs.get("href")
            self._link_stack.append(href)
            if href:
                self._set_bold(False)
                self._emit("[")

    def handle_endtag(self, tag):
        if tag == "table":
            if self._style_stack:
                self._style_stack.pop()
            self._in_table = False
            self._parts.append("\n" + self._render_table() + "\n\n")
            return
        if self._in_table:
            if tag in ("td", "th") and self._in_cell:
                self._finish_cell()
            if self._style_stack:
                self._style_stack.pop()
            return
        if tag in _BLOCK_TAGS:
            self._set_bold(False)
            self._parts.append("\n")
        elif tag == "a" and self._link_stack:
            href = self._link_stack.pop()
            if href:
                self._set_bold(False)
                self._emit(f"]({href})")
        if self._style_stack:
            self._style_stack.pop()

    def handle_startendtag(self, tag, attrs):
        # 自闭合标签（如 <br/>）不进栈；换行前先收尾加粗（下个数据段会自动重开）
        self._set_bold(False)
        if tag == "br":
            self._emit("\n")
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    # ------------------------------------------------------------ 表格

    def _finish_cell(self) -> None:
        self._set_bold(False)  # 收尾当前单元格内未闭合的加粗，避免泄漏到下一格
        text = "".join(self._cell_buf)
        text = re.sub(r"\s*\n\s*", "<br>", text).strip()
        text = text.replace("|", "\\|")
        rs, cs = self._cell_span
        col = 0
        while (self._row_idx, col) in self._grid:  # 跳过上方 rowspan 占用的列
            col += 1
        for dr in range(rs):
            for dc in range(cs):
                self._grid[(self._row_idx + dr, col + dc)] = text
        self._n_cols = max(self._n_cols, col + cs)
        self._in_cell = False
        self._cell_buf = []

    def _render_table(self) -> str:
        if self._row_idx < 0 or self._n_cols == 0:
            return ""
        rows = [[self._grid.get((r, c), "") for c in range(self._n_cols)]
                for r in range(self._row_idx + 1)]
        out = ["| " + " | ".join(rows[0]) + " |",
               "| " + " | ".join("---" for _ in rows[0]) + " |"]
        out += ["| " + " | ".join(row) + " |" for row in rows[1:]]
        return "\n".join(out)

    # ------------------------------------------------------------ 数据

    def handle_data(self, data):
        if self._in_table and not self._in_cell:
            return  # 表格骨架里的空白文本
        red = self._is_red_now()
        # 数据段内的换行先收尾加粗再输出，避免 ** 跨行断裂；纯空白段不切换加粗
        for seg in re.split(r"(\n+)", data):
            if not seg:
                continue
            if seg.startswith("\n"):
                self._set_bold(False)
                self._emit(seg)
            else:
                self._set_bold(red and bool(seg.strip()))
                self._emit(seg)

    def get_markdown(self) -> str:
        self._set_bold(False)
        text = unescape("".join(self._parts))
        lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in text.splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def article_to_markdown(article: dict) -> str:
    """文章 content HTML 转 Markdown：表格保留表形，标红转加粗。"""
    parser = _MarkdownExtractor()
    parser.feed(str(article.get("content", "")))
    parser.close()
    return parser.get_markdown()


def save_article_md(article: dict, out_dir: Path | str = DEFAULT_PLUS_DIR) -> Path:
    """文章存为 Markdown：文件名为文章标题，内容为一级标题 + Markdown 正文。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    title = str(article.get("title", "")).strip()
    path = out_dir / f"{_safe_filename(title)}.md"
    path.write_text(f"# {title}\n\n{article_to_markdown(article)}\n", encoding="utf-8")
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

    print(f"[2/2] 开始抓取，输出目录：{out_dir}（plus 版 -> {DEFAULT_PLUS_DIR}）")
    ok = 0
    for i, link in enumerate(links):
        if i:
            time.sleep(REQUEST_INTERVAL)
        try:
            article = fetch_article(link["catid"], link["id"])
            path = save_article_txt(article, out_dir)
            md_path = save_article_md(article)
            ok += 1
            print(f"  [{ok}/{len(links)}] {link['sect']} -> {path.name}（+plus/{md_path.name}）")
        except (LinkFetchError, ValueError) as exc:
            print(f"  [失败] {link['sect']} {link['url']}：{exc}", file=sys.stderr)

    print(f"完成：成功 {ok}/{len(links)} 篇。")
    return 0 if ok == len(links) else 1


if __name__ == "__main__":
    sys.exit(main())
