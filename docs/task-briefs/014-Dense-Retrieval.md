# 简报014 向量检索

## 目标 
- 新建 src/retriever.py——把两座数据库压平成文档库，支持按问题检索 top-3

## 文档粒度
- 技能库：每个技能一条文档，文本 = skillName + simpleDesc + desc，metadata = {门派, 心法, 类型:"技能"}
    技能库文件为skill-info下的json文件
- 技改库：每个奇穴条目一条文档（data/extra-info/plus/*.json 的 entries + qixue_table 行），metadata = {门派, 心法, 公告日期, is_changed}
    9月8日的体服技改数据存储在data/extra-info/plus文件夹下
    9月24日的体服技改数据存储在data/patches文件夹下（该文件夹下的9月8日仅为技改总览）

## 检索
- 字符级 2-gram TF-IDF + 余弦相似度，返回 top-3

## 联动
- ask_demo.py 升级为 ask.py——接收任意问题 → 检索 top-3 → 拼 prompt → 回答（带数据日期）

## 环境
参考AGENTS.md中的项目架构

## 限制
- 见AGENTS.md的铁律内容
- 见.cursor/rules中的内容