# -*- coding: utf-8 -*-
"""技能库问答 demo：读取本地最新技能库快照，取出「乱天狼」条目作为资料向 Kimi 提问。"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

SKILL_NAME = "乱天狼"
SKILL_INFO_DIR = Path(__file__).resolve().parent.parent / "data" / "skill-info"


def load_latest_snapshot(dir_path: Path = SKILL_INFO_DIR) -> dict:
    """读取技能库目录下最新的快照（文件名即 generatedAt，按文件名排序取最后一份）。"""
    files = sorted(dir_path.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"{dir_path} 下没有技能库快照，请先运行 src/fetch_skill_info.py")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def find_skill_entries(data: dict, name: str) -> list[dict]:
    """在快照中递归收集技能条目（技能名字段为 skillName，兼容 name）。"""
    hits: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("skillName") == name or node.get("name") == name:
                hits.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return hits


snapshot = load_latest_snapshot()
generatedAt = snapshot.get("generatedAt", "未知")
技能JSON = json.dumps(find_skill_entries(snapshot, SKILL_NAME), ensure_ascii=False, indent=2)

load_dotenv()
client = OpenAI(
    api_key=os.environ["MOONSHOT_API_KEY"],
    base_url="https://api.moonshot.cn/v1",
)

completion = client.chat.completions.create(
    model="kimi-k3",
    messages=[
        {"role": "system", "content": "你是剑网3竞技场数据助手，只根据提供的资料回答，资料里没有就说不知道"},
        {"role": "user", "content": f"资料（数据日期{generatedAt}）：{技能JSON}\n问题：万花有没有铁马冰河这个技能？"}
    ]
)

print(completion.choices[0].message.content)