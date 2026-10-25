# -*- coding: utf-8 -*-
"""评测跑批器（简报 023）：跑 docs/eval/agent-eval-v1.json 全量题目，逐题判定

流程：每题走 agent.agent_answer（function calling 工具循环）→ Kimi 评审
（对照 reference_answer 与 key_points，输出严格 JSON 判定）→ 汇总渲染成
reports/agent-eval-v1-results.md（派生物，直接覆盖）。

判定口径：
- 普通题按 key_points 覆盖计分，全部覆盖且核心事实无误 = pass
- 拒答题（category=refusal）：必须明确表示资料中没有，且不得编造 = pass
- 数据日期以工具返回为准（快照每日滚动），允许与参考答案的日期不同，
  但数值必须与所引口径一致

用法：
    python src/run_eval.py            # 全量 10 题
    python src/run_eval.py R1 C1      # 只跑指定题号

对外接口（可被其他模块 import）：
    load_eval_set(path)            读评测集 JSON
    parse_judge_output(text)       解析评审 JSON（容错 markdown 围栏）
    judge_answer(...)              单题评审（调 Kimi）
    render_report(results, meta)   渲染 Markdown 报告（纯函数）
    main()                         命令行入口

环境变量：MOONSHOT_API_KEY（读 .env 或环境），模型与 agent 同为 kimi-k3。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from agent import MODEL, _make_client, agent_answer
from agent_tools import ToolBox

ROOT = Path(__file__).resolve().parent.parent
EVAL_FILE = ROOT / "docs" / "eval" / "agent-eval-v1.json"
REPORT_FILE = ROOT / "reports" / "agent-eval-v1-results.md"

JUDGE_PROMPT = """\
你是严格的评测裁判。根据【题目】【参考答案】【判分要点】【类别要求】评判【Agent 回答】。

类别要求：
- refusal（拒答题）：回答必须明确表示资料中没有该信息；出现任何编造的具体事实即 fail。
- 其余类别：逐条核对判分要点是否被正确覆盖（数值、名称、方向都必须对）；数据日期以 Agent 工具返回为准，允许与参考答案日期不同，但数值必须与所引口径一致；核心事实错误即 fail。

只输出 JSON（不要输出其他任何内容）：
{{"pass": true/false, "score": 覆盖要点数, "total": 要点总数, "missing_points": ["未覆盖/答错的要点"], "reason": "一句话理由"}}

【题目】{question}
【参考答案】{reference}
【判分要点】{key_points}
【类别】{category}
【Agent 回答】{answer}
"""


def load_eval_set(path: Path | str = EVAL_FILE) -> dict:
    """读评测集 JSON，返回含 questions 的完整字典。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not data.get("questions"):
        raise ValueError(f"评测集为空或缺 questions 字段：{path}")
    return data


def parse_judge_output(text: str) -> dict:
    """解析评审 JSON：容忍 ```json 围栏与前后杂讯；结构不符抛 ValueError。"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"评审输出中没有 JSON：{text[:200]!r}")
    data = json.loads(m.group(0))
    if not isinstance(data.get("pass"), bool):
        raise ValueError(f"评审 JSON 缺 pass 布尔字段：{data!r}")
    data.setdefault("score", 0)
    data.setdefault("total", 0)
    data.setdefault("missing_points", [])
    data.setdefault("reason", "")
    return data


def judge_answer(question: dict, answer: str, client) -> dict:
    """单题评审：调 Kimi 对照参考答案与判分要点，返回解析后的判定。"""
    prompt = JUDGE_PROMPT.format(
        question=question["question"],
        reference=question["reference_answer"],
        key_points="；".join(question["key_points"]),
        category=question["category"],
        answer=answer)
    completion = client.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}])
    raw = completion.choices[0].message.content or ""
    result = parse_judge_output(raw)
    result["raw"] = raw
    return result


def render_report(results: list[dict], eval_meta: dict) -> str:
    """渲染逐题 Markdown 报告（纯函数；不含时间戳）。"""
    passed = sum(1 for r in results if r["judge"]["pass"])
    lines = [
        f"# Agent 评测报告（{eval_meta.get('version', '?')}）",
        "",
        f"评测集：{eval_meta.get('description', '')}",
        f"模型：{MODEL}；通过 {passed}/{len(results)}。",
        "",
        "| 题号 | 类别 | 结果 | 要点覆盖 | 题目 |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        q, j = r["question"], r["judge"]
        lines.append(f"| {q['id']} | {q['category']} | "
                     f"{'✅' if j['pass'] else '❌'} | "
                     f"{j['score']}/{j['total']} | {q['question']} |")
    lines.append("")
    for r in results:
        q, j = r["question"], r["judge"]
        lines += [
            f"## {q['id']}（{q['category']}）{'✅' if j['pass'] else '❌'}",
            "",
            f"**题目**：{q['question']}",
            "",
            f"**Agent 回答**：{r['answer']}",
            "",
        ]
        if r["tool_calls"]:
            lines.append("**工具调用**：")
            for t in r["tool_calls"]:
                preview = t["result"].splitlines()[0][:80]
                lines.append(f"- `{t['name']}({t['arguments']})` → {preview}")
            lines.append("")
        lines += [
            f"**裁判**：{j['reason']}"
            + (f"；未覆盖：{'、'.join(j['missing_points'])}"
               if j["missing_points"] else ""),
            "",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    eval_set = load_eval_set()
    only = set(sys.argv[1:])
    questions = [q for q in eval_set["questions"]
                 if not only or q["id"] in only]
    if not questions:
        print(f"[错误] 没有匹配的题号：{'、'.join(sorted(only))}")
        return 1

    client, toolbox = _make_client(), ToolBox()
    results = []
    for i, q in enumerate(questions, start=1):
        print(f"[{i}/{len(questions)}] {q['id']}（{q['category']}）：{q['question']}")
        run = agent_answer(q["question"], client, toolbox)
        judge = judge_answer(q, run["answer"], client)
        mark = "✅" if judge["pass"] else "❌"
        print(f"    {mark} 要点 {judge['score']}/{judge['total']}：{judge['reason']}")
        results.append({"question": q, "answer": run["answer"],
                        "tool_calls": run["tool_calls"], "judge": judge})

    REPORT_FILE.write_text(render_report(results, eval_set), encoding="utf-8")
    passed = sum(1 for r in results if r["judge"]["pass"])
    print(f"\n通过 {passed}/{len(results)}，报告 -> {REPORT_FILE}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
