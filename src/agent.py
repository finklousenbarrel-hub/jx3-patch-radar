# -*- coding: utf-8 -*-
"""工具调用 Agent（简报 023）：LLM function calling 自主选工具，连调复合问题

路由策略按 arch-agent-v1 方案 A：Moonshot chat.completions 的 tools 参数，
由模型按语义自主选工具（规则路由无法穷尽问询关键字，也无法并行调用）。

工具循环防爆：MAX_TOOL_ROUNDS = 3——模型连续要工具最多放行 3 轮，
第 4 次请求不再携带 tools 并要求根据已有资料作答，防止循环烧 token。

回答纪律（arch-agent-v1 失败防御规范层，见 SYSTEM_PROMPT）：
只根据工具返回的资料回答，逐条对应；资料里没有就说不知道；
注明数据日期；强度榜默认口径 2800-3100 / 近7天。

用法：
    python src/agent.py "当前版本输出心法谁最强？"   # 单问单答
    python src/agent.py                             # 交互模式：逐行提问，空行退出

对外接口（可被其他模块 import）：
    agent_answer(question, client, toolbox, max_rounds)  工具循环主逻辑
    ask_agent(question)                                  一问一答便捷入口
    main()                                               命令行入口

环境变量：MOONSHOT_API_KEY（读 .env 或环境），模型 kimi-k3。
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from agent_tools import TOOL_SCHEMAS, ToolBox

MODEL = "kimi-k3"
MAX_TOOL_ROUNDS = 3

SYSTEM_PROMPT = (
    "你是剑网3名剑大会数据助手。回答纪律：\n"
    "1. 只根据工具返回的资料回答，每一句事实都要能对应到某次工具返回；"
    "资料里没有的信息就明说不知道，绝不编造。\n"
    "2. 技能效果类问题用 query_skill；技改改动类问题用 query_patch"
    "（注意区分公告日期，以最新公告的「调整为：」文本为准）；"
    "强度/胜率/出场率/排名类问题用 query_meta_rank。\n"
    "3. 复合问题按需连调多个工具（可在同一轮并行调用）。\n"
    "4. 回答必须注明依据的数据日期（技能库日期、公告日期、强度榜快照日期）。\n"
    "5. 强度榜默认口径：分段 2800-3100、近7天；用户指定分段/周期时按用户指定。"
    "工具返回注明了回退时，回答要如实说明实际口径。\n"
    "6. 检索结果与问题不相关（如查最新改动却只返回旧公告）时，"
    "换更短、只含实体名的查询重试一次（如只发「沁逸」），再下结论。"
)


def _assistant_msg(message) -> dict:
    """把模型返回的 assistant message 转成可回放的 dict（兼容命名空间假对象）。"""
    msg = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        msg["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name,
                          "arguments": tc.function.arguments}}
            for tc in message.tool_calls
        ]
    return msg


def agent_answer(question: str, client: OpenAI, toolbox: ToolBox,
                 max_rounds: int = MAX_TOOL_ROUNDS) -> dict:
    """工具循环主逻辑：最多 max_rounds 轮工具调用，返回
    {"answer": str, "tool_calls": [{name, arguments, result}], "rounds": int}。
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question}]
    trace: list[dict] = []

    for _ in range(max_rounds):
        completion = client.chat.completions.create(
            model=MODEL, messages=messages,
            tools=TOOL_SCHEMAS, tool_choice="auto")
        message = completion.choices[0].message
        if not message.tool_calls:
            return {"answer": message.content or "",
                    "tool_calls": trace, "rounds": len(trace)}
        messages.append(_assistant_msg(message))
        for tc in message.tool_calls:
            result = toolbox.dispatch(tc.function.name, tc.function.arguments)
            trace.append({"name": tc.function.name,
                          "arguments": tc.function.arguments,
                          "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": result})

    messages.append({"role": "user",
                     "content": "工具调用轮数已达上限，请根据已获得的资料直接回答；"
                                "资料不足就明说不知道。"})
    completion = client.chat.completions.create(model=MODEL, messages=messages)
    return {"answer": completion.choices[0].message.content or "",
            "tool_calls": trace, "rounds": len(trace)}


def _make_client() -> OpenAI:
    load_dotenv()
    return OpenAI(
        api_key=os.environ["MOONSHOT_API_KEY"],
        base_url="https://api.moonshot.cn/v1",
    )


def ask_agent(question: str) -> str:
    """一问一答便捷入口：自建客户端与 ToolBox（重复提问请用 agent_answer）。"""
    return agent_answer(question, _make_client(), ToolBox())["answer"]


def main() -> int:
    client, toolbox = _make_client(), ToolBox()
    if len(sys.argv) > 1:
        result = agent_answer(" ".join(sys.argv[1:]), client, toolbox)
        print(result["answer"])
        return 0

    print("剑网3名剑大会问答（工具调用版，空行退出）")
    while True:
        try:
            question = input("问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        result = agent_answer(question, client, toolbox)
        print(result["answer"])
        if result["tool_calls"]:
            calls = "、".join(f"{t['name']}" for t in result["tool_calls"])
            print(f"（本轮工具调用：{calls}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
