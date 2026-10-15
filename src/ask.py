# -*- coding: utf-8 -*-
"""技改/技能问答（简报 014）：任意问题 → 检索 top-3 → 拼 prompt → Kimi 回答（带数据日期）

ask_demo.py 的升级：资料不再写死单个技能，而是由 retriever 按问题
从技能库 + 技改库检索 top-3 文档拼入 prompt，回答注明数据日期。

用法：
    python src/ask.py "万花的沁逸改成什么了？"   # 单问单答
    python src/ask.py                            # 交互模式：逐行提问，空行退出

对外接口（可被其他模块 import）：
    build_prompt(question, hits, skill_generated_at)  拼 user prompt（纯函数）
    answer(question, client, index, skill_generated_at)  检索 + 调 Kimi
    ask(question)                                     一问一答（自建索引与客户端）
    main()                                            命令行入口

环境变量：MOONSHOT_API_KEY（读 .env 或环境），模型 kimi-k3。
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from retriever import (TfidfIndex, build_documents, load_latest_snapshot,
                       patch_documents, skill_documents)

MODEL = "kimi-k3"
SYSTEM_PROMPT = ("你是剑网3竞技场数据助手，只根据提供的资料回答，"
                 "资料里没有就说不知道；回答时注明依据的数据日期。")


def build_prompt(question: str, hits: list[dict],
                 skill_generated_at: str) -> str:
    """把检索命中拼成 user prompt：资料块（含各条来源与日期）+ 问题。

    :param question: 用户问题
    :param hits: retriever 的 top_k 命中（含 text/metadata），可为空
    :param skill_generated_at: 技能库快照 generatedAt（技能文档的数据日期）
    """
    lines = [f"资料（技能库数据日期 {skill_generated_at}；技改条目日期见各条公告）："]
    for i, hit in enumerate(hits, start=1):
        m = hit["metadata"]
        source = f"{m['类型']}｜{m['门派']}/{m['心法']}"
        if m["类型"] == "技改":
            source += f"｜公告{m['公告日期']}"
        lines.append(f"[{i}] {source}")
        lines.append(hit["text"])
    if not hits:
        lines.append("（未检索到相关资料）")
    lines.append(f"问题：{question}")
    return "\n".join(lines)


def answer(question: str, client: OpenAI, index: TfidfIndex,
           skill_generated_at: str) -> str:
    """检索 top-3 → 拼 prompt → 调 Kimi，返回回答文本。"""
    hits = index.search(question, top_k=3)
    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": build_prompt(question, hits, skill_generated_at)},
        ],
    )
    return completion.choices[0].message.content


def _make_client() -> OpenAI:
    load_dotenv()
    return OpenAI(
        api_key=os.environ["MOONSHOT_API_KEY"],
        base_url="https://api.moonshot.cn/v1",
    )


def ask(question: str) -> str:
    """一问一答便捷入口：自建文档库、索引与客户端（重复提问请用 answer）。"""
    snapshot = load_latest_snapshot()
    docs = skill_documents(snapshot) + patch_documents()
    return answer(question, _make_client(), TfidfIndex(docs),
                  snapshot.get("generatedAt", "未知"))


def main() -> int:
    snapshot = load_latest_snapshot()
    skill_generated_at = snapshot.get("generatedAt", "未知")
    index = TfidfIndex(build_documents())
    client = _make_client()

    if len(sys.argv) > 1:
        print(answer(" ".join(sys.argv[1:]), client, index, skill_generated_at))
        return 0

    print("剑网3技改/技能问答（空行退出）")
    while True:
        try:
            question = input("问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        print(answer(question, client, index, skill_generated_at))
    return 0


if __name__ == "__main__":
    sys.exit(main())
