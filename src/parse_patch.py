# -*- coding: utf-8 -*-
"""技改公告 txt 解析器（简报 006）

把 data/patches/*.txt（简报 005 抓取并清洗后的纯文本）解析为结构化 JSON。

对外接口（可被其他模块 import）：
    parse_patch_text(text, title="", date="")  解析正文文本，返回结构化 dict
    parse_patch_file(path)                     解析单个 txt 文件（标题/日期取自文件名）
    save_patch_json(path, out_dir=None)        解析并落盘为 .json，返回文件路径
    parse_plus_md_text(text, title="", date="")   解析 extra-info/plus 的 Markdown
                                                  （简报 011：额外提取奇穴表格）
    parse_plus_md_file(path) / save_plus_json(path)
    main()                                     命令行入口：批量解析 data/patches/*.txt
                                               与 data/extra-info/plus/*.md

输出结构：
    {
      "title": "公告标题",
      "date": "2026/09/24",
      "preamble": "前言段（第一个◎之前的文本）",
      "sects": [
        {"name": "万花", "is_shared": false, "xinfas": [
          {"name": "花间游", "is_shared": false,
           "notes": "调整思路的叙述段落...",
           "entries": ["条目1完整文本", "条目2..."]}
        ]}
      ]
    }

解析规则（以行首标记为准，空行仅作段落分隔）：
- `◎门派名`：门派起始（允许 ◎ 后带空白，如「◎ 万花」）
- `#心法名#`：心法起始
- `·条目`：条目起始，去掉行首 `·` 标记
- 心法下不以 · 开头的行：
  - 若当前心法尚未出现条目 → 收入该心法 notes（如「调整思路」叙述段）
  - 若紧跟在某个条目之后 → 作为该条目的续段并入 entries
    （因此「调整为：…」「伤害降低10%」等保留在同一条目内）
  - 段落之间以 "\\n\\n" 连接
- 第一个 ◎ 之前的所有文本并入 preamble
- 门派下若直接出现条目/叙述而无 # 心法标题（如「◎旗舰通用」），
  归入 name 为空字符串 "" 的隐式心法
- is_shared 标记：门派/心法的 name 含「通用」则为 true，否则 false
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date as _date
from pathlib import Path

# txt / json 落盘目录（相对于本文件：workspace/data/patches）
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "patches"

_SECT_RE = re.compile(r"^◎\s*(?P<name>.+?)\s*$")
_XINFA_RE = re.compile(r"^#\s*(?P<name>.+?)\s*#\s*$")
_ENTRY_RE = re.compile(r"^·\s*(?P<text>.*)$")
# 文件名中的日期，如「9月24日…….txt」
_FILENAME_DATE_RE = re.compile(r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日")
_YEAR_RE = re.compile(r"(?P<year>\d{4})\s*年")

# name 含此关键词即视为共享（通用）章节
SHARED_KEYWORD = "通用"


def _is_shared(name: str) -> bool:
    return SHARED_KEYWORD in name


def _new_sect(name: str) -> dict:
    return {"name": name, "is_shared": _is_shared(name), "xinfas": []}


def _new_xinfa(name: str) -> dict:
    return {"name": name, "is_shared": _is_shared(name), "notes": "", "entries": []}


def parse_patch_text(text: str, title: str = "", date: str = "") -> dict:
    """把技改公告纯文本解析为结构化 dict。

    :param text: 公告正文（已清洗的纯文本）
    :param title: 公告标题（可选，仅写入结果）
    :param date: 公告日期，形如 2026/09/24（可选，仅写入结果）
    :return: 见模块 docstring 的输出结构
    """
    preamble_parts: list[str] = []
    sects: list[dict] = []
    cur_sect: dict | None = None
    cur_xinfa: dict | None = None
    cur_entry: list[str] | None = None  # 当前条目的段落缓冲
    notes_parts: list[str] = []         # 当前心法的 notes 段落缓冲

    def flush_entry() -> None:
        nonlocal cur_entry
        if cur_entry is not None and cur_xinfa is not None:
            cur_xinfa["entries"].append("\n\n".join(cur_entry))
        cur_entry = None

    def flush_notes() -> None:
        nonlocal notes_parts
        if notes_parts and cur_xinfa is not None:
            cur_xinfa["notes"] = "\n\n".join(notes_parts)
        notes_parts = []

    def ensure_sect() -> dict:
        nonlocal cur_sect
        if cur_sect is None:  # 内容出现在任何门派之前，容错：补一个匿名门派
            cur_sect = _new_sect("")
            sects.append(cur_sect)
        return cur_sect

    def ensure_xinfa() -> dict:
        nonlocal cur_xinfa
        if cur_xinfa is None:  # 门派下无 # 心法标题（如「◎旗舰通用」）
            cur_xinfa = _new_xinfa("")
            ensure_sect()["xinfas"].append(cur_xinfa)
        return cur_xinfa

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _SECT_RE.match(line)
        if m:
            flush_entry()
            flush_notes()
            cur_sect = _new_sect(m.group("name"))
            sects.append(cur_sect)
            cur_xinfa = None
            continue

        m = _XINFA_RE.match(line)
        if m:
            flush_entry()
            flush_notes()
            cur_xinfa = _new_xinfa(m.group("name"))
            ensure_sect()["xinfas"].append(cur_xinfa)
            continue

        m = _ENTRY_RE.match(line)
        if m:
            flush_entry()
            flush_notes()
            ensure_xinfa()
            cur_entry = [m.group("text")]
            continue

        # 不以 · 开头的普通行
        if cur_entry is not None:
            cur_entry.append(line)          # 条目续段：并入当前条目
        elif cur_sect is None:
            preamble_parts.append(line)     # 第一个 ◎ 之前：前言
        else:
            ensure_xinfa()
            notes_parts.append(line)        # 心法叙述段：收入 notes

    flush_entry()
    flush_notes()

    return {
        "title": title,
        "date": date,
        "preamble": "\n\n".join(preamble_parts),
        "sects": sects,
    }


def _date_from_filename(stem: str, text: str) -> str:
    """从文件名提取「M月D日」，年份取正文首个「YYYY年」，缺省用当前年份。"""
    m = _FILENAME_DATE_RE.search(stem)
    if not m:
        return ""
    y = _YEAR_RE.search(text)
    year = int(y.group("year")) if y else _date.today().year
    return f"{year}/{int(m.group('month')):02d}/{int(m.group('day')):02d}"


def parse_patch_file(path: str | Path) -> dict:
    """解析单个 txt 文件；标题取文件名（去扩展名），日期按文件名+正文推断。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return parse_patch_text(text, title=path.stem,
                            date=_date_from_filename(path.stem, text))


def save_patch_json(path: str | Path, out_dir: str | Path | None = None) -> Path:
    """解析 txt 并写入同名 .json（UTF-8，中文不转义），返回输出路径。"""
    path = Path(path)
    data = parse_patch_file(path)
    out_dir = Path(out_dir) if out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{path.stem}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return out_path


# ---------------------------------------------------------------- plus md（简报 011）

# plus Markdown 目录（fetch_link_info 的产物）
PLUS_MD_DIR = Path(__file__).resolve().parent.parent / "data" / "extra-info" / "plus"

_MD_H1_RE = re.compile(r"^#\s+(?P<title>.+?)\s*$")   # Markdown 一级标题（文件名行）
_TABLE_ROW_RE = re.compile(r"^\|")
_TABLE_CELL_SPLIT = re.compile(r"(?<!\\)\|")          # 按未转义的 | 切分
_TABLE_SEP_CELL = re.compile(r"^:?-{3,}:?$")          # 分隔行单元格 | --- |

# qixue_table 目标列与表头关键词的映射（效果列取未被认领的最后一列兜底）
_QIXUE_COLS = (("重数", ("重数",)), ("类型", ("类型",)), ("名称", ("名称",)))


def _split_table_row(line: str) -> list[str]:
    """表格行切分为单元格：去首尾 |，按未转义 | 切分，还原 \\| 与 <br>。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells = []
    for c in _TABLE_CELL_SPLIT.split(s):
        c = c.strip().replace("\\|", "|")
        c = re.sub(r"\s*<br>\s*", "\n", c)
        cells.append(c)
    return cells


def _is_sep_row(line: str) -> bool:
    return all(_TABLE_SEP_CELL.match(c) for c in _split_table_row(line) if c != "")


def _strip_bold(s: str) -> str:
    return s.replace("**", "")


def _parse_qixue_table(rows: list[str]) -> list[dict]:
    """表格行列表 -> qixue_table 结构化数组。

    首行为表头（按「重数/类型/名称」关键词定位列，剩余最后一列作效果）；
    分隔行跳过；** 仅用于判断 is_changed，入库前剥掉。
    """
    if not rows:
        return []
    header = _split_table_row(rows[0])
    col_idx: dict[str, int] = {}
    for key, kws in _QIXUE_COLS:
        for i, h in enumerate(header):
            if i not in col_idx.values() and any(k in h for k in kws):
                col_idx[key] = i
                break
    used = set(col_idx.values())
    # 效果列：优先含「效果」表头，否则取未认领的最后一列
    effect_idx = next((i for i, h in enumerate(header)
                       if i not in used and "效果" in h), None)
    if effect_idx is None:
        effect_idx = next((i for i in range(len(header) - 1, -1, -1)
                           if i not in used), None)
    col_idx["效果"] = effect_idx

    out = []
    for line in rows[1:]:
        if _is_sep_row(line):
            continue
        cells = _split_table_row(line)
        is_changed = "**" in line
        cells = [_strip_bold(c) for c in cells]
        get = lambda k: cells[col_idx[k]] if col_idx.get(k) is not None \
            and col_idx[k] < len(cells) else ""
        out.append({"重数": get("重数"), "类型": get("类型"), "名称": get("名称"),
                    "效果": get("效果"), "is_changed": is_changed})
    return out


def parse_plus_md_text(text: str, title: str = "", date: str = "") -> dict:
    """解析 extra-info/plus 的 Markdown 为结构化 JSON。

    与 parse_patch_text 同构（sects/xinfas/entries/notes，保真原则不变），
    每个心法额外增加 qixue_table 字段：奇穴表格结构化数组，
    每行含 重数/类型/名称/效果/is_changed。
    """
    lines = text.splitlines()

    # 首个 Markdown 一级标题作 title（注意与 #心法# 区分：H1 行尾无 #）
    body_start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = _MD_H1_RE.match(line.strip())
        if m and not _XINFA_RE.match(line.strip()):
            title = title or m.group("title")
            body_start = i + 1
        break

    # 剥离表格行（按出现时的 门派/心法 序位暂存），其余行走主公告解析
    body_lines: list[str] = []
    tables: dict[tuple[int, int], list[str]] = {}
    sect_ord = -1
    xinfa_ord = -1
    cur_table: list[str] | None = None
    for line in lines[body_start:]:
        if _TABLE_ROW_RE.match(line.strip()):
            if cur_table is None:
                # 表格标题行（「奇穴表格」）是表格的图注，不并入上一条目
                while body_lines and not body_lines[-1].strip():
                    body_lines.pop()
                if body_lines and body_lines[-1].strip() == "奇穴表格":
                    body_lines.pop()
                cur_table = tables.setdefault((sect_ord, xinfa_ord), [])
            cur_table.append(line.strip())
            continue
        cur_table = None
        stripped = line.strip()
        if _SECT_RE.match(stripped):
            sect_ord += 1
            xinfa_ord = -1
        elif _XINFA_RE.match(stripped):
            xinfa_ord += 1
        body_lines.append(line)

    data = parse_patch_text("\n".join(body_lines), title=title, date=date)

    # 表挂回心法：若某门派首心法为空名（隐式心法），命名心法序位右移一位
    for (s_ord, x_ord), rows in tables.items():
        if s_ord < 0 or s_ord >= len(data["sects"]):
            continue
        xinfas = data["sects"][s_ord]["xinfas"]
        shift = 1 if xinfas and xinfas[0]["name"] == "" and x_ord >= 0 else 0
        idx = 0 if x_ord < 0 else x_ord + shift
        if 0 <= idx < len(xinfas):
            xinfas[idx].setdefault("qixue_table", []).extend(_parse_qixue_table(rows))

    for sect in data["sects"]:
        for xinfa in sect["xinfas"]:
            xinfa.setdefault("qixue_table", [])
    return data


def parse_plus_md_file(path: str | Path) -> dict:
    """解析单个 plus Markdown 文件；标题取 md 一级标题，日期从文件名推断。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    return parse_plus_md_text(text, date=_date_from_filename(path.stem, text))


def save_plus_json(path: str | Path) -> Path:
    """解析 plus Markdown 并在同目录落盘同名 .json（UTF-8，中文不转义）。"""
    path = Path(path)
    data = parse_plus_md_file(path)
    out_path = path.with_suffix(".json")
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return out_path


def main(patch_dir: Path = DEFAULT_DIR, plus_dir: Path = PLUS_MD_DIR) -> int:
    txts = sorted(patch_dir.glob("*.txt"))
    if not txts:
        print(f"[警告] {patch_dir} 下没有 txt 文件。", file=sys.stderr)
        return 1
    for txt in txts:
        out = save_patch_json(txt)
        data = json.loads(out.read_text(encoding="utf-8"))
        n_sect = len(data["sects"])
        n_xinfa = sum(len(s["xinfas"]) for s in data["sects"])
        n_entry = sum(len(x["entries"]) for s in data["sects"] for x in s["xinfas"])
        print(f"已解析 -> {out.name}（门派 {n_sect} / 心法 {n_xinfa} / 条目 {n_entry}）")

    mds = sorted(plus_dir.glob("*.md")) if plus_dir.exists() else []
    for md in mds:
        out = save_plus_json(md)
        data = json.loads(out.read_text(encoding="utf-8"))
        n_rows = sum(len(x["qixue_table"]) for s in data["sects"]
                     for x in s["xinfas"])
        print(f"已解析 -> {out.name}（奇穴表行数 {n_rows}）")
    if mds:
        print(f"plus 目录共解析 {len(mds)} 篇。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
