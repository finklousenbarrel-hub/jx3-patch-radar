# -*- coding: utf-8 -*-
"""问答层工具（简报 023）：query_skill / query_patch / query_meta_rank

工具纪律（铁律）：三个工具只读本地数据——query_skill / query_patch 走现有
retriever 的本地文档库（按类型过滤的封装），query_meta_rank 只读本地快照
（data/jjc-stats 强度榜；view=force 时读 data/arena-rank 的 3v3 门派分布）。
问答层绝不发起网络请求；每日一次的抓取纪律属于管道层（fetch_jjc_stats /
fetch_arena_rank），用户问多少个问题都不该多打一次外部 API。

query_meta_rank 默认口径（arch-agent-v1）：分段 2800-3100（高分段更有
参考价值），时间维度 last7d（防技改前数据影响决策）。快照中样本不足的
组合带 unavailable 标记（推栏官方「数据量过少」），工具自动回退到
node（当前节点期）并在返回中注明；分段快照整体缺失时列出可用分段。

对外接口（可被其他模块 import）：
    ToolBox             工具集合（自建/注入索引与快照目录）
    TOOL_SCHEMAS        OpenAI tools 参数的 schema 列表
    dispatch(...)       ToolBox.dispatch 的模块级便捷封装
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from retriever import (TfidfIndex, load_latest_snapshot, patch_documents,
                       skill_documents)

JJC_STATS_DIR = Path(__file__).resolve().parent.parent / "data" / "jjc-stats"
ARENA_RANK_DIR = Path(__file__).resolve().parent.parent / "data" / "arena-rank"

DEFAULT_SEGMENT = "2800-3100"
DEFAULT_PERIOD = "last7d"
DEFAULT_KUNGFU_TYPE = "dps"
DEFAULT_VIEW = "kungfu"
# period 回退链：用户/默认值优先，其后依次回退；node 是节点期，样本最足
_PERIOD_FALLBACK = ("node", "last7d", "last1d")
_PERIOD_LABEL = {"node": "节点期", "last7d": "近7天", "last1d": "近1天"}
_KUNGFU_TYPE_LABEL = {"dps": "输出", "tps": "治疗"}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_skill",
            "description": "查询剑网3技能库：技能效果、调息、范围、机制。"
                           "适用于「某技能是什么效果/怎么用」类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string",
                                 "description": "检索用问题，保留技能名等关键词"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_patch",
            "description": "查询技改公告库：心法/奇穴/技能的改动条目。"
                           "适用于「某心法/奇穴改了什么」类问题。"
                           "注意区分公告日期，以最新公告的「调整为：」文本为准。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string",
                                 "description": "检索用问题，以奇穴/心法名等实词为主；"
                                                "修饰词堆多了会稀释匹配，检索不到时"
                                                "改用更短查询（如只发实体名）"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_meta_rank",
            "description": "查询名剑大会榜单（本地每日快照，数据日期见返回）。"
                           "view=kungfu：心法强度榜（什么心法强：强度名次/胜率/出场率）；"
                           "view=force：3v3 排行榜前 200 名门派分布（谁排在前面）。"
                           "适用于「当前版本谁强/胜率/出场率/强度排名/门派人数」类问题。"
                           "口径：个人+组队合并匹配（all）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "view": {"type": "string", "enum": ["kungfu", "force"],
                             "description": "kungfu=心法强度榜（默认）；"
                                            "force=3v3 前200名门派分布"},
                    "kungfu_type": {"type": "string", "enum": ["dps", "tps"],
                                    "description": "dps=输出心法（默认），tps=治疗心法"},
                    "period": {"type": "string",
                               "enum": ["last7d", "node", "last1d"],
                               "description": "时间维度，默认 last7d（近7天）；"
                                              "node=当前节点期；last1d=近1天"},
                    "segment": {"type": "string", "enum": ["2800-3100", "all"],
                                "description": "分段区间，默认 2800-3100（高分段）；"
                                               "all=全分段"},
                },
            },
        },
    },
]


class ToolBox:
    """工具集合：技能/技改检索索引 + 强度榜快照目录。

    测试可注入索引与目录；默认自建（读 data/ 本地数据，不出网）。
    """

    def __init__(self, skill_index: TfidfIndex | None = None,
                 patch_index: TfidfIndex | None = None,
                 jjc_dir: Path | str = JJC_STATS_DIR,
                 arena_dir: Path | str = ARENA_RANK_DIR) -> None:
        if skill_index is None:
            skill_index = TfidfIndex(skill_documents(load_latest_snapshot()))
        if patch_index is None:
            patch_index = TfidfIndex(patch_documents())
        self.skill_index = skill_index
        self.patch_index = patch_index
        self.jjc_dir = Path(jjc_dir)
        self.arena_dir = Path(arena_dir)

    # ------------------------------------------------------------ 检索类工具

    @staticmethod
    def _format_hits(hits: list[dict], date_label: str) -> str:
        if not hits:
            return "未检索到相关资料。"
        lines = []
        for i, hit in enumerate(hits, start=1):
            m = hit["metadata"]
            source = f"{m['类型']}｜{m['门派']}/{m['心法']}"
            if m["类型"] == "技改":
                source += f"｜公告{m['公告日期']}"
            lines.append(f"[{i}] {source}\n{hit['text']}")
        return f"{date_label}\n" + "\n\n".join(lines)

    def query_skill(self, question: str, top_k: int = 3) -> str:
        """技能库检索 top_k，返回带来源与数据日期的文本块。"""
        hits = self.skill_index.search(question, top_k=top_k)
        return self._format_hits(hits, "（技能库检索结果）")

    def query_patch(self, question: str, top_k: int = 3) -> str:
        """技改库检索 top_k，返回带来源与公告日期的文本块。"""
        hits = self.patch_index.search(question, top_k=top_k)
        return self._format_hits(hits, "（技改库检索结果）")

    # ------------------------------------------------------------ 强度榜工具

    def _latest_snapshot(self, segment: str) -> Path | None:
        """该分段最新一份快照文件（文件名日期序）；没有则 None。"""
        files = sorted(self.jjc_dir.glob(f"jjc-{segment}-*.json"))
        return files[-1] if files else None

    def available_segments(self) -> list[str]:
        """本地快照覆盖的分段列表（按文件名解析，去重排序）。"""
        segments = set()
        for f in self.jjc_dir.glob("jjc-*-*.json"):
            stem = f.stem
            if not re.search(r"-\d{4}-\d{2}-\d{2}$", stem):
                continue  # 非日期结尾
            segment = stem[len("jjc-"):-len("-0000-00-00")]
            if segment:  # 空段名=旧版无分段文件（jjc-2026-10-24），跳过
                segments.add(segment)
        return sorted(segments)

    def _force_distribution(self) -> str:
        """view=force：最新 3v3 排行榜快照的前 200 名门派分布。"""
        files = sorted(self.arena_dir.glob("3v3-*.json"))
        if not files:
            return "本地没有 3v3 排行榜快照（data/arena-rank），等管道次日抓取。"
        payload = json.loads(files[-1].read_text(encoding="utf-8"))
        stats = payload.get("force_stats")
        if not isinstance(stats, dict) or not stats:
            return f"快照 {files[-1].name} 缺少 force_stats 门派统计。"
        lines = [f"3v3 名剑大会排行榜前 {payload['top_n']} 名门派分布"
                 f"（数据日期 {payload['snapshot_date']}；全榜共 "
                 f"{payload['total']} 人，跨区合并）："]
        for force, count in stats.items():
            lines.append(f"{force}：{count} 人")
        return "\n".join(lines)

    def query_meta_rank(self, kungfu_type: str = DEFAULT_KUNGFU_TYPE,
                        period: str = DEFAULT_PERIOD,
                        segment: str = DEFAULT_SEGMENT,
                        view: str = DEFAULT_VIEW) -> str:
        """读本地榜单快照，返回榜单文本（含数据日期与口径）。

        view=kungfu：心法强度榜。period 样本不足（unavailable）时沿回退链
        找最近可用维度并注明；分段快照整体缺失时列出可用分段。
        view=force：3v3 前 200 名门派分布。绝不发起网络请求。
        """
        if view == "force":
            return self._force_distribution()
        if view != DEFAULT_VIEW:
            return f"参数错误：view 只能是 kungfu/force，收到 {view!r}。"
        if kungfu_type not in _KUNGFU_TYPE_LABEL:
            return f"参数错误：kungfu_type 只能是 dps/tps，收到 {kungfu_type!r}。"
        path = self._latest_snapshot(segment)
        if path is None:
            available = self.available_segments()
            return (f"本地没有分段 {segment} 的强度榜快照。"
                    f"可用分段：{'、'.join(available) or '（无）'}；"
                    "请换用可用分段重试，或等管道次日抓取。")
        payload = json.loads(path.read_text(encoding="utf-8"))

        rankings = payload.get("rankings", {})
        chain = [period] + [p for p in _PERIOD_FALLBACK if p != period]
        entry, used_period, unavailable_note = None, None, ""
        for candidate in chain:
            item = rankings.get(f"{kungfu_type}-{candidate}")
            if item and item.get("rows"):
                entry, used_period = item, candidate
                break
            if item and item.get("unavailable"):
                unavailable_note = (f"（{candidate} 维度样本不足："
                                    f"{item['unavailable']}）")
        if entry is None:
            return (f"快照 {path.name} 中 {kungfu_type} 榜的所有时间维度均无数据"
                    f"{unavailable_note}。")

        scope = payload["score_range"]
        header = (f"名剑大会{_KUNGFU_TYPE_LABEL[kungfu_type]}心法强度榜"
                  f"（数据日期 {payload['snapshot_date']}；分段 {segment} "
                  f"{scope['min']}~{scope['max']}；时间维度 "
                  f"{_PERIOD_LABEL.get(used_period, used_period)}"
                  f"[{used_period}]；个人+组队合并匹配）")
        if used_period != period:
            header += (f"\n注意：请求的 {period} 维度无数据{unavailable_note}，"
                       f"已回退到 {_PERIOD_LABEL.get(used_period, used_period)}。")
        lines = [header]
        for row in entry["rows"]:
            lines.append(f"{row['rank']}. {row['kungfu_name']}"
                         f"｜胜率 {row['win_rate']:.2%}"
                         f"｜出场率 {row['appear_rate']:.2%}")
        return "\n".join(lines)

    # ------------------------------------------------------------ 分发

    def dispatch(self, name: str, arguments: dict | str | None) -> str:
        """按工具名分发；未知工具/坏参数返回错误文本（不抛异常，让循环继续）。"""
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except ValueError:
                return f"工具参数不是合法 JSON：{arguments!r}"
        arguments = dict(arguments or {})
        handlers = {
            "query_skill": self.query_skill,
            "query_patch": self.query_patch,
            "query_meta_rank": self.query_meta_rank,
        }
        handler = handlers.get(name)
        if handler is None:
            return f"未知工具：{name!r}（可用：{'、'.join(handlers)}）"
        try:
            return handler(**arguments)
        except TypeError as exc:
            return f"工具 {name} 参数错误：{exc}"


def dispatch(name: str, arguments: dict | str | None) -> str:
    """模块级便捷封装：自建 ToolBox 后分发（重复调用请自建 ToolBox）。"""
    return ToolBox().dispatch(name, arguments)
