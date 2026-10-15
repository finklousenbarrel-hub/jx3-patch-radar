# -*- coding: utf-8 -*-
"""ask 的验收测试（简报 014）：只测纯函数 build_prompt，不触网。

运行方式（项目根目录）：
    python tests/test_ask.py
或：
    python -m pytest tests/test_ask.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ask import build_prompt  # noqa: E402

SKILL_HIT = {"id": "skill-0", "text": "乱天狼\n伤害技。\n挥舞链刃攻击目标。",
             "metadata": {"门派": "凌雪阁", "心法": "隐龙诀", "类型": "技能"},
             "score": 0.5}
PATCH_HIT = {"id": "patch-0", "text": "第四重奇穴【沁逸】……调整为：……",
             "metadata": {"门派": "万花", "心法": "花间游", "公告日期": "2026/09/24",
                          "is_changed": True, "类型": "技改"},
             "score": 0.4}


def test_build_prompt_carries_dates_and_sources():
    """prompt 必带：技能库数据日期、技改条目的公告日期、来源门派/心法、问题。"""
    prompt = build_prompt("沁逸改成什么了？", [SKILL_HIT, PATCH_HIT],
                          "2026-10-13T04:00:00.027Z")
    assert "2026-10-13T04:00:00.027Z" in prompt          # 技能库数据日期
    assert "公告2026/09/24" in prompt                    # 技改条目的公告日期
    assert "凌雪阁/隐龙诀" in prompt and "万花/花间游" in prompt
    assert SKILL_HIT["text"] in prompt and PATCH_HIT["text"] in prompt
    assert prompt.endswith("问题：沁逸改成什么了？")


def test_build_prompt_empty_hits():
    """零命中时如实标注「未检索到相关资料」，不留空资料块。"""
    prompt = build_prompt("龘靐齉爩？", [], "未知")
    assert "未检索到相关资料" in prompt
    assert "问题：龘靐齉爩？" in prompt


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
