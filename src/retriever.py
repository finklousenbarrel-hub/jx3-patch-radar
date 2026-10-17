# -*- coding: utf-8 -*-
"""向量检索器（简报 014）：两座数据库压平成文档库，按问题检索 top-3

文档粒度：
- 技能库（data/skill-info 最新快照）：每个技能一条文档
  文本 = skillName + 字段行（cd/weapon/distance，简报 017）+ simpleDesc + desc
  metadata = {"门派": ..., "心法": ..., "类型": "技能"}
  只索引 skillData[].remarks[].forceSkills[]（快照中唯一齐备
  skillName/simpleDesc/desc 三字段的技能集合）；阵法 zhenFa、奇穴
  qixueData 字段不齐，不纳入。心法名经全快照 iconName -> name 映射
  解析（kungfuList 为空的「大侠」也能落到「幽罗引」）。
- 技改库：每个条目/奇穴表行一条文档
  metadata = {"门派": ..., "心法": ..., "公告日期": ..., "is_changed": bool,
              "类型": "技改"}
  - data/extra-info/plus/*.json（9/8 首轮子文章）：entries 条目 +
    qixue_table 行（is_changed 取自表格；entries 本身即改动，恒为 True）
  - data/patches/*.json（9/24 第二轮）：entries 条目
    data/patches 下与 plus 同日的公告仅为技改总览（如 9/8 那份），跳过。

检索：字符级 2-gram TF-IDF + 余弦相似度，返回 top-3；
名称命中加权（简报 015）：每条文档带 name 字段（技能=skillName，
技改条目=冒号/括号前的前缀，奇穴表行=「名称」列），问题字串与 name
完整互相包含时该文档 +NAME_MATCH_BOOST，技能本体不再被短文档挤掉；
名称模糊命中（简报 016）：非精确输入（错别字/简写）下按 name 与问题的
重叠率加分 = NAME_MATCH_BOOST × 重叠率。重叠率取两口径较大者——bigram
集合重叠率（散点命中，如「千蝶吐蕊」命中 千蝶/蝶吐 2/3）与连续命中率
（前缀简写，如「千蝶」连续命中 2/4 字符）。阈值 FUZZY_OVERLAP_MIN 禁止
下调：低于 50% 会让「孤影化双」类技能被「什么效果」等泛词误捞。

对外接口（可被其他模块 import）：
    load_latest_snapshot(dir_path)         读最新技能库快照（文件名即 generatedAt）
    skill_documents(snapshot)              技能库快照 -> 文档列表
    patch_documents(plus_dir, patch_dir)   技改 json -> 文档列表
    build_documents(...)                   两座库压平成一份文档库（技能在前）
    tokenize(text)                         字符级 2-gram 切分
    TfidfIndex                             TF-IDF 索引：search(question, top_k)
    search(question, docs=None, top_k=3)   一行检索（缺省用默认数据目录建库）
    main()                                 命令行：python src/retriever.py "问题"
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

# 数据目录（相对于本文件：workspace/data/...）
SKILL_INFO_DIR = Path(__file__).resolve().parent.parent / "data" / "skill-info"
PLUS_JSON_DIR = Path(__file__).resolve().parent.parent / "data" / "extra-info" / "plus"
PATCH_JSON_DIR = Path(__file__).resolve().parent.parent / "data" / "patches"

DOC_TYPE_SKILL = "技能"
DOC_TYPE_PATCH = "技改"

# 名称命中加权的加分量（简报 015：+0.5 或翻倍，实测翻倍不足以反超短文档）
NAME_MATCH_BOOST = 0.5
# name 达到该长度才参与加权（单字 name 误伤面太大）
_NAME_MIN_LEN = 2
# 模糊档（简报 016）的重叠率下限：bigram 集合或连续命中任一口径达到该比例
# 才加分。禁止下调——低于 50% 时「什么效果」之类的泛词足以让「孤影化双」
# 这类 4 字技能被误捞（单 stray bigram 即达线）。
FUZZY_OVERLAP_MIN = 0.5

_WS_RE = re.compile(r"\s+")
# 技改条目的条目名：冒号/括号前的前缀（如「第四重奇穴【沁逸】」「招式【乱洒青荷】」）
_ENTRY_NAME_RE = re.compile(r"^[^\n（(:：]{1,40}(?=[（(:：])")


# ---------------------------------------------------------------- 文档库：技能库

def load_latest_snapshot(dir_path: str | Path = SKILL_INFO_DIR) -> dict:
    """读取技能库目录下最新的快照（文件名即 generatedAt，按文件名排序取最后一份）。"""
    dir_path = Path(dir_path)
    files = sorted(dir_path.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"{dir_path} 下没有技能库快照，请先运行 src/fetch_skill_info.py")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def skill_documents(snapshot: dict) -> list[dict]:
    """把技能库快照压平成文档列表：每个 forceSkill 一条文档。

    文本 = skillName + 字段行（cd/weapon/distance，简报 017）+ simpleDesc
    + desc；字段缺失时跳过对应片段。

    :param snapshot: fetch_skill_info 落盘的全量快照（含 forces/generatedAt）
    :return: [{"id", "text", "metadata"}]，metadata = {门派, 心法, 类型:"技能"}
    """
    # iconName -> 心法名：跨门派合并成一张全局表（「大侠」自身 kungfuList 为空）
    kungfu_names: dict[str, str] = {}
    for force in snapshot.get("forces", []):
        for k in force.get("kungfuList") or []:
            kungfu_names.setdefault(k.get("iconName", ""), k.get("name", ""))

    docs: list[dict] = []
    for force in snapshot.get("forces", []):
        sect = force.get("name", "")
        for sd in force.get("skillData") or []:
            raw_kungfu = sd.get("kungfu", "")
            xinfa = kungfu_names.get(raw_kungfu, raw_kungfu)
            for remark in sd.get("remarks", []):
                for skill in remark.get("forceSkills", []):
                    fields = "，".join(p for p in (
                        skill.get("cd", ""),
                        f"武器：{skill['weapon']}" if skill.get("weapon") else "",
                        f"距离：{skill['distance']}" if skill.get("distance") else "",
                    ) if p)
                    text = "\n".join(p for p in (skill.get("skillName", ""), fields,
                                                 skill.get("simpleDesc", ""),
                                                 skill.get("desc", "")) if p)
                    docs.append({
                        "id": f"skill-{len(docs)}",
                        "name": skill.get("skillName", ""),
                        "text": text,
                        "metadata": {"门派": sect, "心法": xinfa,
                                     "类型": DOC_TYPE_SKILL},
                    })
    return docs


# ---------------------------------------------------------------- 文档库：技改库

def _load_jsons(dir_path: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(dir_path.glob("*.json"))]


def _entry_name(entry: str) -> str:
    """技改条目的条目名：冒号/括号前的前缀；无此前缀的通用条目返回 ""。"""
    m = _ENTRY_NAME_RE.match(entry)
    return m.group(0).strip() if m else ""


def _xinfa_patch_docs(sect: str, xinfa: str, date: str,
                      entries: list[str], qixue_table: list[dict],
                      docs: list[dict]) -> None:
    """把一个心法下的 entries 与 qixue_table 行追加为技改文档。"""
    for entry in entries:
        docs.append({
            "id": f"patch-{len(docs)}",
            "name": _entry_name(entry),
            "text": entry,
            "metadata": {"门派": sect, "心法": xinfa, "公告日期": date,
                         "is_changed": True, "类型": DOC_TYPE_PATCH},
        })
    for row in qixue_table:
        text = "\n".join(p for p in (row.get("名称", ""), row.get("类型", ""),
                                     row.get("效果", "")) if p)
        docs.append({
            "id": f"patch-{len(docs)}",
            "name": row.get("名称", ""),
            "text": text,
            "metadata": {"门派": sect, "心法": xinfa, "公告日期": date,
                         "is_changed": bool(row.get("is_changed")),
                         "类型": DOC_TYPE_PATCH},
        })


def patch_documents(plus_dir: str | Path = PLUS_JSON_DIR,
                    patch_dir: str | Path = PATCH_JSON_DIR) -> list[dict]:
    """把技改库压平成文档列表（plus 首轮子文章 + patches 后续公告）。

    data/patches 下日期与 plus 相同的公告仅为首轮总览，内容已被 plus
    子文章覆盖，跳过不索引。
    """
    plus_dir = Path(plus_dir)
    patch_dir = Path(patch_dir)
    docs: list[dict] = []

    plus_datas = _load_jsons(plus_dir) if plus_dir.exists() else []
    plus_dates = {d.get("date", "") for d in plus_datas}
    for data in plus_datas:
        for sect in data.get("sects", []):
            for xinfa in sect.get("xinfas", []):
                _xinfa_patch_docs(sect.get("name", ""), xinfa.get("name", ""),
                                  data.get("date", ""), xinfa.get("entries", []),
                                  xinfa.get("qixue_table", []), docs)

    if patch_dir.exists():
        for data in _load_jsons(patch_dir):
            if data.get("date", "") in plus_dates:
                continue  # 与 plus 同日的公告仅为技改总览
            for sect in data.get("sects", []):
                for xinfa in sect.get("xinfas", []):
                    _xinfa_patch_docs(sect.get("name", ""), xinfa.get("name", ""),
                                      data.get("date", ""), xinfa.get("entries", []),
                                      [], docs)
    return docs


def build_documents(skill_info_dir: str | Path = SKILL_INFO_DIR,
                    plus_dir: str | Path = PLUS_JSON_DIR,
                    patch_dir: str | Path = PATCH_JSON_DIR) -> list[dict]:
    """两座数据库压平成一份文档库（技能库文档在前，技改库在后）。"""
    return skill_documents(load_latest_snapshot(skill_info_dir)) \
        + patch_documents(plus_dir, patch_dir)


# ---------------------------------------------------------------- 检索：2-gram TF-IDF

def tokenize(text: str) -> list[str]:
    """字符级 2-gram 切分：先去全部空白，再取相邻两字；不足两字返回原串。"""
    chars = _WS_RE.sub("", text)
    if len(chars) < 2:
        return [chars] if chars else []
    return [chars[i:i + 2] for i in range(len(chars) - 1)]


class TfidfIndex:
    """字符级 2-gram TF-IDF 索引（纯 stdlib，余弦相似度检索）。

    权重 = tf * idf，idf = ln((1 + N) / (1 + df)) + 1，文档向量 L2 归一化；
    查询向量同口径归一化后点积即余弦相似度。
    """

    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs: list[dict] = []
        self._idf: dict[str, float] = {}
        self._postings: dict[str, list[tuple[int, float]]] = {}
        self._name_bigrams: list[list[str]] = []
        if docs:
            self.add_documents(docs)

    def add_documents(self, docs: list[dict]) -> None:
        """重建索引（文档库是全量派生物，重建即刷新）。"""
        self.docs = list(docs)
        self._name_bigrams = [
            tokenize(d.get("name", "")) if len(d.get("name", "")) >= _NAME_MIN_LEN
            else []
            for d in self.docs
        ]
        term_counts = [Counter(tokenize(d["text"])) for d in self.docs]
        n_docs = len(self.docs)

        df: Counter[str] = Counter()
        for counts in term_counts:
            df.update(counts.keys())
        self._idf = {t: math.log((1 + n_docs) / (1 + c)) + 1.0
                     for t, c in df.items()}

        self._postings = {}
        for doc_idx, counts in enumerate(term_counts):
            vec = {t: tf * self._idf[t] for t, tf in counts.items()}
            norm = math.sqrt(sum(w * w for w in vec.values()))
            if norm == 0.0:
                continue
            for term, weight in vec.items():
                self._postings.setdefault(term, []).append((doc_idx, weight / norm))

    def search(self, question: str, top_k: int = 3) -> list[dict]:
        """按问题检索，返回 top_k 条命中（[{**doc, "score"}]，相似度降序）。

        名称命中加权（简报 015）：问题字串与文档 name（≥2 字）完整互相
        包含时，该文档得分 +NAME_MATCH_BOOST，再参与排序。
        名称模糊命中（简报 016）：未完整包含时，按 name bigram 与问题的
        重叠率（集合重叠率、连续命中率取大）加分 NAME_MATCH_BOOST × 重叠率，
        仅当重叠率 ≥ FUZZY_OVERLAP_MIN 时生效。
        无词面重叠（得分全零）时返回空列表，而不是任意文档。
        """
        q_counts = Counter(tokenize(question))
        q_vec = {t: tf * self._idf[t] for t, tf in q_counts.items() if t in self._idf}
        q_norm = math.sqrt(sum(w * w for w in q_vec.values()))
        if q_norm == 0.0:
            return []

        scores: dict[int, float] = {}
        for term, q_weight in q_vec.items():
            for doc_idx, d_weight in self._postings.get(term, []):
                scores[doc_idx] = scores.get(doc_idx, 0.0) \
                    + (q_weight / q_norm) * d_weight

        q_flat = _WS_RE.sub("", question)
        q_grams = set(q_counts)
        for doc_idx, score in scores.items():
            name = self.docs[doc_idx].get("name", "")
            name_grams = self._name_bigrams[doc_idx]
            if not q_flat or not name_grams:
                continue
            if name in q_flat or q_flat in name:
                scores[doc_idx] = score + NAME_MATCH_BOOST
                continue
            matched = [g in q_grams for g in name_grams]
            set_ratio = sum(matched) / len(name_grams)
            run = best = 0
            for ok in matched:
                run = run + 1 if ok else 0
                best = max(best, run)
            coverage = (best + 1) / len(name) if best else 0.0
            fuzzy_ratio = max(set_ratio, coverage)
            if fuzzy_ratio >= FUZZY_OVERLAP_MIN:
                scores[doc_idx] = score + NAME_MATCH_BOOST * fuzzy_ratio

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
        return [{**self.docs[i], "score": score} for i, score in ranked]


def search(question: str, docs: list[dict] | None = None,
           top_k: int = 3) -> list[dict]:
    """一行检索：缺省用默认数据目录现建文档库与索引，返回 top_k 命中。"""
    if docs is None:
        docs = build_documents()
    return TfidfIndex(docs).search(question, top_k=top_k)


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python src/retriever.py \"问题\"", file=sys.stderr)
        return 1
    question = sys.argv[1]
    docs = build_documents()
    n_skill = sum(1 for d in docs if d["metadata"]["类型"] == DOC_TYPE_SKILL)
    print(f"文档库：技能 {n_skill} 条 / 技改 {len(docs) - n_skill} 条")
    for rank, hit in enumerate(search(question, docs), start=1):
        m = hit["metadata"]
        head = (f"{rank}. [{m['类型']}] {m['门派']}/{m['心法']}"
                + (f"（公告 {m['公告日期']}）" if m["类型"] == DOC_TYPE_PATCH else "")
                + f"  相似度 {hit['score']:.4f}")
        print(f"{head}\n   {hit['text'][:80].replace(chr(10), ' / ')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
