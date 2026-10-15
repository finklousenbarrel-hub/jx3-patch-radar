# -*- coding: utf-8 -*-
"""retriever 的验收测试（简报 014）

运行方式（项目根目录）：
    python tests/test_retriever.py
或：
    python -m pytest tests/test_retriever.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from retriever import (  # noqa: E402
    TfidfIndex,
    build_documents,
    load_latest_snapshot,
    patch_documents,
    search,
    skill_documents,
    tokenize,
)

SNAPSHOT = load_latest_snapshot()
SKILL_DOCS = skill_documents(SNAPSHOT)
PATCH_DOCS = patch_documents()


# ---------------------------------------------------------------- 文档库：技能库

def test_skill_documents_count():
    """验收：技能库 22 门派压平为 558 条技能文档。"""
    assert len(SKILL_DOCS) == 558, len(SKILL_DOCS)


def test_skill_document_metadata():
    """技能文档 metadata = {门派, 心法, 类型:"技能"}；文本含 skillName/simpleDesc/desc。"""
    doc = next(d for d in SKILL_DOCS if d["text"].startswith("乱天狼"))
    assert doc["metadata"] == {"门派": "凌雪阁", "心法": "隐龙诀", "类型": "技能"}
    assert "伤害技，对多个目标持续造成伤害" in doc["text"]  # simpleDesc
    assert "日月吴钩" in doc["text"]                        # desc 内容


def test_skill_xinfa_fallback():
    """kungfuList 为空的「大侠」也经全局 iconName 映射落到心法名。"""
    docs = [d for d in SKILL_DOCS if d["metadata"]["门派"] == "大侠"]
    assert docs and all(d["metadata"]["心法"] == "幽罗引" for d in docs)


# ---------------------------------------------------------------- 文档库：技改库

def test_patch_documents_count():
    """验收：技改库 = 9/8（365 条目 + 1152 奇穴行）+ 9/24（352 条目）= 1869。"""
    assert len(PATCH_DOCS) == 1869, len(PATCH_DOCS)


def test_patch_documents_skip_overview():
    """data/patches 下与 plus 同日的 9/8 总览不入库：9/8 文档全部来自 plus。"""
    docs_0908 = [d for d in PATCH_DOCS if d["metadata"]["公告日期"] == "2026/09/08"]
    docs_0924 = [d for d in PATCH_DOCS if d["metadata"]["公告日期"] == "2026/09/24"]
    assert (len(docs_0908), len(docs_0924)) == (1517, 352)
    # 9/8 总览的 3 条旗舰通用条目若混入会带 entries 文本，此处条数已排除


def test_patch_document_metadata():
    """技改文档 metadata = {门派, 心法, 公告日期, is_changed, 类型}；奇穴行带 is_changed。"""
    doc = next(d for d in PATCH_DOCS if d["text"].startswith("沁逸"))
    assert doc["metadata"] == {"门派": "万花", "心法": "花间游",
                               "公告日期": "2026/09/08", "is_changed": True,
                               "类型": "技改"}
    n_changed = sum(1 for d in PATCH_DOCS
                    if d["metadata"]["公告日期"] == "2026/09/08"
                    and d["metadata"]["is_changed"])
    assert n_changed == 346 + 365  # 奇穴行改动 346 + entries 恒为 True


def test_build_documents_order_and_total():
    """文档库 = 技能 558 + 技改 1869 = 2427，技能文档在前。"""
    docs = build_documents()
    assert len(docs) == 2427
    assert docs[0]["metadata"]["类型"] == "技能"
    assert docs[-1]["metadata"]["类型"] == "技改"
    assert {d["id"] for d in docs} and len({d["id"] for d in docs}) == len(docs)


# ---------------------------------------------------------------- 检索

def test_tokenize_bigrams():
    """字符级 2-gram：去空白后取相邻两字；单字返回原串，空串返回空。"""
    assert tokenize("乱天狼") == ["乱天", "天狼"]
    assert tokenize("万 花\n") == ["万花"]
    assert tokenize("a") == ["a"]
    assert tokenize("  ") == []


def test_search_top3_hits():
    """按问题检索 top-3：「沁逸」命中两轮公告各一条，含门派/心法/公告日期。"""
    hits = search("沁逸改成什么了")
    assert len(hits) == 2  # 语料仅两份文档含「沁逸」；零重叠文档不应凑数
    assert all("沁逸" in h["text"] for h in hits)
    top = hits[0]
    assert top["metadata"]["门派"] == "万花" and top["metadata"]["心法"] == "花间游"
    assert top["metadata"]["公告日期"] in ("2026/09/08", "2026/09/24")
    assert hits[0]["score"] > hits[1]["score"] > 0


def test_search_top_k_cap():
    """命中多于 3 条时只返回 top-3，且得分降序。"""
    hits = search("乱天狼")
    assert len(hits) == 3
    assert all("乱天狼" in h["text"] for h in hits)
    assert {h["metadata"]["门派"] for h in hits} == {"凌雪阁"}
    assert hits[0]["score"] >= hits[1]["score"] >= hits[2]["score"] > 0


def test_search_deterministic():
    """同一问题连续检索两次，结果逐条一致（含得分）。"""
    assert search("坐忘无我") == search("坐忘无我")


def test_search_no_overlap_returns_empty():
    """与语料零词面重叠的问题返回空列表，而不是任意文档。"""
    assert search("龘靐齉爩") == []
    assert TfidfIndex(build_documents()).search("") == []


# ---------------------------------------------------------------- 名称命中加权（简报 015）

def test_doc_name_fields():
    """name 字段：技能=skillName；奇穴表行=「名称」列；技改条目=冒号/括号前前缀。"""
    skill = next(d for d in SKILL_DOCS if d["text"].startswith("乱天狼"))
    assert skill["name"] == "乱天狼"
    qixue = next(d for d in PATCH_DOCS if d["text"].startswith("沁逸\n"))
    assert qixue["name"] == "沁逸"
    entry = next(d for d in PATCH_DOCS if d["text"].startswith("第四重奇穴【沁逸】"))
    assert entry["name"] == "第四重奇穴【沁逸】"
    generic = next(d for d in PATCH_DOCS
                   if d["text"].startswith("对非侠士目标造成的伤害提升53%"))
    assert generic["name"] == ""  # 无前缀的通用条目不参与加权


def test_name_boost_luantianlang_acceptance():
    """验收：「乱天狼什么效果」top-1 必须是技能文档（本体不再被挤掉）。"""
    top = search("乱天狼什么效果")[0]
    assert top["metadata"]["类型"] == "技能"
    assert top["name"] == "乱天狼"


def test_name_boost_qinyi_acceptance():
    """验收：「沁逸改成什么了」top-1 仍必须是技改文档。"""
    top = search("沁逸改成什么了")[0]
    assert top["metadata"]["类型"] == "技改"
    assert top["name"] == "沁逸"


def _doc(doc_id: str, name: str, text: str) -> dict:
    return {"id": doc_id, "name": name, "text": text, "metadata": {}}


def test_name_boost_flips_ranking():
    """加权逻辑：名称完整命中问题 -> +0.5 反超纯余弦更高的文档。"""
    doc_a = _doc("a", "青冥剑", "青冥剑\n效果独特的冷门招式，需要在特定场合才能施展，泛用性一般。")
    doc_b = _doc("b", "剑甲", "青冥剑青冥剑青冥剑，配合剑甲使用。")
    index = TfidfIndex([doc_a, doc_b])
    # 对照问题（名称未完整命中）：纯余弦排序，高热文档在前
    assert index.search("青冥好用吗")[0]["name"] == "剑甲"
    # 名称完整命中后：本体反超到 top-1
    assert index.search("青冥剑值得点吗")[0]["name"] == "青冥剑"


def test_name_boost_requires_two_char_name():
    """单字 name 不加权；≥2 字且与问题完整互相包含才加权。"""
    text = "独门看剑剑法要诀，冷门知识。"
    index = TfidfIndex([_doc("c", "剑", text),
                        _doc("d", "剑甲", text),
                        _doc("e", "看剑", text)])
    hits = index.search("来看看剑法吧")
    assert hits[0]["name"] == "看剑"                    # 命中加权
    assert hits[0]["score"] - hits[1]["score"] == pytest.approx(0.5)
    assert {h["name"] for h in hits[1:]} == {"剑", "剑甲"}  # 单字/未命中：同分
    assert hits[1]["score"] == hits[2]["score"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
