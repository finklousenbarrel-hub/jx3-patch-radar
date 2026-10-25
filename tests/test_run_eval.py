# -*- coding: utf-8 -*-
"""run_eval 的函数测试（简报 023：评测跑批器的纯函数部分，不触网）

运行方式（项目根目录）：
    python tests/test_run_eval.py
或：
    python -m pytest tests/test_run_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from run_eval import load_eval_set, parse_judge_output, render_report  # noqa: E402


# ---------------------------------------------------------------- 评审解析

def test_parse_plain_json():
    out = parse_judge_output('{"pass": true, "score": 4, "total": 4, '
                             '"missing_points": [], "reason": "全对"}')
    assert out["pass"] is True and out["score"] == 4 and out["reason"] == "全对"


def test_parse_fenced_json_with_noise():
    """容忍 markdown 围栏与前后杂讯。"""
    text = '好的，判定如下：\n```json\n{"pass": false, "score": 1, "total": 3}\n```\n以上。'
    out = parse_judge_output(text)
    assert out["pass"] is False and out["score"] == 1
    assert out["missing_points"] == [] and out["reason"] == ""  # 缺省补齐


def test_parse_garbage_raises():
    try:
        parse_judge_output("没有任何 JSON")
    except ValueError:
        return
    raise AssertionError("无 JSON 应抛 ValueError")


def test_parse_missing_pass_raises():
    try:
        parse_judge_output('{"score": 3}')
    except ValueError:
        return
    raise AssertionError("缺 pass 字段应抛 ValueError")


# ---------------------------------------------------------------- 评测集与报告

def test_load_eval_set_real_file():
    """仓库内 eval v1：10 题，分布 3 技能+3 技改+2 强度榜+1 复合+1 拒答。"""
    data = load_eval_set()
    assert len(data["questions"]) == 10
    from collections import Counter
    dist = Counter(q["category"] for q in data["questions"])
    assert dist == {"skill": 3, "patch": 3, "strength-rank": 2,
                    "compound": 1, "refusal": 1}
    for q in data["questions"]:
        assert q["question"] and q["reference_answer"] and q["key_points"]


def _fake_result(qid, passed, score=4, total=4):
    return {"question": {"id": qid, "category": "skill",
                         "question": f"题目{qid}？"},
            "answer": f"回答{qid}",
            "tool_calls": [{"name": "query_skill", "arguments": "{}",
                            "result": "首行预览\n第二行"}],
            "judge": {"pass": passed, "score": score, "total": total,
                      "missing_points": [], "reason": "理由"}}


def test_render_report_structure():
    """报告含汇总表、逐题小节、工具调用预览；不含时间戳字段。"""
    md = render_report([_fake_result("S1", True), _fake_result("X1", False, 0)],
                       {"version": "v1", "description": "测试集"})
    assert "通过 1/2" in md
    assert "| S1 | skill | ✅ | 4/4 |" in md
    assert "| X1 | skill | ❌ | 0/4 |" in md
    assert "## S1（skill）✅" in md and "## X1（skill）❌" in md
    assert "`query_skill({})` → 首行预览" in md
    assert "**裁判**：理由" in md


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
