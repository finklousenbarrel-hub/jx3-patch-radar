# 简报 006：技改内容提取为json格式

## 目标1
- 写src/parse_patch.py，把 data/patches/*.txt 解析成结构化 JSON
- 心法下面不以 · 开头的行收进 notes，以 · 开头的进 entries
- 同时对该数据结构添加标记字段 is_shared {"name": "旗舰通用", "is_shared": true, "entries": [...]}
    判断规则："通用" in name，则is_shared = true
- 输出结构：
    {
  "title": "公告标题",
  "date": "2026/09/24",
  "preamble": "前言段（第一个◎之前的文本）",
  "sects": [
    {"name": "万花", "xinfas": [
      {"name": "花间游", "is_shared": false, "notes": "调整思路的叙述段落...", "entries": [...]}
    ]}
  ]
}

## 目标2
- 修改 fetch_news.py
    html_to_text 现在把链接地址弄丢了，改成遇到 <a> 时保留成 链接文字 (URL) 的纯文本形式


## 环境
jx3-patch-radar 项目
- src存放代码文件 
  src/fetch_news.py用于抓取公告并储存为txt格式文件
- tests为函数测试用
- docs用来存放开发日志
- data用来存放技改信息抓取结果

数据源 https://www.jx3api.com/news/records 

## 限制
- 从已清洗的 txt 解析（不碰 HTML）
- parse_patch_text() 必须可 import
- JSON 用 UTF-8、中文不转义（ensure_ascii=False）

## 验收标准
9/24：门派21 / 心法65 / 条目352（原有）
9/8：JSON 全部文本字数 ≥ 原 txt 字数 95%（防静默丢数据）
抽查少林门派下 旗舰通用 的 is_shared = true