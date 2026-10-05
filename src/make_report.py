# -*- coding: utf-8 -*-
"""技改报告生成器（简报 008）

读 data/patches/*.json（简报 006 的结构化产物），生成 Markdown 简报到 reports/。

对外接口（可被其他模块 import）：
    generate_report(data)                    由解析后的 dict 生成 Markdown 文本
    generate_report_file(json_path, out_dir) 解析单个 json 并写入 .md，返回路径
    main()                                   命令行入口：批量全量重新生成

简报结构：
    标题头（标题 / 日期 / 三数统计）
    -> 改动变化榜（按门派条目数降序，条数相同按门派名排序，保证确定性）
    -> 分门派展开（心法 + 条目）
       - is_shared 的门派/心法在标题后标注「（通用）」
       - 心法 notes 叙述文放在该心法开头、条目之前
       - 无 # 心法标题的隐式心法（name 为空）不输出心法标题，条目直接挂在门派下

简报是派生物：每次全量重新生成、直接覆盖；输出不含时间戳，同一输入产出逐字节一致。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# json 输入目录 / md 输出目录（相对于本文件：workspace/...）
DEFAULT_JSON_DIR = Path(__file__).resolve().parent.parent / "data" / "patches"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "reports"

SHARED_LABEL = "（通用）"


def _counts(data: dict) -> tuple[int, int, int]:
    """三数统计：门派数 / 心法数 / 条目数。"""
    n_sect = len(data["sects"])
    n_xinfa = sum(len(s["xinfas"]) for s in data["sects"])
    n_entry = sum(len(x["entries"]) for s in data["sects"] for x in s["xinfas"])
    return n_sect, n_xinfa, n_entry


def _sect_entry_count(sect: dict) -> int:
    return sum(len(x["entries"]) for x in sect["xinfas"])


def _shared_suffix(flag: bool) -> str:
    return SHARED_LABEL if flag else ""


def _render_entry(entry: str) -> list[str]:
    """条目渲染为列表项：首行加 '- '，续行缩进两格保持 Markdown 段落归属。"""
    lines = entry.split("\n")
    out = []
    for i, line in enumerate(lines):
        if not line:
            out.append("")
        elif i == 0:
            out.append(f"- {line}")
        else:
            out.append(f"  {line}")
    return out


def generate_report(data: dict) -> str:
    """由 parse_patch 的结构化 dict 生成 Markdown 简报文本。

    :param data: parse_patch_text() 的输出（含 title/date/preamble/sects）
    :return: Markdown 字符串（以单个换行结尾）
    """
    n_sect, n_xinfa, n_entry = _counts(data)
    lines: list[str] = []

    # ---- 标题头
    lines.append(f"# {data.get('title', '技改简报')}")
    lines.append("")
    lines.append(f"- 日期：{data.get('date', '未知')}")
    lines.append(f"- 门派数：{n_sect} ｜ 心法数：{n_xinfa} ｜ 条目数：{n_entry}")
    lines.append("")
    preamble = (data.get("preamble") or "").strip()
    if preamble:
        lines.append(f"> {preamble}")
        lines.append("")

    # ---- 改动变化榜（按条目数降序，同名按门派名排序保证确定性）
    lines.append("## 改动变化榜")
    lines.append("")
    lines.append("| 排名 | 门派 | 条目数 |")
    lines.append("| ---: | --- | ---: |")
    ranked = sorted(data["sects"],
                    key=lambda s: (-_sect_entry_count(s), s["name"]))
    for rank, sect in enumerate(ranked, start=1):
        name = sect["name"] + _shared_suffix(sect.get("is_shared", False))
        lines.append(f"| {rank} | {name} | {_sect_entry_count(sect)} |")
    lines.append("")

    # ---- 分门派展开
    lines.append("## 分门派详情")
    lines.append("")
    for sect in data["sects"]:
        sect_name = sect["name"] + _shared_suffix(sect.get("is_shared", False))
        lines.append(f"### {sect_name}")
        lines.append("")
        for xinfa in sect["xinfas"]:
            if xinfa["name"]:  # 隐式心法（空名）不输出心法标题
                xname = xinfa["name"] + _shared_suffix(xinfa.get("is_shared", False))
                lines.append(f"#### {xname}")
                lines.append("")
            notes = (xinfa.get("notes") or "").strip()
            if notes:  # 叙述文放在心法开头、条目之前
                lines.append(notes)
                lines.append("")
            for entry in xinfa["entries"]:
                lines.extend(_render_entry(entry))
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_report_file(json_path: str | Path,
                         out_dir: str | Path = DEFAULT_OUT_DIR) -> Path:
    """解析单个 json 并写入同名 .md（UTF-8），返回输出路径。"""
    json_path = Path(json_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{json_path.stem}.md"
    out_path.write_text(generate_report(data), encoding="utf-8")
    return out_path


def main(json_dir: Path = DEFAULT_JSON_DIR, out_dir: Path = DEFAULT_OUT_DIR) -> int:
    jsons = sorted(json_dir.glob("*.json"))
    if not jsons:
        print(f"[警告] {json_dir} 下没有 json 文件。", file=sys.stderr)
        return 1
    for jp in jsons:
        out = generate_report_file(jp, out_dir)
        data = json.loads(jp.read_text(encoding="utf-8"))
        n_sect, n_xinfa, n_entry = _counts(data)
        print(f"已生成 -> {out.name}（门派 {n_sect} / 心法 {n_xinfa} / 条目 {n_entry}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
