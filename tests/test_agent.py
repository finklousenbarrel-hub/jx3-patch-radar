# -*- coding: utf-8 -*-
"""agent 的函数测试（简报 023：function calling 工具循环，3 轮防爆）

运行方式（项目根目录）：
    python tests/test_agent.py
或：
    python -m pytest tests/test_agent.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent import MAX_TOOL_ROUNDS, _assistant_msg, agent_answer  # noqa: E402


def _msg(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tool_call(name, arguments, call_id="call_1"):
    return SimpleNamespace(
        id=call_id, type="function",
        function=SimpleNamespace(name=name, arguments=arguments))


def _completion(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    """按脚本返回响应的假客户端；记录每次 create 的 kwargs。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _completion(self.script.pop(0))


class FakeToolBox:
    def __init__(self):
        self.dispatched = []

    def dispatch(self, name, arguments):
        self.dispatched.append((name, arguments))
        return f"[{name} 返回] 镇山河：4尺气场队友免疫伤害"


# ---------------------------------------------------------------- 循环行为

def test_direct_answer_without_tools():
    """模型首轮直接回答：不触发工具，rounds=0。"""
    client = FakeClient([_msg(content="镇山河是4尺气场。")])
    result = agent_answer("镇山河效果？", client, FakeToolBox())
    assert result["answer"] == "镇山河是4尺气场。"
    assert result["tool_calls"] == [] and result["rounds"] == 0
    assert len(client.calls) == 1


def test_one_tool_round_then_answer():
    """首轮要工具 → 工具结果回填 → 次轮回答；trace 记录调用。"""
    client = FakeClient([
        _msg(tool_calls=[_tool_call("query_skill", '{"question": "镇山河"}')]),
        _msg(content="镇山河：4尺气场，队友免疫伤害。"),
    ])
    toolbox = FakeToolBox()
    result = agent_answer("镇山河效果？", client, toolbox)
    assert toolbox.dispatched == [("query_skill", '{"question": "镇山河"}')]
    assert result["rounds"] == 1 and result["tool_calls"][0]["name"] == "query_skill"
    # 第二轮请求里应包含 tool 角色的回填消息
    second_messages = client.calls[1]["messages"]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "call_1"
               for m in second_messages)
    assert "镇山河" in result["answer"]


def test_max_rounds_brake():
    """模型每轮都要工具：最多放行 MAX_TOOL_ROUNDS 轮，随后无 tools 收尾。"""
    client = FakeClient(
        [_msg(tool_calls=[_tool_call("query_skill", '{"question": "x"}')])
         for _ in range(MAX_TOOL_ROUNDS)]
        + [_msg(content="根据已有资料回答。")])
    result = agent_answer("循环？", client, FakeToolBox())
    assert len(client.calls) == MAX_TOOL_ROUNDS + 1
    assert "tools" not in client.calls[-1]          # 收尾请求不带工具
    last_user = client.calls[-1]["messages"][-1]
    assert "轮数已达上限" in last_user["content"]
    assert result["rounds"] == MAX_TOOL_ROUNDS
    assert result["answer"] == "根据已有资料回答。"


def test_assistant_msg_serialization():
    """assistant 消息回放格式：OpenAI tool_calls 结构。"""
    msg = _assistant_msg(_msg(content=None, tool_calls=[
        _tool_call("query_meta_rank", '{"period": "last7d"}', "call_9")]))
    assert msg == {"role": "assistant", "content": "",
                   "tool_calls": [{"id": "call_9", "type": "function",
                                   "function": {"name": "query_meta_rank",
                                                "arguments": '{"period": "last7d"}'}}]}


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[通过] {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"[失败] {t.__name__}: {exc!r}", file=sys.stderr)
    print(f"\n{len(tests) - failed}/{len(tests)} 项通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
